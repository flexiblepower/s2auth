from enum import Enum
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from collections.abc import AsyncGenerator
from contextvars import ContextVar
from typing import Awaitable, Callable, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from wepositive_di import Depends, register_provider
from wepositive_di.context import (
    ContextStorage as BaseContextStorage,
    InMemoryContextStorage as BaseInMemoryContextStorage,
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


class ClientState(str, Enum):
    PAIRING = "Pairing"
    PAIRED = "Paired"
    CONNECTED = "Connected"
    DISCONNECTED = "Disconnected"


class PairingState(str, Enum):
    INITIATED = "Initiated"
    COMPLETED = "Completed"
    FAILED = "Failed"


class ClientContext(BaseModel):
    """Context data for a client connection.

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
    access_token: AccessToken | None = None


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
    algorithm: HmacHashingAlgorithm | None = None
    server_hmac_challenge: HmacChallenge | None = None


class ReadOnlyClientContext(ClientContext):
    """Read-only view of ClientContext for passing to hooks.

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


class ContextStorage(BaseContextStorage):
    """Context storage interface with s2auth-specific convenience methods."""

    def get_context(
        self, ctx_type: type[ContextTypeT], context_id: UUID
    ) -> AbstractAsyncContextManager[ContextTypeT]:
        raise NotImplementedError

    async def store_context(
        self, ctx_type: type[ContextTypeT], context_id: UUID, context: ContextTypeT
    ) -> None:
        raise NotImplementedError

    async def get_context_snapshot(
        self, ctx_type: type[ContextTypeT], context_id: UUID
    ) -> ContextTypeT:
        raise NotImplementedError

    async def get_client_context(
        self, client_node_id: ClientNodeId
    ) -> AsyncGenerator[ClientContext, None]:
        try:
            async with self.get_context(ClientContext, client_node_id) as ctx:
                yield ctx
        except KeyError as exc:
            raise KeyError(f"No context known for {client_node_id}") from exc

    async def get_pairing_attempt_context(
        self, pairing_attempt_id: PairingAttemptId
    ) -> AsyncGenerator[PairingAttemptContext, None]:
        try:
            async with self.get_context(PairingAttemptContext, pairing_attempt_id) as ctx:
                yield ctx
        except KeyError as exc:
            raise KeyError(f"No context known for {pairing_attempt_id}") from exc

    async def store_client_context(self, context: ClientContext) -> None:
        if context.client_node_id is None:
            raise ValueError("ClientContext must have client_node_id set")
        await self.store_context(ClientContext, context.client_node_id, context)

    async def store_pairing_attempt_context(self, context: PairingAttemptContext) -> None:
        await self.store_context(
            PairingAttemptContext, context.pairing_attempt_id, context
        )


class InMemoryContextStorage(BaseInMemoryContextStorage, ContextStorage):
    """In-memory storage backed by wepositive-di's typed context storage."""

    def __init__(self) -> None:
        super().__init__()
        self._client_states = self._states.setdefault(ClientContext, {})
        self._pairing_attempt_states = self._states.setdefault(PairingAttemptContext, {})


@register_provider(singleton=True)
def context_storage_singleton() -> ContextStorage:
    """Singleton provider for the context storage."""
    return InMemoryContextStorage()


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
    return UUID(p_id.root.decode("utf-8"))


@register_provider(context_manager=True)
@asynccontextmanager
async def client_context(
    client_node_id: ClientNodeId = Depends[client_node_id],
    storage: ContextStorage = Depends[context_storage_singleton],
) -> AsyncGenerator[ClientContext, None]:
    """Retrieves the context for the specified client_node_id.

    This is an async generator provider that yields the context while holding
    its per-ID lock. The lock is held for the entire duration that dependent
    functions use the context, ensuring thread-safe and async-safe modifications.

    Works in both async and threaded environments through wepositive-di storage.
    """
    async for ctx in storage.get_client_context(client_node_id):
        yield ctx


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
    async for ctx in storage.get_pairing_attempt_context(pairing_attempt_id):
        yield ctx


@register_provider()
async def store_client_context(
    storage: ContextStorage = Depends[context_storage_singleton],
) -> Callable[[ClientContext], Awaitable[None]]:
    """Provider that returns a function to store client contexts.

    Returns a callable that can be used to safely store ClientContext objects
    in the context storage. Thread-safe and async-safe.

    Usage:
        @inject
        async def my_function(
            store_ctx: Callable[[ClientContext], Awaitable[None]] = Depends[store_client_context]
        ):
            ctx = ClientContext(client_node_id=some_uuid)
            await store_ctx(ctx)
    """
    return storage.store_client_context


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
    return storage.store_pairing_attempt_context
