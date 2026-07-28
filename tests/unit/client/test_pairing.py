import json
import os
from base64 import b64encode
from pathlib import PosixPath
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import httpx
import pytest
from pydantic import AnyUrl, TypeAdapter
from pytest_mock.plugin import MockerFixture

from s2auth.client.dao import Dao
from s2auth.client.pairing import (add_header, confirmToken, connect,
                                   finalize_pairing, pair,
                                   post_connection_details,
                                   request_connection_details,
                                   strip_pairing_url, unpair)
from s2auth.common.exceptions import S2PairingError
from s2auth.common.hmac import (create_challenge, create_pairing_code,
                                create_response)
from s2auth.common.model.s2_connect_common import (AccessToken, Deployment,
                                                   EndpointDescription,
                                                   NodeDescription, NodeId,
                                                   Role)
from s2auth.common.model.s2_connect_pairing import (
    ConnectionDetails, FinalizePairingPostRequest,
    HmacChallengeResponse,
    HmacHashingAlgorithm, PairingAttemptId,
    RequestConnectionDetailsPostRequest, RequestPairingPostRequest,
    RequestPairingPostResponse)

PAIRING_TOKEN: str = 'nua9nov3QNUd'
PAIRING_CODE: str = '550e8400-nua9nov3QNUd'
DOMAIN_NAME = 's2.example.com'
PENDING_TOKEN = create_pairing_code()
WS_TOKEN = create_pairing_code()


