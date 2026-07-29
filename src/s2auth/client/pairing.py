"""Utilities for performing the pairing process of S2 as a client.
"""

import hashlib
import logging
from base64 import b64encode
from pathlib import Path
import re
import ssl
from typing import Any, List, Optional, cast
from uuid import UUID

import httpx

from s2auth.client.dao import Dao
from s2auth.common.exceptions import S2PairingError, VerificationError
from s2auth.common.hmac import (create_challenge, create_pairing_code,
                                create_response, verify_response)
from s2auth.common.model.s2_connect_common import (CommunicationProtocol,
                                                   Deployment,
                                                   EndpointDescription,
                                                   NodeDescription, NodeId,
                                                   Role)
from s2auth.common.model.s2_connect_session_init import \
    InitiateSessionPostRequest
from s2auth.common.model.s2_connect_pairing import (
    ConnectionDetails, FinalizePairingPostRequest,
    HmacChallengeResponse, HmacHashingAlgorithm, NodeIdAlias,
    PostConnectionDetailsPostRequest, RequestConnectionDetailsPostRequest,
    RequestPairingPostRequest, RequestPairingPostResponse)

LOGGER = logging.getLogger(__name__)

#def detect_deployment(domain_name: str | None, certificate_file: str | None) -> str:
#    """
#    Detects the deployment type based on the provided domain name and certificate file.
#    Args:
#        domain_name: The domain name to check for WAN deployment.
#        certificate_file: The path to the certificate file to check for LAN deployment.
#    Returns:
#        A string indicating the deployment type: "WAN" or "LAN".
#    Raises:
#        S2PairingError: If both domain_name and certificate_file are provided, or if neither is provided.
#    """
#    if domain_name and certificate_file:
#        raise S2PairingError("Both --domain and --certificate_file are set; please specify only one.")
#    elif domain_name:
#        return "WAN"
#    elif certificate_file:
#        return "LAN"
#    else:
#        raise S2PairingError("Neither --domain nor --certificate_file is set; please specify one.")


def detect_certificate_file_validation(certificate_validation: str | bool) -> str | bool:
    """
    Detects the certificate file to use for LAN deployment.
    Args:
        certificate_file: The path to the certificate file to check for LAN deployment.
    Returns:
        The path to the certificate file if it exists, or None if not provided.
    Raises:
        S2PairingError: If the certificate file does not exist.
    """
    if certificate_validation:
        assert isinstance(certificate_validation, str)
        if Path(certificate_validation).is_file():
            raise S2PairingError(f"Certificate file '{certificate_validation}' not found")
    if certificate_validation == "":
        return "localhost.chain.pem"
#        # Auto-detect certificate file
#        cert_files = list(Path("/etc/ssl/certs").glob("*.pem"))
#        if cert_files:
#            certificate_validation = str(cert_files[0])
#            LOGGER.info(f"Auto-detected certificate file: {certificate_validation}")
#        else:
#            raise S2PairingError("No certificate file found for auto-detection.")
    return certificate_validation


