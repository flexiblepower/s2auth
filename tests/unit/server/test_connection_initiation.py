"""Tests for server-side connection initiation helpers."""

from base64 import b64encode
from uuid import uuid4

import pytest
from wepositive_di import provider_overrides

from s2auth.common.exceptions import (
    InvalidAccessTokenError,
    InvalidServerError,
    NoCompatibleCommunitcationProtocol,
    NoCompatibleS2ConnectVersionError,
    NoCompatibleS2VersionError,
    PairingNotCompleteError,
)
from s2auth.common.hmac import generate_access_token
from s2auth.common.model.s2_connect_common import (
    AccessToken,
    CommunicationProtocol,
    Deployment,
    NodeId,
    Role,
)
from s2auth.server.connection_initiation import (
    initiateConnection,
    validate_access_token,
    validate_s2_connection_token,
)
from s2auth.server.context import AuthenticationContext, ClientState
from s2auth.server.hooks import HookRegistry
from s2auth.server.settings import Settings, settings


def access_token(value: bytes) -> AccessToken:
    return AccessToken(root=b64encode(value))


def make_settings(
    deployment: Deployment = Deployment.WAN,
) -> Settings:
    return Settings(
        server_s2_node_id=uuid4(),
        cem_s2_node_id=uuid4(),
        cem_brand="TestBrand",
        cem_type="TestType",
        cem_model_name="TestModel",
        pairing_node_id="pairing123",
        cem_deployment_type=deployment,
    )


def authentication_context(current_access_token: AccessToken) -> AuthenticationContext:
    return AuthenticationContext(
        client_node_id=uuid4(),
        state=ClientState.PAIRED,
        current_access_token=current_access_token,
    )


async def test_initiate_connection_generates_pending_token_and_returns_negotiated_details() -> (
    None
):
    current_token = access_token(b"current-token-current-token-1234")
    next_token = access_token(b"next-token-next-token-next-token12")
    server_settings = make_settings(deployment=Deployment.WAN)
    auth_ctx = authentication_context(current_token)

    def test_settings_provider() -> Settings:
        return server_settings

    def new_access_token() -> AccessToken:
        return next_token

    with provider_overrides(
        {settings: test_settings_provider, generate_access_token: new_access_token}
    ):
        response = await initiateConnection(
            server_node_id=NodeId(root=server_settings.server_s2_node_id),
            access_token=current_token,
            supported_communication_protocols=[CommunicationProtocol.WebSocket],
            supported_s2_versions=["v1", "v0.02-beta"],
            selected_s2_connect_version="v1",
            server_settings=server_settings,
            authentication_ctx=auth_ctx,
            hooks=HookRegistry(),
        )

    assert auth_ctx.next_access_token == next_token
    assert response.accessToken == next_token
    assert response.selectedCommunicationProtocol == CommunicationProtocol.WebSocket
    assert response.selectedS2MessageVersion == "v1"
    assert response.serverEndpointDescription is not None
    assert response.serverEndpointDescription.deployment == Deployment.WAN
    assert response.serverNodeDescription is not None
    assert response.serverNodeDescription.id == NodeId(
        root=server_settings.cem_s2_node_id
    )
    assert response.serverNodeDescription.brand == "TestBrand"
    assert response.serverNodeDescription.role == Role.CEM


async def test_initiate_connection_rejects_unsupported_s2_connect_version() -> None:
    current_token = access_token(b"current-token-current-token-1234")
    server_settings = make_settings()

    with pytest.raises(NoCompatibleS2ConnectVersionError):
        await initiateConnection(
            server_node_id=NodeId(root=server_settings.server_s2_node_id),
            access_token=current_token,
            supported_communication_protocols=[CommunicationProtocol.WebSocket],
            supported_s2_versions=["v1"],
            selected_s2_connect_version="v2.0",
            server_settings=server_settings,
            authentication_ctx=authentication_context(current_token),
            new_access_token=access_token(b"next-token-next-token-next-token12"),
            hooks=HookRegistry(),
        )


async def test_initiate_connection_requires_completed_pairing() -> None:
    current_token = access_token(b"current-token-current-token-1234")
    server_settings = make_settings()
    auth_ctx = AuthenticationContext(
        client_node_id=uuid4(),
        state=ClientState.PAIRING,
        current_access_token=current_token,
    )

    with pytest.raises(PairingNotCompleteError):
        await initiateConnection(
            server_node_id=NodeId(root=server_settings.server_s2_node_id),
            access_token=current_token,
            supported_communication_protocols=[CommunicationProtocol.WebSocket],
            supported_s2_versions=["v1"],
            selected_s2_connect_version="v1",
            server_settings=server_settings,
            authentication_ctx=auth_ctx,
            new_access_token=access_token(b"next-token-next-token-next-token12"),
            hooks=HookRegistry(),
        )


