import pytest
import asyncio
import threading
from uuid import UUID
from s2auth.server.dependencies import setup, Depends, inject, provider_overrides
from s2auth.server.dependencies.context import (
    client_node_id,
    context_storage_singleton,
    client_context,
    ClientContext,
    ClientNodeId,
    AsyncContextStorage,
    SyncContextStorage,
    AsyncInMemoryContextStorage,
    SyncInMemoryContextStorage,
    PairingAttemptContext,
    PairingAttemptId,
)


class MockAsyncContextStorage(AsyncContextStorage):
    """Test implementation of AsyncContextStorage with pre-populated data."""

    def __init__(
        self,
        client_contexts: dict[ClientNodeId, ClientContext] | None = None,
        pairing_contexts: dict[PairingAttemptId, PairingAttemptContext] | None = None,
    ):
        self.client_contexts = client_contexts or {}
        self.pairing_contexts = pairing_contexts or {}

    async def get_client_context(self, client_node_id: ClientNodeId) -> ClientContext:
        if client_node_id not in self.client_contexts:
            self.client_contexts[client_node_id] = ClientContext()
        return self.client_contexts[client_node_id]

    async def get_pairing_attempt_context(
        self, pairing_attempt_id: PairingAttemptId
    ) -> PairingAttemptContext:
        if pairing_attempt_id not in self.pairing_contexts:
            self.pairing_contexts[pairing_attempt_id] = PairingAttemptContext()
        return self.pairing_contexts[pairing_attempt_id]


class MockSyncContextStorage(SyncContextStorage):
    """Test implementation of SyncContextStorage with pre-populated data."""

    def __init__(
        self,
        client_contexts: dict[ClientNodeId, ClientContext] | None = None,
        pairing_contexts: dict[PairingAttemptId, PairingAttemptContext] | None = None,
    ):
        self.client_contexts = client_contexts or {}
        self.pairing_contexts = pairing_contexts or {}

    def get_client_context(self, client_node_id: ClientNodeId) -> ClientContext:
        if client_node_id not in self.client_contexts:
            self.client_contexts[client_node_id] = ClientContext()
        return self.client_contexts[client_node_id]

    def get_pairing_attempt_context(
        self, pairing_attempt_id: PairingAttemptId
    ) -> PairingAttemptContext:
        if pairing_attempt_id not in self.pairing_contexts:
            self.pairing_contexts[pairing_attempt_id] = PairingAttemptContext()
        return self.pairing_contexts[pairing_attempt_id]


@pytest.mark.skip_wire
async def test_client_context_with_multiple_clients():
    """Test that client_context returns the correct context for multiple clients."""
    # Create a test storage with pre-populated data
    test_uuid_1 = UUID("00000000-0000-0000-0000-000000000001")
    test_uuid_2 = UUID("00000000-0000-0000-0000-000000000002")
    test_uuid_3 = UUID("00000000-0000-0000-0000-000000000003")

    test_storage = MockAsyncContextStorage(
        client_contexts={
            test_uuid_1: ClientContext(state="client_1_state"),
            test_uuid_2: ClientContext(state="client_2_state"),
            test_uuid_3: ClientContext(state="client_3_state"),
        }
    )

    def test_context_storage() -> AsyncContextStorage:
        return test_storage

    # Override client_node_id to return different values
    def test_client_node_id_1() -> UUID:
        return test_uuid_1

    def test_client_node_id_2() -> UUID:
        return test_uuid_2

    def test_client_node_id_3() -> UUID:
        return test_uuid_3

    @inject
    async def get_context(ctx: ClientContext = Depends[client_context]) -> ClientContext:
        return ctx

    setup()

    # Test client 1
    with provider_overrides(
        {
            context_storage_singleton: test_context_storage,
            client_node_id: test_client_node_id_1,
        }
    ):
        result = await get_context()
        assert result.state == "client_1_state"

    # Test client 2
    with provider_overrides(
        {
            context_storage_singleton: test_context_storage,
            client_node_id: test_client_node_id_2,
        }
    ):
        result = await get_context()
        assert result.state == "client_2_state"

    # Test client 3
    with provider_overrides(
        {
            context_storage_singleton: test_context_storage,
            client_node_id: test_client_node_id_3,
        }
    ):
        result = await get_context()
        assert result.state == "client_3_state"


