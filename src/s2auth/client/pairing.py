"""Utilities for performing the pairing process of S2 as a client.
"""

import logging
from base64 import b64encode
from typing import Any, List, Optional
from uuid import UUID

import httpx
from pydantic import AnyUrl, TypeAdapter
from s2auth.client.dao import Dao
from s2auth.common.exceptions import S2PairingError, VerificationError
from s2auth.common.hmac import (create_challenge, create_pairing_code,
                                verify_response)
from s2auth.common.model.s2_over_ip_common import (AccessToken,
                                                   CommunicationProtocol,
                                                   Deployment,
                                                   S2EndpointDescription,
                                                   S2NodeDescription, S2NodeId,
                                                   S2Role)
from s2auth.common.model.s2_over_ip_connection_init import \
    InitiateConnectionPostRequest
from s2auth.common.model.s2_over_ip_pairing import (
    ConnectionDetails, FinalizePairingPostRequest, HmacChallenge,
    HmacChallengeResponse, HmacHashingAlgorithm,
    PostConnectionDetailsPostRequest, RequestConnectionDetailsPostRequest,
    RequestPairingPostRequest, RequestPairingPostResponse, PairingS2NodeId)

LOGGER = logging.getLogger(__name__)

async def _log_request(request: httpx.Request):
    LOGGER.info(f"Call to {request.url}")
    LOGGER.debug(f"Method: {request.method}")
    LOGGER.debug(f"Headers: {request.headers}")
    LOGGER.debug(f"Content: {request.content}")

async def _log_response(response: httpx.Response):
    LOGGER.info(f"Rsponse: {response.status_code}")
    LOGGER.info(f"Headers: {response.headers}")
    LOGGER.info(f"Content: {response.text}")

HTTPX_HOOKS = {"request": [_log_request], "response": [_log_response]}
event_hooks=HTTPX_HOOKS


