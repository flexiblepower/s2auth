"""Tests for server-side pairing helpers."""

from base64 import b64decode, b64encode
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import AnyUrl, SecretStr
from wepositive_di import provider_overrides
from wepositive_di.context import ContextStorage, context_storage_singleton

from s2auth.common.exceptions import AccessError, PairingNotCompleteError, VerificationError
from s2auth.common.hmac import (
    calculate_certificate_fingerprint_from_certificate_file,
    create_challenge,
    create_response,
    generate_access_token,
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
    FinalizePairingPostRequest,
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
    S2InMemoryContextStorage,
    client_node_id as client_node_id_provider,
)
from s2auth.server.hooks import (
    HookRegistry,
    get_server_connection_initiation_endpoint,
    get_server_endpoint_description,
    get_server_node_description,
    pairing_attempt_request,
)
import s2auth.server.pairing as pairing_module
from s2auth.server.pairing import (
    finalize_pairing,
    handle_client_response,
    initiate_pairing,
    request_pairing,
    unpair,
)
from s2auth.server.settings import Settings, settings
from s2auth.server.token_manager import consume_pending_pairing_token, set_pending_pairing_token
from s2auth.server.token_manager import prime_default_pairing_token


PAIRING_TOKEN = "pairingToken123"
DOMAIN_NAME = "s2.example.com"


def access_token(value: bytes) -> AccessToken:
    return AccessToken(root=b64encode(value))


def server_settings() -> Settings:
    return Settings(
        server_s2_node_id=uuid4(),
        cem_s2_node_id=uuid4(),
        cem_brand="TestBrand",
        cem_type="TestType",
        cem_model_name="TestModel",
        pairing_node_id="PAIR1234",
        cem_url=AnyUrl("https://cem.example.com/connection/"),
        pairing_token_ttl_seconds=300,
    )


def server_settings_with_default_pairing_token() -> Settings:
    return Settings(
        server_s2_node_id=uuid4(),
        cem_s2_node_id=uuid4(),
        cem_brand="TestBrand",
        cem_type="TestType",
        cem_model_name="TestModel",
        pairing_node_id="PAIR1234",
        cem_url=AnyUrl("https://cem.example.com/connection/"),
        default_pairing_token=PAIRING_TOKEN,
        pairing_token_ttl_seconds=300,
    )


def server_settings_lan() -> Settings:
    return Settings(
        server_s2_node_id=uuid4(),
        cem_s2_node_id=uuid4(),
        cem_brand="TestBrand",
        cem_type="TestType",
        cem_model_name="TestModel",
        pairing_node_id="PAIR1234",
        cem_url=AnyUrl("https://cem.example.com/connection/"),
        cem_deployment_type=Deployment.LAN,
        pairing_token_ttl_seconds=300,
        ssl_certfile="tests/localhost.chain.pem",
    )