@pytest.mark.skip_wire
async def test_context_storage_singleton_is_singleton():
    """Test that context_storage_singleton is instantiated only once and changes persist."""

    @inject
    async def get_storage(
        storage: AsyncContextStorage = Depends[context_storage_singleton],
    ) -> AsyncContextStorage:
        return storage

    @inject
    async def modify_storage(
        storage: AsyncContextStorage = Depends[context_storage_singleton],
    ) -> None:
        test_uuid = UUID("00000000-0000-0000-0000-000000000999")
        # Modify the storage
        ctx = await storage.get_client_context(test_uuid)
        ctx.state = "modified_state"

    setup()

    # Get the singleton
    storage1 = await get_storage()
    initial_id = id(storage1)

    # Modify the storage
    await modify_storage()

    # Get the singleton again
    storage2 = await get_storage()

    # Verify it's the same object
    assert id(storage2) == initial_id, "Singleton should be the same instance"

    # Verify the modification persisted
    test_uuid = UUID("00000000-0000-0000-0000-000000000999")
    ctx = await storage2.get_client_context(test_uuid)
    assert ctx.state == "modified_state", "Modified state should be preserved"


@pytest.mark.skip_wire
async def test_client_context_returns_existing_context():
    """Test that client_context returns existing context when client_node_id already exists."""
    test_uuid = UUID("00000000-0000-0000-0000-00000000002a")

    # Create a test storage with pre-populated data
    existing_context = ClientContext(state="existing_state")
    test_storage = MockAsyncContextStorage(
        client_contexts={test_uuid: existing_context}
    )

    def test_context_storage() -> AsyncContextStorage:
        return test_storage

    def test_client_node_id() -> UUID:
        return test_uuid

    @inject
    async def get_context(ctx: ClientContext = Depends[client_context]) -> ClientContext:
        return ctx

    setup()

    # Test that existing context is returned
    with provider_overrides(
        {
            context_storage_singleton: test_context_storage,
            client_node_id: test_client_node_id,
        }
    ):
        result = await get_context()
        assert result.state == "existing_state"

        # Verify the context is the same object from the storage
        assert result is existing_context


@pytest.mark.skip_wire
async def test_client_context_creates_then_returns_context():
    """Test that client_context creates a new context and then returns the same context on subsequent calls."""
    test_uuid = UUID("00000000-0000-0000-0000-000000000063")

    # Create an empty test storage
    test_storage = MockAsyncContextStorage()

    def test_context_storage() -> AsyncContextStorage:
        return test_storage

    def test_client_node_id() -> UUID:
        return test_uuid

    @inject
    async def get_context(ctx: ClientContext = Depends[client_context]) -> ClientContext:
        return ctx

    setup()

    with provider_overrides(
        {
            context_storage_singleton: test_context_storage,
            client_node_id: test_client_node_id,
        }
    ):
        # First call - should create a new context
        result1 = await get_context()
        assert result1.state == "default"
        assert test_uuid in test_storage.client_contexts

        # Second call - should return the existing context
        result2 = await get_context()
        assert result2.state == "default"
        assert result2 is result1  # Same object
        assert result2 is test_storage.client_contexts[test_uuid]  # Same object from storage


@pytest.mark.skip_wire
async def test_async_in_memory_storage_concurrency():
    """Test that AsyncInMemoryContextStorage properly handles concurrent async access."""
    storage = AsyncInMemoryContextStorage()
    test_uuid = UUID("00000000-0000-0000-0000-000000000001")

    async def get_context() -> int:
        ctx = await storage.get_client_context(test_uuid)
        return id(ctx)

    # Create multiple async tasks that try to get the same context
    results = await asyncio.gather(*[get_context() for _ in range(10)])

    # All tasks should get the same context instance
    assert len(set(results)) == 1, "All async tasks should get the same context instance"


@pytest.mark.skip_wire
async def test_async_in_memory_storage_multiple_contexts():
    """Test that AsyncInMemoryContextStorage maintains separate contexts for different IDs."""
    storage = AsyncInMemoryContextStorage()

    test_uuid_1 = UUID("00000000-0000-0000-0000-000000000001")
    test_uuid_2 = UUID("00000000-0000-0000-0000-000000000002")

    ctx1 = await storage.get_client_context(test_uuid_1)
    ctx1.state = "state_1"

    ctx2 = await storage.get_client_context(test_uuid_2)
    ctx2.state = "state_2"

    # Verify contexts are different
    assert ctx1 is not ctx2
    assert ctx1.state == "state_1"
    assert ctx2.state == "state_2"

    # Verify contexts are persistent
    ctx1_again = await storage.get_client_context(test_uuid_1)
    ctx2_again = await storage.get_client_context(test_uuid_2)

    assert ctx1_again is ctx1
    assert ctx2_again is ctx2
    assert ctx1_again.state == "state_1"
    assert ctx2_again.state == "state_2"


