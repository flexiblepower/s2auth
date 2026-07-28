import os
from pathlib import PosixPath

from s2auth.client.dao import Dao


def test_load_connection_details_roundtrip(tmp_path: PosixPath) -> None:
    dao = Dao(f"sqlite:///{os.path.join(str(tmp_path), 'connection_details.db')}")
    s2_node_id = "550e8400-e29b-41d4-a716-446655440000"

    dao.store_connection_details(
        s2_node_id,
        {
            "initiateSessionUrl": "https://test.example.com",
            "accessToken": "AHsUZCP0B+uXe6k/Pjm9aFKNWouRjWdnoD2DhIi2844=",
            "supportedS2MessageVersion": "v0.0.2-beta",
            "selectedCommunicationProtocol": "WebSocket",
            "serverNodeDescription": '{"id":"123","brand":"Brand","type":"CEM","modelName":"Model","role":"CEM"}',
            "serverEndpointDescription": '{"name":"Endpoint","logoUrl":"https://logo.example.com","deployment":"WAN"}',
        },
    )

    details = dao.load_connection_details(s2_node_id)

    assert details is not None
    assert details["s2_node_id"] == s2_node_id
    assert details["initiateSessionUrl"] == "https://test.example.com"
    assert details["accessToken"] == "AHsUZCP0B+uXe6k/Pjm9aFKNWouRjWdnoD2DhIi2844="
    assert details["supportedS2MessageVersion"] == "v0.0.2-beta"
    assert details["selectedCommunicationProtocol"] == "WebSocket"
    assert details["serverNodeDescription"] == '{"id":"123","brand":"Brand","type":"CEM","modelName":"Model","role":"CEM"}'
    assert details["serverEndpointDescription"] == '{"name":"Endpoint","logoUrl":"https://logo.example.com","deployment":"WAN"}'


def test_load_connection_details_missing_node(tmp_path: PosixPath) -> None:
    dao = Dao(f"sqlite:///{os.path.join(str(tmp_path), 'connection_details.db')}")

    assert dao.load_connection_details("missing-node") is None


def test_remove_connection_details(tmp_path: PosixPath) -> None:
    dao = Dao(f"sqlite:///{os.path.join(str(tmp_path), 'connection_details.db')}")
    s2_node_id = "550e8400-e29b-41d4-a716-446655440000"

    dao.store_connection_details(
        s2_node_id,
        {
            "initiateSessionUrl": "https://test.example.com",
            "accessToken": "token-value",
        },
    )

    assert dao.remove_connection_details(s2_node_id) is True
    assert dao.load_connection_details(s2_node_id) is None
    assert dao.remove_connection_details("missing-node") is False
