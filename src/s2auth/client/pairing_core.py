"""Utilities for performing the pairing process of S2 as a client.
"""

import hashlib
import json
import logging
from base64 import b64encode
from pathlib import Path
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


def build_httpx_verify(verify_tls: bool, ssl_certfile: str | None) -> str | bool:
    if not verify_tls:
        return False
    if isinstance(ssl_certfile, str) and ssl_certfile.strip() == "":
        return True
    if ssl_certfile is None:
        return True
    if not Path(ssl_certfile).is_file():
        raise S2PairingError(f"Certificate file '{ssl_certfile}' not found")
    return ssl_certfile

def calculate_fingerprint_from_response_certificate(response: httpx.Response) -> bytes | None:
    network_stream = response.extensions.get("network_stream")
    if network_stream is None:
        return None

    get_extra_info = getattr(network_stream, "get_extra_info", None)
    if not callable(get_extra_info):
        return None

    ssl_object = get_extra_info("ssl_object")
    if ssl_object is None:
        return None

    get_peer_cert = getattr(ssl_object, "getpeercert", None)
    if not callable(get_peer_cert):
        return None

    cert_der = get_peer_cert(binary_form=True)
    if not isinstance(cert_der, (bytes, bytearray)) or not cert_der:
        return None

    return hashlib.sha256(bytes(cert_der)).digest()


async def _log_request(request: httpx.Request):
    LOGGER.debug("--- HTTP REQUEST ---")
    LOGGER.debug(f"Call to {request.url}")
    LOGGER.debug(f"Method: {request.method}")
    LOGGER.debug(f"Headers: {request.headers}")
    LOGGER.debug(f"Content: {request.content}")