def calculate_fingerprint(certificate_file: str | None) -> bytes | None:
    if not certificate_file:
        return None

    pem_data = Path(certificate_file).read_text()
    blocks = re.findall(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", pem_data, flags=re.S)
    cert_pem = blocks[0]
    der = ssl.PEM_cert_to_DER_cert(cert_pem)
    digest = hashlib.sha256(der).digest()
    return digest


async def _log_request(request: httpx.Request):
    LOGGER.info(f"Call to {request.url}")
    LOGGER.debug(f"Method: {request.method}")
    LOGGER.debug(f"Headers: {request.headers}")
    LOGGER.debug(f"Content: {request.content}")


async def _log_response(response: httpx.Response):
    await response.aread()
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
               s2_client_description: NodeDescription,
               domain_name: str | None,
               certificate_file: str | None,
               pairingS2NodeId: Optional[str] = None,
               certificate_validation: str | bool = True) -> bool:
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
        domain_name the domain name to use in a wan deployment
        certificate_file: certificate to use in a lan deployment
        certificate_validation: the ssl certificates to verify server calls against, 
            "" will lead to autodetect and False will skip verification
    """
    # Create client HMAC challenge that the server needs to solve
    # Create /requestPairing request body object
    # Do the HTTP request
    # Check the client HMAC challenge response
    # Solve the server HMAC challenge
    # Depending on the client/server role in the connection initiation of other S2 node either requestConnectionDetails or postConnectionDetails
    # In any case, store the connection details in the database.

    # If no id given use id from client
    certificate_validation = detect_certificate_file_validation(certificate_validation)
    s2_role: Role = Role(role)
    s2_deployment: Deployment = Deployment(deployment)
    communication_protocols: List[CommunicationProtocol] = list(map(CommunicationProtocol, supported_communication_protocols))
    supported_hmac_hashing_algorithms: List[HmacHashingAlgorithm] = list(map(HmacHashingAlgorithm, supportedHmacHashingAlgorithms))

    if pairing_code is not None and '-' in pairing_code:
        split_code = pairing_code.split('-')
        pairing_s2_node_id, pairing_token = "".join(split_code[:-1]), split_code[-1]
    else:
        pairing_s2_node_id, pairing_token = None, pairing_code

    if not pairing_token and s2_role == Role.RM:
        raise S2PairingError("Access token required for pairing RM")
    elif not pairing_token:
        pairing_token = create_pairing_code()

    fingerprint = None
    if isinstance(certificate_validation, str) and certificate_validation != "":
        fingerprint = calculate_fingerprint(certificate_validation)

    # id logic seperately in case we get something like "-pairing_token" (i.e. an empty id but still combined)
    s2_node_id: str = str(pairing_s2_node_id) if pairing_s2_node_id else str(s2_client_description.id.root)

    LOGGER.warning(f"Using access token: {pairing_token} and s2_node_id {s2_node_id}")

    # remove any previously stored connection details for this node id
    storage.remove_connection_details(s2_node_id)

    client_hmac_challenge = create_challenge()
    request_payload: RequestPairingPostRequest = RequestPairingPostRequest(
        clientNodeDescription=s2_client_description,
        clientEndpointDescription=EndpointDescription(
            name=f"{s2_client_description.userDefinedName if s2_client_description.userDefinedName else s2_client_description.brand} endpoint",
            logoUrl=s2_client_description.logoUrl,
            deployment=s2_deployment,
        ),
        nodeIdAlias=NodeIdAlias(str(pairing_s2_node_id)) if pairing_s2_node_id is not None else None,
        supportedCommunicationProtocols=communication_protocols,
        supportedS2MessageVersions=supported_s2_message_versions,
        supportedHmacHashingAlgorithms=supported_hmac_hashing_algorithms,
        clientHmacChallenge=client_hmac_challenge,
        forcePairing=True,
    )
    body = request_payload.model_dump_json(exclude_none=True)

    try:
        async with httpx.AsyncClient(verify=certificate_validation, event_hooks=HTTPX_HOOKS) as client:
            response = await client.post(f'{pairing_uri}/requestPairing', content=body, headers={"Content-Type": "application/json"})
            response.raise_for_status()

            pairing_response: RequestPairingPostResponse = RequestPairingPostResponse.model_validate(response.json())
            if not verify_response(pairing_token=pairing_token,
                                   challenge=client_hmac_challenge,
                                   response=pairing_response.clientHmacChallengeResponse.root,
                                   deployment = s2_deployment,
                                   domain_name = domain_name,
                                   fingerprint = fingerprint,
                                   algorithm=pairing_response.selectedHmacHashingAlgorithm):
                raise VerificationError("HMAC chellange does not match")
            assert s2_role in (Role.RM, Role.CEM)


            resp: HmacChallengeResponse = HmacChallengeResponse(b64encode(
                create_response(pairing_token=pairing_token,
                                challenge=pairing_response.serverHmacChallenge,
                                deployment=s2_deployment,
                                domain_name=domain_name,
                                fingerprint=fingerprint,
                                algorithm=pairing_response.selectedHmacHashingAlgorithm)))

            connection_details_dict:dict[str, Any] = {}
            if s2_role == Role.RM:
                connection_details_dict = await request_connection_details(pairing_uri=pairing_uri,
                                                                           attempt_id=pairing_response.pairingAttemptId.root,
                                                                           hmacChallangeResponse=resp,
                                                                           certificate_validation=certificate_validation)
            else:
                assert s2_role == Role.CEM
                # Post connection details logic for CEM role
                initiateSessionUrl: str = f"{pairing_uri}/initiateSession"
                access_token = b64encode(pairing_token.encode("utf-8")).decode("ascii")
                connection_details_dict = {"initiateSessionUrl": initiateSessionUrl, "accessToken": access_token}
                response = await post_connection_details(pairing_uri=pairing_uri,
                                                         attempt_id=pairing_response.pairingAttemptId.root,
                                                         connection_details=ConnectionDetails.model_validate(connection_details_dict),
                                                         serverHmacChallangeResponse=resp,
                                                         certificate_validation=certificate_validation)

            # Store connection details in the database
            storage.store_connection_details(
                s2_node_id,
                connection_details_dict,
            )
            final_response = await finalize_pairing(pairing_uri=pairing_uri,
                                                    attempt_id=pairing_response.pairingAttemptId.root,
                                                    success=True,
                                                    certificate_validation=certificate_validation)

            return (final_response.status_code == 204)
    except httpx.HTTPError as e:
        # Handle HTTP error
        raise S2PairingError(f"Pairing connection failed: {e}") from e


async def request_connection_details(pairing_uri: str,
                                     attempt_id: str,
                                     hmacChallangeResponse: HmacChallengeResponse,
                                     certificate_validation: bool | str = True) -> dict[str, Any]:
    """
    Request connection details from server
    Attributes:
        pairing_uri: the uri of the pairing endpoint
        attempt_id: a unique id of this pairing attempt
        serverHmacChallangeResponse: the response to the hmac challange received from the server
        certificate_validation: the ssl certificates to verify server calls against, 
            "" will lead to autodetect and False will skip verification
    """
    async with httpx.AsyncClient(verify=certificate_validation, event_hooks=HTTPX_HOOKS) as client:
        payload: RequestConnectionDetailsPostRequest = RequestConnectionDetailsPostRequest(
            serverHmacChallengeResponse=hmacChallangeResponse
        )
        body = payload.model_dump_json(exclude_none=True)
        headers = add_header(token=attempt_id)
        response = await client.post(
            f'{pairing_uri}/requestConnectionDetails',
            headers=headers,
            content=body,
        )
        response_json = response.json()
        if not isinstance(response_json, dict):
            raise S2PairingError("requestConnectionDetails returned invalid JSON payload")
        return cast(dict[str, Any], response_json)


async def post_connection_details(pairing_uri: str,
                                  attempt_id: str,
                                  connection_details: ConnectionDetails,
                                  serverHmacChallangeResponse: HmacChallengeResponse,
                                  certificate_validation: bool | str = True) -> None:
    """
    Post connection details to server
    Attributes:
        pairing_uri: the uri of the pairing endpoint
        attempt_id: a unique id of this pairing attempt
        connection_details: details object for this connection in a ConnectionDetails object
        serverHmacChallangeResponse: the response to the hmac challange received from teh server
        certificate_validation: the ssl certificates to verify server calls against, 
            "" will lead to autodetect and False will skip verification
    """
    payload: PostConnectionDetailsPostRequest = PostConnectionDetailsPostRequest(
        serverHmacChallengeResponse=HmacChallengeResponse(serverHmacChallangeResponse.model_dump()),
        connectionDetails=connection_details,
    )
    async with httpx.AsyncClient(verify=certificate_validation, event_hooks=HTTPX_HOOKS) as client:
        body = payload.model_dump_json(exclude_none=True)
        headers = add_header(token=attempt_id)
        response = await client.post(
            f'{pairing_uri}/postConnectionDetails',
            headers=headers,
            content=body,
        )
        response.raise_for_status()
        if not response.status_code == 204:
            raise S2PairingError("postConnectionDetails failed")


async def finalize_pairing(pairing_uri: str,
                           attempt_id: str,
                           success: Optional[bool] = None,
                           certificate_validation: str | bool = True) -> httpx.Response:
    """
    Finalise the pairing process: post statusthe to finalizePairing endpoint
    Attributes:
        pairing_uri: the uri of the pairing endpoint
        attempt_id: a unique id of this pairing attempt
        success: did pairing succeed
        certificate_validation: the ssl certificates to verify server calls against, 
            "" will lead to autodetect and False will skip verification
    """
    finalize_pairing_postRequest = FinalizePairingPostRequest(success=success)

    async with httpx.AsyncClient(verify=certificate_validation, event_hooks=HTTPX_HOOKS) as client:
        body = finalize_pairing_postRequest.model_dump_json(exclude_none=True)
        headers = add_header(token=attempt_id)
        response = await client.post(f'{pairing_uri}/finalizePairing',
                                     headers=headers,
                                     content=body)
        return response


async def connect(pairing_uri: str,
                  storage: Dao,
                  supported_s2_message_versions: List[str],
                  supported_communication_protocols: List[str],
                  s2_client_description: NodeDescription,
                  serverS2NodeId: str,
                  clientS2NodeId: Optional[str] = None,
                  certificate_validation: str | bool = True) -> bool:
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
        certificate_validation: the ssl certificates to verify server calls against, 
            "" will lead to autodetect and False will skip verification
    """
    certificate_validation = detect_certificate_file_validation(certificate_validation)
    supported_comms_protocols: List[CommunicationProtocol] = list(map(CommunicationProtocol, supported_communication_protocols))
    # If no id given use id from client
    client_s2_node_id: str = str(clientS2NodeId) if clientS2NodeId else str(serverS2NodeId)

    async with httpx.AsyncClient(verify=certificate_validation, event_hooks=HTTPX_HOOKS) as client:
        init_payload: InitiateSessionPostRequest = InitiateSessionPostRequest(
            serverNodeId=NodeId(UUID(serverS2NodeId)),
            clientNodeId=NodeId(UUID(client_s2_node_id)),
            supportedS2MessageVersions=supported_s2_message_versions,
            supportedCommunicationProtocols=supported_comms_protocols,
        )

        body = init_payload.model_dump_json(exclude_none=True)
        connection_details = storage.load_connection_details(client_s2_node_id) or {}
        headers = add_header(token=connection_details.get("accessToken"))
        response = await client.post(
            f'{pairing_uri}/initiateSession',
            headers=headers,
            content=body
        )
        response.raise_for_status()
        access_token = response.json().get("accessToken")
        supported_s2_message_version = response.json().get("selectedS2MessageVersion")
        selected_communication_protocol = response.json().get("selectedCommunicationProtocol")

        assert supported_s2_message_version in supported_s2_message_versions
        assert selected_communication_protocol in supported_communication_protocols

        storage.store_connection_details(
            client_s2_node_id,
            {
                "accessToken": access_token,
                "pendingToken": response.json().get("pendingToken"),
                "supportedS2MessageVersion": supported_s2_message_version,
                "selectedCommunicationProtocol": selected_communication_protocol,
            },
        )
        confirmation = await confirmToken(pairing_uri, storage, client_s2_node_id, response.json().get("accessToken"), certificate_validation)

        storage.store_connection_details(
            client_s2_node_id,
            {
                "websocketToken": confirmation.json().get("websocketToken"),
                "websocketUrl": confirmation.json().get("websocketUrl"),
            },
        )
        return confirmation.status_code == 200


