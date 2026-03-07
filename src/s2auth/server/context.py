from abc import ABC, abstractmethod
from enum import StrEnum
import aiologic
from collections.abc import AsyncGenerator
from contextvars import ContextVar
from typing import Awaitable, Callable
from uuid import UUID
from pydantic import BaseModel, ConfigDict


from s2auth.common.hmac import PairingToken
from s2auth.common.model.s2_over_ip_pairing import (
    HmacChallenge,
    HmacHashingAlgorithm,
    PairingAttemptId as S2PairingAttemptId,
    PairingS2NodeId,
)
from s2auth.common.model.s2_over_ip_common import (
    AccessToken,
    S2EndpointDescription,
    S2NodeDescription,
    S2NodeId,
)
from s2auth.common.dependencies import Depends, register_provider


# Type aliases for the root types
ClientNodeId = UUID
PairingAttemptId = UUID

# Context variables
s2_client_node_id_var: ContextVar[S2NodeId | None] = ContextVar(
    "s2_client_node_id", default=None
)
pairing_attempt_id_var: ContextVar[S2PairingAttemptId | None] = ContextVar(
    "pairing_attempt_id", default=None
)


class ClientState(StrEnum):
    PAIRING = "Pairing"
    PAIRED = "Paired"
    CONNECTED = "Connected"
    DISCONNECTED = "Disconnected"


class PairingState(StrEnum):
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
    s2_node_description: S2NodeDescription | None = None
    s2_endpoint_description: S2EndpointDescription | None = None
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
    pairing_node_id: PairingS2NodeId
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


class ContextStorage(ABC):
    """Abstract base class for context storage implementations.

    This interface allows for different storage backends (in-memory, Redis, etc.)
    to be used for storing client and pairing attempt contexts.

    Implementations must be thread-safe and async-safe.

    Methods are async generators that yield contexts while holding locks,
    ensuring safe modifications during the entire usage period.
    """

    @abstractmethod
    def get_client_context(
        self, client_node_id: ClientNodeId
    ) -> AsyncGenerator[ClientContext, None]:
        """Get a ClientContext for the given client_node_id.

        This is an async generator that yields the context while holding a lock.
        The lock is held until the generator is exhausted.

        Args:
            client_node_id: The UUID of the client node

        Yields:
            The ClientContext for this client

        Raises:
            KeyError: If the context does not exist
        """
        pass

    @abstractmethod
    def get_pairing_attempt_context(
        self, pairing_attempt_id: PairingAttemptId
    ) -> AsyncGenerator[PairingAttemptContext, None]:
        """Get a PairingAttemptContext for the given pairing_attempt_id.

        This is an async generator that yields the context while holding a lock.
        The lock is held until the generator is exhausted.

        Args:
            pairing_attempt_id: The UUID of the pairing attempt

        Yields:
            The PairingAttemptContext for this attempt

        Raises:
            KeyError: If the context does not exist
        """
        pass

    @abstractmethod
    async def store_client_context(self, context: ClientContext) -> None:
        """Store a new ClientContext.

        This creates or replaces a ClientContext for the given client_node_id.
        Thread-safe and async-safe.

        Args:
            context: The ClientContext to store (must have client_node_id set)
        """
        pass

    @abstractmethod
    async def store_pairing_attempt_context(
        self, context: PairingAttemptContext
    ) -> None:
        """Store a new PairingAttemptContext.

        This creates or replaces a PairingAttemptContext for the given pairing_attempt_id.
        Thread-safe and async-safe.

        Args:
            context: The PairingAttemptContext to store (must have pairing_attempt_id set)
        """
        pass