async def pair(pairing_uri: str,
               pairing_code: str | None,
               storage: Dao,
               role: str,
               deployment: str,
               supported_s2_message_versions: List[str],
               supported_communication_protocols: List[str],
               supportedHmacHashingAlgorithms: List[str],
               s2_client_description: S2NodeDescription,
               pairingS2NodeId: Optional[str] = None,
               verify: bool = True) -> bool:
    """
    Preform the initial pairing
    Attributes:
        pairing_uri: the uri of the pairing endpoint
        pairing_code: the pairing code: [pairing S2 node ID]-[pairing token] or [pairing token] if no code is given
        storage: The storage backend for persisting pairing information.
        role: The S2 role (CEM/RM) of the client.
        deployment: The deployment (WAN/LAN) of this client
        supported_s2_message_versions: List of versions of the S2 messages that the client supports
        supported_communication_protocols: List of communication protocols (e.g. WebSockets) that the client supports
        supportedHmacHashingAlgorithms: list of the supported hmac hashing algorithms
        s2_client_description: Information about this client that will be send to the server,
        such as brand, model, logo URL etc. Also contains a globally unique identifier
        of the S2 node this client wants to pair to a node on the server
        verify: should ssl certificates be verified
    """
    # Create client HMAC challenge that the server needs to solve
    # Create /requestPairing request body object
    # Do the HTTP request
    # Check the client HMAC challenge response
    # Solve the server HMAC challenge
    # Depending on the client/server role in the connection initiation of other S2 node either requestConnectionDetails or postConnectionDetails
    # In any case, store the connection details in the database.

    # If no id given use id from client
    s2_role: S2Role = S2Role(role)
    s2_deployment: Deployment = Deployment(deployment)
    communication_protocols: List[CommunicationProtocol] = list(map(CommunicationProtocol, supported_communication_protocols))
    supported_hmac_hashing_algorithms: List[HmacHashingAlgorithm] = list(map(HmacHashingAlgorithm, supportedHmacHashingAlgorithms))

    if pairing_code is not None and '-' in pairing_code:
        split_code = pairing_code.split('-')
        pairing_s2_node_id, pairing_token = split_code[:-1], split_code[-1]
    else:
        pairing_s2_node_id, pairing_token = None, pairing_code

    if not pairing_token and s2_role == S2Role.RM:
        raise S2PairingError("Access token required for pairing RM")
    elif not pairing_token:
        pairing_token = create_pairing_code()

    # id logic seperately in case we get something like "-pairing_token" (i.e. an empty id but still combined)
    s2_node_id: str = str(pairing_s2_node_id) if pairing_s2_node_id else str(s2_client_description.id.model_dump(exclude_none=True))

    LOGGER.warning(f"Using access token: {pairing_token} and s2_node_id {s2_node_id}")

    client_hmac_challenge = create_challenge()
    request_payload: RequestPairingPostRequest = RequestPairingPostRequest(
        clientS2NodeDescription=s2_client_description,
        clientS2EndpointDescription=S2EndpointDescription(
            name=f"{s2_client_description.userDefinedName if s2_client_description.userDefinedName else s2_client_description.brand} endpoint",
            logoUrl=s2_client_description.logoUrl,
            deployment=s2_deployment,
        ),
        pairingS2NodeId=PairingS2NodeId(str(pairingS2NodeId)) if pairingS2NodeId is not None else None,
        supportedCommunicationProtocols=communication_protocols,
        supportedS2MessageVersions=supported_s2_message_versions,
        supportedHmacHashingAlgorithms=supported_hmac_hashing_algorithms,
        clientHmacChallenge=client_hmac_challenge,
        forcePairing=True,
    )
    body = request_payload.model_dump_json(exclude_none=True)

    try:
        async with httpx.AsyncClient(verify=verify, event_hooks=HTTPX_HOOKS) as client:
            response = await client.post(f'{pairing_uri}/requestPairing', content=body, headers={"Content-Type": "application/json"})
            response.raise_for_status()

            pairing_response: RequestPairingPostResponse = RequestPairingPostResponse.model_validate(response.json())
            if not verify_response(pairing_token=pairing_token,
                                   challenge=client_hmac_challenge,
                                   response=pairing_response.clientHmacChallengeResponse.root,
                                   algorithm=pairing_response.selectedHmacHashingAlgorithm):
                raise VerificationError("HMAC chellange does not match")
            assert s2_role in (S2Role.RM, S2Role.CEM)
            if s2_role == S2Role.RM:
                connection_details_dict = await request_connection_details(pairing_uri=pairing_uri,
                                                                           attempt_id=pairing_response.pairingAttemptId.model_dump(exclude_none=True),
                                                                           serverHmacChallangeResponse=pairing_response.serverHmacChallenge,
                                                                           storage=storage,
                                                                           verify=verify)
                # Store connection details in the database
                storage.store_connection_details(s2_node_id, connection_details_dict.get("accessToken", ""))
            else:  # s2_role.CEM
                # Post connection details logic for CEM role
                initiateConnectionUrl: AnyUrl = TypeAdapter(AnyUrl).validate_python(f"{pairing_uri}/initiateConnection")
                b64str_token = b64encode(pairing_token.encode("utf-8")).decode("ascii")
                access_token: AccessToken = AccessToken(b64str_token)
                connection_details: ConnectionDetails = ConnectionDetails(initiateConnectionUrl=initiateConnectionUrl, accessToken=access_token)
                response = await post_connection_details(pairing_uri,
                                                         pairing_response.pairingAttemptId.model_dump(exclude_none=True),
                                                         connection_details,
                                                         pairing_response.serverHmacChallenge,
                                                         storage=storage,
                                                         verify=verify)

            final_response = await finalize_pairing(pairing_uri=pairing_uri,
                                                    attempt_id=pairing_response.pairingAttemptId.model_dump(exclude_none=True),
                                                    success=True,
                                                    verify=verify)
            return (final_response.status_code == 204)
    except httpx.HTTPError as e:
        # Handle HTTP error
        raise S2PairingError(f"Pairing connection failed: {e}") from e


async def request_connection_details(pairing_uri: str, attempt_id: str, serverHmacChallangeResponse: HmacChallenge, storage: Dao, verify: bool = True) -> dict[Any, Any]:
    """
    Request connection details from server
    Attributes:
        pairing_uri: the uri of the pairing endpoint
        attempt_id: a unique id of this pairing attempt
        serverHmacChallangeResponse: the response to the hmac challange received from teh server
        verify: should ssl certificates be verified
    """
    async with httpx.AsyncClient(verify=verify, event_hooks=HTTPX_HOOKS) as client:
        payload: RequestConnectionDetailsPostRequest = RequestConnectionDetailsPostRequest(
            serverHmacChallengeResponse=HmacChallengeResponse(serverHmacChallangeResponse.model_dump(exclude_none=True))
        )
        body = payload.model_dump_json(exclude_none=True)
        headers = add_header(pairing_attempt_id=attempt_id)
        response = await client.post(
            f'{pairing_uri}/requestConnectionDetails',
            headers=headers,
            content=body,
        )
        return response.json()