async def _log_response(response: httpx.Response):
    await response.aread()
    LOGGER.debug("--- HTTP RESPONSE ---")
    LOGGER.debug(f"Headers: {response.headers}")
    LOGGER.debug(f"Content: {response.text}")
    LOGGER.debug("--------------------\n")


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
               pairingS2NodeId: Optional[str] = None,
               verify_tls: bool = True,
               ssl_certfile: str | None = None) -> bool:
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
        verify_tls: should ssl certificates be verified
        ssl_certfile: optional CA/certificate bundle path used for TLS verification
    """
    # Create client HMAC challenge that the server needs to solve
    # Create /requestPairing request body object
    # Do the HTTP request
    # Check the client HMAC challenge response
    # Solve the server HMAC challenge
    # Depending on the client/server role in the connection initiation of other S2 node either requestConnectionDetails or postConnectionDetails
    # In any case, store the connection details in the database.

    httpx_verify = build_httpx_verify(verify_tls, ssl_certfile)

    # If no id given use id from client
    s2_role: Role = Role(role)
    s2_deployment: Deployment = Deployment(deployment)
    communication_protocols: List[CommunicationProtocol] = list(map(CommunicationProtocol, supported_communication_protocols))
    supported_hmac_hashing_algorithms: List[HmacHashingAlgorithm] = list(map(HmacHashingAlgorithm, supportedHmacHashingAlgorithms))
    fingerprint: bytes | None = None

    if s2_deployment == Deployment.WAN and (domain_name is None or domain_name.strip() == ""):
        raise S2PairingError("WAN deployment requires domain_name.")

    if pairingS2NodeId is not None:
        pairing_s2_node_id, pairing_token = pairingS2NodeId, pairing_code
    elif pairing_code is not None and '-' in pairing_code:
        # Keep backward compatibility with "alias-token" pairing codes while
        # preserving hyphens in aliases (for example UUID-based aliases).
        pairing_s2_node_id, pairing_token = pairing_code.rsplit('-', 1)
    else:
        pairing_s2_node_id, pairing_token = None, pairing_code

    if not pairing_token and s2_role == Role.RM:
        raise S2PairingError("Access token required for pairing RM")
    elif not pairing_token:
        pairing_token = create_pairing_code()

    target_node_id: NodeId | None = None
    target_node_alias: NodeIdAlias | None = None
    if pairing_s2_node_id is not None:
        try:
            # UUID values should be sent as full nodeId, not nodeIdAlias.
            target_node_id = NodeId(UUID(pairing_s2_node_id))
        except ValueError:
            if pairing_s2_node_id.isalnum():
                target_node_alias = NodeIdAlias(pairing_s2_node_id)
            else:
                raise S2PairingError(
                    "pairing_s2_node_id must be either a UUID (for nodeId) or an alphanumeric alias (for nodeIdAlias)."
                )

    # id logic seperately in case we get something like "-pairing_token" (i.e. an empty id but still combined)
    s2_node_id: str = str(pairing_s2_node_id) if pairing_s2_node_id else str(s2_client_description.id.root)

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
        nodeId=target_node_id,
        nodeIdAlias=target_node_alias,
        supportedCommunicationProtocols=communication_protocols,
        supportedS2MessageVersions=supported_s2_message_versions,
        supportedHmacHashingAlgorithms=supported_hmac_hashing_algorithms,
        clientHmacChallenge=client_hmac_challenge,
        forcePairing=True,
    )
    body = request_payload.model_dump_json(exclude_none=True)
    try:
        async with httpx.AsyncClient(verify=httpx_verify, event_hooks=HTTPX_HOOKS) as client:
            response = await client.post(f'{pairing_uri}/requestPairing', content=body, headers={"Content-Type": "application/json"})
            response.raise_for_status()
            if s2_deployment == Deployment.LAN and fingerprint is None:
                fingerprint = calculate_fingerprint_from_response_certificate(response)
                if fingerprint is None:
                    raise S2PairingError(
                        "Could not determine LAN certificate fingerprint from /requestPairing TLS connection. "
                        "Provide certificate_file or enable TLS cert access in the HTTP transport."
                    )

            pairing_response: RequestPairingPostResponse = RequestPairingPostResponse.model_validate(response.json())

            LOGGER.debug("--- HMAC: verifying server's response to client challenge ---")
            if not verify_response(pairing_token=pairing_token,
                                   challenge=client_hmac_challenge,
                                   response=pairing_response.clientHmacChallengeResponse.root,
                                   deployment = s2_deployment,
                                   domain_name = domain_name,
                                   fingerprint = fingerprint,
                                   algorithm=pairing_response.selectedHmacHashingAlgorithm):
                raise VerificationError("HMAC chellange does not match")
            LOGGER.debug("--- HMAC: client challenge verified OK ---\n")
            assert s2_role in (Role.RM, Role.CEM)

            LOGGER.debug("--- HMAC: creating response to server challenge ---")
            resp: HmacChallengeResponse = HmacChallengeResponse(b64encode(
                create_response(pairing_token=pairing_token,
                                challenge=pairing_response.serverHmacChallenge,
                                deployment=s2_deployment,
                                domain_name=domain_name,
                                fingerprint=fingerprint,
                                algorithm=pairing_response.selectedHmacHashingAlgorithm)))
            LOGGER.debug("--- HMAC: server challenge response created ---\n")

            connection_details_dict: dict[str, Any] = {
                "pairing_server_url": pairing_uri,
                "client_s2_node_id": str(s2_client_description.id.root),
                "supported_s2_message_versions": supported_s2_message_versions,
                "supported_communication_protocols": supported_communication_protocols,
                "supported_hmac_hashing_algorithms": supportedHmacHashingAlgorithms,
                "verify_tls": verify_tls,
                "ssl_certfile": ssl_certfile,
            }
            if s2_role == Role.RM:
                rm_connection_details = await request_connection_details(
                    pairing_uri=pairing_uri,
                    attempt_id=pairing_response.pairingAttemptId.root,
                    hmacChallangeResponse=resp,
                    httpx_verify=httpx_verify,
                )
                connection_details_dict |= {
                    "initiate_session_url": rm_connection_details.get("initiateSessionUrl"),
                    "access_token": rm_connection_details.get("accessToken"),
                }
            else:
                assert s2_role == Role.CEM
                # Post connection details logic for CEM role
                initiateSessionUrl: str = f"{pairing_uri}/initiateSession"
                access_token = b64encode(pairing_token.encode("utf-8")).decode("ascii")
                connection_details_dict |= {
                    "initiate_session_url": initiateSessionUrl,
                    "access_token": access_token,
                }
                cem_connection_details = {
                    "initiateSessionUrl": initiateSessionUrl,
                    "accessToken": access_token,
                }
                response = await post_connection_details(pairing_uri=pairing_uri,
                                                         attempt_id=pairing_response.pairingAttemptId.root,
                                                         connection_details=ConnectionDetails.model_validate(cem_connection_details),
                                                         serverHmacChallangeResponse=resp,
                                                         httpx_verify=httpx_verify)

            # Store connection details in the database
            storage.store_connection_details(
                s2_node_id,
                connection_details_dict,
            )
            final_response = await finalize_pairing(pairing_uri=pairing_uri,
                                                    attempt_id=pairing_response.pairingAttemptId.root,
                                                    success=True,
                                                    httpx_verify=httpx_verify)

            return (final_response.status_code == 204)
    except httpx.HTTPError as e:
        # Handle HTTP error
        raise S2PairingError(f"Pairing connection failed: {e}") from e


async def request_connection_details(pairing_uri: str,
                                     attempt_id: str,
                                     hmacChallangeResponse: HmacChallengeResponse,
                                     httpx_verify: bool | str) -> dict[str, Any]:
    """
    Request connection details from server
    Attributes:
        pairing_uri: the uri of the pairing endpoint
        attempt_id: a unique id of this pairing attempt
        serverHmacChallangeResponse: the response to the hmac challange received from the server
        httpx_verify: httpx verify parameter for TLS verification
    """
    async with httpx.AsyncClient(verify=httpx_verify, event_hooks=HTTPX_HOOKS) as client:
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
                                  httpx_verify: bool | str) -> None:
    """
    Post connection details to server
    Attributes:
        pairing_uri: the uri of the pairing endpoint
        attempt_id: a unique id of this pairing attempt
        connection_details: details object for this connection in a ConnectionDetails object
        serverHmacChallangeResponse: the response to the hmac challange received from teh server
        httpx_verify: httpx verify parameter for TLS verification
    """
    payload: PostConnectionDetailsPostRequest = PostConnectionDetailsPostRequest(
        serverHmacChallengeResponse=HmacChallengeResponse(serverHmacChallangeResponse.model_dump()),
        connectionDetails=connection_details,
    )
    async with httpx.AsyncClient(verify=httpx_verify, event_hooks=HTTPX_HOOKS) as client:
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
                           httpx_verify: bool | str,
                           success: Optional[bool] = None) -> httpx.Response:
    """
    Finalise the pairing process: post statusthe to finalizePairing endpoint
    Attributes:
        pairing_uri: the uri of the pairing endpoint
        attempt_id: a unique id of this pairing attempt
        success: did pairing succeed
        httpx_verify: httpx verify parameter for TLS verification
    """
    finalize_pairing_postRequest = FinalizePairingPostRequest(success=success)

    async with httpx.AsyncClient(verify=httpx_verify, event_hooks=HTTPX_HOOKS) as client:
        body = finalize_pairing_postRequest.model_dump_json(exclude_none=True)
        headers = add_header(token=attempt_id)
        response = await client.post(f'{pairing_uri}/finalizePairing',
                                     headers=headers,
                                     content=body)
        return response


async def connect(storage: Dao,
                 pairing_s2_node_id: str) -> bool:
    """
    Sent command to terminate the pairing
    Attributes:
        storage: The storage backend for persisting pairing information.
        pairing_s2_node_id id of the node to unpair
    """
    details = storage.load_connection_details(pairing_s2_node_id)
    pairing_uri = details.get("pairing_server_url", None) if details else None
    access_token = details.get("access_token", None) if details else None
    verify_tls = details.get("verify_tls", None) if details else None
    ssl_certfile = details.get("ssl_certfile", None) if details else None
    client_s2_node_id = details.get("client_s2_node_id", None) if details else None

    supported_s2_message_versions = details.get("supported_s2_message_versions", None) if details else None
    supported_communication_protocols = details.get("supported_communication_protocols", None) if details else None
    supported_hmac_hashing_algorithms = details.get("supported_hmac_hashing_algorithms", None) if details else None

    if not details or pairing_uri is None or access_token is None or verify_tls is None or ssl_certfile is None or client_s2_node_id is None \
        or supported_s2_message_versions is None or supported_communication_protocols is None or supported_hmac_hashing_algorithms is None:
        raise S2PairingError(
            f"Connection details for pairing_s2_node_id '{pairing_s2_node_id}' not found or incomplete."
        )

    httpx_verify = build_httpx_verify(verify_tls, ssl_certfile)
    async with httpx.AsyncClient(verify=httpx_verify, event_hooks=HTTPX_HOOKS) as client:
        init_payload: InitiateSessionPostRequest = InitiateSessionPostRequest(
            clientNodeId=NodeId(UUID(client_s2_node_id)),
            serverNodeId=NodeId(UUID(pairing_s2_node_id)),
            supportedS2MessageVersions=supported_s2_message_versions,
            supportedCommunicationProtocols=supported_communication_protocols,
        )

        body = init_payload.model_dump_json(exclude_none=True)
        headers = add_header(token=access_token)
        response = await client.post(
            f'{pairing_uri}/initiateSession',
            headers=headers,
            content=body
        )
        response.raise_for_status()
        access_token = response.json().get("accessToken")
        selected_s2_message_version = response.json().get("selectedS2MessageVersion")
        selected_communication_protocol = response.json().get("selectedCommunicationProtocol")

        assert selected_s2_message_version in supported_s2_message_versions
        assert selected_communication_protocol in supported_communication_protocols
        assert access_token is not None, "Access token not found in response from initiateSession"
        storage.store_connection_details(
            pairing_s2_node_id,
            {"selected_s2_message_version": selected_s2_message_version,
             "selected_communication_protocol": selected_communication_protocol,
             "server_node_description": response.json().get("serverNodeDescription", None),
             "server_endpoint_description": response.json().get("serverEndpointDescription", None),
             "access_token": access_token,
            }
        )
        confirmation = await confirmToken(pairing_uri, access_token, httpx_verify=httpx_verify)
        return confirmation.status_code == 200


async def confirmToken(pairing_uri: str,
                       pemding_token: str,
                       httpx_verify: bool | str) -> httpx.Response:
    """
    Sent confirmation the token
    Attributes:
        pairing_uri: the uri of the initiateConnection endpoint
        storage: The storage backend for persisting pairing information.
        client_s2_node_id: The s2 node id of the client
        pemding_token: the pending token to send
        httpx_verify: httpx verify parameter for TLS verification
    """
    async with httpx.AsyncClient(verify=httpx_verify, event_hooks=HTTPX_HOOKS) as client:
        body = '{"accessToken": "' + pemding_token + '"}'
        headers = add_header(token=pemding_token)
        response = await client.post(f'{pairing_uri}/confirmAccessToken',
                                     headers=headers,
                                     content=body)
        response.raise_for_status()
        return response


async def unpair(storage: Dao,
                 pairing_s2_node_id: str) -> bool:
    """
    Sent command to terminate the pairing
    Attributes:
        storage: The storage backend for persisting pairing information.
        pairing_s2_node_id id of the node to unpair
    """

    details = storage.load_connection_details(pairing_s2_node_id)
    pairing_uri = details.get("pairing_server_url", None) if details else None
    access_token = details.get("access_token", None) if details else None
    verify_tls = details.get("verify_tls", None) if details else None
    ssl_certfile = details.get("ssl_certfile", None) if details else None
    client_s2_node_id = details.get("client_s2_node_id", None) if details else None
    if not details or pairing_uri is None or access_token is None or verify_tls is None or ssl_certfile is None and client_s2_node_id is not None:
        raise S2PairingError(
            f"Connection details for pairing_s2_node_id '{pairing_s2_node_id}' not found or incomplete."
        )
    unpair_request = {
        "clientNodeId": client_s2_node_id,
        "serverNodeId": pairing_s2_node_id,
    }

    httpx_verify = build_httpx_verify(bool(verify_tls), ssl_certfile)
    async with httpx.AsyncClient(verify=httpx_verify, event_hooks=HTTPX_HOOKS) as client:
        headers = add_header(token=access_token)
        response = await client.post(f'{pairing_uri}/unpair',
                                     headers=headers,
                                     content=json.dumps(unpair_request))
        response.raise_for_status()
        return response.status_code == 204


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
