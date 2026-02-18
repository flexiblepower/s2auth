import json
import os
from base64 import b64encode, urlsafe_b64encode
from pathlib import PosixPath
from secrets import token_bytes
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import httpx
import pytest
from pydantic import AnyUrl, TypeAdapter
from pytest_mock.plugin import MockerFixture
from s2auth.client.dao import Dao
from s2auth.client.pairing import (ConnectionClient, PairingClient, add_header,
                                   strip_pairing_url)
from s2auth.common.exceptions import S2PairingError
from s2auth.common.hmac import create_challenge, create_response
from s2auth.common.model.s2_over_ip_common import (AccessToken,
                                                   CommunicationProtocol,
                                                   CommunicationToken,
                                                   Deployment,
                                                   S2EndpointDescription,
                                                   S2NodeDescription, S2NodeId,
                                                   S2Role)
from s2auth.common.model.s2_over_ip_connection_init import \
    WebSocketCommunicationDetails
from s2auth.common.model.s2_over_ip_pairing import (
    ConnectionDetails, FinalizePairingPostRequest, HmacChallengeResponse,
    HmacHashingAlgorithm, PairingAttemptId,
    RequestConnectionDetailsPostRequest, RequestPairingPostRequest,
    RequestPairingPostResponse)

PAIRING_TOKEN: str = 'nua9nov3QNUd'

@pytest.fixture()
def dao(tmp_path: PosixPath) -> Dao:
    return Dao("sqlite:///" + os.path.join("sqlite://", tmp_path, "connection_details.db"))


@pytest.fixture()
def pairing_client_rm(dao: Dao) -> PairingClient:
    return PairingClient(pairing_uri='http://s2server.example.com/requestPairing',
                         pairing_token=PAIRING_TOKEN,
                         storage=dao,
                         role="RM",
                         deployment="WAN",
                         supported_s2_message_versions=["NEN-EN 50491-12-2"],
                         supported_communication_protocols=["WebSocket"],
                         supportedHmacHashingAlgorithms=[HmacHashingAlgorithm.SHA256])

@pytest.fixture()
def pairing_client_cem(dao: Dao) -> PairingClient:
    return PairingClient(pairing_uri='http://s2server.example.com/requestPairing',
                         pairing_token=PAIRING_TOKEN,
                         storage=dao,
                         role="CEM",
                         deployment="WAN",
                         supported_s2_message_versions=["NEN-EN 50491-12-2"],
                         supported_communication_protocols=["WebSocket"],
                         supportedHmacHashingAlgorithms=[HmacHashingAlgorithm.SHA256])

@pytest.fixture()
def connection_client(dao: Dao) -> ConnectionClient:
    return ConnectionClient(client_uri='http://s2server.example.com/initiateConnection',
                            storage=dao,
                            role="RM",
                            deployment="WAN",
                            supported_s2_message_versions=["0.0.1-beta", "0.0.2-beta"],
                            supported_communication_protocols=["WebSocket"])


@pytest.fixture()
def s2_client_description() -> S2NodeDescription:
    return S2NodeDescription(id=S2NodeId(UUID("550e8400-e29b-41d4-a716-446655440000")),
                             brand="ExampleHeatCo",
                             type="Heatpump",
                             modelName="SmartHeatPump X200",
                             role=S2Role("RM"))


def gen_s2_pairing_response(pairing_request: RequestPairingPostRequest) -> RequestPairingPostResponse:

    response = create_response(PAIRING_TOKEN, pairing_request.clientHmacChallenge)
    challenge_response:HmacChallengeResponse = HmacChallengeResponse(b64encode(response.encode("utf-8")).decode("ascii"))

    s2_server_description = S2NodeDescription(id=S2NodeId(UUID("12345678-1234-1234-1234-123456789abc")),
                                              brand="ExampleCemCo",
                                              type="CEM",
                                              modelName="Cem P50",
                                              role=S2Role("CEM"))

    endpoint_description = S2EndpointDescription(name='Cem p50 endpoint', deployment=Deployment("WAN"))

    return RequestPairingPostResponse(
        pairingAttemptId=PairingAttemptId(b64encode(b"42").decode('utf-8')),
        serverS2NodeDescription=s2_server_description,
        serverS2EndpointDescription=endpoint_description,
        selectedHmacHashingAlgorithm=HmacHashingAlgorithm.SHA256,
        clientHmacChallengeResponse=challenge_response,
        serverHmacChallenge=pairing_request.clientHmacChallenge)