async def test_initiate_connection_rejects_invalid_access_token() -> None:
    current_token = access_token(b"current-token-current-token-1234")
    server_settings = make_settings()

    with pytest.raises(InvalidAccessTokenError):
        await initiateConnection(
            server_node_id=NodeId(root=server_settings.server_s2_node_id),
            access_token=access_token(b"wrong-token-wrong-token-wrong123"),
            supported_communication_protocols=[CommunicationProtocol.WebSocket],
            supported_s2_versions=["v1"],
            selected_s2_connect_version="v1",
            server_settings=server_settings,
            authentication_ctx=authentication_context(current_token),
            new_access_token=access_token(b"next-token-next-token-next-token12"),
            hooks=HookRegistry(),
        )


async def test_initiate_connection_rejects_wrong_server_node_id() -> None:
    current_token = access_token(b"current-token-current-token-1234")
    server_settings = make_settings()

    with pytest.raises(InvalidServerError):
        await initiateConnection(
            server_node_id=NodeId(root=uuid4()),
            access_token=current_token,
            supported_communication_protocols=[CommunicationProtocol.WebSocket],
            supported_s2_versions=["v1"],
            selected_s2_connect_version="v1",
            server_settings=server_settings,
            authentication_ctx=authentication_context(current_token),
            new_access_token=access_token(b"next-token-next-token-next-token12"),
            hooks=HookRegistry(),
        )


async def test_initiate_connection_rejects_incompatible_s2_versions() -> None:
    current_token = access_token(b"current-token-current-token-1234")
    server_settings = make_settings()

    with pytest.raises(NoCompatibleS2VersionError):
        await initiateConnection(
            server_node_id=NodeId(root=server_settings.server_s2_node_id),
            access_token=current_token,
            supported_communication_protocols=[CommunicationProtocol.WebSocket],
            supported_s2_versions=["v0.01-beta"],
            selected_s2_connect_version="v1",
            server_settings=server_settings,
            authentication_ctx=authentication_context(current_token),
            new_access_token=access_token(b"next-token-next-token-next-token12"),
            hooks=HookRegistry(),
        )


async def test_initiate_connection_rejects_incompatible_protocols() -> None:
    current_token = access_token(b"current-token-current-token-1234")
    server_settings = make_settings()
    server_settings.supported_communication_protocols = []

    with pytest.raises(NoCompatibleCommunitcationProtocol):
        await initiateConnection(
            server_node_id=NodeId(root=server_settings.server_s2_node_id),
            access_token=current_token,
            supported_communication_protocols=[CommunicationProtocol.WebSocket],
            supported_s2_versions=["v1"],
            selected_s2_connect_version="v1",
            server_settings=server_settings,
            authentication_ctx=authentication_context(current_token),
            new_access_token=access_token(b"next-token-next-token-next-token12"),
            hooks=HookRegistry(),
        )


async def test_validate_access_token_promotes_pending_token() -> None:
    current_token = access_token(b"current-token-current-token-1234")
    next_token = access_token(b"next-token-next-token-next-token12")
    auth_ctx = authentication_context(current_token)
    auth_ctx.next_access_token = next_token

    await validate_access_token(next_token, authentication_ctx=auth_ctx)

    assert auth_ctx.current_connection_token == current_token
    assert auth_ctx.current_access_token == next_token
    assert auth_ctx.next_access_token is None
    assert auth_ctx.state == ClientState.CONNECTION_INITIATED


async def test_validate_access_token_rejects_unknown_pending_token() -> None:
    auth_ctx = authentication_context(access_token(b"current-token-current-token-1234"))
    auth_ctx.next_access_token = access_token(b"next-token-next-token-next-token12")

    with pytest.raises(InvalidAccessTokenError):
        await validate_access_token(
            access_token(b"wrong-token-wrong-token-wrong123"),
            authentication_ctx=auth_ctx,
        )


async def test_validate_s2_connection_token_invalidates_one_time_token() -> None:
    connection_token = access_token(b"connection-token-connection-123")
    auth_ctx = authentication_context(access_token(b"current-token-current-token-1234"))
    auth_ctx.current_connection_token = connection_token

    assert await validate_s2_connection_token(
        connection_token, authentication_ctx=auth_ctx
    )
    assert auth_ctx.current_connection_token is None


async def test_validate_s2_connection_token_rejects_reuse() -> None:
    connection_token = access_token(b"connection-token-connection-123")
    auth_ctx = authentication_context(access_token(b"current-token-current-token-1234"))
    auth_ctx.current_connection_token = connection_token

    assert await validate_s2_connection_token(
        connection_token, authentication_ctx=auth_ctx
    )
    with pytest.raises(InvalidAccessTokenError):
        await validate_s2_connection_token(
            connection_token, authentication_ctx=auth_ctx
        )
