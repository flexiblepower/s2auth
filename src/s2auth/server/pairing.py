"""Pairing functionality for the S2 server."""

from base64 import b64encode
from typing import Awaitable, Callable
from uuid import uuid4
from s2auth.common.model.s2_over_ip_pairing import (
    HmacChallengeResponse,
    PairingAttemptId as S2PairingAttemptId,
    PairingS2NodeId,
    RequestPairingPostRequest,
    RequestPairingPostResponse,
)
from s2auth.common.model.s2_over_ip_common import S2NodeId
from s2auth.common.dependencies import Depends, inject
from s2auth.server.context import (
    ClientContext,
    PairingAttemptContext,
    PairingAttemptId,
    ReadOnlyClientContext,
    ReadOnlyPairingAttemptContext,
    pairing_attempt_context,
    pairing_attempt_id_var,
    s2_client_node_id_var,
    store_client_context,
    store_pairing_attempt_context,
)
from s2auth.common.hmac import (
    PairingToken,
    create_challenge,
    create_pairing_token,
    create_response,
    select_algorithm,
)
from s2auth.server.settings import Settings, settings
from s2auth.server.hooks import HookRegistry, hook_registry, pairing_attempt_request


@inject
async def initiate_pairing(
    store_pairing_ctx: Callable[[PairingAttemptContext], Awaitable[None]] = Depends[
        store_pairing_attempt_context
    ],
    server_settings: Settings = Depends[settings],
    pairing_token: PairingToken = Depends[create_pairing_token],
):
    pairing_attempt_id: PairingAttemptId = uuid4()
    # Encode UUID string as base64 for S2PairingAttemptId (Base64Str requires valid UTF-8)
    pairing_attempt_id_b64 = b64encode(str(pairing_attempt_id).encode("utf-8")).decode(
        "utf-8"
    )
    pairing_attempt_id_var.set(S2PairingAttemptId(root=pairing_attempt_id_b64))
    pairing_node_id = server_settings.pairing_node_id
    ctx = PairingAttemptContext(
        pairing_attempt_id=pairing_attempt_id,
        pairing_token=pairing_token,
        pairing_node_id=PairingS2NodeId(root=pairing_node_id),
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
    client_node_id = request.clientS2NodeDescription.id.root
    client_ctx = ClientContext(client_node_id=client_node_id, state="pairing")
    await store_client_ctx(client_ctx)
    s2_client_node_id_var.set(S2NodeId(root=client_node_id))

    pairing_context.client_node_id = client_node_id

    algorithm = select_algorithm(request.supportedHmacHashingAlgorithms)
    client_response = create_response(
        pairing_token=pairing_context.pairing_token,
        challenge=request.clientHmacChallenge,
        algorithm=algorithm,
    )
    # Set the state to "initiated" and store both IDs
    pairing_context.state = "initiated"
    server_challenge = create_challenge()

    # Call the hook to get server descriptions (can be overridden)
    # Pass read-only copies to enforce immutability in hooks
    pairing_hook = hooks.get(pairing_attempt_request)
    server_endpoint_description, server_node_description = await pairing_hook(
        ReadOnlyClientContext.model_validate(client_ctx),
        ReadOnlyPairingAttemptContext.model_validate(pairing_context),
    )

    return RequestPairingPostResponse(
        selectedHmacHashingAlgorithm=algorithm,
        serverS2NodeDescription=server_node_description,
        serverS2EndpointDescription=server_endpoint_description,
        clientHmacChallengeResponse=HmacChallengeResponse(root=client_response),
        serverHmacChallenge=server_challenge,
        pairingAttemptId=S2PairingAttemptId(
            # TODO should probably be a regular UUID or str, not Base64Str
            root=b64encode(
                str(pairing_context.pairing_attempt_id).encode("ascii")
            ).decode("ascii")
        ),
    )
