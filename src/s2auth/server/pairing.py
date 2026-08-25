"""Pairing functionality for the S2 server."""

from base64 import b64encode
from typing import Awaitable, Callable
from uuid import uuid4
from s2auth.common.exceptions import AccessError, PairingNotCompleteError
from s2auth.common.model.s2_connect_pairing import (
    ConnectionDetails,
    FinalizePairingPostRequest,
    HmacChallengeResponse,
    PairingAttemptId as S2PairingAttemptId,
    NodeIdAlias,
    RequestConnectionDetailsPostRequest,
    RequestPairingPostRequest,
    RequestPairingPostResponse,
)
from s2auth.common.model.s2_connect_common import AccessToken, NodeId
from wepositive_di import Depends, inject
from wepositive_di.context import ContextStorage, context_storage_singleton
from s2auth.server.context import (
    AuthenticationContext,
    ClientNodeId,
    ClientState,
    PairingAttemptContext,
    PairingAttemptId,
    PairingState,
    ReadOnlyAuthenticationContext,
    ReadOnlyPairingAttemptContext,
    S2InMemoryContextStorage,
    authentication_context,
    authentication_context_by_pairing_attempt_context,
    pairing_attempt_context,
    pairing_attempt_context_by_client_node_id,
    pairing_attempt_id_var,
    s2_client_node_id_var,
    store_authentication_context,
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
from s2auth.server.config import Config, config
from s2auth.server.hooks import (
    HookRegistry,
    get_server_connection_initiation_endpoint,
    get_server_endpoint_description,
    get_server_node_description,
    hook_registry,
    pairing_attempt_request,
)
from s2auth.server.settings import Settings, settings
from s2auth.server.token_manager import consume_pending_pairing_token
import logging

log = logging.getLogger(__name__)


@inject
async def initiate_pairing(
    client_node_id: ClientNodeId,
    store_pairing_ctx: Callable[[PairingAttemptContext], Awaitable[None]] = Depends[
        store_pairing_attempt_context
    ],
    server_settings: Settings = Depends[settings],
    pairing_token: PairingToken = Depends[create_pairing_code],
):
    """Create and store a pairing attempt for a client node.

    This function is the supported Python API for starting pairing state.
    In-process callers should invoke ``initiate_pairing`` directly and either
    provide a pairing token explicitly or rely on the configured token provider.
    """
    log.info("Initiating pairing for client %s", client_node_id)
    log.info("Generated pairing token for client %s: %s", client_node_id, pairing_token)
    pairing_attempt_id: PairingAttemptId = uuid4()
    # Encode UUID string as base64 bytes for S2PairingAttemptId (str)
    pairing_attempt_id_b64 = b64encode(str(pairing_attempt_id).encode("utf-8")).decode("utf-8")
    pairing_attempt_id_var.set(S2PairingAttemptId(root=pairing_attempt_id_b64))
    pairing_node_id = server_settings.pairing_node_id
    ctx = PairingAttemptContext(
        pairing_attempt_id=pairing_attempt_id,
        pairing_token=pairing_token,
        pairing_node_id=NodeIdAlias(root=pairing_node_id),
        client_node_id=client_node_id,
    )
    await store_pairing_ctx(ctx)
    return ctx


@inject
async def unpair(
    auth_ctx: AuthenticationContext = Depends[authentication_context],
    pairing_context: PairingAttemptContext = Depends[
        pairing_attempt_context_by_client_node_id
    ],
    storage: ContextStorage = Depends[context_storage_singleton],
) -> None:
    """Remove the authentication and pairing contexts for a paired client."""
    if auth_ctx.client_node_id is None:
        raise ValueError("AuthenticationContext must have client_node_id set")
    if not isinstance(storage, S2InMemoryContextStorage):
        raise TypeError("unpair requires S2InMemoryContextStorage.")

    await storage.delete_context(AuthenticationContext, auth_ctx.client_node_id)
    await storage.delete_context(
        PairingAttemptContext, pairing_context.pairing_attempt_id
    )


@inject
async def request_pairing(
    request: RequestPairingPostRequest,
    store_authentication_ctx: Callable[
        [AuthenticationContext], Awaitable[None]
    ] = Depends[store_authentication_context],
    storage: ContextStorage = Depends[context_storage_singleton],
    hooks: HookRegistry = Depends[hook_registry],
    cfg: Config = Depends[config],
    server_settings: Settings = Depends[settings],
) -> RequestPairingPostResponse:
    """Initiate a new pairing attempt.

    Args:
        request: The pairing request containing client descriptions
        store_authentication_ctx: Function to store authentication context
        pairing_context: The pairing attempt context
        hooks: Hook registry for calling server hooks

    Returns:
        The pairing response with server descriptions and challenge
    """

    client_node_id = request.clientNodeDescription.id.root

    if not isinstance(storage, S2InMemoryContextStorage):
        raise TypeError(
            "request_pairing requires S2InMemoryContextStorage to retrieve pairing contexts by client_node_id."
        )

    pairing_attempt_id: PairingAttemptId | None = None
    for ctx in await storage.list_contexts(PairingAttemptContext):
        if ctx.client_node_id == client_node_id:
            pairing_attempt_id = ctx.pairing_attempt_id
            break

    if pairing_attempt_id is None:
        log.info(
            "No pairing context known for client %s. Initializing one from requestPairing.",
            client_node_id,
        )
        default_token = (
            consume_pending_pairing_token() or server_settings.default_pairing_token
        )
        if default_token is None:
            initiated_ctx = await initiate_pairing(client_node_id=client_node_id)
        else:
            initiated_ctx = await initiate_pairing(
                client_node_id=client_node_id,
                pairing_token=default_token,
            )
        pairing_attempt_id = initiated_ctx.pairing_attempt_id

    if pairing_attempt_id is None:
        raise RuntimeError("Failed to initialize pairing attempt context")

    async with storage.get_context(
        PairingAttemptContext, pairing_attempt_id
    ) as pairing_context:
        auth_ctx = AuthenticationContext(
            client_node_id=client_node_id,
            state=ClientState.PAIRING,
            s2_endpoint_description=request.clientEndpointDescription,
            s2_node_description=request.clientNodeDescription,
        )
        await store_authentication_ctx(auth_ctx)
        s2_client_node_id_var.set(NodeId(root=client_node_id))

        pairing_context.client_node_id = client_node_id

        algorithm = select_algorithm(request.supportedHmacHashingAlgorithms)
        pairing_context.algorithm = algorithm

        client_response = create_response(
            pairing_token=pairing_context.pairing_token,
            challenge=request.clientHmacChallenge,
            deployment=server_settings.cem_deployment_type,
            domain_name=cfg.domain_name,
            fingerprint=None,
            algorithm=algorithm,
        )
        pairing_context.state = PairingState.INITIATED
        server_challenge = create_challenge()
        pairing_context.server_hmac_challenge = server_challenge

        pairing_hook = hooks.get(pairing_attempt_request)
        pairing_allowed = await pairing_hook(
            ReadOnlyAuthenticationContext.model_validate(auth_ctx.model_dump()),
            ReadOnlyPairingAttemptContext.model_validate(pairing_context.model_dump()),
        )
        if not pairing_allowed:
            raise AccessError(
                f"Client node {auth_ctx.client_node_id} is not allowed to connect."
            )

        endpoint_hook = hooks.get(get_server_endpoint_description)
        node_hook = hooks.get(get_server_node_description)
        server_endpoint_description = await endpoint_hook(auth_ctx.client_node_id)
        server_node_description = await node_hook(auth_ctx.client_node_id)

        return RequestPairingPostResponse(
            selectedHmacHashingAlgorithm=algorithm,
            serverNodeDescription=server_node_description,
            serverEndpointDescription=server_endpoint_description,
            clientHmacChallengeResponse=HmacChallengeResponse(
                root=b64encode(client_response)
            ),
            serverHmacChallenge=server_challenge,
            pairingAttemptId=S2PairingAttemptId(
                root=b64encode(str(pairing_context.pairing_attempt_id).encode("utf-8")).decode("utf-8")
            ),
        )


@inject
async def handle_client_response(
    request: RequestConnectionDetailsPostRequest,
    pairing_context: PairingAttemptContext = Depends[pairing_attempt_context],
    auth_ctx: AuthenticationContext = Depends[
        authentication_context_by_pairing_attempt_context
    ],
    hooks: HookRegistry = Depends[hook_registry],
    new_access_token: AccessToken = Depends[generate_access_token],
    cfg: Config = Depends[config],
    server_settings: Settings = Depends[settings],
) -> ConnectionDetails:
    """Handle the client's response and return the server's connection details.

    Args:
        request: The request from the client for connection details
        pairing_context: The pairing attempt context
        auth_ctx: The authentication context with its connection and endpoint details
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
        deployment=server_settings.cem_deployment_type,
        domain_name=cfg.domain_name,
        fingerprint=None,
    )

    endpoint_hook = hooks.get(get_server_connection_initiation_endpoint)
    server_endpoint = await endpoint_hook(
        ReadOnlyAuthenticationContext.model_validate(auth_ctx.model_dump()),
    )
    access_token = new_access_token
    auth_ctx.current_access_token = access_token
    auth_ctx.next_access_token = None
    pairing_context.state = PairingState.COMPLETED
    return ConnectionDetails(
        initiateSessionUrl=server_endpoint, accessToken=access_token
    )


@inject
async def finalize_pairing(
    request: FinalizePairingPostRequest,
    pairing_context: PairingAttemptContext = Depends[pairing_attempt_context],
    auth_ctx: AuthenticationContext = Depends[
        authentication_context_by_pairing_attempt_context
    ],
) -> None:
    """Finalize a completed pairing attempt.

    The client calls ``finalizePairing`` after it has successfully stored the
    connection details returned by ``requestConnectionDetails``. Only then is the
    authentication context marked as paired.

    Args:
        request: Finalization request with the client-reported success flag.
        pairing_context: Pairing attempt context loaded from context storage.
        auth_ctx: Authentication context loaded from context storage.

    Raises:
        PairingNotCompleteError: If the pairing attempt has not reached the
            completed state.
    """
    if not request.success:
        pairing_context.state = PairingState.FAILED
        return

    if pairing_context.state != PairingState.COMPLETED:
        raise PairingNotCompleteError(
            f"The pairing state was {pairing_context.state} while we expected {PairingState.COMPLETED}."
        )

    auth_ctx.state = ClientState.PAIRED
