from fastapi import FastAPI
import s2auth

from s2auth.common.model.s2_connect_connection_init import (
    CommunicationDetailsErrorMessage,
    ConfirmAccessTokenPostResponse,
    InitiateConnectionPostRequest,
    InitiateConnectionPostResponse,
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
from s2auth.common.model.s2_connect_common import NodeId

app = FastAPI(
    version=s2auth.__version__,
    title="s2-over-ip pairing and connection initiation",
    description="The HTTP API specification of the pairing process for S2 over IP connections, as well as initiating connections. For more information, please find the specification at [S2 documentation](https://docs.s2standard.org).",
    license={
        "name": "Apache-2.0",
        "url": "https://raw.githubusercontent.com/flexiblepower/s2-ws-json/refs/heads/main/LICENSE",
    },
    servers=[{"url": "/v1"}],
)


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
    "/initiateConnection",
    response_model=InitiateConnectionPostResponse,
    responses={"400": {"model": CommunicationDetailsErrorMessage}},
    tags=["Connection initiation"],
)
def initiate_connection(
    body: InitiateConnectionPostRequest = None,  # pyright: ignore[reportArgumentType]
) -> InitiateConnectionPostResponse | CommunicationDetailsErrorMessage:  # pyright: ignore[reportReturnType]
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
