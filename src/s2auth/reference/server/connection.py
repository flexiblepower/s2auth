from typing import Annotated

from fastapi import APIRouter, Depends, Header

from s2auth.common.model.s2_connect_common import AccessToken
from s2auth.common.model.s2_connect_session_init import (
    CommunicationDetailsErrorMessage,
    InitiateSessionPostRequest,
    InitiateSessionPostResponse,
)
from s2auth.reference.server.context import (
    set_client_node_id_from_body_variable,
    set_client_node_id_from_headers,
)
from s2auth.reference.server.versions import (
    check_s2_connect_version,
    get_supported_s2_connect_versions,
)
from s2auth.server.connection_initiation import (
    initiateConnection,
    validate_access_token,
)

router = APIRouter()


router.get(
    "/",
    response_model=list[str],
    tags=["Connection initiation"],
    name="connection_root",
)(
    get_supported_s2_connect_versions
)


@router.post(
    "/{s2_connect_version}/confirmAccessToken",
    response_model=None,
    tags=["Connection initiation"],
    dependencies=[Depends(set_client_node_id_from_headers)],
)
async def post_confirm_access_token(
    s2_connect_version: str = Depends(check_s2_connect_version),
    access_token: Annotated[str, Header(alias="accessToken")] = "",
) -> None:
    """
    Client confirms that is has stored a new accessToken
    """
    _ = s2_connect_version
    await validate_access_token(AccessToken(root=access_token.encode("utf-8")))


@router.post(
    "/{s2_connect_version}/initiateConnection",
    response_model=InitiateSessionPostResponse,
    responses={"400": {"model": CommunicationDetailsErrorMessage}},
    tags=["Connection initiation"],
    dependencies=[Depends(set_client_node_id_from_body_variable)],
)
async def initiate_connection(
    s2_connect_version: str = Depends(check_s2_connect_version),
    access_token: Annotated[str, Header(alias="accessToken")] = "",
    body: InitiateSessionPostRequest = None,  # pyright: ignore[reportArgumentType]
) -> InitiateSessionPostResponse | CommunicationDetailsErrorMessage:
    """
    Initiate an S2 communication session
    """
    return await initiateConnection(
        server_node_id=body.serverNodeId,
        access_token=AccessToken(root=access_token.encode("utf-8")),
        supported_communication_protocols=body.supportedCommunicationProtocols,
        supported_s2_versions=body.supportedS2MessageVersions,
        selected_s2_connect_version=s2_connect_version,
    )
