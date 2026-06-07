from __future__ import annotations

import socket
import threading
import time
from base64 import b64encode
from collections.abc import Iterator
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
import uvicorn
from pydantic import AnyUrl
from pytest_bdd import given, scenarios, then, when

from s2auth.common.hmac import create_challenge, create_response
from s2auth.common.model.s2_connect_common import CommunicationProtocol
from s2auth.common.model.s2_connect_pairing import HmacChallenge
from s2auth.server.settings import Settings

scenarios("features/reference_server_pairing_and_connection_initiation.feature")


class PairingWorld:
    base_url: str = ""
    request_pairing_response: dict[str, object] | None = None
    connection_details_response: dict[str, object] | None = None
    connection_initiation_response: dict[str, object] | None = None


@pytest.fixture
def reference_settings() -> Settings:
    return Settings(
        pairing_node_id="PAIR1234",
        server_s2_node_id=UUID("11111111-1111-4111-8111-111111111111"),
        supported_communication_protocols=[CommunicationProtocol.WebSocket],
        supported_s2_versions=["v0.02-beta"],
        supported_s2_connect_versions=["v1.0-beta-2"],
        cem_s2_node_id=UUID("22222222-2222-4222-8222-222222222222"),
        cem_type="CEM",
        cem_model_name="Reference CEM",
        cem_brand="Reference",
        cem_url=AnyUrl("http://127.0.0.1/connection/"),
    )


@pytest.fixture
def pairing_token() -> str:
    return "pairingToken123"


@pytest.fixture
def hmac_salt() -> str:
    return "s2.example.com"


@pytest.fixture
def client_node_id() -> UUID:
    return UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
