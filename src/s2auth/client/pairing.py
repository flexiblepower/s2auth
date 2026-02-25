"""Utilities for performing the pairing process of S2 as a client.
"""

import logging
import re
from base64 import b64encode
from typing import Any, List, Optional
from uuid import UUID

import httpx
from pydantic import AnyUrl, TypeAdapter
from s2auth.client.dao import Dao
from s2auth.common.exceptions import S2PairingError, VerificationError
from s2auth.common.hmac import (create_challenge, create_pairing_token,
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
    RequestPairingPostRequest, RequestPairingPostResponse)

LOGGER = logging.getLogger(__name__)


async def pair(pairing_uri: str,
               pairing_token: str,
               storage: Dao,
               role: str,
               deployment: str,
               supported_s2_message_versions: List[str],
               supported_communication_protocols: List[str],
               supportedHmacHashingAlgorithms: List[str],
               s2_client_description: S2NodeDescription,
               pairing_s2_node_id: Optional[str] = None,
               verify: bool = True) -> bool:
    """
    Preform the initial pairing
    Attributes:
        storage (Dao): The storage backend for persisting pairing information.
        role: The S2 role (CEM/RM) of the client.
        deployment: The deployment (WAN/LAN) of this client
        supported_s2_message_versions: List of versions of the S2 messages that the client supports
        supported_communication_protocols: List of communication protocols (e.g. WebSockets) that the client supports
        s2_client_description: Information about this client that will be send to the server,
        such as brand, model, logo URL etc. Also contains a globally unique identifier
        of the S2 node this client wants to pair to a node on the server
    """
    # Create client HMAC challenge that the server needs to solve
    # Create /requestPairing request body object
    # Do the HTTP request
    # Check the client HMAC challenge response
    # Solve the server HMAC challenge
    # Depending on the client/server role in the connection initiation of other S2 node either requestConnectionDetails or postConnectionDetails
    # In any case, store the connection details in the database.

    # If no id given use id from client
    pairing_uri = strip_pairing_url(pairing_uri)
    s2_role: S2Role = S2Role(role)
    s2_deployment: Deployment = Deployment(deployment)
    communication_protocols: List[CommunicationProtocol] = list(map(CommunicationProtocol, supported_communication_protocols))
    supported_hmac_hashing_algorithms: List[HmacHashingAlgorithm] = list(map(HmacHashingAlgorithm, supportedHmacHashingAlgorithms))

    if not pairing_token and s2_role == S2Role.RM:
        raise S2PairingError("Access token required for pairing RM")
    elif not pairing_token:
        pairing_token = create_pairing_token()

    LOGGER.warning(f"Using access token: {pairing_token}")

    s2_node_id: str = str(pairing_s2_node_id) if pairing_s2_node_id else str(s2_client_description.id.model_dump(exclude_none=True))
    client_hmac_challenge = create_challenge()
    request_payload: RequestPairingPostRequest = RequestPairingPostRequest(
        clientS2NodeDescription=s2_client_description,
        clientS2EndpointDescription=S2EndpointDescription(
            name=f"{s2_client_description.userDefinedName if s2_client_description.userDefinedName else s2_client_description.brand} endpoint",
            logoUrl=s2_client_description.logoUrl,
            deployment=s2_deployment,
        ),
        pairingS2NodeId=None,
        supportedCommunicationProtocols=communication_protocols,
        supportedS2MessageVersions=supported_s2_message_versions,
        supportedHmacHashingAlgorithms=supported_hmac_hashing_algorithms,
        clientHmacChallenge=client_hmac_challenge,
        forcePairing=True
    )
    body = request_payload.model_dump_json(exclude_none=True)

    try:
        async with httpx.AsyncClient(verify=verify) as client:
            LOGGER.debug(f'posting {pairing_uri}/requestPairing with json:\n{body}')
            response = await client.post(f'{pairing_uri}/requestPairing', content=body, headers={"Content-Type": "application/json"})
            LOGGER.debug(f'Response: {response}')
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
                                                         verify=verify)

            final_response = await finalize_pairing(pairing_uri=pairing_uri,
                                                    attempt_id=pairing_response.pairingAttemptId.model_dump(exclude_none=True),
                                                    verify=verify,
                                                    success=True)
            return (final_response.status_code == 204)
    except httpx.HTTPError as e:
        # Handle HTTP error
        raise S2PairingError(f"Pairing connection failed: {e}") from e


async def request_connection_details(pairing_uri: str, attempt_id: str, serverHmacChallangeResponse: HmacChallenge, verify: bool) -> dict[Any, Any]:
    async with httpx.AsyncClient(verify=verify) as client:
        payload: RequestConnectionDetailsPostRequest = RequestConnectionDetailsPostRequest(
            serverHmacChallengeResponse=HmacChallengeResponse(serverHmacChallangeResponse.model_dump(exclude_none=True))
        )
        body = payload.model_dump_json(exclude_none=True)
        headers = add_header(pairing_attempt_id=attempt_id)
        LOGGER.debug(f'posting {pairing_uri}/requestConnectionDetails with headers:\n{headers}\nand json:\n{body}')
        response = await client.post(
            f'{pairing_uri}/requestConnectionDetails',
            headers=headers,
            content=body,
        )
        LOGGER.debug(f'Response: {response}')
        return response.json()