@pytest.mark.skip_wire
async def test_async_in_memory_storage_pairing_attempt_contexts():
    """Test that AsyncInMemoryContextStorage handles pairing attempt contexts correctly."""
    storage = AsyncInMemoryContextStorage()

    pairing_id_1 = "pairing_001"
    pairing_id_2 = "pairing_002"

    # Get first pairing context
    ctx1 = await storage.get_pairing_attempt_context(pairing_id_1)
    ctx1.state = "pairing_1_state"
    test_uuid_1 = UUID("00000000-0000-0000-0000-000000000001")
    ctx1.client_node_id = test_uuid_1

    # Get second pairing context
    ctx2 = await storage.get_pairing_attempt_context(pairing_id_2)
    ctx2.state = "pairing_2_state"

    # Verify contexts are different
    assert ctx1 is not ctx2
    assert ctx1.state == "pairing_1_state"
    assert ctx2.state == "pairing_2_state"
    assert ctx1.client_node_id == test_uuid_1
    assert ctx2.client_node_id is None

    # Verify contexts are persistent
    ctx1_again = await storage.get_pairing_attempt_context(pairing_id_1)
    ctx2_again = await storage.get_pairing_attempt_context(pairing_id_2)

    assert ctx1_again is ctx1
    assert ctx2_again is ctx2


