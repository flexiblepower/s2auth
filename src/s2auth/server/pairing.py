"""Pairing functionality for the S2 server."""

from typing import Awaitable, Callable
from uuid import uuid4
from s2auth.common.models import (
    PairingAttemptId as S2PairingAttemptId,
    PairingS2NodeId,
    RequestPairingPostRequest,
    S2NodeId,
)
from s2auth.server.dependencies import Depends, inject
from s2auth.server.dependencies.context import (
    ClientContext,
    PairingAttemptContext,
    PairingAttemptId,
    pairing_attempt_context,
    pairing_attempt_id_var,
    s2_client_node_id_var,
    store_client_context,
    store_pairing_attempt_context,
)
from s2auth.common.hmac import create_challenge, create_pairing_token
from s2auth.server.settings import Settings, settings


@inject
async def initiate_pairing(
    store_pairing_ctx: Callable[[PairingAttemptContext], Awaitable[None]] = Depends[store_pairing_attempt_context],
    server_settings: Settings = Depends[settings],
):
    pairing_attempt_id: PairingAttemptId = uuid4()
    pairing_attempt_id_var.set(S2PairingAttemptId(root=str(pairing_attempt_id)))
    pairing_token = create_pairing_token()
    pairing_node_id = server_settings.pairing_node_id
    ctx = PairingAttemptContext(
        pairing_attempt_id=pairing_attempt_id,
        pairing_token=pairing_token,
        pairing_node_id=PairingS2NodeId(root=pairing_node_id),
    )
    await store_pairing_ctx(ctx)


@inject
async def request_pairing(
    request: RequestPairingPostRequest,
    store_client_ctx: Callable[[ClientContext], Awaitable[None]] = Depends[store_client_context],
    pairing_context: PairingAttemptContext = Depends[pairing_attempt_context],
) -> str:
    """Initiate a new pairing attempt.

    Args:
        request: The pairing request containing client node description
        store_client_context: Function to store client context
        pairing_context: The pairing attempt context

    Returns:
        The pairing attempt ID (as a string)
    """

    # Create a new pairing_attempt_id

    # Set the contextvars
    client_node_id = request.s2ClientNodeDescription.id.root
    client_ctx = ClientContext(client_node_id=client_node_id, state="pairing")
    await store_client_ctx(client_ctx)
    s2_client_node_id_var.set(S2NodeId(root=client_node_id))

    # Get or create the PairingAttemptContext
    pairing_context.client_node_id = client_node_id
    # Set the state to "initiated" and store both IDs
    pairing_context.state = "initiated"
    challenge = create_challenge()

    return challenge
