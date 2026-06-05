"""Tests for server-side pairing helpers."""

from base64 import b64encode
from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

import pytest
from pydantic import AnyUrl, SecretStr

from s2auth.common.exceptions import AccessError, VerificationError
from s2auth.common.hmac import (
    AccessTokenGenerator,
    create_challenge,
    create_response,
)
from s2auth.common.model.s2_connect_common import (
    AccessToken,
    CommunicationProtocol,
    Deployment,
    EndpointDescription,
    NodeDescription,
    NodeId,
    Role,
)
from s2auth.common.model.s2_connect_pairing import (
    HmacChallengeResponse,
    HmacHashingAlgorithm,
    NodeIdAlias,
    RequestConnectionDetailsPostRequest,
    RequestPairingPostRequest,
)
from s2auth.server.config import Config
from s2auth.server.context import (
    AuthenticationContext,
    ClientState,
    PairingAttemptContext,
    PairingState,
    ReadOnlyAuthenticationContext,
)
from s2auth.server.hooks import (
    HookRegistry,
    get_server_connection_initiation_endpoint,
    get_server_endpoint_description,
    get_server_node_description,
    pairing_attempt_request,
)
from s2auth.server.pairing import (
    handle_client_response,
    initiate_pairing,
    request_pairing,
)
from s2auth.server.settings import Settings


PAIRING_TOKEN = "pairingToken123"
HMAC_SALT = "s2.example.com"


def access_token(value: bytes) -> AccessToken:
    return AccessToken(root=b64encode(value))


def token_generator(token: AccessToken) -> AccessTokenGenerator:
    def generate(length: int = 32) -> AccessToken:
        return token

    return generate


def server_settings() -> Settings:
    return Settings(
        server_s2_node_id=uuid4(),
        cem_s2_node_id=uuid4(),
        cem_brand="TestBrand",
        cem_type="TestType",
        cem_model_name="TestModel",
        pairing_node_id="PAIR1234",
        cem_url=AnyUrl("https://cem.example.com/connection/"),
    )


def config() -> Config:
    return Config(
        sqlalchemy_db_uri=SecretStr("sqlite+aiosqlite:///:memory:"),
        hmac_salt=HMAC_SALT,
    )


def client_node_description(client_node_id: UUID) -> NodeDescription:
    return NodeDescription(
        id=NodeId(root=client_node_id),
        brand="ClientBrand",
        role=Role.RM,
        type="HeatPump",
        modelName="HP-1",
    )


def hook_registry() -> HookRegistry:
    async def allow_pairing(*args: object) -> bool:
        return True

    async def endpoint_description(client_node_id: NodeId) -> EndpointDescription:
        return EndpointDescription(deployment=Deployment.WAN)

    async def node_description(client_node_id: NodeId) -> NodeDescription:
        return NodeDescription(
            id=NodeId(root=uuid4()),
            brand="TestBrand",
            role=Role.CEM,
            type="CEM",
            modelName="CEM-1",
        )

    async def connection_endpoint(
        authentication_context: ReadOnlyAuthenticationContext,
    ) -> AnyUrl:
        return AnyUrl("https://cem.example.com/connection/")

    hooks = HookRegistry()
    hooks.register(pairing_attempt_request, allow_pairing)
    hooks.register(get_server_endpoint_description, endpoint_description)
    hooks.register(get_server_node_description, node_description)
    hooks.register(get_server_connection_initiation_endpoint, connection_endpoint)
    return hooks


def pairing_request(client_node_id: UUID) -> RequestPairingPostRequest:
    return RequestPairingPostRequest(
        clientNodeDescription=client_node_description(client_node_id),
        clientEndpointDescription=EndpointDescription(deployment=Deployment.WAN),
        nodeIdAlias=NodeIdAlias(root="PAIR1234"),
        supportedCommunicationProtocols=[CommunicationProtocol.WebSocket],
        supportedS2MessageVersions=["v0.02-beta"],
        supportedHmacHashingAlgorithms=[HmacHashingAlgorithm.SHA256],
        clientHmacChallenge=create_challenge(),
    )


async def store_pairing_context(
    stored_contexts: list[PairingAttemptContext],
) -> Callable[[PairingAttemptContext], Awaitable[None]]:
    async def store(ctx: PairingAttemptContext) -> None:
        stored_contexts.append(ctx)

    return store


async def store_authentication_context(
    stored_contexts: list[AuthenticationContext],
) -> Callable[[AuthenticationContext], Awaitable[None]]:
    async def store(ctx: AuthenticationContext) -> None:
        stored_contexts.append(ctx)

    return store


async def test_initiate_pairing_stores_context_and_sets_pairing_id() -> None:
    stored_contexts: list[PairingAttemptContext] = []

    ctx = await initiate_pairing(
        store_pairing_ctx=await store_pairing_context(stored_contexts),
        server_settings=server_settings(),
        pairing_token=PAIRING_TOKEN,
    )

    assert stored_contexts == [ctx]
    assert ctx.pairing_node_id == NodeIdAlias(root="PAIR1234")
    assert ctx.pairing_token == PAIRING_TOKEN
    assert ctx.state is None