def world() -> PairingWorld:
    return PairingWorld()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def reference_server(
    monkeypatch: pytest.MonkeyPatch,
    reference_settings: Settings,
    hmac_salt: str,
) -> Iterator[str]:
    monkeypatch.setenv("PAIRING_NODE_ID", reference_settings.pairing_node_id)
    monkeypatch.setenv("SERVER_S2_NODE_ID", str(reference_settings.server_s2_node_id))
    monkeypatch.setenv("CEM_S2_NODE_ID", str(reference_settings.cem_s2_node_id))
    monkeypatch.setenv("CEM_TYPE", reference_settings.cem_type)
    monkeypatch.setenv("CEM_MODEL_NAME", reference_settings.cem_model_name)
    monkeypatch.setenv("CEM_BRAND", reference_settings.cem_brand)
    monkeypatch.setenv("HMAC_SALT", hmac_salt)

    port = _free_port()
    config = uvicorn.Config(
        "s2auth.reference.server.main:app",
        host="127.0.0.1",
        port=port,
        log_level="warning",
        lifespan="on",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{base_url}/pairing/", timeout=0.5)
            if response.status_code == 200:
                break
        except httpx.TransportError:
            time.sleep(0.05)
    else:
        server.should_exit = True
        thread.join(timeout=5)
        raise RuntimeError("Reference server did not start")

    try:
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@given("the reference server is running")
def reference_server_is_running(
    reference_server: str,
    world: PairingWorld,
) -> None:
    world.base_url = reference_server


@when("user alice begins pairing with a pairing token")
def user_begins_pairing(world: PairingWorld, pairing_token: str) -> None:
    response = httpx.post(
        f"{world.base_url}/pairing/userBeginPairing",
        auth=("alice", "alice"),
        json=pairing_token,
        timeout=5,
    )
    assert response.status_code == 200


@when("the client requests pairing")
def client_requests_pairing(
    world: PairingWorld,
    reference_settings: Settings,
    client_node_id: UUID,
) -> None:
    response = httpx.post(
        f"{world.base_url}/pairing/{reference_settings.supported_s2_connect_versions[0]}/requestPairing",
        json={
            "clientNodeDescription": {
                "id": str(client_node_id),
                "brand": "ClientBrand",
                "role": "RM",
                "type": "HeatPump",
                "modelName": "HP-1",
            },
            "clientEndpointDescription": {"deployment": "WAN"},
            "nodeIdAlias": reference_settings.pairing_node_id,
            "supportedCommunicationProtocols": ["WebSocket"],
            "supportedS2MessageVersions": [reference_settings.supported_s2_versions[0]],
            "supportedHmacHashingAlgorithms": ["SHA256"],
            "clientHmacChallenge": b64encode(create_challenge().root).decode(
                "utf-8"
            ),
        },
        timeout=5,
    )
    assert response.status_code == 200
    world.request_pairing_response = response.json()


@when("the client requests connection details")
def client_requests_connection_details(
    world: PairingWorld,
    reference_settings: Settings,
    pairing_token: str,
    hmac_salt: str,
) -> None:
    assert world.request_pairing_response is not None
    server_challenge = HmacChallenge(
        root=str(world.request_pairing_response["serverHmacChallenge"]).encode(
            "utf-8"
        )
    )
    hmac_response = create_response(
        pairing_token=pairing_token,
        challenge=server_challenge,
        hmac_salt=hmac_salt,
    )
    response = httpx.post(
        f"{world.base_url}/pairing/{reference_settings.supported_s2_connect_versions[0]}/requestConnectionDetails",
        headers={
            "pairingAttemptId": str(
                world.request_pairing_response["pairingAttemptId"]
            )
        },
        json={
            "serverHmacChallengeResponse": b64encode(hmac_response).decode(
                "utf-8"
            )
        },
        timeout=5,
    )
    assert response.status_code == 200
    world.connection_details_response = response.json()


@then("the connection initiation endpoint is the reference connection router URL")
def connection_initiation_endpoint_is_reference_router(world: PairingWorld) -> None:
    assert world.connection_details_response is not None
    assert (
        world.connection_details_response["initiateConnectionUrl"]
        == f"{world.base_url}/connection/"
    )


@when("the client finalizes pairing successfully")
def client_finalizes_pairing(
    world: PairingWorld,
    reference_settings: Settings,
) -> None:
    assert world.request_pairing_response is not None
    response = httpx.post(
        f"{world.base_url}/pairing/{reference_settings.supported_s2_connect_versions[0]}/finalizePairing",
        headers={
            "pairingAttemptId": str(
                world.request_pairing_response["pairingAttemptId"]
            )
        },
        json={"success": True},
        timeout=5,
    )
    assert response.status_code == 200


@when("the client initiates a connection")
def client_initiates_connection(
    world: PairingWorld,
    reference_settings: Settings,
    client_node_id: UUID,
) -> None:
    assert world.connection_details_response is not None
    response = httpx.post(
        f"{world.base_url}/connection/{reference_settings.supported_s2_connect_versions[0]}/initiateConnection",
        headers={
            "accessToken": str(world.connection_details_response["accessToken"]),
        },
        json={
            "clientNodeId": str(client_node_id),
            "serverNodeId": str(reference_settings.server_s2_node_id),
            "supportedS2MessageVersions": reference_settings.supported_s2_versions,
            "supportedCommunicationProtocols": ["WebSocket"],
        },
        timeout=5,
    )
    assert response.status_code == 200
    world.connection_initiation_response = response.json()


@then("the connection initiation response contains the negotiated connection details")
def connection_initiation_response_contains_negotiated_details(
    world: PairingWorld,
    reference_settings: Settings,
) -> None:
    assert world.connection_initiation_response is not None
    response = world.connection_initiation_response
    endpoint_description = cast(dict[str, Any], response["serverEndpointDescription"])
    node_description = cast(dict[str, Any], response["serverNodeDescription"])
    assert response["selectedCommunicationProtocol"] == "WebSocket"
    assert response["selectedS2MessageVersion"] == reference_settings.supported_s2_versions[0]
    assert response["accessToken"]
    assert endpoint_description["deployment"] == "WAN"
    assert node_description["id"] == str(reference_settings.cem_s2_node_id)
    assert node_description["brand"] == reference_settings.cem_brand
    assert node_description["role"] == "CEM"
