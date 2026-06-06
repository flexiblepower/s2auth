import secrets
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from s2auth.common.exceptions import PairingNotCompleteError
from s2auth.common.hmac import PairingToken
from s2auth.common.model.s2_connect_common import NodeId
from s2auth.common.model.s2_connect_connection_init import UnpairPostRequest
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
)
from s2auth.reference.server.versions import (
    check_s2_connect_version,
    get_supported_s2_connect_versions,
)
from s2auth.server.pairing import (
    finalize_pairing as handle_finalize_pairing,
    handle_client_response,
    initiate_pairing,
    request_pairing as handle_request_pairing,
)

router = APIRouter()
security = HTTPBasic()

USER_CLIENT_NODE_IDS: dict[str, UUID] = {
    "alice": UUID("00000000-0000-0000-0000-000000000001"),
    "bob": UUID("00000000-0000-0000-0000-000000000002"),
}


def authenticated_client_node_id(
    credentials: HTTPBasicCredentials = Depends(security),
) -> UUID:
    username = credentials.username
    if username not in USER_CLIENT_NODE_IDS or not secrets.compare_digest(
        credentials.password, username
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    return USER_CLIENT_NODE_IDS[username]


router.get("/", response_model=list[str], tags=["Pairing process"])(
    get_supported_s2_connect_versions
)


@router.post(
    "/userBeginPairing",
    tags=["Pairing process"],
)
async def user_being_pairing(
    pairing_token: PairingToken = Body(...),
    client_node_id: UUID = Depends(authenticated_client_node_id),
) -> None:
    await initiate_pairing(
        client_node_id=client_node_id,
        pairing_token=pairing_token,
    )


@router.post(
    "/{s2_connect_version}/unpair",
    response_model=None,
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
    dependencies=[Depends(set_pairing_attempt_id_from_headers)],
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
    dependencies=[Depends(set_client_node_id_from_body_node_description)],
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
