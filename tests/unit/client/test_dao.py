import os
from pathlib import PosixPath

from s2auth.client.dao import Dao


def test_load_connection_details_roundtrip(tmp_path: PosixPath) -> None:
    dao = Dao(f"sqlite:///{os.path.join(str(tmp_path), 'connection_details.db')}")
    s2_node_id = "550e8400-e29b-41d4-a716-446655440000"

    dao.store_connection_details(
        s2_node_id,
        {
            "client_s2_node_id": "client_s2_node_id",
            "pairing_server_url": "https://pairing.example.com/v1",
            "verify_tls": True,
            "ssl_certfile": "path/to/ca_cert.pem",
            "initiate_session_url": "https://test.example.com",
            "access_token": "AHsUZCP0B+uXe6k/Pjm9aFKNWouRjWdnoD2DhIi2844=",
            "supported_s2_message_versions": ["v0.0.2-beta"],
            "supported_communication_protocols": ["WebSocket"],
            "supported_hmac_hashing_algorithms": ["SHA256"],
            "selected_s2_message_version": "v0.0.2-beta",
            "selected_communication_protocol": "WebSocket",
            "selected_hmac_hashing_algorithm": "SHA256",
            "server_node_description": '{"id":"123","brand":"Brand","type":"CEM","modelName":"Model","role":"CEM"}',
            "server_endpoint_description": '{"name":"Endpoint","logoUrl":"https://logo.example.com","deployment":"WAN"}',
        },
    )

    details = dao.load_connection_details(s2_node_id)

    assert details is not None
    assert details["s2_node_id"] == s2_node_id
    assert details["pairing_server_url"] == "https://pairing.example.com/v1"
    assert details["verify_tls"] is True
    assert details["ssl_certfile"] == "path/to/ca_cert.pem"
    assert details["initiate_session_url"] == "https://test.example.com"
    assert details["access_token"] == "AHsUZCP0B+uXe6k/Pjm9aFKNWouRjWdnoD2DhIi2844="
    assert details["supported_s2_message_versions"] == ["v0.0.2-beta"]
    assert details["supported_communication_protocols"] == ["WebSocket"]
    assert details["supported_hmac_hashing_algorithms"] == ["SHA256"]
    assert details["selected_s2_message_version"] == "v0.0.2-beta"
    assert details["selected_communication_protocol"] == "WebSocket"
    assert details["selected_hmac_hashing_algorithm"] == "SHA256"
    assert details["server_node_description"] == '{"id":"123","brand":"Brand","type":"CEM","modelName":"Model","role":"CEM"}'
    assert details["server_endpoint_description"] == '{"name":"Endpoint","logoUrl":"https://logo.example.com","deployment":"WAN"}'


def test_load_connection_details_missing_node(tmp_path: PosixPath) -> None:
    dao = Dao(f"sqlite:///{os.path.join(str(tmp_path), 'connection_details.db')}")

    assert dao.load_connection_details("missing-node") is None


def test_remove_connection_details(tmp_path: PosixPath) -> None:
    dao = Dao(f"sqlite:///{os.path.join(str(tmp_path), 'connection_details.db')}")
    s2_node_id = "550e8400-e29b-41d4-a716-446655440000"

    dao.store_connection_details(
        s2_node_id,
        {
            "pairing_server_url": "https://pairing.example.com/v1",
            "initiate_session_url": "https://test.example.com",
            "access_token": "token-value",
        },
    )

    assert dao.remove_connection_details(s2_node_id) is True
    assert dao.load_connection_details(s2_node_id) is None
    assert dao.remove_connection_details("missing-node") is False
