from typing import Any, cast
from unittest.mock import AsyncMock

from pytest import MonkeyPatch
from pytest_mock.plugin import MockerFixture

from s2auth.client.dao import Dao
from s2auth.client.pairing import PairingClient, build_pairing_settings, detect_deployment
from s2auth.client.settings import ClientSettings
from s2auth.common.model.s2_connect_common import Deployment, Role


class InMemoryStore:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, Any]] = {}

    def store_connection_details(self, s2_node_id: str, details: dict[str, Any]) -> None:
        self.data[s2_node_id] = details

    def load_connection_details(self, s2_node_id: str) -> dict[str, Any] | None:
        return self.data.get(s2_node_id)

    def remove_connection_details(self, s2_node_id: str) -> bool:
        return self.data.pop(s2_node_id, None) is not None


def _make_settings(**kwargs: Any) -> ClientSettings:
    return cast(ClientSettings, cast(Any, ClientSettings)(_env_file=None, **kwargs))


def test_client_settings_from_env(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("SERVER_URL", "https://env.example.com/v1")
    monkeypatch.setenv("CLIENT_ROLE", "CEM")
    monkeypatch.setenv("CLIENT_DEPLOYMENT", "WAN")
    monkeypatch.setenv("SSL_CERTFILE", "./tests/localhost.chain.pem")

    settings = _make_settings()

    assert settings.server_url == "https://env.example.com/v1"
    assert settings.client_role == Role.CEM
    assert settings.client_deployment == Deployment.WAN
    assert settings.ssl_certfile == "./tests/localhost.chain.pem"


async def test_pairing_client_pair_delegates_to_low_level(mocker: MockerFixture) -> None:
    settings = _make_settings(
        server_url="https://s2.example.com/v1",
        pairing_token="pairing-token",
        pairing_s2_node_id="pairingnode",
        client_deployment=Deployment.WAN,
        domain_name="s2.example.com",
        client_role=Role.RM,
    )
    dao = Dao("sqlite://")

    low_level_pair = mocker.patch(
        "s2auth.client.pairing.low_level_pair",
        new=AsyncMock(return_value=True),
    )

    client = PairingClient.from_settings(settings, storage=dao)
    result = await client.pair()

    assert result.success is True
    assert result.pairing_s2_node_id == "pairingnode"
    low_level_pair.assert_awaited_once()
    call = low_level_pair.await_args
    assert call is not None
    assert call.kwargs["storage"] is dao
    assert call.kwargs["deployment"] == "WAN"
    assert call.kwargs["domain_name"] == "s2.example.com"


async def test_pairing_client_connect_uses_default_pairing_id(mocker: MockerFixture) -> None:
    settings = _make_settings(
        server_url="https://s2.example.com/v1",
        pairing_s2_node_id="node-123",
    )
    dao = Dao("sqlite://")

    low_level_connect = mocker.patch(
        "s2auth.client.pairing.low_level_connect",
        new=AsyncMock(return_value=True),
    )

    client = PairingClient.from_settings(settings, storage=dao)

    assert await client.connect() is True
    low_level_connect.assert_awaited_once_with(storage=dao, pairing_s2_node_id="node-123")


async def test_pairing_client_connect_does_not_require_uuid_client_id(mocker: MockerFixture) -> None:
    settings = _make_settings(
        client_s2_node_id="not-a-uuid",
        pairing_s2_node_id="node-123",
    )
    dao = Dao("sqlite://")

    low_level_connect = mocker.patch(
        "s2auth.client.pairing.low_level_connect",
        new=AsyncMock(return_value=True),
    )

    client = PairingClient.from_settings(settings, storage=dao)

    assert await client.connect() is True
    low_level_connect.assert_awaited_once_with(storage=dao, pairing_s2_node_id="node-123")


async def test_pairing_client_pair_with_custom_store(mocker: MockerFixture) -> None:
    settings = _make_settings(
        server_url="https://s2.example.com/v1",
        pairing_token="pairing-token",
        pairing_s2_node_id="custom-node",
        client_deployment=Deployment.WAN,
        domain_name="s2.example.com",
        client_role=Role.RM,
    )
    store = InMemoryStore()
    store.store_connection_details("custom-node", {"access_token": "token-123"})

    low_level_pair = mocker.patch(
        "s2auth.client.pairing.low_level_pair",
        new=AsyncMock(return_value=True),
    )

    client = PairingClient.from_settings(settings, storage=store)
    result = await client.pair()

    assert result.success is True
    assert result.pairing_s2_node_id == "custom-node"
    assert result.connection_details == {"access_token": "token-123"}
    low_level_pair.assert_awaited_once()
    call = low_level_pair.await_args
    assert call is not None
    assert call.kwargs["storage"] is store


async def test_pairing_client_connect_with_custom_store(mocker: MockerFixture) -> None:
    settings = _make_settings(
        pairing_s2_node_id="custom-node",
    )
    store = InMemoryStore()

    low_level_connect = mocker.patch(
        "s2auth.client.pairing.low_level_connect",
        new=AsyncMock(return_value=True),
    )

    client = PairingClient.from_settings(settings, storage=store)

    assert await client.connect() is True
    low_level_connect.assert_awaited_once_with(storage=store, pairing_s2_node_id="custom-node")


def test_detect_deployment_prefers_domain() -> None:
    deployment, reason = detect_deployment(
        pairing_url="https://localhost.local:8000/v1",
        domain_name="s2connect.example.com",
        certificate_file="./tests/localhost.chain.pem",
    )

    assert deployment == Deployment.WAN
    assert reason == "domain provided"


def test_build_pairing_settings_auto_detects_wan_domain() -> None:
    settings = _make_settings(
        supported_s2_versions=["v1"],
    )

    runtime_settings, warnings = build_pairing_settings(
        settings,
        server_url="https://example.com/v1",
        pairing_token="token-123",
        pairing_s2_node_id="pair-node",
        client_s2_node_id="550e8400-e29b-41d4-a716-446655440000",
        role="RM",
        deployment=None,
        domain_name=None,
        verify_tls=True,
        ssl_certfile=None,
        supported_s2_message_versions=None,
        communication_protocols=None,
        supported_hmac_hashing_algorithms=None,
        brand="ExampleHeatCo",
        client_device_type="Heatpump",
        client_model_name="SmartHeatPump X200",
    )

    assert runtime_settings.client_deployment == Deployment.WAN
    assert runtime_settings.domain_name == "example.com"
    assert any("Auto-detected deployment=WAN" in warning for warning in warnings)
    assert any("Auto-detected domain='example.com'" in warning for warning in warnings)
