from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

import s2auth
<<<<<<< HEAD
from s2auth.common.model.s2_connect_common import NodeId
from s2auth.common.model.s2_connect_session_init import (
    CommunicationDetailsErrorMessage, ConfirmAccessTokenPostResponse,
    InitiateSessionPostRequest, InitiateSessionPostResponse,
    UnpairPostRequest)
from s2auth.common.model.s2_connect_pairing import (
    ConnectionDetails, FinalizePairingPostRequest, PairingResponseErrorMessage,
    PostConnectionDetailsPostRequest, PreparePairingPostRequest,
    RequestConnectionDetailsPostRequest, RequestPairingPostRequest,
    RequestPairingPostResponse, WaitForPairingPostRequest,
    WaitForPairingPostResponse)
=======
from s2auth.reference.server.connection import router as connection_router
from s2auth.reference.server.pairing import router as pairing_router
from s2auth.reference.server.logging import setupLogging, LogLevel
from s2auth.server import setup as setup_s2auth_server


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Initialize reference server hooks and dependency injection."""
    _ = app
    setupLogging(default_log_level=LogLevel.DEBUG, logger_config={})
    setup_s2auth_server(additional_hook_modules=["s2auth.reference.server.hooks"])
    yield

>>>>>>> bfbc5c3 (Add more endpoints and add and fix tests)

app = FastAPI(
    version=s2auth.__version__,
    title="s2-over-ip pairing and connection initiation",
    description="The HTTP API specification of the pairing process for S2 over IP connections, as well as initiating connections. For more information, please find the specification at [S2 documentation](https://docs.s2standard.org).",
    license={
        "name": "Apache-2.0",
        "url": "https://raw.githubusercontent.com/flexiblepower/s2-ws-json/refs/heads/main/LICENSE",
    },
    lifespan=lifespan,
)

<<<<<<< HEAD

@app.post(
    "/confirmAccessToken",
    response_model=ConfirmAccessTokenPostResponse,
    tags=["Connection initiation"],
)
def post_confirm_access_token() -> ConfirmAccessTokenPostResponse:  # pyright: ignore[reportReturnType]
    """
    Client confirms that is has stored a new accessToken
    """
    pass


@app.post(
    "/initiateSession",
    response_model=InitiateSessionPostResponse,
    responses={"400": {"model": CommunicationDetailsErrorMessage}},
    tags=["Connection initiation"],
)
def initiate_connection(
    body: InitiateSessionPostRequest = None,  # pyright: ignore[reportArgumentType]
) -> InitiateSessionPostResponse | CommunicationDetailsErrorMessage:  # pyright: ignore[reportReturnType]
    """
    Initiate an S2 communication session
    """
    pass


@app.post("/unpair", response_model=None, tags=["Unpairing"])
def unpair(body: UnpairPostRequest = None) -> None:  # pyright: ignore[reportArgumentType]
    """
    Unpair two S2Nodes.
    """
    pass


@app.post(
    "/cancelPreparePairing", response_model=None, tags=["LAN-LAN only extensions"]
)
def cancel_prepare_pairing(body: NodeId = None) -> None:  # pyright: ignore[reportArgumentType]
    """
    Cancel a previous call to preparePairing
    """
    pass


@app.post("/finalizePairing", response_model=None, tags=["Pairing process"])
def confirm_pairing(body: FinalizePairingPostRequest = None) -> None:  # pyright: ignore[reportArgumentType]
    """
    Confirm that the pairing was successful or has failed.
    """
    pass


@app.post("/postConnectionDetails", response_model=None, tags=["Pairing process"])
def post_connection_details(body: PostConnectionDetailsPostRequest = None) -> None:  # pyright: ignore[reportArgumentType]
    """
    Send connection information to the server. This only used if the PairingClient is the CommunicationServer.
    """
    pass


@app.post(
    "/preparePairing",
    response_model=None,
    responses={"400": {"model": PairingResponseErrorMessage}},
    tags=["LAN-LAN only extensions"],
)
def prepare_pairing(
    body: PreparePairingPostRequest = None,  # pyright: ignore[reportArgumentType]
) -> PairingResponseErrorMessage | None:
    """
    Inform the server that a S2Node on the client is planning to attempt pairing with a S2Node on the server.
    """
    pass


@app.post(
    "/requestConnectionDetails",
    response_model=ConnectionDetails,
    tags=["Pairing process"],
)
def request_connection_details(
    body: RequestConnectionDetailsPostRequest = None,  # pyright: ignore[reportArgumentType]
) -> ConnectionDetails:  # pyright: ignore[reportReturnType]
    """
    Request connection information from the server. This is only used if the PairingServer is also the CommunicationServer.
    """
    pass


@app.post(
    "/requestPairing",
    response_model=RequestPairingPostResponse,
    responses={"400": {"model": PairingResponseErrorMessage}},
    tags=["Pairing process"],
)
def request_pairing(
    body: RequestPairingPostRequest = None,  # pyright: ignore[reportArgumentType]
) -> RequestPairingPostResponse | PairingResponseErrorMessage:  # pyright: ignore[reportReturnType]
    """
    Initiate the pairing process.
    """
    pass


@app.post(
    "/waitForPairing",
    response_model=WaitForPairingPostResponse,
    tags=["LAN-LAN only extensions"],
)
def wait_for_pairing(
    body: WaitForPairingPostRequest = None,  # pyright: ignore[reportArgumentType]
) -> WaitForPairingPostResponse:  # pyright: ignore[reportReturnType]
    """
    Long polling operation to indicate to the server that the client is available for pairing.
    """
    pass
=======
app.include_router(pairing_router, prefix="/pairing")
app.include_router(connection_router, prefix="/connection")
>>>>>>> bfbc5c3 (Add more endpoints and add and fix tests)