async def confirmToken(pairing_uri: str, storage: Dao, client_s2_node_id: str, accessToken: str, certificate_validation: bool | str = True) -> httpx.Response:
    """
    Sent confirmation the token
    Attributes:
        pairing_uri: the uri of the initiateConnection endpoint
        storage: The storage backend for persisting pairing information.
        client_s2_node_id: The s2 node id of the client
        accessToken: the pending token to send
        certificate_validation: should ssl certificates be verified
    """
    async with httpx.AsyncClient(verify=certificate_validation, event_hooks=HTTPX_HOOKS) as client:
        body = '{"accessToken": "' + accessToken + '"}'
        details = storage.load_connection_details(client_s2_node_id) or {}
        headers = add_header(token=details.get("accessToken"))
        response = await client.post(f'{pairing_uri}/confirmAccessToken',
                                     headers=headers,
                                     content=body)
        response.raise_for_status()
        return response


async def unpair(pairing_uri: str, storage: Dao, pairing_s2_node_id: str, serverS2NodeId: str, clientS2NodeId: Optional[str] = None, certificate_validation: bool = True) -> bool:
    """
    Sent command to terminate the pairing
    Attributes:
        pairing_uri: the uri of the initiateConnection endpoint
        storage: The storage backend for persisting pairing information.
        pairing_s2_node_id id of the node to unpair
        serverS2NodeId: The s2 node id node of this pairing client/server instance server
        clientS2NodeId: The s2 node id of the client node if different e.g. if this server takes care of multile S2 devices
        certificate_validation: should ssl certificates be verified
    """

    client_s2_node_id: str = str(clientS2NodeId) if clientS2NodeId else str(serverS2NodeId)
    async with httpx.AsyncClient(verify=certificate_validation, event_hooks=HTTPX_HOOKS) as client:
        body = pairing_s2_node_id
        details = storage.load_connection_details(client_s2_node_id) or {}
        headers = add_header(token=details.get("accessToken"))
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
        "/initiateSession",
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


def add_header(token: Optional[str] = None) -> dict[str, str]:
    """
    Returns an appropriate header dicti for pairing requests
    Attributes:
        token: security bearer token e.g. pairing_attempt_id or accessToken
    """

    header = {"Content-Type": "application/json"}
    if token:
        header["Authorization"] = f"Bearer {token}"
    return header
