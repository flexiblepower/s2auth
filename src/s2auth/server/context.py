from base64 import b64decode
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime
from enum import Enum
from typing import Awaitable, Callable, TypeVar, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from wepositive_di import Depends, override_provider, register_provider
from wepositive_di.context import (
    ContextStorage,
    InMemoryContextStorage,
    context_storage_singleton,
)


from s2auth.common.hmac import PairingToken
from s2auth.common.model.s2_connect_pairing import (
    HmacChallenge,
    HmacHashingAlgorithm,
    PairingAttemptId as S2PairingAttemptId,
    NodeIdAlias,
)
from s2auth.common.model.s2_connect_common import (
    AccessToken,
    EndpointDescription,
    NodeDescription,
    NodeId,
)
import logging

log = logging.getLogger(__name__)

# Type aliases for the root types
ClientNodeId = UUID
PairingAttemptId = UUID
ContextTypeT = TypeVar("ContextTypeT", bound=BaseModel)

# Context variables
s2_client_node_id_var: ContextVar[NodeId | None] = ContextVar(
    "s2_client_node_id", default=None
)
pairing_attempt_id_var: ContextVar[S2PairingAttemptId | None] = ContextVar(
    "pairing_attempt_id", default=None
)
pairing_token_var: ContextVar[PairingToken | None] = ContextVar(
    "pairing_token", default=None
)


class ClientState(str, Enum):
    PAIRING = "Pairing"
    PAIRED = "Paired"
    CONNECTION_INITIATED = "Connection Initiated"
    CONNECTED = "Connected"
    DISCONNECTED = "Disconnected"


class PairingState(str, Enum):
    INITIATED = "Initiated"
    COMPLETED = "Completed"
    FAILED = "Failed"


class S2InMemoryContextStorage(InMemoryContextStorage):
    """In-memory context storage with typed context listing support."""

    async def list_contexts(self, ctx_type: type[ContextTypeT]) -> list[ContextTypeT]:
        """Return snapshots of all stored contexts for the requested type."""
        type_store = self._states.get(ctx_type, {})  # pyright: ignore[reportPrivateUsage]
        return [
            cast(ContextTypeT, context.model_copy(deep=True))
            for context in type_store.values()
        ]

    async def delete_context(
        self, ctx_type: type[ContextTypeT], context_id: UUID
    ) -> None:
        """Delete a stored context for the requested type and ID."""
        lock = await self._get_lock(  # pyright: ignore[reportPrivateUsage]
            ctx_type, context_id
        )
        async with lock:
            type_store = self._states.get(ctx_type, {})  # pyright: ignore[reportPrivateUsage]
            if context_id not in type_store:
                raise KeyError(f"No {ctx_type.__name__} context known for {context_id}")
            del type_store[context_id]


@override_provider(context_storage_singleton)
def s2_context_storage_singleton() -> ContextStorage:
    """Use s2auth context storage for server context providers."""
    log.debug("Instantiating storage")
    return S2InMemoryContextStorage()


class AuthenticationContext(BaseModel):
    """Authentication context data for a client connection.

    Note: Modifications to context instances should be done carefully in
    multi-threaded/async environments. Consider using the storage's locking
    mechanisms if implementing complex state updates.
    """

    # TODO: implement validators to ensure certain combinations of values are invalid
    # for instance with state PAIRED, we also need to have an access_token

    state: ClientState | None = None
    client_node_id: ClientNodeId | None = None
    s2_node_description: NodeDescription | None = None
    s2_endpoint_description: EndpointDescription | None = None
    current_connection_token: AccessToken | None = None
    current_access_token: AccessToken | None = None
    next_access_token: AccessToken | None = None


class PairingAttemptContext(BaseModel):
    """Context data for a pairing attempt.

    Note: Modifications to context instances should be done carefully in
    multi-threaded/async environments. Consider using the storage's locking
    mechanisms if implementing complex state updates.
    """

    state: PairingState | None = None
    client_node_id: ClientNodeId | None = None
    pairing_attempt_id: PairingAttemptId
    pairing_node_id: NodeIdAlias
    pairing_token: PairingToken
    pairing_token_expires_at: datetime | None = None
    algorithm: HmacHashingAlgorithm | None = None
    server_hmac_challenge: HmacChallenge | None = None


class ReadOnlyAuthenticationContext(AuthenticationContext):
    """Read-only view of AuthenticationContext for passing to hooks.

    This class prevents accidental modification of context state in hooks.
    Any attempt to modify attributes will raise a ValidationError.
    """

    model_config = ConfigDict(frozen=True)


class ReadOnlyPairingAttemptContext(PairingAttemptContext):
    """Read-only view of PairingAttemptContext for passing to hooks.

    This class prevents accidental modification of context state in hooks.
    Any attempt to modify attributes will raise a ValidationError.
    """

    model_config = ConfigDict(frozen=True)


@register_provider()
def client_node_id() -> ClientNodeId:
    """Returns the s2_client_node_id from contextvars."""
    node_id = s2_client_node_id_var.get()
    if node_id is None:
        raise ValueError("s2_client_node_id not set in context")
    return node_id.root


@register_provider()
def pairing_attempt_id() -> PairingAttemptId:
    """Returns the pairing_attempt_id from contextvars."""
    p_id = pairing_attempt_id_var.get()
    if p_id is None:
        raise ValueError("pairing_attempt_id not set in context")
    return UUID(b64decode(p_id.root).decode("utf-8"))


