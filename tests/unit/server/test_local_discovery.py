from dataclasses import dataclass
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from pytest import MonkeyPatch
from pytest_mock.plugin import MockerFixture

from s2auth.server import local_discovery
from s2auth.server.local_discovery import LocalDiscoveryRegistration


@dataclass
class _FakeConfig:
    domain_name: str


@dataclass
class _FakeSettings:
    server_port: int
    pairing_node_id: str
    server_hostname: str


def test_local_ipv4_returns_loopback_on_socket_error(monkeypatch: MonkeyPatch) -> None:
    fake_socket = MagicMock()
    fake_socket.connect.side_effect = OSError("boom")
    fake_socket_cls = MagicMock(return_value=fake_socket)
    monkeypatch.setattr(local_discovery.socket, "socket", fake_socket_cls)

    assert local_discovery._local_ipv4() == "127.0.0.1"  # pyright: ignore[reportPrivateUsage]
    fake_socket.close.assert_called_once_with()


def test_send_local_discover_registers_service_with_expected_payload(mocker: MockerFixture) -> None:
    cfg = cast(Any, _FakeConfig(domain_name="local"))
    settings = cast(Any, _FakeSettings(server_port=8443, pairing_node_id="pairnode1", server_hostname='localhost'))

    mocker.patch("s2auth.server.local_discovery._local_ipv4", return_value="127.0.0.1")

    mock_service_info = object()
    mock_subtype_service_info = object()
    service_info_ctor = mocker.patch(
        "s2auth.server.local_discovery.ServiceInfo",
        side_effect=[mock_service_info, mock_subtype_service_info],
    )
    mock_zeroconf = mocker.MagicMock()
    zeroconf_ctor = mocker.patch(
        "s2auth.server.local_discovery.Zeroconf",
        return_value=mock_zeroconf,
    )

    registration = local_discovery.send_local_discover(cfg, settings)

    zeroconf_ctor.assert_called_once_with()
    assert service_info_ctor.call_count == 2

    base_kwargs = service_info_ctor.call_args_list[0].kwargs
    subtype_kwargs = service_info_ctor.call_args_list[1].kwargs

    assert base_kwargs["type_"] == "_s2connect._tcp.local."
    assert base_kwargs["name"] == "localhost._s2connect._tcp.local."
    assert base_kwargs["port"] == 8443
    assert base_kwargs["server"] == "localhost.local"
    assert base_kwargs["properties"]["pairingUrl"] == "https://localhost.local:8443/pairing/"
    assert base_kwargs["properties"]["deployment"] == "LAN"

    assert subtype_kwargs["type_"] == "_cem._sub._s2connect._tcp.local."
    assert subtype_kwargs["name"] == "localhost-cem._s2connect._tcp.local."
    assert subtype_kwargs["port"] == 8443
    assert subtype_kwargs["server"] == "localhost.local"
    assert subtype_kwargs["properties"]["pairingUrl"] == "https://localhost.local:8443/pairing/"
    assert subtype_kwargs["properties"]["deployment"] == "LAN"

    assert mock_zeroconf.register_service.call_count == 2
    mock_zeroconf.register_service.assert_any_call(mock_service_info)
    mock_zeroconf.register_service.assert_any_call(mock_subtype_service_info)
    assert isinstance(registration, LocalDiscoveryRegistration)
    assert registration.zeroconf is mock_zeroconf
    assert registration.service_infos == [mock_service_info, mock_subtype_service_info]


def test_registration_close_unregisters_then_closes() -> None:
    mock_zeroconf = MagicMock()
    service_info = object()
    subtype_service_info = object()
    registration = LocalDiscoveryRegistration(
        zeroconf=cast(Any, mock_zeroconf),
        service_infos=[cast(Any, service_info), cast(Any, subtype_service_info)],
    )

    registration.close()

    assert mock_zeroconf.unregister_service.call_count == 2
    mock_zeroconf.unregister_service.assert_any_call(service_info)
    mock_zeroconf.unregister_service.assert_any_call(subtype_service_info)
    mock_zeroconf.close.assert_called_once_with()


def test_registration_close_closes_even_if_unregister_fails() -> None:
    mock_zeroconf = MagicMock()
    mock_zeroconf.unregister_service.side_effect = RuntimeError("unregister failed")
    registration = LocalDiscoveryRegistration(
        zeroconf=cast(Any, mock_zeroconf),
        service_infos=[cast(Any, object())],
    )

    with pytest.raises(RuntimeError, match="unregister failed"):
        registration.close()

    mock_zeroconf.close.assert_called_once_with()
