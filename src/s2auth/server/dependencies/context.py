from abc import ABC, abstractmethod
import asyncio
import threading
from contextvars import ContextVar
from uuid import UUID


from pydantic import BaseModel

from s2auth.common.models import PairingAttemptId as S2PairingAttemptId
from s2auth.common.models import S2NodeId
from s2auth.server.dependencies import Depends, register_provider


# Type aliases for the root types
ClientNodeId = UUID
PairingAttemptId = str

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


class PairingAttemptContext(BaseModel):
    """Context data for a pairing attempt.

    Note: Modifications to context instances should be done carefully in
    multi-threaded/async environments. Consider using the storage's locking
    mechanisms if implementing complex state updates.
    """

    state: str = "default"
    client_node_id: ClientNodeId | None = None


class SyncContextStorage(ABC):
    """Abstract base class for context storage implementations.

    This interface allows for different storage backends (in-memory, Redis, etc.)
    to be used for storing client and pairing attempt contexts.

    Implementations must be thread-safe and async-safe.
    """

    @abstractmethod
    def get_client_context(self, client_node_id: ClientNodeId) -> ClientContext:
        """Get or create a ClientContext for the given client_node_id.

        Args:
            client_node_id: The UUID of the client node

        Returns:
            The ClientContext for this client (created if it doesn't exist)
        """
        pass

    @abstractmethod
    def get_pairing_attempt_context(
        self, pairing_attempt_id: PairingAttemptId
    ) -> PairingAttemptContext:
        """Get or create a PairingAttemptContext for the given pairing_attempt_id.

        Args:
            pairing_attempt_id: The string ID of the pairing attempt

        Returns:
            The PairingAttemptContext for this attempt (created if it doesn't exist)
        """
        pass


class AsyncContextStorage(ABC):
    """Abstract base class for context storage implementations.

    This interface allows for different storage backends (in-memory, Redis, etc.)
    to be used for storing client and pairing attempt contexts.

    Implementations must be thread-safe and async-safe.
    """

    @abstractmethod
    async def get_client_context(self, client_node_id: ClientNodeId) -> ClientContext:
        """Get or create a ClientContext for the given client_node_id.

        Args:
            client_node_id: The UUID of the client node

        Returns:
            The ClientContext for this client (created if it doesn't exist)
        """
        pass

    @abstractmethod
    async def get_pairing_attempt_context(
        self, pairing_attempt_id: PairingAttemptId
    ) -> PairingAttemptContext:
        """Get or create a PairingAttemptContext for the given pairing_attempt_id.

        Args:
            pairing_attempt_id: The string ID of the pairing attempt

        Returns:
            The PairingAttemptContext for this attempt (created if it doesn't exist)
        """
        pass


class AsyncInMemoryContextStorage(AsyncContextStorage):
    """Async-safe in-memory storage for contexts.

    Uses asyncio.Lock for non-blocking synchronization, which is optimal for
    async/await code (FastAPI, async endpoints, etc.).

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
        self._lock = asyncio.Lock()

    async def get_client_context(self, client_node_id: ClientNodeId) -> ClientContext:
        """Async-safe get-or-create for ClientContext.

        Uses asyncio.Lock to ensure non-blocking synchronization across
        multiple concurrent async tasks.
        """
        async with self._lock:
            if client_node_id not in self._client_states:
                self._client_states[client_node_id] = ClientContext()
            return self._client_states[client_node_id]

    async def get_pairing_attempt_context(
        self, pairing_attempt_id: PairingAttemptId
    ) -> PairingAttemptContext:
        """Async-safe get-or-create for PairingAttemptContext.

        Uses asyncio.Lock to ensure non-blocking synchronization across
        multiple concurrent async tasks.
        """
        async with self._lock:
            if pairing_attempt_id not in self._pairing_attempt_states:
                self._pairing_attempt_states[pairing_attempt_id] = (
                    PairingAttemptContext()
                )
            return self._pairing_attempt_states[pairing_attempt_id]


class SyncInMemoryContextStorage(SyncContextStorage):
    """Thread-safe synchronous in-memory storage for contexts.

    Uses threading.Lock for synchronization, making it suitable for:
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
        self._lock = threading.Lock()

    def get_client_context(self, client_node_id: ClientNodeId) -> ClientContext:
        """Thread-safe get-or-create for ClientContext.

        Uses setdefault() under lock for atomic get-or-create operation.
        """
        with self._lock:
            return self._client_states.setdefault(client_node_id, ClientContext())

    def get_pairing_attempt_context(
        self, pairing_attempt_id: PairingAttemptId
    ) -> PairingAttemptContext:
        """Thread-safe get-or-create for PairingAttemptContext.

        Uses setdefault() under lock for atomic get-or-create operation.
        """
        with self._lock:
            return self._pairing_attempt_states.setdefault(
                pairing_attempt_id, PairingAttemptContext()
            )


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
    return p_id.root


@register_provider()
async def client_context(
    client_node_id: ClientNodeId = Depends[client_node_id],
    storage: AsyncContextStorage = Depends[context_storage_singleton],
) -> ClientContext:
    """Retrieves or initializes the context for the specified client_node_id.

    Async-safe through the storage implementation's asyncio.Lock.
    """
    return await storage.get_client_context(client_node_id)


@register_provider()
async def pairing_attempt_context(
    pairing_attempt_id: PairingAttemptId = Depends[pairing_attempt_id],
    storage: AsyncContextStorage = Depends[context_storage_singleton],
) -> PairingAttemptContext:
    """Retrieves or initializes the context for the specified pairing_attempt_id.

    Async-safe through the storage implementation's asyncio.Lock.
    """
    return await storage.get_pairing_attempt_context(pairing_attempt_id)