@register_provider()
def pairing_token() -> PairingToken:
    """Returns the pairing token from contextvars."""
    token = pairing_token_var.get()
    if token is None:
        raise ValueError("pairing_token not set in context")
    return token


@register_provider(context_manager=True)
@asynccontextmanager
async def authentication_context(
    client_node_id: ClientNodeId = Depends[client_node_id],
    storage: ContextStorage = Depends[context_storage_singleton],
) -> AsyncGenerator[AuthenticationContext, None]:
    """Retrieves the context for the specified client_node_id.

    This is an async generator provider that yields the context while holding
    its per-ID lock. The lock is held for the entire duration that dependent
    functions use the context, ensuring thread-safe and async-safe modifications.

    Works in both async and threaded environments through wepositive-di storage.
    """
    try:
        async with storage.get_context(AuthenticationContext, client_node_id) as ctx:
            yield ctx
    except KeyError as exc:
        raise KeyError(f"No context known for {client_node_id}") from exc


@register_provider(context_manager=True)
@asynccontextmanager
async def pairing_attempt_context(
    pairing_attempt_id: PairingAttemptId = Depends[pairing_attempt_id],
    storage: ContextStorage = Depends[context_storage_singleton],
) -> AsyncGenerator[PairingAttemptContext, None]:
    """Retrieves the context for the specified pairing_attempt_id.

    This is an async generator provider that yields the context while holding
    its per-ID lock. The lock is held for the entire duration that dependent
    functions use the context, ensuring thread-safe and async-safe modifications.

    Works in both async and threaded environments through wepositive-di storage.
    """
    try:
        async with storage.get_context(
            PairingAttemptContext, pairing_attempt_id
        ) as ctx:
            yield ctx
    except KeyError as exc:
        raise KeyError(f"No context known for {pairing_attempt_id}") from exc


@register_provider(context_manager=True)
@asynccontextmanager
async def pairing_attempt_context_by_client_node_id(
    client_node_id: ClientNodeId = Depends[client_node_id],
    storage: ContextStorage = Depends[context_storage_singleton],
) -> AsyncGenerator[PairingAttemptContext, None]:
    """Retrieve a pairing attempt context by its client_node_id."""
    if not isinstance(storage, S2InMemoryContextStorage):
        raise TypeError(
            "pairing_attempt_context_by_client_context_id requires S2InMemoryContextStorage."
        )
    for ctx in await storage.list_contexts(PairingAttemptContext):
        if ctx.client_node_id == client_node_id:
            async with storage.get_context(
                PairingAttemptContext, ctx.pairing_attempt_id
            ) as stored_ctx:
                yield stored_ctx
                return

    raise KeyError(f"No context known for client_node_id {client_node_id}")


@register_provider(context_manager=True)
@asynccontextmanager
async def authentication_context_by_pairing_attempt_context(
    pairing_attempt_id: PairingAttemptId = Depends[pairing_attempt_id],
    storage: ContextStorage = Depends[context_storage_singleton],
) -> AsyncGenerator[AuthenticationContext, None]:
    """Retrieve authentication context through the current pairing attempt."""
    try:
        async with storage.get_context(
            PairingAttemptContext, pairing_attempt_id
        ) as pairing_context:
            client_node_id = pairing_context.client_node_id
    except KeyError as exc:
        raise KeyError(f"No context known for {pairing_attempt_id}") from exc

    if client_node_id is None:
        raise ValueError("PairingAttemptContext must have client_node_id set")

    try:
        async with storage.get_context(AuthenticationContext, client_node_id) as ctx:
            yield ctx
    except KeyError as exc:
        raise KeyError(f"No context known for {client_node_id}") from exc


@register_provider()
async def store_authentication_context(
    storage: ContextStorage = Depends[context_storage_singleton],
) -> Callable[[AuthenticationContext], Awaitable[None]]:
    """Provider that returns a function to store authentication contexts.

    Returns a callable that can be used to safely store AuthenticationContext objects
    in the context storage. Thread-safe and async-safe.

    Usage:
        @inject
        async def my_function(
            store_ctx: Callable[[AuthenticationContext], Awaitable[None]] = Depends[store_authentication_context]
        ):
            ctx = AuthenticationContext(client_node_id=some_uuid)
            await store_ctx(ctx)
    """

    async def store_context(context: AuthenticationContext) -> None:
        if context.client_node_id is None:
            raise ValueError("AuthenticationContext must have client_node_id set")
        await storage.store_context(
            AuthenticationContext, context.client_node_id, context
        )

    return store_context


@register_provider()
async def store_pairing_attempt_context(
    storage: ContextStorage = Depends[context_storage_singleton],
) -> Callable[[PairingAttemptContext], Awaitable[None]]:
    """Provider that returns a function to store pairing attempt contexts.

    Returns a callable that can be used to safely store PairingAttemptContext objects
    in the context storage. Thread-safe and async-safe.

    Usage:
        @inject
        async def my_function(
            store_ctx: Callable[[PairingAttemptContext], Awaitable[None]] = Depends[store_pairing_attempt_context]
        ):
            ctx = PairingAttemptContext(pairing_attempt_id=some_uuid, ...)
            await store_ctx(ctx)
    """

    async def store_context(context: PairingAttemptContext) -> None:
        await storage.store_context(
            PairingAttemptContext, context.pairing_attempt_id, context
        )

    return store_context
