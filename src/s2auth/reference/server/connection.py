import base64
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException

from s2auth.common.model.s2_connect_common import AccessToken, CommunicationToken
from s2auth.common.model.s2_connect_session_init import (
    WebSocketCommunicationDetails,
    CommunicationDetailsErrorMessage,
    InitiateSessionPostRequest,
    InitiateSessionPostResponse,
)
from s2auth.reference.server.context import (
    set_client_node_id_from_body_variable,
)
from s2auth.reference.server.versions import (
    check_s2_connect_version,
    get_supported_s2_connect_versions,
)
from s2auth.server.context import (
    AuthenticationContext,
    S2InMemoryContextStorage,
    s2_context_storage_singleton,
)
from s2auth.server.settings import Settings, settings
from s2auth.server.connection_initiation import (
    initiateConnection,
    validate_access_token,
)

router = APIRouter()
log = logging.getLogger(__name__)


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
    response_model=WebSocketCommunicationDetails,
    tags=["Connection initiation"],
)
async def post_confirm_access_token(
    s2_connect_version: str = Depends(check_s2_connect_version),
    access_token: Annotated[str | None, Header(alias="accessToken")] = None,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    storage: S2InMemoryContextStorage = Depends(s2_context_storage_singleton),
    server_settings: Settings = Depends(settings),
) -> WebSocketCommunicationDetails:
    """
    Client confirms that is has stored a new accessToken
    """
    _ = s2_connect_version
    token = access_token or authorization
    if not token:
        raise HTTPException(status_code=401, detail="Missing access token")
    token = token.removeprefix("Bearer ") if token.startswith("Bearer ") else token

    auth_contexts = await storage.list_contexts(AuthenticationContext)
    token_model = AccessToken(root=token.encode("utf-8"))
    for cts in auth_contexts:
        if await validate_access_token(token_model, cts):
            websocket_token_source = cts.current_connection_token or token_model
            log.info(server_settings.cem_url)
            assert server_settings.cem_url is not None, "CEM URL must be set in server settings"
            return WebSocketCommunicationDetails(
                websocketToken=CommunicationToken(root=base64.b64encode(websocket_token_source.root)),
                websocketUrl=str(server_settings.cem_url),
            )

    raise HTTPException(status_code=401, detail="No matching authentication context found for access token")

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
        cem_s2_node_id=body.serverNodeId,
        access_token=AccessToken(root=access_token.encode("utf-8")),
        supported_communication_protocols=body.supportedCommunicationProtocols,
        supported_s2_versions=body.supportedS2MessageVersions,
        selected_s2_connect_version=s2_connect_version,
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
        cem_s2_node_id=body.serverNodeId,
        access_token=AccessToken(root=access_token_str.encode("utf-8")),
        supported_communication_protocols=body.supportedCommunicationProtocols,
        supported_s2_versions=body.supportedS2MessageVersions,
        selected_s2_connect_version=s2_connect_version,
    )