@pytest.mark.skip_wire
def test_sync_in_memory_storage_thread_safety():
    """Test that SyncInMemoryContextStorage properly handles concurrent thread access."""
    storage = SyncInMemoryContextStorage()
    test_uuid = UUID("00000000-0000-0000-0000-000000000001")
    results: list[int] = []

    def get_context() -> None:
        ctx = storage.get_client_context(test_uuid)
        results.append(id(ctx))

    # Create multiple threads that try to get the same context
    threads = [threading.Thread(target=get_context) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # All threads should get the same context instance
    assert len(set(results)) == 1, "All threads should get the same context instance"


@pytest.mark.skip_wire
def test_sync_in_memory_storage_multiple_contexts():
    """Test that SyncInMemoryContextStorage maintains separate contexts for different IDs."""
    storage = SyncInMemoryContextStorage()

    test_uuid_1 = UUID("00000000-0000-0000-0000-000000000001")
    test_uuid_2 = UUID("00000000-0000-0000-0000-000000000002")

    ctx1 = storage.get_client_context(test_uuid_1)
    ctx1.state = "state_1"

    ctx2 = storage.get_client_context(test_uuid_2)
    ctx2.state = "state_2"

    # Verify contexts are different
    assert ctx1 is not ctx2
    assert ctx1.state == "state_1"
    assert ctx2.state == "state_2"

    # Verify contexts are persistent
    ctx1_again = storage.get_client_context(test_uuid_1)
    ctx2_again = storage.get_client_context(test_uuid_2)

    assert ctx1_again is ctx1
    assert ctx2_again is ctx2
    assert ctx1_again.state == "state_1"
    assert ctx2_again.state == "state_2"


@pytest.mark.skip_wire
def test_sync_in_memory_storage_pairing_attempt_contexts():
    """Test that SyncInMemoryContextStorage handles pairing attempt contexts correctly."""
    storage = SyncInMemoryContextStorage()

    pairing_id_1 = "pairing_001"
    pairing_id_2 = "pairing_002"

    # Get first pairing context
    ctx1 = storage.get_pairing_attempt_context(pairing_id_1)
    ctx1.state = "pairing_1_state"
    test_uuid_1 = UUID("00000000-0000-0000-0000-000000000001")
    ctx1.client_node_id = test_uuid_1

    # Get second pairing context
    ctx2 = storage.get_pairing_attempt_context(pairing_id_2)
    ctx2.state = "pairing_2_state"

    # Verify contexts are different
    assert ctx1 is not ctx2
    assert ctx1.state == "pairing_1_state"
    assert ctx2.state == "pairing_2_state"
    assert ctx1.client_node_id == test_uuid_1
    assert ctx2.client_node_id is None

    # Verify contexts are persistent
    ctx1_again = storage.get_pairing_attempt_context(pairing_id_1)
    ctx2_again = storage.get_pairing_attempt_context(pairing_id_2)

    assert ctx1_again is ctx1
    assert ctx2_again is ctx2


@pytest.mark.skip_wire
def test_sync_storage_setdefault_atomicity():
    """Test that SyncInMemoryContextStorage uses setdefault for atomic get-or-create."""
    storage = SyncInMemoryContextStorage()
    test_uuid = UUID("00000000-0000-0000-0000-000000000042")

    # First call creates the context
    ctx1 = storage.get_client_context(test_uuid)
    ctx1.state = "modified"

    # Second call should return the same instance with modified state
    ctx2 = storage.get_client_context(test_uuid)
    assert ctx2 is ctx1
    assert ctx2.state == "modified"


@pytest.mark.skip_wire
async def test_client_node_id_provider_with_contextvar_set():
    """Test that client_node_id provider returns UUID from contextvar when set."""
    from s2auth.server.dependencies.context import (
        s2_client_node_id_var,
        client_node_id as client_node_id_provider,
    )
    from s2auth.common.models import S2NodeId

    test_uuid = UUID("00000000-0000-0000-0000-000000000042")

    @inject
    def get_client_node_id(node_id: ClientNodeId = Depends[client_node_id_provider]) -> ClientNodeId:
        return node_id

    setup()

    # Set the contextvar
    token = s2_client_node_id_var.set(S2NodeId(root=test_uuid))
    try:
        result = get_client_node_id()
        assert result == test_uuid
    finally:
        # Clean up
        s2_client_node_id_var.reset(token)


@pytest.mark.skip_wire
async def test_client_node_id_provider_without_contextvar():
    """Test that client_node_id provider raises ValueError when contextvar is not set."""
    from s2auth.server.dependencies.context import (
        s2_client_node_id_var,
        client_node_id as client_node_id_provider,
    )

    @inject
    def get_client_node_id(node_id: ClientNodeId = Depends[client_node_id_provider]) -> ClientNodeId:
        return node_id

    setup()

    # Ensure contextvar is not set
    s2_client_node_id_var.set(None)

    with pytest.raises(ValueError, match="s2_client_node_id not set in context"):
        get_client_node_id()


@pytest.mark.skip_wire
async def test_pairing_attempt_id_provider_with_contextvar_set():
    """Test that pairing_attempt_id provider returns string from contextvar when set."""
    from s2auth.server.dependencies.context import (
        pairing_attempt_id_var,
        pairing_attempt_id as pairing_attempt_id_provider,
    )
    from s2auth.common.models import PairingAttemptId as S2PairingAttemptId

    test_pairing_id = "test_pairing_123"

    @inject
    def get_pairing_attempt_id(p_id: PairingAttemptId = Depends[pairing_attempt_id_provider]) -> PairingAttemptId:
        return p_id

    setup()

    # Set the contextvar
    token = pairing_attempt_id_var.set(S2PairingAttemptId(root=test_pairing_id))
    try:
        result = get_pairing_attempt_id()
        assert result == test_pairing_id
    finally:
        # Clean up
        pairing_attempt_id_var.reset(token)


@pytest.mark.skip_wire
async def test_pairing_attempt_id_provider_without_contextvar():
    """Test that pairing_attempt_id provider raises ValueError when contextvar is not set."""
    from s2auth.server.dependencies.context import (
        pairing_attempt_id_var,
        pairing_attempt_id as pairing_attempt_id_provider,
    )

    @inject
    def get_pairing_attempt_id(p_id: PairingAttemptId = Depends[pairing_attempt_id_provider]) -> PairingAttemptId:
        return p_id

    setup()

    # Ensure contextvar is not set
    pairing_attempt_id_var.set(None)

    with pytest.raises(ValueError, match="pairing_attempt_id not set in context"):
        get_pairing_attempt_id()


@pytest.mark.skip_wire
async def test_pairing_attempt_context_provider():
    """Test that pairing_attempt_context provider works correctly."""
    from s2auth.server.dependencies.context import (
        pairing_attempt_id_var,
        pairing_attempt_context as pairing_attempt_context_provider,
    )
    from s2auth.common.models import PairingAttemptId as S2PairingAttemptId

    test_pairing_id = "test_pairing_456"

    @inject
    async def get_pairing_context(
        ctx: PairingAttemptContext = Depends[pairing_attempt_context_provider]
    ) -> PairingAttemptContext:
        return ctx

    setup()

    # Set the contextvar
    token = pairing_attempt_id_var.set(S2PairingAttemptId(root=test_pairing_id))
    try:
        # First call - should create new context
        result1 = await get_pairing_context()
        assert result1.state == "default"
        assert result1.client_node_id is None

        # Modify the context
        result1.state = "modified"
        test_uuid = UUID("00000000-0000-0000-0000-000000000099")
        result1.client_node_id = test_uuid

        # Second call - should return same context
        result2 = await get_pairing_context()
        assert result2 is result1
        assert result2.state == "modified"
        assert result2.client_node_id == test_uuid
    finally:
        # Clean up
        pairing_attempt_id_var.reset(token)