@pytest.fixture(autouse=True)
def mock_calculate_fingerprint(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("s2auth.client.pairing.calculate_fingerprint", return_value=b"")


def encode_base64_text(text: str) -> str:
    return b64encode(text.encode('ascii')).decode('ascii')


@pytest.fixture()
def dao(tmp_path: PosixPath) -> Dao:
    return Dao("sqlite:///" + os.path.join("sqlite://", tmp_path, "connection_details.db"))


@pytest.fixture()
def s2_client_description() -> NodeDescription:
    return NodeDescription(id=NodeId(UUID("550e8400-e29b-41d4-a716-446655440000")),
                             brand="ExampleHeatCo",
                             type="Heatpump",
                             modelName="SmartHeatPump X200",
                             role=Role("RM"))


def gen_s2_pairing_response(pairing_request: RequestPairingPostRequest) -> RequestPairingPostResponse:
    deployment = pairing_request.clientEndpointDescription.deployment or Deployment.WAN
    response = create_response(PAIRING_TOKEN, pairing_request.clientHmacChallenge, deployment, DOMAIN_NAME, b'')
    challenge_response: HmacChallengeResponse = HmacChallengeResponse(b64encode(response))

    s2_server_description = NodeDescription(id=NodeId(UUID("12345678-1234-1234-1234-123456789abc")),
                                              brand="ExampleCemCo",
                                              type="CEM",
                                              modelName="Cem P50",
                                              role=Role("CEM"))

    endpoint_description = EndpointDescription(name='Cem p50 endpoint', deployment=deployment)

    pid = PairingAttemptId("550e8400-e29b-41d4-a716-446655440000")
    return RequestPairingPostResponse(
        pairingAttemptId=pid,
        serverNodeDescription=s2_server_description,
        serverEndpointDescription=endpoint_description,
        selectedHmacHashingAlgorithm=HmacHashingAlgorithm.SHA256,
        clientHmacChallengeResponse=challenge_response,
        serverHmacChallenge=create_challenge())


async def test_paiting_wrong_url(dao: Dao, s2_client_description: NodeDescription) -> None:
    # testing calling url that does not exist
    with pytest.raises(S2PairingError) as excinfo:
        assert await pair(pairing_uri='http://s2server.example.com/v1',
                          pairing_code=PAIRING_CODE,
                          storage=dao,
                          role="RM",
                          deployment=Deployment.WAN,
                          supported_s2_message_versions=["v0.0.2-beta"],
                          supported_communication_protocols=["WebSocket"],
                          supportedHmacHashingAlgorithms=[HmacHashingAlgorithm.SHA256],
                          s2_client_description=s2_client_description,
                          domain_name=DOMAIN_NAME,
                              certificate_file="localhost.chain.pem")
    assert 'No address associated with hostname' in str(excinfo.value)


@pytest.fixture
def mock_AsyncClient_404(mocker: MockerFixture) -> tuple[MagicMock, MagicMock]:
    """
    Patches s2auth.client.pairing.httpx.AsyncClient so that:
      - `async with AsyncClient() as client:` works
      - `await client.post(url, json=...)` returns an httpx.Response
        whose JSON payload depends on what was posted.
    """
    # Build the client mock (we'll use AsyncMock for async call support)
    mock_client = MagicMock(name="AsyncClientMock")
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    async def post_side_effect(url: str, *args: Any, **kwargs: dict[str, Any]):
        req = httpx.Request("POST", url)  # attach this
        body = {"error": "Bad request"}
        return httpx.Response(
            404,
            content=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            request=req,  # <-- critical
        )

    # post must be AsyncMock to support `await client.post(...)`
    mock_client.post = AsyncMock(side_effect=post_side_effect)

    # Patch where your code constructs the client
    mocked_ctor = mocker.patch(
        "s2auth.client.pairing.httpx.AsyncClient",
        return_value=mock_client,
        autospec=True,
    )
    return mocked_ctor, mock_client


async def test_paiting_404(dao: Dao, mock_AsyncClient_404: tuple[MagicMock, MagicMock], s2_client_description: NodeDescription) -> None:
    with pytest.raises(S2PairingError) as excinfo:
        assert await pair(pairing_uri='http://s2server.example.com/v1',
                          pairing_code=PAIRING_TOKEN,
                          storage=dao,
                          role="RM",
                          deployment=Deployment.WAN,
                          supported_s2_message_versions=["v0.0.2-beta"],
                          supported_communication_protocols=["WebSocket"],
                          supportedHmacHashingAlgorithms=[HmacHashingAlgorithm.SHA256],
                          s2_client_description=s2_client_description,
                          domain_name=DOMAIN_NAME,
                          certificate_file="localhost.chain.pem")
    assert "Client error '404 Not Found'" in str(excinfo.value)


@pytest.fixture
def mock_AsyncClient(mocker: MockerFixture) -> tuple[MagicMock, MagicMock]:
    """
    Patches s2auth.client.pairing.httpx.AsyncClient so that:
      - `async with AsyncClient() as client:` works
      - `await client.post(url, json=...)` returns an httpx.Response
        whose JSON payload depends on what was posted.
    """
    # Build the client mock (we'll use AsyncMock for async call support)
    mock_client = MagicMock(name="AsyncClientMock")
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    # --- Define the side-effect for POST ---
    async def post_side_effect(url: str, *args: Any, **kwargs: dict[str, Any]):
        """
        Capture the payload the code posted and echo it in the response.
        Support both json=<obj> and data=<...>.
        """
        # Build a real httpx.Response so .json() parses bytes content
        request = httpx.Request("POST", url)

        if url.endswith('/requestPairing'):
            pairing_request = RequestPairingPostRequest.model_validate_json(str(kwargs["content"]))

            return httpx.Response(
                status_code=200,
                content=gen_s2_pairing_response(pairing_request).model_dump_json(),
                headers={"Content-Type": "application/json"},
                request=request,
            )
        elif url.endswith('/requestConnectionDetails'):
            RequestConnectionDetailsPostRequest.model_validate_json(str(kwargs["content"]))
            validated_url: AnyUrl = TypeAdapter(AnyUrl).validate_python('http://s2server.example.com/v1')
            connection_details = \
                ConnectionDetails(accessToken=AccessToken(create_pairing_code(length=32)),
                                  initiateSessionUrl=validated_url)
            return httpx.Response(
                status_code=200,
                content=connection_details.model_dump_json(),
                headers={"Content-Type": "application/json"},
                request=request,
            )
        elif url.endswith('/finalizePairing'):
            finalize_pairing_postRequest: FinalizePairingPostRequest = FinalizePairingPostRequest.model_validate_json(str(kwargs["content"]))
            if finalize_pairing_postRequest.success:
                return httpx.Response(status_code=204)
            else:
                return httpx.Response(status_code=401)
        elif url.endswith('/postConnectionDetails'):
            return httpx.Response(
                status_code=204,
                headers={"Content-Type": "application/json"},
                request=request,
            )
        elif url.endswith('/unpair'):
            return httpx.Response(
                status_code=204,
                headers={"Content-Type": "application/json"},
                request=request,
            )
        elif url.endswith('/initiateSession'):
            return httpx.Response(
                status_code=200,
                content=json.dumps({"selectedCommunicationProtocol": "WebSocket",
                                    "selectedS2MessageVersion": "v0.0.2-beta",
                                    "accessToken": PENDING_TOKEN}),
                headers={"Content-Type": "application/json"},
                request=request,
            )
        elif url.endswith('/confirmAccessToken'):
            return httpx.Response(
                status_code=200,
                content=json.dumps({"websocketToken": WS_TOKEN, "websocketUrl": "wss://example.com/v1/s2exampleWS"}),
                headers={"Content-Type": "application/json"},
                request=request,
            )
        else:
            print(url)
            assert False, f'post of wrong type received: {kwargs.get("content")} + {type(kwargs.get("content"))}'

    # post must be AsyncMock to support `await client.post(...)`
    mock_client.post = AsyncMock(side_effect=post_side_effect)

    # Patch where your code constructs the client
    mocked_ctor = mocker.patch(
        "s2auth.client.pairing.httpx.AsyncClient",
        return_value=mock_client,
        autospec=True,
    )
    return mocked_ctor, mock_client


async def test_request_connection_details(dao: Dao, mock_AsyncClient: tuple[MagicMock, MagicMock]) -> None:
    resp: dict[str, Any] = await request_connection_details(pairing_uri='http://s2server.example.com/v1',
                                                           attempt_id="550e8400-e29b-41d4-a716-446655440000",
                                                           hmacChallangeResponse=HmacChallengeResponse(b64encode(b"server-hmac-response")),
                                                           verify=True)
    assert 'accessToken' in resp
    assert resp['initiateSessionUrl'] == 'http://s2server.example.com/v1'


def test_add_header() -> None:
    assert add_header(token="bla_token") == {"Authorization": "Bearer bla_token", "Content-Type": "application/json"}
    assert add_header() == {"Content-Type": "application/json"}


def test_strip_pairing_url():
    assert strip_pairing_url("http://localhost") == "http://localhost"
    assert strip_pairing_url("http://localhost/bla") == "http://localhost/bla"
    assert strip_pairing_url("http://localhost/requestPairing") == "http://localhost"
    assert strip_pairing_url("http://localhost/initiateSession") == "http://localhost"
    assert strip_pairing_url("http://localhost/v1/initiateSession") == "http://localhost/v1"


async def test_finalize_pairing(dao: Dao, mock_AsyncClient: tuple[MagicMock, MagicMock]) -> None:
    response = await finalize_pairing("http://localhost", "550e8400-e29b-41d4-a716-446655440000", True, True)
    assert response.status_code == 204

    response = await finalize_pairing("http://localhost", "550e8400-e29b-41d4-a716-446655440000", False, True)
    assert response.status_code == 401


async def test_paiting_rm(dao: Dao,
                          mocker: MockerFixture,
                          mock_AsyncClient: tuple[MagicMock, MagicMock],
                          s2_client_description: NodeDescription) -> None:
    import s2auth.client.pairing as pairing

    request_connection_details_spy = mocker.spy(pairing, "request_connection_details")
    finalize_pairing_spy = mocker.spy(pairing, "finalize_pairing")
    post_connection_details_spy = mocker.spy(pairing, "post_connection_details")

    assert await pair(pairing_uri='http://s2server.example.com/v1',
                      pairing_code=PAIRING_TOKEN,
                      storage=dao,
                      role="RM",
                      deployment=Deployment.WAN,
                      supported_s2_message_versions=["v0.0.2-beta"],
                      supported_communication_protocols=["WebSocket"],
                      supportedHmacHashingAlgorithms=[HmacHashingAlgorithm.SHA256],
                      s2_client_description=s2_client_description,
                      domain_name=DOMAIN_NAME,
                      certificate_file="localhost.chain.pem")
    request_connection_details_spy.assert_awaited_once()
    finalize_pairing_spy.assert_awaited_once()
    post_connection_details_spy.assert_not_awaited()

    server_s2_node_id: str = str(s2_client_description.id.model_dump(exclude_none=True))
    assert await connect(pairing_uri='http://s2server.example.com/v1', storage=dao, supported_s2_message_versions=["v0.0.2-beta"], supported_communication_protocols=["WebSocket"], s2_client_description=s2_client_description, serverS2NodeId=server_s2_node_id)
    connection_details = dao.load_connection_details(server_s2_node_id)
    assert connection_details is not None
    assert connection_details['accessToken'] == PENDING_TOKEN

    assert connection_details['websocketToken'] != connection_details['accessToken']
    assert connection_details['websocketToken'] == WS_TOKEN
    assert connection_details['websocketUrl'] == 'wss://example.com/v1/s2exampleWS'


async def test_paiting_cem(dao: Dao, mocker: MockerFixture, mock_AsyncClient: tuple[MagicMock, MagicMock], s2_client_description: NodeDescription) -> None:
    import s2auth.client.pairing as pairing

    request_connection_details_spy = mocker.spy(pairing, "request_connection_details")
    finalize_pairing_spy = mocker.spy(pairing, "finalize_pairing")
    post_connection_details_spy = mocker.spy(pairing, "post_connection_details")

    assert await pair(pairing_uri='http://s2server.example.com/v1',
                      pairing_code=PAIRING_TOKEN,
                      storage=dao,
                      role="CEM",
                      deployment=Deployment.WAN,
                      supported_s2_message_versions=["v0.0.2-beta"],
                      supported_communication_protocols=["WebSocket"],
                      supportedHmacHashingAlgorithms=[HmacHashingAlgorithm.SHA256],
                      s2_client_description=s2_client_description,
                      domain_name=DOMAIN_NAME,
                      certificate_file="localhost.chain.pem")
    request_connection_details_spy.assert_not_awaited()
    finalize_pairing_spy.assert_awaited_once()
    post_connection_details_spy.assert_awaited_once()


async def test_get_pairing_token_str(dao: Dao,
                                     mocker: MockerFixture,
                                     mock_AsyncClient: tuple[MagicMock, MagicMock],
                                     s2_client_description: NodeDescription) -> None:
    assert await pair(pairing_uri='http://s2server.example.com/v1',
                      pairing_code=PAIRING_TOKEN,
                      storage=dao,
                      role="RM",
                      deployment=Deployment.WAN,
                      supported_s2_message_versions=["v0.0.2-beta"],
                      supported_communication_protocols=["WebSocket"],
                      supportedHmacHashingAlgorithms=[HmacHashingAlgorithm.SHA256],
                      s2_client_description=s2_client_description,
                      domain_name=DOMAIN_NAME,
                      certificate_file="localhost.chain.pem")

    client_s2_node_id = str(s2_client_description.id.model_dump(exclude_none=True))
    connection_details: dict[str, Any] | None = dao.load_connection_details(client_s2_node_id)
    assert connection_details is not None
    assert isinstance(connection_details['accessToken'], str), connection_details['accessToken']
    assert len(connection_details['accessToken']) > 0


async def test_post_connection_details(dao: Dao, mock_AsyncClient: tuple[MagicMock, MagicMock]) -> None:
    validated_url: AnyUrl = TypeAdapter(AnyUrl).validate_python('http://s2server.example.com/v1')
    connection_details: ConnectionDetails = \
        ConnectionDetails(accessToken=create_pairing_code(length=32),
                          initiateSessionUrl=validated_url)
    await post_connection_details('http://s2server.example.com/v1',
                                  "550e8400-e29b-41d4-a716-446655440000", connection_details,
                                  HmacChallengeResponse(b64encode(b"server-hmac-response")),
                                  verify=True)


async def test_confirmToken(dao: Dao, mock_AsyncClient: tuple[MagicMock, MagicMock],
                            s2_client_description: NodeDescription) -> None:
    await confirmToken('http://s2server.example.com/v1', dao, s2_client_description.id.model_dump(), "550e8400-e29b-41d4-a716-446655440000", False)


async def test_unpair(dao: Dao, mock_AsyncClient: tuple[MagicMock, MagicMock],
                      s2_client_description: NodeDescription) -> None:
    assert await unpair('http://s2server.example.com/v1', dao, s2_client_description.id.model_dump(), "550e8400-e29b-41d4-a716-446655440000", verify=True)
