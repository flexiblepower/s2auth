"""Pairing functionality for the S2 server."""

from base64 import b64encode
from typing import Awaitable, Callable
from uuid import uuid4
from s2auth.common.model.s2_connect_pairing import (
    ConnectionDetails,
    HmacChallengeResponse,
    PairingAttemptId as S2PairingAttemptId,
    NodeIdAlias,
    RequestConnectionDetailsPostRequest,
    RequestPairingPostRequest,
    RequestPairingPostResponse,
)
from s2auth.common.model.s2_connect_common import AccessToken, NodeId
from s2auth.common.dependencies import Depends, inject
from s2auth.server.context import (
    ClientContext,
    ClientState,
    PairingAttemptContext,
    PairingAttemptId,
    PairingState,
    ReadOnlyClientContext,
    ReadOnlyPairingAttemptContext,
    client_context,
    pairing_attempt_context,
    pairing_attempt_id_var,
    s2_client_node_id_var,
    store_client_context,
    store_pairing_attempt_context,
)
from s2auth.common.hmac import (
    PairingToken,
    create_challenge,
    create_response,
    create_pairing_code,
    generate_access_token,
    select_algorithm,
    verify_response,
)
from s2auth.server.settings import Settings, settings
from s2auth.server.config import Config, config
from s2auth.server.hooks import (
    HookRegistry,
    get_server_endpoint,
    hook_registry,
    pairing_attempt_request,
)


@inject
async def initiate_pairing(
    store_pairing_ctx: Callable[[PairingAttemptContext], Awaitable[None]] = Depends[
        store_pairing_attempt_context
    ],
    server_settings: Settings = Depends[settings],
    pairing_token: PairingToken = Depends[create_pairing_code],
):
    pairing_attempt_id: PairingAttemptId = uuid4()
    # Encode UUID string as base64 bytes for S2PairingAttemptId (Base64Bytes)
    pairing_attempt_id_b64 = b64encode(str(pairing_attempt_id).encode("utf-8"))
    pairing_attempt_id_var.set(S2PairingAttemptId(root=pairing_attempt_id_b64))
    pairing_node_id = server_settings.pairing_node_id
    ctx = PairingAttemptContext(
        pairing_attempt_id=pairing_attempt_id,
        pairing_token=pairing_token,
        pairing_node_id=NodeIdAlias(root=pairing_node_id),
    )
    await store_pairing_ctx(ctx)
    return ctx


@inject
async def request_pairing(
    request: RequestPairingPostRequest,
    store_client_ctx: Callable[[ClientContext], Awaitable[None]] = Depends[
        store_client_context
    ],
    pairing_context: PairingAttemptContext = Depends[pairing_attempt_context],
    hooks: HookRegistry = Depends[hook_registry],
    cfg: Config = Depends[config],
) -> RequestPairingPostResponse:
    """Initiate a new pairing attempt.

    Args:
        request: The pairing request containing client node description
        store_client_context: Function to store client context
        pairing_context: The pairing attempt context
        hooks: Hook registry for calling server hooks

    Returns:
        The pairing response with server descriptions and challenge
    """

    # Set the contextvars
    client_node_id = request.clientNodeDescription.id.root
    client_ctx = ClientContext(
        client_node_id=client_node_id,
        state=ClientState.PAIRING,
        s2_endpoint_description=request.clientEndpointDescription,
        s2_node_description=request.clientNodeDescription,
    )
    await store_client_ctx(client_ctx)
    s2_client_node_id_var.set(NodeId(root=client_node_id))

    pairing_context.client_node_id = client_node_id

    algorithm = select_algorithm(request.supportedHmacHashingAlgorithms)
    pairing_context.algorithm = algorithm

    client_response = create_response(
        pairing_token=pairing_context.pairing_token,
        challenge=request.clientHmacChallenge,
        algorithm=algorithm,
        hmac_salt=cfg.hmac_salt,
    )
    # Set the state to "initiated" and store both IDs
    pairing_context.state = PairingState.INITIATED
    server_challenge = create_challenge()

    pairing_context.server_hmac_challenge = server_challenge

    # Call the hook to get server descriptions (can be overridden)
    # Pass read-only copies to enforce immutability in hooks
    pairing_hook = hooks.get(pairing_attempt_request)
    server_endpoint_description, server_node_description = await pairing_hook(
        ReadOnlyClientContext.model_validate(client_ctx),
        ReadOnlyPairingAttemptContext.model_validate(pairing_context),
    )

    return RequestPairingPostResponse(
        selectedHmacHashingAlgorithm=algorithm,
        serverNodeDescription=server_node_description,
        serverEndpointDescription=server_endpoint_description,
        clientHmacChallengeResponse=HmacChallengeResponse(root=client_response),
        serverHmacChallenge=server_challenge,
        pairingAttemptId=S2PairingAttemptId(
            root=b64encode(
                str(pairing_context.pairing_attempt_id).encode("utf-8")
            )
        ),
    )


@inject
async def handle_client_response(
    request: RequestConnectionDetailsPostRequest,
    pairing_context: PairingAttemptContext = Depends[pairing_attempt_context],
    client_ctx: ClientContext = Depends[client_context],
    hooks: HookRegistry = Depends[hook_registry],
    generate_access_token: Callable[[], AccessToken] = Depends[generate_access_token],
    cfg: Config = Depends[config],
) -> ConnectionDetails:
    """Handle the client's response and return the server's connection details.

    Args:
        request: The request from the client for connection details
        pairing_context: The pairing attempt context
        client_ctx: The client context with its connection and endpoint details
        hooks: Hook registry for calling server hooks

    Returns:
        The ConnectionDetails for the client to setup the s2 connection.


    """
    challenge_response = request.serverHmacChallengeResponse.root
    assert pairing_context.algorithm is not None, "No algorithm selected."
    assert pairing_context.server_hmac_challenge is not None, "No known hmac challenge."
    verify_response(
        pairing_token=pairing_context.pairing_token,
        algorithm=pairing_context.algorithm,
        challenge=pairing_context.server_hmac_challenge,
        response=challenge_response,
        hmac_salt=cfg.hmac_salt,
    )

    endpoint_hook = hooks.get(get_server_endpoint)
    server_endpoint = await endpoint_hook(
        ReadOnlyClientContext.model_validate(client_ctx),
    )
    access_token = generate_access_token()
    client_ctx.access_token = access_token
    client_ctx.state = ClientState.PAIRED
    pairing_context.state = PairingState.COMPLETED
    return ConnectionDetails(
        initiateConnectionUrl=server_endpoint, accessToken=access_token
    )