class InMemoryContextStorage(ContextStorage):
    """Unified in-memory storage for contexts that works in both async and threaded environments.

    Uses aiologic.Lock for synchronization, which works seamlessly across:
    - Pure async servers (FastAPI with single event loop)
    - Threaded servers (Flask with multiple threads)
    - Hybrid environments (multiple threads each with their own event loop)

    Unlike asyncio.Lock (async-only) or threading.Lock (sync-only), aiologic.Lock
    is designed to synchronize between async tasks AND threads, preventing deadlocks
    and race conditions in mixed environments.

    Fine-grained locking per ID allows multiple requests to access different
    contexts in parallel while ensuring safe access to the same context.

    Note: This implementation is single-process only. For multi-process
    deployments (e.g., gunicorn with multiple processes), consider using
    a distributed storage backend like Redis.
    """

    def __init__(self):
        self._client_states: dict[ClientNodeId, ClientContext] = {}
        self._pairing_attempt_states: dict[PairingAttemptId, PairingAttemptContext] = {}
        # Per-ID locks for fine-grained synchronization
        # Use RLock (reentrant) to allow the same task/thread to acquire the lock multiple times
        self._client_locks: dict[ClientNodeId, aiologic.RLock] = {}
        self._pairing_locks: dict[PairingAttemptId, aiologic.RLock] = {}
        # Global lock to protect the lock dictionaries themselves
        self._locks_lock = aiologic.RLock()

    async def _get_client_lock(self, client_node_id: ClientNodeId) -> aiologic.RLock:
        """Get or create a lock for the given client_node_id."""
        async with self._locks_lock:
            if client_node_id not in self._client_locks:
                self._client_locks[client_node_id] = aiologic.RLock()
            return self._client_locks[client_node_id]

    async def _get_pairing_lock(
        self, pairing_attempt_id: PairingAttemptId
    ) -> aiologic.RLock:
        """Get or create a lock for the given pairing_attempt_id."""
        async with self._locks_lock:
            if pairing_attempt_id not in self._pairing_locks:
                self._pairing_locks[pairing_attempt_id] = aiologic.RLock()
            return self._pairing_locks[pairing_attempt_id]

    async def get_client_context(
        self, client_node_id: ClientNodeId
    ) -> AsyncGenerator[ClientContext, None]:
        lock = await self._get_client_lock(client_node_id)
        async with lock:
            if client_node_id not in self._client_states:
                raise KeyError(f"No context known for {client_node_id}")
            try:
                yield self._client_states[client_node_id]
            finally:
                # Lock is released when exiting the async with block
                pass

    async def get_pairing_attempt_context(
        self, pairing_attempt_id: PairingAttemptId
    ) -> AsyncGenerator[PairingAttemptContext, None]:
        lock = await self._get_pairing_lock(pairing_attempt_id)
        async with lock:
            if pairing_attempt_id not in self._pairing_attempt_states:
                raise KeyError(f"No context known for {pairing_attempt_id}")
            try:
                yield self._pairing_attempt_states[pairing_attempt_id]
            finally:
                # Lock is released when exiting the async with block
                pass

    async def store_client_context(self, context: ClientContext) -> None:
        """Store a new ClientContext.

        Thread-safe creation/replacement of client context.
        Acquires the fine-grained lock for this client_node_id.
        """
        if context.client_node_id is None:
            raise ValueError("ClientContext must have client_node_id set")

        lock = await self._get_client_lock(context.client_node_id)
        async with lock:
            self._client_states[context.client_node_id] = context

    async def store_pairing_attempt_context(
        self, context: PairingAttemptContext
    ) -> None:
        """Store a new PairingAttemptContext.

        Thread-safe creation/replacement of pairing attempt context.
        Acquires the fine-grained lock for this pairing_attempt_id.
        """
        lock = await self._get_pairing_lock(context.pairing_attempt_id)
        async with lock:
            self._pairing_attempt_states[context.pairing_attempt_id] = context


@register_provider(singleton=True)
def context_storage_singleton() -> ContextStorage:
    """Singleton provider for the context storage.

    Returns the same InMemoryContextStorage instance for the lifetime of the application.

    This implementation uses aiologic.Lock which works seamlessly in:
    - Async servers (FastAPI): Non-blocking async synchronization
    - Threaded servers (Flask): Thread-safe synchronization
    - Hybrid environments: Multiple threads with event loops per thread

    The DI system's support for async dependencies in sync contexts combines with
    aiologic's cross-environment locking to provide a unified storage implementation.

    For multi-process deployments, replace with RedisContextStorage or another
    distributed storage implementation.
    """
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
    return UUID(p_id.root)


@register_provider()
async def client_context(
    client_node_id: ClientNodeId = Depends[client_node_id],
    storage: ContextStorage = Depends[context_storage_singleton],
) -> AsyncGenerator[ClientContext, None]:
    """Retrieves the context for the specified client_node_id.

    This is an async generator provider that yields the context while holding
    its per-ID lock. The lock is held for the entire duration that dependent
    functions use the context, ensuring thread-safe and async-safe modifications.

    Works in both async and threaded environments through aiologic's hybrid locking.
    """
    async for ctx in storage.get_client_context(client_node_id):
        yield ctx


@register_provider()
async def pairing_attempt_context(
    pairing_attempt_id: PairingAttemptId = Depends[pairing_attempt_id],
    storage: ContextStorage = Depends[context_storage_singleton],
) -> AsyncGenerator[PairingAttemptContext, None]:
    """Retrieves the context for the specified pairing_attempt_id.

    This is an async generator provider that yields the context while holding
    its per-ID lock. The lock is held for the entire duration that dependent
    functions use the context, ensuring thread-safe and async-safe modifications.

    Works in both async and threaded environments through aiologic's hybrid locking.
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