def config() -> Config:
    return Config(
        sqlalchemy_db_uri=SecretStr("sqlite+aiosqlite:///:memory:"),
        domain_name=DOMAIN_NAME,
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


def pairing_request(
    client_node_id: UUID,
    deployment: Deployment = Deployment.WAN,
) -> RequestPairingPostRequest:
    return RequestPairingPostRequest(
        clientNodeDescription=client_node_description(client_node_id),
        clientEndpointDescription=EndpointDescription(deployment=deployment),
        nodeIdAlias=NodeIdAlias(root="PAIR1234"),
        supportedCommunicationProtocols=[CommunicationProtocol.WebSocket],
        supportedS2MessageVersions=["v1"],
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
    test_client_node_id = uuid4()
    started_at = datetime.now(UTC)

    ctx = await initiate_pairing(
        store_pairing_ctx=await store_pairing_context(stored_contexts),
        client_node_id=test_client_node_id,
        server_settings=server_settings(),
        pairing_token=PAIRING_TOKEN,
    )

    assert stored_contexts == [ctx]
    assert ctx.pairing_node_id == NodeIdAlias(root="PAIR1234")
    assert ctx.pairing_token == PAIRING_TOKEN
    assert ctx.client_node_id == test_client_node_id
    assert ctx.state is None
    assert ctx.pairing_token_expires_at is not None
    expected_expires_at = started_at + timedelta(minutes=5)
    assert ctx.pairing_token_expires_at >= expected_expires_at - timedelta(seconds=1)
    assert ctx.pairing_token_expires_at <= expected_expires_at + timedelta(seconds=1)


async def test_request_pairing_stores_authentication_context_and_returns_challenge_response() -> None:
    test_client_node_id = uuid4()
    request = pairing_request(test_client_node_id)
    stored_auth_contexts: list[AuthenticationContext] = []
    storage = S2InMemoryContextStorage()
    pairing_attempt_id = uuid4()
    pairing_ctx = PairingAttemptContext(
        pairing_attempt_id=pairing_attempt_id,
        client_node_id=test_client_node_id,
        pairing_node_id=NodeIdAlias(root="PAIR1234"),
        pairing_token=PAIRING_TOKEN,
    )
    await storage.store_context(PairingAttemptContext, pairing_attempt_id, pairing_ctx)

    def test_context_storage() -> ContextStorage:
        return storage

    def override_client_node_id() -> UUID:
        return test_client_node_id

    with provider_overrides(
        {
            context_storage_singleton: test_context_storage,
            client_node_id_provider: override_client_node_id,
            settings: server_settings,
        }
    ):
        response = await request_pairing(
            request=request,
            store_authentication_ctx=await store_authentication_context(
                stored_auth_contexts
            ),
            hooks=hook_registry(),
            cfg=config(),
        )

    assert len(stored_auth_contexts) == 1
    stored_pairing_ctx = await storage.get_context_snapshot(
        PairingAttemptContext, pairing_attempt_id
    )
    auth_ctx = stored_auth_contexts[0]
    assert auth_ctx.client_node_id == test_client_node_id
    assert auth_ctx.state == ClientState.PAIRING
    assert stored_pairing_ctx.client_node_id == test_client_node_id
    assert stored_pairing_ctx.state == PairingState.INITIATED
    assert stored_pairing_ctx.algorithm == HmacHashingAlgorithm.SHA256
    assert stored_pairing_ctx.server_hmac_challenge == response.serverHmacChallenge
    assert response.serverNodeDescription.brand == "TestBrand"
    assert response.serverEndpointDescription.deployment == Deployment.WAN

    expected_response = create_response(
        pairing_token=PAIRING_TOKEN,
        challenge=request.clientHmacChallenge,
        deployment=Deployment.WAN,
        domain_name=DOMAIN_NAME,
        fingerprint=None,
    )
    assert response.clientHmacChallengeResponse.root == expected_response


async def test_request_pairing_refuses_when_pairing_hook_returns_false() -> None:
    async def deny_pairing(*args: object) -> bool:
        return False

    hooks = HookRegistry()
    hooks.register(pairing_attempt_request, deny_pairing)
    storage = S2InMemoryContextStorage()
    pairing_attempt_id = uuid4()
    request = pairing_request(uuid4())
    await storage.store_context(
        PairingAttemptContext,
        pairing_attempt_id,
        PairingAttemptContext(
            pairing_attempt_id=pairing_attempt_id,
            client_node_id=request.clientNodeDescription.id.root,
            pairing_node_id=NodeIdAlias(root="PAIR1234"),
            pairing_token=PAIRING_TOKEN,
        ),
    )

    def test_context_storage() -> ContextStorage:
        return storage

    def override_client_node_id() -> UUID:
        return request.clientNodeDescription.id.root

    with provider_overrides(
        {
            context_storage_singleton: test_context_storage,
            client_node_id_provider: override_client_node_id,
            settings: server_settings,
        }
    ):
        with pytest.raises(AccessError):
            await request_pairing(
                request=request,
                store_authentication_ctx=await store_authentication_context([]),
                hooks=hooks,
                cfg=config(),
            )


async def test_request_pairing_initializes_context_when_missing() -> None:
    test_client_node_id = uuid4()
    request = pairing_request(test_client_node_id)
    stored_auth_contexts: list[AuthenticationContext] = []
    storage = S2InMemoryContextStorage()

    def test_context_storage() -> ContextStorage:
        return storage

    with provider_overrides(
        {
            context_storage_singleton: test_context_storage,
            settings: server_settings,
        }
    ):
        response = await request_pairing(
            request=request,
            store_authentication_ctx=await store_authentication_context(
                stored_auth_contexts
            ),
            hooks=hook_registry(),
            cfg=config(),
        )

    pairing_contexts = await storage.list_contexts(PairingAttemptContext)
    assert len(pairing_contexts) == 1

    pairing_ctx = pairing_contexts[0]
    assert pairing_ctx.client_node_id == test_client_node_id
    assert pairing_ctx.state == PairingState.INITIATED
    assert pairing_ctx.algorithm == HmacHashingAlgorithm.SHA256
    assert pairing_ctx.server_hmac_challenge == response.serverHmacChallenge
    assert UUID(b64decode(response.pairingAttemptId.root).decode("utf-8")) == pairing_ctx.pairing_attempt_id

    assert len(stored_auth_contexts) == 1
    assert stored_auth_contexts[0].client_node_id == test_client_node_id
    assert stored_auth_contexts[0].state == ClientState.PAIRING


async def test_default_pairing_token_is_consumed_once() -> None:
    storage = S2InMemoryContextStorage()
    stored_auth_contexts: list[AuthenticationContext] = []

    def test_context_storage() -> ContextStorage:
        return storage

    settings_instance = server_settings_with_default_pairing_token()

    def test_settings_provider() -> Settings:
        return settings_instance

    with provider_overrides(
        {
            context_storage_singleton: test_context_storage,
            settings: test_settings_provider,
        }
    ):
        await request_pairing(
            request=pairing_request(uuid4()),
            store_authentication_ctx=await store_authentication_context(
                stored_auth_contexts
            ),
            hooks=hook_registry(),
            cfg=config(),
        )
        await request_pairing(
            request=pairing_request(uuid4()),
            store_authentication_ctx=await store_authentication_context(
                stored_auth_contexts
            ),
            hooks=hook_registry(),
            cfg=config(),
        )

    pairing_contexts = await storage.list_contexts(PairingAttemptContext)
    pairing_tokens = [ctx.pairing_token for ctx in pairing_contexts]
    assert pairing_tokens.count(PAIRING_TOKEN) == 1


async def test_empty_default_pairing_token_falls_back_to_generated_token() -> None:
    storage = S2InMemoryContextStorage()

    def test_context_storage() -> ContextStorage:
        return storage

    settings_instance = server_settings_with_default_pairing_token()
    settings_instance.default_pairing_token = ""

    def test_settings_provider() -> Settings:
        return settings_instance

    with provider_overrides(
        {
            context_storage_singleton: test_context_storage,
            settings: test_settings_provider,
        }
    ):
        await request_pairing(
            request=pairing_request(uuid4()),
            store_authentication_ctx=await store_authentication_context([]),
            hooks=hook_registry(),
            cfg=config(),
        )

    pairing_contexts = await storage.list_contexts(PairingAttemptContext)
    assert len(pairing_contexts) == 1
    assert pairing_contexts[0].pairing_token != ""
    assert pairing_contexts[0].pairing_token != PAIRING_TOKEN


async def test_default_pairing_token_expires_from_startup_time() -> None:
    storage = S2InMemoryContextStorage()

    def test_context_storage() -> ContextStorage:
        return storage

    settings_instance = server_settings_with_default_pairing_token()
    settings_instance.default_pairing_token_created_at = datetime.now(UTC) - timedelta(
        minutes=10
    )

    def test_settings_provider() -> Settings:
        return settings_instance

    with provider_overrides(
        {
            context_storage_singleton: test_context_storage,
            settings: test_settings_provider,
        }
    ):
        with pytest.raises(AccessError, match="Pairing token has expired"):
            await request_pairing(
                request=pairing_request(uuid4()),
                store_authentication_ctx=await store_authentication_context([]),
                hooks=hook_registry(),
                cfg=config(),
            )

    pairing_contexts = await storage.list_contexts(PairingAttemptContext)
    assert len(pairing_contexts) == 0


async def test_request_pairing_rejects_expired_pending_pairing_token() -> None:
    storage = S2InMemoryContextStorage()

    # Ensure clean global token-manager state for this test.
    consume_pending_pairing_token()
    set_pending_pairing_token("expired-pending-token", ttl_seconds=0)

    def test_context_storage() -> ContextStorage:
        return storage

    with provider_overrides(
        {
            context_storage_singleton: test_context_storage,
            settings: server_settings,
        }
    ):
        with pytest.raises(AccessError, match="Pairing token has expired"):
            await request_pairing(
                request=pairing_request(uuid4()),
                store_authentication_ctx=await store_authentication_context([]),
                hooks=hook_registry(),
                cfg=config(),
            )

    pairing_contexts = await storage.list_contexts(PairingAttemptContext)
    assert len(pairing_contexts) == 0


def test_prime_default_pairing_token_moves_token_to_pending_bucket() -> None:
    consume_pending_pairing_token()
    settings_instance = server_settings_with_default_pairing_token()

    prime_default_pairing_token(settings_instance)

    assert settings_instance.default_pairing_token is None
    assert consume_pending_pairing_token() == PAIRING_TOKEN


def test_default_pairing_token_created_at_is_stable_across_settings_instances() -> None:
    first = server_settings_with_default_pairing_token()
    second = server_settings_with_default_pairing_token()

    assert first.default_pairing_token_created_at == second.default_pairing_token_created_at


async def test_request_pairing_uses_request_deployment_when_server_default_is_lan() -> None:
    test_client_node_id = uuid4()
    request = pairing_request(test_client_node_id)
    stored_auth_contexts: list[AuthenticationContext] = []
    storage = S2InMemoryContextStorage()

    def test_context_storage() -> ContextStorage:
        return storage

    with provider_overrides(
        {
            context_storage_singleton: test_context_storage,
            settings: server_settings_lan,
        }
    ):
        response = await request_pairing(
            request=request,
            store_authentication_ctx=await store_authentication_context(
                stored_auth_contexts
            ),
            hooks=hook_registry(),
            cfg=config(),
        )

    assert response.serverHmacChallenge is not None
    assert len(stored_auth_contexts) == 1


async def test_request_pairing_forced_lan_provides_fingerprint() -> None:
    # forcing LAN pairing should compute a fingerprint from the configured certificate file
    test_client_node_id = uuid4()
    request = pairing_request(test_client_node_id, deployment=Deployment.LAN)
    stored_auth_contexts: list[AuthenticationContext] = []
    storage = S2InMemoryContextStorage()
    pairing_attempt_id = uuid4()
    await storage.store_context(
        PairingAttemptContext,
        pairing_attempt_id,
        PairingAttemptContext(
            pairing_attempt_id=pairing_attempt_id,
            client_node_id=test_client_node_id,
            pairing_node_id=NodeIdAlias(root="PAIR1234"),
            pairing_token=PAIRING_TOKEN,
        ),
    )

    def test_context_storage() -> ContextStorage:
        return storage

    with provider_overrides(
        {
            context_storage_singleton: test_context_storage,
            settings: server_settings_lan,
        }
    ):
        response = await request_pairing(
            request=request,
            store_authentication_ctx=await store_authentication_context(
                stored_auth_contexts
            ),
            hooks=hook_registry(),
            cfg=config(),
        )

    assert response.serverHmacChallenge is not None
    assert len(stored_auth_contexts) == 1


@pytest.mark.parametrize("deployment", [Deployment.WAN, Deployment.LAN])
async def test_request_pairing_uses_request_deployment_for_hmac(
    deployment: Deployment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_client_node_id = uuid4()
    request = pairing_request(test_client_node_id, deployment=deployment)
    stored_auth_contexts: list[AuthenticationContext] = []
    storage = S2InMemoryContextStorage()
    pairing_attempt_id = uuid4()
    await storage.store_context(
        PairingAttemptContext,
        pairing_attempt_id,
        PairingAttemptContext(
            pairing_attempt_id=pairing_attempt_id,
            client_node_id=test_client_node_id,
            pairing_node_id=NodeIdAlias(root="PAIR1234"),
            pairing_token=PAIRING_TOKEN,
        ),
    )
    seen: dict[str, Deployment] = {}

    def test_context_storage() -> ContextStorage:
        return storage

    def fake_create_response(*args: object, **kwargs: object) -> bytes:
        seen["deployment"] = kwargs["deployment"]  # type: ignore[index]
        return b"client-response"

    monkeypatch.setattr(pairing_module, "create_response", fake_create_response)

    with provider_overrides(
        {
            context_storage_singleton: test_context_storage,
            settings: server_settings_lan,
        }
    ):
        response = await request_pairing(
            request=request,
            store_authentication_ctx=await store_authentication_context(
                stored_auth_contexts
            ),
            hooks=hook_registry(),
            cfg=config(),
        )

    assert response.clientHmacChallengeResponse.root == b"client-response"
    assert seen["deployment"] == deployment


@pytest.mark.parametrize("deployment", [Deployment.WAN, Deployment.LAN])
async def test_handle_client_response_uses_auth_context_deployment_for_hmac_verification(
    deployment: Deployment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access_token_value = access_token(b"server-access-token-server-token")
    pairing_ctx = PairingAttemptContext(
        pairing_attempt_id=uuid4(),
        pairing_node_id=NodeIdAlias(root="PAIR1234"),
        pairing_token=PAIRING_TOKEN,
        state=PairingState.INITIATED,
        algorithm=HmacHashingAlgorithm.SHA256,
        server_hmac_challenge=create_challenge(),
    )
    auth_ctx = AuthenticationContext(
        client_node_id=uuid4(),
        state=ClientState.PAIRING,
        s2_endpoint_description=EndpointDescription(deployment=deployment),
    )
    seen: dict[str, Deployment] = {}

    def new_access_token() -> AccessToken:
        return access_token_value

    def fake_verify_response(*args: object, **kwargs: object) -> bool:
        seen["deployment"] = kwargs["deployment"]  # type: ignore[index]
        return True

    monkeypatch.setattr(pairing_module, "verify_response", fake_verify_response)

    with provider_overrides(
        {generate_access_token: new_access_token, settings: server_settings_lan}
    ):
        connection_details = await handle_client_response(
            request=RequestConnectionDetailsPostRequest(
                serverHmacChallengeResponse=HmacChallengeResponse(root=b64encode(b"response"))
            ),
            pairing_context=pairing_ctx,
            auth_ctx=auth_ctx,
            hooks=hook_registry(),
            cfg=config(),
        )

    assert connection_details.accessToken == access_token_value
    assert seen["deployment"] == deployment


async def test_unpair_removes_authentication_and_pairing_contexts() -> None:
    storage = S2InMemoryContextStorage()
    test_client_node_id = uuid4()
    pairing_attempt_id = uuid4()
    await storage.store_context(
        AuthenticationContext,
        test_client_node_id,
        AuthenticationContext(
            client_node_id=test_client_node_id,
            state=ClientState.PAIRED,
        ),
    )
    await storage.store_context(
        PairingAttemptContext,
        pairing_attempt_id,
        PairingAttemptContext(
            pairing_attempt_id=pairing_attempt_id,
            client_node_id=test_client_node_id,
            pairing_node_id=NodeIdAlias(root="PAIR1234"),
            pairing_token=PAIRING_TOKEN,
            state=PairingState.COMPLETED,
        ),
    )

    def test_context_storage() -> ContextStorage:
        return storage

    def override_client_node_id() -> UUID:
        return test_client_node_id

    with provider_overrides(
        {
            context_storage_singleton: test_context_storage,
            client_node_id_provider: override_client_node_id,
        }
    ):
        await unpair()

    with pytest.raises(KeyError):
        await storage.get_context_snapshot(AuthenticationContext, test_client_node_id)
    with pytest.raises(KeyError):
        await storage.get_context_snapshot(PairingAttemptContext, pairing_attempt_id)


async def test_handle_client_response_verifies_hmac_and_returns_connection_details_wan() -> None:
    access_token_value = access_token(b"server-access-token-server-token")
    pairing_ctx = PairingAttemptContext(
        pairing_attempt_id=uuid4(),
        pairing_node_id=NodeIdAlias(root="PAIR1234"),
        pairing_token=PAIRING_TOKEN,
        state=PairingState.INITIATED,
        algorithm=HmacHashingAlgorithm.SHA256,
        server_hmac_challenge=create_challenge(),
    )
    auth_ctx = AuthenticationContext(
        client_node_id=uuid4(),
        state=ClientState.PAIRING,
        s2_endpoint_description=EndpointDescription(deployment=Deployment.WAN),
    )
    assert pairing_ctx.server_hmac_challenge is not None
    response = create_response(
        pairing_token=PAIRING_TOKEN,
        challenge=pairing_ctx.server_hmac_challenge,
        deployment=Deployment.WAN,
        domain_name=DOMAIN_NAME,
        fingerprint=None,
    )

    def new_access_token() -> AccessToken:
        return access_token_value

    with provider_overrides({generate_access_token: new_access_token, settings: server_settings}):
        connection_details = await handle_client_response(
            request=RequestConnectionDetailsPostRequest(
                serverHmacChallengeResponse=HmacChallengeResponse(root=b64encode(response))
            ),
            pairing_context=pairing_ctx,
            auth_ctx=auth_ctx,
            hooks=hook_registry(),
            cfg=config(),
        )

    assert connection_details.accessToken == access_token_value
    assert str(connection_details.initiateSessionUrl) == "https://cem.example.com/connection/"
    assert auth_ctx.current_access_token == access_token_value
    assert auth_ctx.next_access_token is None
    assert auth_ctx.state == ClientState.PAIRING
    assert pairing_ctx.state == PairingState.COMPLETED


async def test_handle_client_response_verifies_hmac_and_returns_connection_details_lan() -> None:
    access_token_value = access_token(b"server-access-token-server-token")
    pairing_ctx = PairingAttemptContext(
        pairing_attempt_id=uuid4(),
        pairing_node_id=NodeIdAlias(root="PAIR1234"),
        pairing_token=PAIRING_TOKEN,
        state=PairingState.INITIATED,
        algorithm=HmacHashingAlgorithm.SHA256,
        server_hmac_challenge=create_challenge(),
    )
    auth_ctx = AuthenticationContext(
        client_node_id=uuid4(),
        state=ClientState.PAIRING,
        s2_endpoint_description=EndpointDescription(deployment=Deployment.LAN),
    )
    server_cfg = server_settings_lan()
    assert pairing_ctx.server_hmac_challenge is not None
    fingerprint = calculate_certificate_fingerprint_from_certificate_file(
        server_cfg.ssl_certfile
    )
    response = create_response(
        pairing_token=PAIRING_TOKEN,
        challenge=pairing_ctx.server_hmac_challenge,
        deployment=Deployment.LAN,
        domain_name=DOMAIN_NAME,
        fingerprint=fingerprint,
    )

    def new_access_token() -> AccessToken:
        return access_token_value

    def test_settings_provider() -> Settings:
        return server_cfg

    with provider_overrides(
        {generate_access_token: new_access_token, settings: test_settings_provider}
    ):
        connection_details = await handle_client_response(
            request=RequestConnectionDetailsPostRequest(
                serverHmacChallengeResponse=HmacChallengeResponse(root=b64encode(response))
            ),
            pairing_context=pairing_ctx,
            auth_ctx=auth_ctx,
            hooks=hook_registry(),
            cfg=config(),
        )

    assert connection_details.accessToken == access_token_value
    assert str(connection_details.initiateSessionUrl) == "https://cem.example.com/connection/"
    assert auth_ctx.current_access_token == access_token_value
    assert auth_ctx.next_access_token is None
    assert auth_ctx.state == ClientState.PAIRING
    assert pairing_ctx.state == PairingState.COMPLETED


async def test_finalize_pairing_success_marks_auth_context_paired() -> None:
    pairing_ctx = PairingAttemptContext(
        pairing_attempt_id=uuid4(),
        pairing_node_id=NodeIdAlias(root="PAIR1234"),
        pairing_token=PAIRING_TOKEN,
        state=PairingState.COMPLETED,
    )
    auth_ctx = AuthenticationContext(client_node_id=uuid4(), state=ClientState.PAIRING)

    await finalize_pairing(
        request=FinalizePairingPostRequest(success=True),
        pairing_context=pairing_ctx,
        auth_ctx=auth_ctx,
    )

    assert auth_ctx.state == ClientState.PAIRED
    assert pairing_ctx.state == PairingState.COMPLETED


async def test_finalize_pairing_requires_completed_pairing_context() -> None:
    pairing_ctx = PairingAttemptContext(
        pairing_attempt_id=uuid4(),
        pairing_node_id=NodeIdAlias(root="PAIR1234"),
        pairing_token=PAIRING_TOKEN,
        state=PairingState.INITIATED,
    )

    with pytest.raises(PairingNotCompleteError):
        await finalize_pairing(
            request=FinalizePairingPostRequest(success=True),
            pairing_context=pairing_ctx,
            auth_ctx=AuthenticationContext(client_node_id=uuid4(), state=ClientState.PAIRING),
        )


async def test_finalize_pairing_failure_marks_pairing_failed() -> None:
    pairing_ctx = PairingAttemptContext(
        pairing_attempt_id=uuid4(),
        pairing_node_id=NodeIdAlias(root="PAIR1234"),
        pairing_token=PAIRING_TOKEN,
        state=PairingState.INITIATED,
    )
    auth_ctx = AuthenticationContext(client_node_id=uuid4(), state=ClientState.PAIRING)

    await finalize_pairing(
        request=FinalizePairingPostRequest(success=False),
        pairing_context=pairing_ctx,
        auth_ctx=auth_ctx,
    )

    assert auth_ctx.state == ClientState.PAIRING
    assert pairing_ctx.state == PairingState.FAILED


async def test_handle_client_response_rejects_invalid_hmac_response() -> None:
    pairing_ctx = PairingAttemptContext(
        pairing_attempt_id=uuid4(),
        pairing_node_id=NodeIdAlias(root="PAIR1234"),
        pairing_token=PAIRING_TOKEN,
        state=PairingState.INITIATED,
        algorithm=HmacHashingAlgorithm.SHA256,
        server_hmac_challenge=create_challenge(),
    )

    with provider_overrides({settings: server_settings}):
        with pytest.raises(VerificationError):
            await handle_client_response(
                request=RequestConnectionDetailsPostRequest(
                    serverHmacChallengeResponse=HmacChallengeResponse(root=b64encode(b"wrong"))
                ),
                pairing_context=pairing_ctx,
                auth_ctx=AuthenticationContext(client_node_id=uuid4(), state=ClientState.PAIRING),
                hooks=HookRegistry(),
                new_access_token=access_token(b"unused-token-unused-token-1234"),
                cfg=config(),
            )


async def test_handle_client_response_rejects_expired_pairing_token() -> None:
    pairing_ctx = PairingAttemptContext(
        pairing_attempt_id=uuid4(),
        pairing_node_id=NodeIdAlias(root="PAIR1234"),
        pairing_token=PAIRING_TOKEN,
        pairing_token_expires_at=datetime.now(UTC) - timedelta(seconds=1),
        state=PairingState.INITIATED,
        algorithm=HmacHashingAlgorithm.SHA256,
        server_hmac_challenge=create_challenge(),
    )

    with provider_overrides({settings: server_settings}):
        with pytest.raises(AccessError, match="Pairing token has expired"):
            await handle_client_response(
                request=RequestConnectionDetailsPostRequest(
                    serverHmacChallengeResponse=HmacChallengeResponse(root=b64encode(b"unused"))
                ),
                pairing_context=pairing_ctx,
                auth_ctx=AuthenticationContext(client_node_id=uuid4(), state=ClientState.PAIRING),
                hooks=HookRegistry(),
                new_access_token=access_token(b"unused-token-unused-token-1234"),
                cfg=config(),
            )

    assert pairing_ctx.state == PairingState.FAILED
