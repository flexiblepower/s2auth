from abc import ABC, abstractmethod
import asyncio
from collections.abc import AsyncGenerator, Generator
import threading
from contextvars import ContextVar
from uuid import UUID
from pydantic import BaseModel


from s2auth.common.hmac import PairingToken
from s2auth.common.models import PairingAttemptId as S2PairingAttemptId, PairingS2NodeId
from s2auth.common.models import S2NodeId
from s2auth.server.dependencies import Depends, register_provider


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


class ClientContext(BaseModel):
    """Context data for a client connection.

    Note: Modifications to context instances should be done carefully in
    multi-threaded/async environments. Consider using the storage's locking
    mechanisms if implementing complex state updates.
    """

    state: str = "default"
    client_node_id: ClientNodeId | None = None


class PairingAttemptContext(BaseModel):
    """Context data for a pairing attempt.

    Note: Modifications to context instances should be done carefully in
    multi-threaded/async environments. Consider using the storage's locking
    mechanisms if implementing complex state updates.
    """

    state: str = "default"
    client_node_id: ClientNodeId | None = None
    pairing_attempt_id: PairingAttemptId
    pairing_node_id: PairingS2NodeId
    pairing_token: PairingToken


class SyncContextStorage(ABC):
    """Abstract base class for context storage implementations.

    This interface allows for different storage backends (in-memory, Redis, etc.)
    to be used for storing client and pairing attempt contexts.

    Implementations must be thread-safe.

    Methods are generators that yield contexts while holding locks,
    ensuring safe modifications during the entire usage period.
    """

    @abstractmethod
    def get_client_context(
        self, client_node_id: ClientNodeId
    ) -> Generator[ClientContext, None, None]:
        """Get a ClientContext for the given client_node_id.

        This is a generator that yields the context while holding a lock.
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
    ) -> Generator[PairingAttemptContext, None, None]:
        """Get a PairingAttemptContext for the given pairing_attempt_id.

        This is a generator that yields the context while holding a lock.
        The lock is held until the generator is exhausted.

        Args:
            pairing_attempt_id: The UUID of the pairing attempt

        Yields:
            The PairingAttemptContext for this attempt

        Raises:
            KeyError: If the context does not exist
        """
        pass


class AsyncContextStorage(ABC):
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


class AsyncInMemoryContextStorage(AsyncContextStorage):
    """Async-safe in-memory storage for contexts.

    Uses asyncio.Lock for non-blocking synchronization with fine-grained
    locking per ID. This allows multiple async tasks to access different
    contexts in parallel while ensuring safe access to the same context.

    IMPORTANT: This implementation uses asyncio.Lock and is designed for
    async-based deployments (FastAPI with async endpoints). For thread-based
    deployments (Flask with gunicorn in threading mode), you should use
    the SyncInMemoryContextStorage which uses threading.Lock instead.

    Note: This implementation is single-process only. For multi-process
    deployments (e.g., gunicorn with multiple processes), consider using
    a distributed storage backend like Redis.
    """

    def __init__(self):
        self._client_states: dict[ClientNodeId, ClientContext] = {}
        self._pairing_attempt_states: dict[PairingAttemptId, PairingAttemptContext] = {}
        # Per-ID locks for fine-grained synchronization
        self._client_locks: dict[ClientNodeId, asyncio.Lock] = {}
        self._pairing_locks: dict[PairingAttemptId, asyncio.Lock] = {}
        # Global lock to protect the lock dictionaries themselves
        self._locks_lock = asyncio.Lock()

    async def _get_client_lock(self, client_node_id: ClientNodeId) -> asyncio.Lock:
        """Get or create a lock for the given client_node_id."""
        async with self._locks_lock:
            if client_node_id not in self._client_locks:
                self._client_locks[client_node_id] = asyncio.Lock()
            return self._client_locks[client_node_id]

    async def _get_pairing_lock(
        self, pairing_attempt_id: PairingAttemptId
    ) -> asyncio.Lock:
        """Get or create a lock for the given pairing_attempt_id."""
        async with self._locks_lock:
            if pairing_attempt_id not in self._pairing_locks:
                self._pairing_locks[pairing_attempt_id] = asyncio.Lock()
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


class SyncInMemoryContextStorage(SyncContextStorage):
    """Thread-safe synchronous in-memory storage for contexts.

    Uses threading.Lock for synchronization with fine-grained locking per ID.
    This allows multiple threads to access different contexts in parallel
    while ensuring safe access to the same context.

    Suitable for:
    - Flask with threading-based workers
    - Any synchronous/threading based application

    Note: This implementation is single-process only. For multi-process
    deployments (e.g., gunicorn with multiple processes), consider using
    a distributed storage backend like Redis.

    To use this storage instead of the default async version, override the
    context_storage_singleton provider and the context providers:
    """

    def __init__(self):
        self._client_states: dict[ClientNodeId, ClientContext] = {}
        self._pairing_attempt_states: dict[PairingAttemptId, PairingAttemptContext] = {}
        # Per-ID locks for fine-grained synchronization
        self._client_locks: dict[ClientNodeId, threading.Lock] = {}
        self._pairing_locks: dict[PairingAttemptId, threading.Lock] = {}
        # Global lock to protect the lock dictionaries themselves
        self._locks_lock = threading.Lock()

    def _get_client_lock(self, client_node_id: ClientNodeId) -> threading.Lock:
        """Get or create a lock for the given client_node_id."""
        with self._locks_lock:
            if client_node_id not in self._client_locks:
                self._client_locks[client_node_id] = threading.Lock()
            return self._client_locks[client_node_id]

    def _get_pairing_lock(self, pairing_attempt_id: PairingAttemptId) -> threading.Lock:
        """Get or create a lock for the given pairing_attempt_id."""
        with self._locks_lock:
            if pairing_attempt_id not in self._pairing_locks:
                self._pairing_locks[pairing_attempt_id] = threading.Lock()
            return self._pairing_locks[pairing_attempt_id]

    def get_client_context(
        self, client_node_id: ClientNodeId
    ) -> Generator[ClientContext, None, None]:
        lock = self._get_client_lock(client_node_id)
        with lock:
            if client_node_id not in self._client_states:
                raise KeyError(f"No context known for {client_node_id}")
            try:
                yield self._client_states[client_node_id]
            finally:
                # Lock is released when exiting the with block
                pass

    def get_pairing_attempt_context(
        self, pairing_attempt_id: PairingAttemptId
    ) -> Generator[PairingAttemptContext, None, None]:
        lock = self._get_pairing_lock(pairing_attempt_id)
        with lock:
            if pairing_attempt_id not in self._pairing_attempt_states:
                raise KeyError(f"No context known for {pairing_attempt_id}")
            try:
                yield self._pairing_attempt_states[pairing_attempt_id]
            finally:
                # Lock is released when exiting the with block
                pass


@register_provider(singleton=True)
def context_storage_singleton() -> AsyncContextStorage:
    """Singleton provider for the context storage.

    Returns the same AsyncInMemoryContextStorage instance for the lifetime of the application.

    This default implementation uses asyncio.Lock and is optimized for async deployments
    (FastAPI with async endpoints). For thread-based deployments (Flask with gunicorn),
    override this provider with one that provides the SyncInMemoryContextStorage.

    For multi-process deployments, replace with RedisContextStorage or another
    distributed storage implementation.
    """
    return AsyncInMemoryContextStorage()


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
    storage: AsyncContextStorage = Depends[context_storage_singleton],
) -> AsyncGenerator[ClientContext, None]:
    """Retrieves the context for the specified client_node_id.

    This is an async generator provider that yields the context while holding
    its per-ID lock. The lock is held for the entire duration that dependent
    functions use the context, ensuring thread-safe modifications.

    Async-safe through fine-grained per-ID locking.
    """
    async for ctx in storage.get_client_context(client_node_id):
        yield ctx


@register_provider()
async def pairing_attempt_context(
    pairing_attempt_id: PairingAttemptId = Depends[pairing_attempt_id],
    storage: AsyncContextStorage = Depends[context_storage_singleton],
) -> AsyncGenerator[PairingAttemptContext, None]:
    """Retrieves the context for the specified pairing_attempt_id.

    This is an async generator provider that yields the context while holding
    its per-ID lock. The lock is held for the entire duration that dependent
    functions use the context, ensuring thread-safe modifications.

    Async-safe through fine-grained per-ID locking.
    """
    async for ctx in storage.get_pairing_attempt_context(pairing_attempt_id):
        yield ctx
