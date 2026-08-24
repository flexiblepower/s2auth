from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException

from s2auth.common.exceptions import PairingNotCompleteError
from s2auth.common.model.s2_connect_common import AccessToken, NodeId
from s2auth.common.model.s2_connect_session_init import (
    CommunicationDetailsErrorMessage,
    InitiateSessionPostRequest,
    InitiateSessionPostResponse,
    UnpairPostRequest,
)
from s2auth.common.model.s2_connect_pairing import (
    ConnectionDetails,
    FinalizePairingPostRequest,
    PairingResponseErrorMessage,
    PostConnectionDetailsPostRequest,
    PreparePairingPostRequest,
    RequestConnectionDetailsPostRequest,
    RequestPairingPostRequest,
    RequestPairingPostResponse,
    WaitForPairingPostRequest,
    WaitForPairingPostResponse,
)
from s2auth.reference.server.context import (
    set_client_node_id_from_body_node_description,
    set_client_node_id_from_body_variable,
    set_client_node_id_from_first_body_item,
    set_pairing_attempt_id_from_headers,
    set_request,
)
from s2auth.reference.server.versions import (
    check_s2_connect_version,
    get_supported_s2_connect_versions,
)
from s2auth.server.connection_initiation import initiateConnection
from s2auth.server.pairing import (
    finalize_pairing as handle_finalize_pairing,
    handle_client_response,
    request_pairing as handle_request_pairing,
)

router = APIRouter()


router.get("/", response_model=list[str], tags=["Pairing process"])(
    get_supported_s2_connect_versions
)


@router.post(
    "/{s2_connect_version}/initiateSession",
    response_model=InitiateSessionPostResponse,
    responses={"400": {"model": CommunicationDetailsErrorMessage}},
    tags=["Connection initiation"],
    dependencies=[Depends(set_client_node_id_from_body_variable)],
)
async def initiate_session(
    s2_connect_version: str = Depends(check_s2_connect_version),
    authorization: Annotated[str, Header(alias="Authorization")] = "",
    body: InitiateSessionPostRequest = None,  # pyright: ignore[reportArgumentType]
) -> InitiateSessionPostResponse | CommunicationDetailsErrorMessage:
    """
    Initiate an S2 communication session (called by client after pairing).
    """
    access_token_str = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else authorization
    return await initiateConnection(
        server_node_id=body.serverNodeId,
        access_token=AccessToken(root=access_token_str.encode("utf-8")),
        supported_communication_protocols=body.supportedCommunicationProtocols,
        supported_s2_versions=body.supportedS2MessageVersions,
        selected_s2_connect_version=s2_connect_version,
    )


@router.post(
    "/{s2_connect_version}/confirmAccessToken",
    response_model=None,
    tags=["Connection initiation"],
)
async def confirm_access_token(
    s2_connect_version: str = Depends(check_s2_connect_version),
) -> None:
    """
    Client confirms that it has stored a new accessToken.
    This endpoint just acknowledges the confirmation.
    """
    _ = s2_connect_version
    pass


@router.post(
    "/{s2_connect_version}/unpair",
    response_model=None,
    status_code=204,
    tags=["Unpairing"],
    dependencies=[Depends(set_client_node_id_from_body_variable)],
)
def unpair(
    s2_connect_version: str = Depends(check_s2_connect_version),
    body: UnpairPostRequest = None,  # pyright: ignore[reportArgumentType]
) -> None:
    """
    Unpair two S2Nodes.
    """
    _ = s2_connect_version
    pass


@router.post(
    "/{s2_connect_version}/cancelPreparePairing",
    response_model=None,
    tags=["LAN-LAN only extensions"],
    dependencies=[Depends(set_client_node_id_from_body_variable)],
)
def cancel_prepare_pairing(
    s2_connect_version: str = Depends(check_s2_connect_version),
    body: NodeId = None,  # pyright: ignore[reportArgumentType]
) -> None:
    """
    Cancel a previous call to preparePairing
    """
    _ = s2_connect_version
    pass