async def post_connection_details(pairing_uri: str,
                                  attempt_id: str,
                                  connection_details: ConnectionDetails,
                                  serverHmacChallangeResponse: HmacChallenge,
                                  storage: Dao,
                                  verify: bool = True) -> None:
    """
    Post connection details to server
    Attributes:
        pairing_uri: the uri of the pairing endpoint
        attempt_id: a unique id of this pairing attempt
        connection_details: details object for this connection in a ConnectionDetails object
        serverHmacChallangeResponse: the response to the hmac challange received from teh server
        verify: should ssl certificates be verified
    """
    payload: PostConnectionDetailsPostRequest = PostConnectionDetailsPostRequest(
        serverHmacChallengeResponse=HmacChallengeResponse(serverHmacChallangeResponse.model_dump()),
        connectionDetails=connection_details,
    )
    async with httpx.AsyncClient(verify=verify, event_hooks=HTTPX_HOOKS) as client:
        body = payload.model_dump_json(exclude_none=True)
        headers = add_header(pairing_attempt_id=attempt_id)
        response = await client.post(
            f'{pairing_uri}/postConnectionDetails',
            headers=headers,
            content=body,
        )
        response.raise_for_status()
        if not response.status_code == 204:
            raise S2PairingError("postConnectionDetails failed")


async def finalize_pairing(pairing_uri: str, attempt_id: str, success: Optional[bool] = None, verify: bool = True) -> httpx.Response:
    """
    Finalise the pairing process: post statusthe to finalizePairing endpoint
    Attributes:
        pairing_uri: the uri of the pairing endpoint
        attempt_id: a unique id of this pairing attempt
        success: did pairing succeed
        verify: should ssl certificates be verified
    """
    finalize_pairing_postRequest = FinalizePairingPostRequest(success=success)

    async with httpx.AsyncClient(verify=verify, event_hooks=HTTPX_HOOKS) as client:
        body = finalize_pairing_postRequest.model_dump_json(exclude_none=True)
        headers = add_header(pairing_attempt_id=attempt_id)
        response = await client.post(f'{pairing_uri}/finalizePairing',
                                     headers=headers,
                                     content=body)
        return response


async def connect(pairing_uri: str,
                  storage: Dao,
                  supported_s2_message_versions: List[str],
                  supported_communication_protocols: List[str],
                  s2_client_description: S2NodeDescription,
                  serverS2NodeId: str,
                  clientS2NodeId: Optional[str] = None,
                  verify: bool = True) -> bool:
    """
    Connect with previously stablished pairing
    Attributes:
        pairing_uri: the uri of the initiateConnection endpoint
        storage: The storage backend for persisting pairing information.
        supported_s2_message_versions: List of versions of the S2 messages that the client supports
        supported_communication_protocols: List of communication protocols (e.g. WebSockets) that the client supports
        serverS2NodeId: The s2 node id node of this pairing client/server instance server
        clientS2NodeId: The s2 node id of the client node if different e.g. if this server takes care of multile S2 devices
        attempt_id: a unique id of this pairing attempt
        verify: should ssl certificates be verified
    """

    supported_comms_protocols: List[CommunicationProtocol] = list(map(CommunicationProtocol, supported_communication_protocols))
    # If no id given use id from client
    client_s2_node_id: str = str(clientS2NodeId) if clientS2NodeId else str(serverS2NodeId)

    async with httpx.AsyncClient(verify=verify, event_hooks=HTTPX_HOOKS) as client:
        init_payload: InitiateConnectionPostRequest = InitiateConnectionPostRequest(
            serverS2NodeId=S2NodeId(UUID(serverS2NodeId)),
            clientS2NodeId=S2NodeId(UUID(client_s2_node_id)),
            supportedS2MessageVersions=supported_s2_message_versions,
            supportedCommunicationProtocols=supported_comms_protocols,
        )

        body = init_payload.model_dump_json(exclude_none=True)
        headers = add_header(access_token=storage.load_token(client_s2_node_id))
        response = await client.post(
            f'{pairing_uri}/initiateConnection',
            headers=headers,
            content=body
        )
        response.raise_for_status()
        access_token = response.json().get("accessToken")
        supported_s2_message_version = response.json().get("selectedS2MessageVersion")
        selected_communication_protocol = response.json().get("selectedCommunicationProtocol")

        assert supported_s2_message_version in supported_s2_message_versions
        assert selected_communication_protocol in supported_communication_protocols

        # Store connection details in the database
        storage.store_pending_token(client_s2_node_id, access_token, supported_s2_message_version, selected_communication_protocol)

        confirmation = await confirmToken(pairing_uri, storage, client_s2_node_id, response.json().get("pendingToken"), verify)

        # store websocek connectin details
        storage.store_ws_connection_details(client_s2_node_id, confirmation.json().get("websocketToken"), confirmation.json().get("websocketUrl"))
        return confirmation.status_code == 200


