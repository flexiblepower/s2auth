from argparse import Namespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

from pytest import MonkeyPatch
from pytest_mock.plugin import MockerFixture

from s2auth.client import main as compat_main
from s2auth.client.settings import ClientSettings
from s2auth.reference.client import main as client_main


async def test_run_client_uses_env_backed_defaults(
    monkeypatch: MonkeyPatch,
    mocker: MockerFixture,
) -> None:
    monkeypatch.setenv("SERVER_URL", "https://localhost.local:8000/v1")
    monkeypatch.setenv("SSL_CERTFILE", "./tests/localhost.chain.pem")
    monkeypatch.setenv("CLIENT_ROLE", "RM")
    monkeypatch.setenv("PAIRING_S2_NODE_ID", "9e0e3a62-1b2d-4bb1-89ca-7bc0d9a7e09c")

    captured: dict[str, object] = {}

    async def capture_pairing_mode(
        args: Namespace,
        settings: ClientSettings,
        dao: object,
        pairing_s2_node_id: str | None,
        clientS2NodeId: UUID,
        storage_key: str,
    ) -> None:
        captured["server_url"] = args.server_url
        captured["certificate_file"] = args.certificate_file
        captured["pairing_s2_node_id"] = pairing_s2_node_id
        captured["storage_key"] = storage_key

    mocker.patch("s2auth.reference.client.main.Dao", return_value=MagicMock())
    mocker.patch("s2auth.reference.client.main._run_pairing_mode", new=AsyncMock(side_effect=capture_pairing_mode))
    mocker.patch("sys.argv", ["client", "--pairing_token", "DkYf"])

    await client_main._run_client()  # pyright: ignore[reportPrivateUsage]

    assert captured["server_url"] == "https://localhost.local:8000/v1"
    assert captured["certificate_file"] == "./tests/localhost.chain.pem"
    assert captured["pairing_s2_node_id"] == "9e0e3a62-1b2d-4bb1-89ca-7bc0d9a7e09c"
    assert captured["storage_key"] == "9e0e3a62-1b2d-4bb1-89ca-7bc0d9a7e09c"


def test_compat_client_main_delegates(mocker: MockerFixture) -> None:
    delegated_main = mocker.patch("s2auth.reference.client.main.main")

    compat_main.main()

    delegated_main.assert_called_once_with()