async def post_connection_details(pairing_uri: str,
                                  attempt_id: str,
                                  connection_details: ConnectionDetails,
                                  serverHmacChallangeResponse: HmacChallenge,
                                  verify: bool) -> None:
    payload: PostConnectionDetailsPostRequest = PostConnectionDetailsPostRequest(
        serverHmacChallengeResponse=HmacChallengeResponse(serverHmacChallangeResponse.model_dump()),
        connectionDetails=connection_details,
    )
    async with httpx.AsyncClient(verify=verify) as client:
        body = payload.model_dump_json(exclude_none=True)
        headers = add_header(pairing_attempt_id=attempt_id)
        LOGGER.debug(f'posting {pairing_uri}/postConnectionDetails with headers:\n{headers}\nand json:\n{body}')
        response = await client.post(
            f'{pairing_uri}/postConnectionDetails',
            headers=headers,
            content=body,
        )
        LOGGER.debug(f'Response: {response}')
        response.raise_for_status()
        if not response.status_code == 204:
            raise S2PairingError("postConnectionDetails failed")


async def finalize_pairing(pairing_uri: str, attempt_id: str, verify: bool, success: Optional[bool] = None) -> httpx.Response:
    finalize_pairing_postRequest = FinalizePairingPostRequest(success=success)

    async with httpx.AsyncClient(verify=verify) as client:
        body = finalize_pairing_postRequest.model_dump_json(exclude_none=True)
        headers = add_header(pairing_attempt_id=attempt_id)
        LOGGER.debug(f'posting {pairing_uri}/finalizePairing with headers:\n{headers}\nand json:\n{body}')
        response = await client.post(f'{pairing_uri}/finalizePairing',
                                     headers=headers,
                                     content=body)
        LOGGER.debug(f'Response: {response}')
        return response


class ConnectionClient:
    def __init__(self, client_uri: str,
                 storage: Dao, role: str,
                 deployment: str,
                 supported_s2_message_versions: List[str],
                 supported_communication_protocols: List[str],
                 verify: bool = True) -> None:
        self._logger = logging.getLogger("ConnectionClient")

        self._client_uri: str = strip_pairing_url(client_uri)
        self._storage: Dao = storage
        self._deployment = Deployment(deployment)
        self._role: S2Role = S2Role(role)
        self._supported_s2_message_versions: List[str] = supported_s2_message_versions
        self._supported_communication_protocols: List[CommunicationProtocol] = list(map(CommunicationProtocol, supported_communication_protocols))
        self._verify = verify

    async def connect(self, s2_client_description: S2NodeDescription, serverS2NodeId: str, clientS2NodeId: Optional[str] = None):
        # If no id given use id from client
        client_s2_node_id: str = str(clientS2NodeId) if clientS2NodeId else str(serverS2NodeId)

        async with httpx.AsyncClient(verify=self._verify) as client:
            init_payload: InitiateConnectionPostRequest = InitiateConnectionPostRequest(
                serverS2NodeId=S2NodeId(UUID(serverS2NodeId)),
                clientS2NodeId=S2NodeId(UUID(client_s2_node_id)),
                supportedS2MessageVersions=self._supported_s2_message_versions,
                supportedCommunicationProtocols=self._supported_communication_protocols,
            )

            body = init_payload.model_dump_json(exclude_none=True)
            headers = add_header(access_token=self.get_pairing_token_str(client_s2_node_id))
            self._logger.debug(f'posting {self._client_uri}/initiateConnection with headers:\n{headers}\nand json:\n{body}')
            response = await client.post(
                f'{self._client_uri}/initiateConnection',
                headers=headers,
                content=body
            )
            self._logger.debug(f'Response: {response}')
            response.raise_for_status()
            confirmation = await self.confirmToken(client_s2_node_id, response.json().get("pendingToken"))
            # Store connection details in the database
            token: str = confirmation.json().get("websocketToken")
            self._storage.store_connection_details(client_s2_node_id, token)
            return confirmation.status_code == 200

    def get_pairing_token_str(self, s2_node_id: str) -> Optional[str]:
        return self._storage.load_connection_details(s2_node_id)

    async def confirmToken(self, client_s2_node_id: str, pendingToken: str):
        async with httpx.AsyncClient(verify=self._verify) as client:
            body = '{"pendingToken": "pendingToken"}'
            headers = add_header(access_token=self.get_pairing_token_str(client_s2_node_id))
            self._logger.debug(f'posting {self._client_uri}/confirmToken with headers:\n{headers}\nand json:\n{body}')
            response = await client.post(f'{self._client_uri}/confirmToken',
                                         headers=headers,
                                         content=body)
            self._logger.debug(f'Response: {response}')
            response.raise_for_status()
            return response.json()

    async def unpair(self, pairing_s2_node_id: str, serverS2NodeId: str, clientS2NodeId: Optional[str] = None):
        client_s2_node_id: str = str(clientS2NodeId) if clientS2NodeId else str(serverS2NodeId)
        async with httpx.AsyncClient(verify=self._verify) as client:
            body = pairing_s2_node_id
            headers = add_header(access_token=self.get_pairing_token_str(client_s2_node_id))
            self._logger.debug(f'posting {self._client_uri}/unpair with headers:\n{headers}\nand json:\n{body}')
            response = await client.post(f'{self._client_uri}/unpair',
                                         headers=headers,
                                         content=body)
            self._logger.debug(f'Response: {response}')
            response.raise_for_status()
            return response.status_code == 204


def strip_pairing_url(url_str: str):
    return re.sub('/$', '', re.sub('requestPairing$', '', re.sub('initiateConnection$', '', url_str)))


def add_header(access_token: Optional[str] = None, pairing_attempt_id: Optional[str] = None):
    header = {"Content-Type": "application/json"}
    if access_token:
        header["accessToken"] = access_token
    if pairing_attempt_id:
        header["pairingAttemptId"] = pairing_attempt_id
    return header
