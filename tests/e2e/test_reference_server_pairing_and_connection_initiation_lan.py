from __future__ import annotations

import socket
import ssl
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
from wepositive_di import override_provider

from s2auth.common.hmac import (
    calculate_certificate_fingerprint_from_certificate_file,
    create_response,
)
from s2auth.common.model.s2_connect_common import CommunicationProtocol, Deployment
from s2auth.common.model.s2_connect_pairing import HmacChallenge
from s2auth.server.settings import Settings, settings as settings_provider

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
        supported_s2_versions=["v1"],
        supported_s2_connect_versions=["v1"],
        cem_s2_node_id=UUID("22222222-2222-4222-8222-222222222222"),
        cem_type="CEM",
        cem_model_name="Reference CEM",
        cem_brand="Reference",
        cem_url=AnyUrl("http://127.0.0.1/connection/"),
        cem_deployment_type=Deployment.LAN,
        default_pairing_token="testtoken",
        ssl_certfile="tests/localhost.chain.pem",
    )


@pytest.fixture
def pairing_token() -> str:
    # Must match DEFAULT_PAIRING_TOKEN set in reference_server fixture
    return "testtoken"


@pytest.fixture
def domain_name() -> str:
    return "s2.example.com"


@pytest.fixture
def client_node_id() -> UUID:
    return UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
def world() -> PairingWorld:
    return PairingWorld()


@pytest.fixture
def certificate_fingerprint() -> bytes:
    return calculate_certificate_fingerprint_from_certificate_file(
        "tests/localhost.chain.pem"
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def reference_server(
    monkeypatch: pytest.MonkeyPatch,
    reference_settings: Settings,
    domain_name: str,
) -> Iterator[str]:
    monkeypatch.setenv("PAIRING_NODE_ID", reference_settings.pairing_node_id)
    monkeypatch.setenv("SERVER_S2_NODE_ID", str(reference_settings.server_s2_node_id))
    monkeypatch.setenv("CEM_S2_NODE_ID", str(reference_settings.cem_s2_node_id))
    monkeypatch.setenv("CEM_TYPE", reference_settings.cem_type)
    monkeypatch.setenv("CEM_MODEL_NAME", reference_settings.cem_model_name)
    monkeypatch.setenv("CEM_BRAND", reference_settings.cem_brand)
    monkeypatch.setenv("CEM_DEPLOYMENT_TYPE", "LAN")
    monkeypatch.setenv("DOMAIN_NAME", domain_name)
    monkeypatch.setenv("SUPPORTED_S2_VERSIONS", str(reference_settings.supported_s2_versions).replace("'", '"'))
    monkeypatch.setenv("SUPPORTED_S2_CONNECT_VERSIONS", str(reference_settings.supported_s2_connect_versions).replace("'", '"'))

    port = _free_port()
    monkeypatch.setenv("SSL_CERTFILE", "tests/localhost.chain.pem")
    monkeypatch.setenv("SSL_KEYFILE", "tests/localhost.key")
    monkeypatch.setenv("DEFAULT_PAIRING_TOKEN", "testtoken")

    config = uvicorn.Config(
        "s2auth.reference.server.main:app",
        host="127.0.0.1",
        port=port,
        log_level="warning",
        lifespan="on",
        ssl_certfile="tests/localhost.chain.pem",
        ssl_keyfile="tests/localhost.key",
    )
    def test_settings_provider() -> Settings:
        return reference_settings

    override_provider(settings_provider, test_settings_provider)

    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base_url = f"https://127.0.0.1:{port}"
    deadline = time.monotonic() + 15
    time.sleep(0.5)
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{base_url}/pairing/", timeout=1.0, verify=False)
            if response.status_code == 200:
                break
        except Exception:
            time.sleep(0.1)
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
            "clientEndpointDescription": {"deployment": "LAN"},
            "nodeIdAlias": reference_settings.pairing_node_id,
            "supportedCommunicationProtocols": ["WebSocket"],
            "supportedS2MessageVersions": [reference_settings.supported_s2_versions[0]],
            "supportedHmacHashingAlgorithms": ["SHA256"],
            "clientHmacChallenge": "R0a+6F8zSQwT9RJcxaa6T6/gKKq6tCyeRmcl9BNlc0jboFj8FsN4dlrhvVoH/P6Upc5gWCe9c8qvg5wxPOzZXLS6DSWL1lrzv7VnnRqbkeLxpizG6ZTShkw2rwyKEUMccOpKIqG3bH+ahhMjyP10fCOFi8K/E/VjfUcpCRHdZU4=",
        },
        timeout=5,
        verify=False,
    )
    assert response.status_code == 200
    world.request_pairing_response = response.json()


@when("the client requests connection details")
def client_requests_connection_details(
    world: PairingWorld,
    reference_settings: Settings,
    pairing_token: str,
    domain_name: str,
    certificate_fingerprint: bytes,
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
        deployment=Deployment.LAN,
        domain_name=domain_name,
        fingerprint=certificate_fingerprint,
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
        verify=False,
    )
    assert response.status_code == 200
    world.connection_details_response = response.json()


@then("the connection initiation endpoint is the reference connection router URL")
def connection_initiation_endpoint_is_reference_router(world: PairingWorld) -> None:
    assert world.connection_details_response is not None
    assert "accessToken" in world.connection_details_response


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
        verify=False,
    )
    assert response.status_code == 204


@when("the client initiates a connection")
def client_initiates_connection(
    world: PairingWorld,
    reference_settings: Settings,
    client_node_id: UUID,
) -> None:
    assert world.connection_details_response is not None
    response = httpx.post(
        f"{world.base_url}/pairing/{reference_settings.supported_s2_connect_versions[0]}/initiateSession",
        headers={
            "Authorization": f"Bearer {world.connection_details_response['accessToken']}",
        },
        json={
            "clientNodeId": str(client_node_id),
            "serverNodeId": str(reference_settings.server_s2_node_id),
            "supportedS2MessageVersions": reference_settings.supported_s2_versions,
            "supportedCommunicationProtocols": ["WebSocket"],
        },
        timeout=5,
        verify=False,
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
    assert endpoint_description["deployment"] == "LAN"
    assert node_description["id"] == str(reference_settings.cem_s2_node_id)
    assert node_description["brand"] == reference_settings.cem_brand
    assert node_description["role"] == "CEM"