@router.post(
    "/{s2_connect_version}/finalizePairing",
    response_model=None,
    status_code=204,
    tags=["Pairing process"],
    dependencies=[Depends(set_pairing_attempt_id_from_headers)],
)
async def confirm_pairing(
    s2_connect_version: str = Depends(check_s2_connect_version),
    body: FinalizePairingPostRequest = None,  # pyright: ignore[reportArgumentType]
) -> None:
    """
    Confirm that the pairing was successful or has failed.
    """
    _ = s2_connect_version
    try:
        await handle_finalize_pairing(body)
    except PairingNotCompleteError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc


@router.post(
    "/{s2_connect_version}/postConnectionDetails",
    response_model=None,
    tags=["Pairing process"],
    dependencies=[Depends(set_pairing_attempt_id_from_headers)],
)
def post_connection_details(
    s2_connect_version: str = Depends(check_s2_connect_version),
    body: PostConnectionDetailsPostRequest = None,  # pyright: ignore[reportArgumentType]
) -> None:
    """
    Send connection information to the server. This only used if the PairingClient is the CommunicationServer.
    """
    _ = s2_connect_version
    pass


@router.post(
    "/{s2_connect_version}/preparePairing",
    response_model=None,
    responses={"400": {"model": PairingResponseErrorMessage}},
    tags=["LAN-LAN only extensions"],
    dependencies=[Depends(set_client_node_id_from_body_node_description)],
)
def prepare_pairing(
    s2_connect_version: str = Depends(check_s2_connect_version),
    body: PreparePairingPostRequest = None,  # pyright: ignore[reportArgumentType]
) -> PairingResponseErrorMessage | None:
    """
    Inform the server that a S2Node on the client is planning to attempt pairing with a S2Node on the server.
    """
    _ = s2_connect_version
    pass


@router.post(
    "/{s2_connect_version}/requestConnectionDetails",
    response_model=ConnectionDetails,
    tags=["Pairing process"],
    dependencies=[Depends(set_pairing_attempt_id_from_headers), Depends(set_request)],
)
async def request_connection_details(
    s2_connect_version: str = Depends(check_s2_connect_version),
    body: RequestConnectionDetailsPostRequest = None,  # pyright: ignore[reportArgumentType]
) -> ConnectionDetails:
    """
    Request connection information from the server. This is only used if the PairingServer is also the CommunicationServer.
    """
    _ = s2_connect_version
    return await handle_client_response(body)


@router.post(
    "/{s2_connect_version}/requestPairing",
    response_model=RequestPairingPostResponse,
    responses={"400": {"model": PairingResponseErrorMessage}},
    tags=["Pairing process"],
    dependencies=[
        Depends(set_request),
        Depends(set_client_node_id_from_body_node_description),
    ],
)
async def request_pairing(
    s2_connect_version: str = Depends(check_s2_connect_version),
    body: RequestPairingPostRequest = None,  # pyright: ignore[reportArgumentType]
) -> RequestPairingPostResponse | PairingResponseErrorMessage:
    """
    Initiate the pairing process.
    """
    _ = s2_connect_version
    return await handle_request_pairing(body)


@router.post(
    "/{s2_connect_version}/waitForPairing",
    response_model=WaitForPairingPostResponse,
    tags=["LAN-LAN only extensions"],
    dependencies=[Depends(set_client_node_id_from_first_body_item)],
)
def wait_for_pairing(
    s2_connect_version: str = Depends(check_s2_connect_version),
    body: WaitForPairingPostRequest = None,  # pyright: ignore[reportArgumentType]
) -> WaitForPairingPostResponse:  # pyright: ignore[reportReturnType]
    """
    Long polling operation to indicate to the server that the client is available for pairing.
    """
    _ = s2_connect_version
    pass