async def confirmToken(pairing_uri: str, storage: Dao, client_s2_node_id: str, pendingToken: str, verify: bool = True) -> httpx.Response:
    """
    Sent confirmation the token
    Attributes:
        pairing_uri: the uri of the initiateConnection endpoint
        storage: The storage backend for persisting pairing information.
        client_s2_node_id: The s2 node id of the client
        pendingToken: the token to send
        verify: should ssl certificates be verified
    """

    async with httpx.AsyncClient(verify=verify, event_hooks=HTTPX_HOOKS) as client:
        body = '{"pendingToken": "pendingToken"}'
        headers = add_header(access_token=storage.load_pending_token(client_s2_node_id))
        response = await client.post(f'{pairing_uri}/confirmAccessToken',
                                     headers=headers,
                                     content=body)
        response.raise_for_status()
        return response


async def unpair(pairing_uri: str, storage: Dao, pairing_s2_node_id: str, serverS2NodeId: str, clientS2NodeId: Optional[str] = None, verify: bool = True) -> bool:
    """
    Sent command to terminate the pairing
    Attributes:
        pairing_uri: the uri of the initiateConnection endpoint
        storage: The storage backend for persisting pairing information.
        pairing_s2_node_id id of the node to unpair
        serverS2NodeId: The s2 node id node of this pairing client/server instance server
        clientS2NodeId: The s2 node id of the client node if different e.g. if this server takes care of multile S2 devices
        verify: should ssl certificates be verified
    """

    client_s2_node_id: str = str(clientS2NodeId) if clientS2NodeId else str(serverS2NodeId)
    async with httpx.AsyncClient(verify=verify, event_hooks=HTTPX_HOOKS) as client:
        body = pairing_s2_node_id
        headers = add_header(access_token=storage.load_token(client_s2_node_id))
        response = await client.post(f'{pairing_uri}/unpair',
                                     headers=headers,
                                     content=body)
        response.raise_for_status()
        return response.status_code == 204


def strip_pairing_url(url_str: str) -> str:
    """
    Remove the endpoint suffixes from a url_str. This is a conveniance method to allow a user to enter  for example
    https://www.example.com/v1/requestPairing as well as https://www.example.com/v1/
    Attributes:
        url_str: the uri to process
    """

    endpoint_suffixes = (
        "/requestPairing",
        "/initiateConnection",
        "/requestConnectionDetails",
        "/postConnectionDetails",
        "/finalizePairing",
        "/confirmToken",
    )
    url_str = url_str.rstrip("/")

    for suffix in endpoint_suffixes:
        if url_str.endswith(suffix):
            url_str = url_str[: -len(suffix)]
            break
    return url_str.rstrip("/")


def add_header(access_token: Optional[str] = None, pairing_attempt_id: Optional[str] = None) -> dict[str, str]:
    """
    Returns an appropriate header dicti for pairing requests
    Attributes:
        access_token: for calls where we need an access token added
        pairing_attempt_id: for calls where we need an pairing_attempt_id added
    """

    header = {"Content-Type": "application/json"}
    if access_token:
        header["accessToken"] = access_token
    if pairing_attempt_id:
        header["pairingAttemptId"] = pairing_attempt_id
    return header