async def test_paiting_wront_url(pairing_client_rm: PairingClient, s2_client_description: S2NodeDescription) -> None:
    # testing calling url that does not exist
    with pytest.raises(S2PairingError) as excinfo:
        assert await pairing_client_rm.pair(s2_client_description)
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


async def test_paiting_404(mock_AsyncClient_404: tuple[MagicMock, MagicMock], pairing_client_rm: PairingClient, s2_client_description: S2NodeDescription) -> None:
    with pytest.raises(S2PairingError) as excinfo:
        assert await pairing_client_rm.pair(s2_client_description)
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
            pairing_request = RequestPairingPostRequest.model_validate(kwargs.get("json"))

            return httpx.Response(
                status_code=200,
                content=gen_s2_pairing_response(pairing_request).model_dump_json(),
                headers={"Content-Type": "application/json"},
                request=request,
            )
        elif url.endswith('/requestConnectionDetails'):
            RequestConnectionDetailsPostRequest.model_validate(kwargs.get("json"))
            validated_url: AnyUrl = TypeAdapter(AnyUrl).validate_python('http://s2server.example.com/initiateConnection')
            connection_details = ConnectionDetails(accessToken=AccessToken(b64encode(urlsafe_b64encode(token_bytes(32))).decode('UTF-8')),
                                                   initiateConnectionUrl=validated_url)
            return httpx.Response(
                status_code=200,
                content=connection_details.model_dump_json(),
                headers={"Content-Type": "application/json"},
                request=request,
            )
        elif url.endswith('/finalizePairing'):
            finalize_pairing_postRequest: FinalizePairingPostRequest = FinalizePairingPostRequest.model_validate(kwargs.get("json"))
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
        elif url.endswith('/confirmToken'):
            web_socket_communication_details: WebSocketCommunicationDetails = WebSocketCommunicationDetails(communicationProtocol=CommunicationProtocol.WebSocket,
                                                                                                            websocketToken=CommunicationToken('\U000b708a\U00031996\U000b3048\U0002fc4d\U00075b6b\U00109703'),
                                                                                                            websocketUrl='wss://example.com/wbsocket_endpoint')
            return httpx.Response(
                status_code=200,
                content=web_socket_communication_details.model_dump_json(),
                headers={"Content-Type": "application/json"},
                request=request,
            )
        elif url.endswith('/unpair'):
            return httpx.Response(
                status_code=204,
                headers={"Content-Type": "application/json"},
                request=request,
            )
        else:
            print(url)
            assert False, f'post of wrong type received: {kwargs.get("json")} + {type(kwargs.get("json"))}'

    # post must be AsyncMock to support `await client.post(...)`
    mock_client.post = AsyncMock(side_effect=post_side_effect)

    # Patch where your code constructs the client
    mocked_ctor = mocker.patch(
        "s2auth.client.pairing.httpx.AsyncClient",
        return_value=mock_client,
        autospec=True,
    )
    return mocked_ctor, mock_client


async def test_request_connection_details(mock_AsyncClient: tuple[MagicMock, MagicMock], pairing_client_rm: PairingClient) -> None:
    resp = await pairing_client_rm.request_connection_details("42", create_challenge())
    assert 'accessToken' in resp
    assert resp['initiateConnectionUrl'] == 'http://s2server.example.com/initiateConnection'


