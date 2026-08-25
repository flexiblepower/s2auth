from typing import Any, cast
from unittest.mock import AsyncMock

from pytest import MonkeyPatch
from pytest_mock.plugin import MockerFixture

from s2auth.client.dao import Dao
from s2auth.client.orchestrator import PairingClient
from s2auth.client.settings import ClientSettings
from s2auth.common.model.s2_connect_common import Deployment, Role


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
        "s2auth.client.orchestrator.low_level_pair",
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
        "s2auth.client.orchestrator.low_level_connect",
        new=AsyncMock(return_value=True),
    )

    client = PairingClient.from_settings(settings, storage=dao)

    assert await client.connect() is True
    low_level_connect.assert_awaited_once_with(storage=dao, pairing_s2_node_id="node-123")