async def test_request_pairing_stores_authentication_context_and_returns_challenge_response() -> None:
    client_node_id = uuid4()
    request = pairing_request(client_node_id)
    stored_auth_contexts: list[AuthenticationContext] = []
    pairing_ctx = PairingAttemptContext(
        pairing_attempt_id=uuid4(),
        pairing_node_id=NodeIdAlias(root="PAIR1234"),
        pairing_token=PAIRING_TOKEN,
    )

    response = await request_pairing(
        request=request,
        store_authentication_ctx=await store_authentication_context(stored_auth_contexts),
        pairing_context=pairing_ctx,
        hooks=hook_registry(),
        cfg=config(),
    )

    assert len(stored_auth_contexts) == 1
    auth_ctx = stored_auth_contexts[0]
    assert auth_ctx.client_node_id == client_node_id
    assert auth_ctx.state == ClientState.PAIRING
    assert pairing_ctx.client_node_id == client_node_id
    assert pairing_ctx.state == PairingState.INITIATED
    assert pairing_ctx.algorithm == HmacHashingAlgorithm.SHA256
    assert pairing_ctx.server_hmac_challenge == response.serverHmacChallenge
    assert response.serverNodeDescription.brand == "TestBrand"
    assert response.serverEndpointDescription.deployment == Deployment.WAN

    expected_response = create_response(
        pairing_token=PAIRING_TOKEN,
        challenge=request.clientHmacChallenge,
        hmac_salt=HMAC_SALT,
    )
    assert response.clientHmacChallengeResponse.root == expected_response


async def test_request_pairing_refuses_when_pairing_hook_returns_false() -> None:
    async def deny_pairing(*args: object) -> bool:
        return False

    hooks = HookRegistry()
    hooks.register(pairing_attempt_request, deny_pairing)

    with pytest.raises(AccessError):
        await request_pairing(
            request=pairing_request(uuid4()),
            store_authentication_ctx=await store_authentication_context([]),
            pairing_context=PairingAttemptContext(
                pairing_attempt_id=uuid4(),
                pairing_node_id=NodeIdAlias(root="PAIR1234"),
                pairing_token=PAIRING_TOKEN,
            ),
            hooks=hooks,
            cfg=config(),
        )


async def test_handle_client_response_verifies_hmac_and_returns_connection_details() -> None:
    access_token_value = access_token(b"server-access-token-server-token")
    pairing_ctx = PairingAttemptContext(
        pairing_attempt_id=uuid4(),
        pairing_node_id=NodeIdAlias(root="PAIR1234"),
        pairing_token=PAIRING_TOKEN,
        state=PairingState.INITIATED,
        algorithm=HmacHashingAlgorithm.SHA256,
        server_hmac_challenge=create_challenge(),
    )
    auth_ctx = AuthenticationContext(client_node_id=uuid4(), state=ClientState.PAIRING)
    assert pairing_ctx.server_hmac_challenge is not None
    response = create_response(
        pairing_token=PAIRING_TOKEN,
        challenge=pairing_ctx.server_hmac_challenge,
        hmac_salt=HMAC_SALT,
    )

    connection_details = await handle_client_response(
        request=RequestConnectionDetailsPostRequest(
            serverHmacChallengeResponse=HmacChallengeResponse(root=b64encode(response))
        ),
        pairing_context=pairing_ctx,
        auth_ctx=auth_ctx,
        hooks=hook_registry(),
        generate_access_token=token_generator(access_token_value),
        cfg=config(),
    )

    assert connection_details.accessToken == access_token_value
    assert str(connection_details.initiateConnectionUrl) == "https://cem.example.com/connection/"
    assert auth_ctx.current_access_token == access_token_value
    assert auth_ctx.next_access_token is None
    assert auth_ctx.state == ClientState.PAIRED
    assert pairing_ctx.state == PairingState.COMPLETED


async def test_handle_client_response_rejects_invalid_hmac_response() -> None:
    pairing_ctx = PairingAttemptContext(
        pairing_attempt_id=uuid4(),
        pairing_node_id=NodeIdAlias(root="PAIR1234"),
        pairing_token=PAIRING_TOKEN,
        state=PairingState.INITIATED,
        algorithm=HmacHashingAlgorithm.SHA256,
        server_hmac_challenge=create_challenge(),
    )

    with pytest.raises(VerificationError):
        await handle_client_response(
            request=RequestConnectionDetailsPostRequest(
                serverHmacChallengeResponse=HmacChallengeResponse(root=b64encode(b"wrong"))
            ),
            pairing_context=pairing_ctx,
            auth_ctx=AuthenticationContext(client_node_id=uuid4(), state=ClientState.PAIRING),
            hooks=HookRegistry(),
            generate_access_token=token_generator(access_token(b"unused-token-unused-token-1234")),
            cfg=config(),
        )