def test_add_header() -> None:
    assert add_header(access_token="bla_token") == {"accessToken": "bla_token", "Content-Type": "application/json"}
    assert add_header(pairing_attempt_id="bla_id") == {"pairingAttemptId": "bla_id", "Content-Type": "application/json"}
    assert add_header(pairing_attempt_id="bla_id", access_token="bla_token") == {"pairingAttemptId": "bla_id", "accessToken": "bla_token", "Content-Type": "application/json"}
    assert add_header() == {"Content-Type": "application/json"}


def test_strip_pairing_url():
    assert strip_pairing_url("http://localhost") == "http://localhost"
    assert strip_pairing_url("http://localhost/bla") == "http://localhost/bla"
    assert strip_pairing_url("http://localhost/requestPairing") == "http://localhost"
    assert strip_pairing_url("http://localhost/initiateConnection") == "http://localhost"


async def test_finalize_pairing(mock_AsyncClient: tuple[MagicMock, MagicMock], pairing_client_rm: PairingClient) -> None:
    response = await pairing_client_rm.finalize_pairing("42", True)
    assert response.status_code == 204

    response = await pairing_client_rm.finalize_pairing("42", False)
    assert response.status_code == 401


async def test_paiting_rm(mocker: MockerFixture, mock_AsyncClient: tuple[MagicMock, MagicMock], pairing_client_rm: PairingClient, s2_client_description: S2NodeDescription) -> None:
    request_connection_details_spy = mocker.spy(pairing_client_rm, "request_connection_details")
    finalize_pairing_spy = mocker.spy(pairing_client_rm, "finalize_pairing")
    post_connection_details_spy = mocker.spy(pairing_client_rm, "post_connection_details")

    assert await pairing_client_rm.pair(s2_client_description)
    request_connection_details_spy.assert_awaited_once()
    finalize_pairing_spy.assert_awaited_once()
    post_connection_details_spy.assert_not_awaited()


async def test_paiting_cem(mocker: MockerFixture, mock_AsyncClient: tuple[MagicMock, MagicMock], pairing_client_cem: PairingClient, s2_client_description: S2NodeDescription) -> None:
    request_connection_details_spy = mocker.spy(pairing_client_cem, "request_connection_details")
    finalize_pairing_spy = mocker.spy(pairing_client_cem, "finalize_pairing")
    post_connection_details_spy = mocker.spy(pairing_client_cem, "post_connection_details")

    assert await pairing_client_cem.pair(s2_client_description)
    request_connection_details_spy.assert_not_awaited()
    finalize_pairing_spy.assert_awaited_once()
    post_connection_details_spy.assert_awaited_once()


async def test_get_pairing_token_str(mocker: MockerFixture, mock_AsyncClient: tuple[MagicMock, MagicMock], pairing_client_rm: PairingClient, s2_client_description: S2NodeDescription, connection_client: ConnectionClient) -> None:
    assert await pairing_client_rm.pair(s2_client_description)

    token = connection_client.get_pairing_token_str(s2_client_description.id.model_dump(exclude_none=True))
    assert isinstance(token, str)
    assert len(token) == 60

async def test_post_connection_details(mock_AsyncClient: tuple[MagicMock, MagicMock], pairing_client_cem: PairingClient) -> None:
    validated_url: AnyUrl = TypeAdapter(AnyUrl).validate_python('http://s2server.example.com/initiateConnection')
    connection_details: ConnectionDetails = ConnectionDetails(accessToken=AccessToken(b64encode(urlsafe_b64encode(token_bytes(32))).decode('UTF-8')),
                                                              initiateConnectionUrl=validated_url)
    await pairing_client_cem.post_connection_details("42", connection_details, create_challenge())


async def test_confirmToken(mock_AsyncClient: tuple[MagicMock, MagicMock], connection_client: ConnectionClient, s2_client_description: S2NodeDescription) -> None:
    await connection_client.confirmToken(s2_client_description.id.model_dump(), "exampleid42")

async def test_unpair(mock_AsyncClient: tuple[MagicMock, MagicMock], connection_client: ConnectionClient, s2_client_description: S2NodeDescription) -> None:
    assert await connection_client.unpair(s2_client_description.id.model_dump(), "exampleid42")
