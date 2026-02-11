import pytest
import asyncio
import threading
from typing import Any
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

    async def get_client_context(self, client_node_id: ClientNodeId):
        if client_node_id not in self.client_contexts:
            raise KeyError(f"No context known for {client_node_id}")
        yield self.client_contexts[client_node_id]

    async def get_pairing_attempt_context(
        self, pairing_attempt_id: PairingAttemptId
    ):
        if pairing_attempt_id not in self.pairing_contexts:
            raise KeyError(f"No context known for {pairing_attempt_id}")
        yield self.pairing_contexts[pairing_attempt_id]


class MockSyncContextStorage(SyncContextStorage):
    """Test implementation of SyncContextStorage with pre-populated data."""

    def __init__(
        self,
        client_contexts: dict[ClientNodeId, ClientContext] | None = None,
        pairing_contexts: dict[PairingAttemptId, PairingAttemptContext] | None = None,
    ):
        self.client_contexts = client_contexts or {}
        self.pairing_contexts = pairing_contexts or {}

    def get_client_context(self, client_node_id: ClientNodeId):
        if client_node_id not in self.client_contexts:
            raise KeyError(f"No context known for {client_node_id}")
        yield self.client_contexts[client_node_id]

    def get_pairing_attempt_context(
        self, pairing_attempt_id: PairingAttemptId
    ):
        if pairing_attempt_id not in self.pairing_contexts:
            raise KeyError(f"No context known for {pairing_attempt_id}")
        yield self.pairing_contexts[pairing_attempt_id]


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
        # Create and modify the storage
        storage._client_states[test_uuid] = ClientContext(state="modified_state")  # type: ignore[attr-defined]

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
    ctx = await anext(storage2.get_client_context(test_uuid))
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
async def test_client_context_raises_keyerror_for_unknown_id():
    """Test that client_context raises KeyError when client_node_id is not known."""
    test_uuid = UUID("00000000-0000-0000-0000-000000000063")

    # Create an empty test storage
    test_storage = AsyncInMemoryContextStorage()

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
        # Should raise KeyError for unknown ID
        with pytest.raises(KeyError, match=f"No context known for {test_uuid}"):
            await get_context()


@pytest.mark.skip_wire
async def test_async_in_memory_storage_concurrency():
    """Test that AsyncInMemoryContextStorage properly handles concurrent async access."""
    storage = AsyncInMemoryContextStorage()
    test_uuid = UUID("00000000-0000-0000-0000-000000000001")

    # Pre-populate the storage
    storage._client_states[test_uuid] = ClientContext()  # type: ignore[attr-defined]

    async def get_context() -> int:
        ctx = await anext(storage.get_client_context(test_uuid))
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

    # Pre-populate the storage
    storage._client_states[test_uuid_1] = ClientContext(state="state_1")  # type: ignore[attr-defined]
    storage._client_states[test_uuid_2] = ClientContext(state="state_2")  # type: ignore[attr-defined]

    ctx1 = await anext(storage.get_client_context(test_uuid_1))
    ctx2 = await anext(storage.get_client_context(test_uuid_2))

    # Verify contexts are different
    assert ctx1 is not ctx2
    assert ctx1.state == "state_1"
    assert ctx2.state == "state_2"

    # Verify contexts are persistent
    ctx1_again = await anext(storage.get_client_context(test_uuid_1))
    ctx2_again = await anext(storage.get_client_context(test_uuid_2))

    assert ctx1_again is ctx1
    assert ctx2_again is ctx2
    assert ctx1_again.state == "state_1"
    assert ctx2_again.state == "state_2"


@pytest.mark.skip_wire
async def test_async_in_memory_storage_keyerror_for_unknown_id():
    """Test that AsyncInMemoryContextStorage raises KeyError for unknown IDs."""
    storage = AsyncInMemoryContextStorage()
    unknown_uuid = UUID("00000000-0000-0000-0000-999999999999")

    with pytest.raises(KeyError, match=f"No context known for {unknown_uuid}"):
        await anext(storage.get_client_context(unknown_uuid))


@pytest.mark.skip_wire
async def test_async_in_memory_storage_pairing_attempt_contexts():
    """Test that AsyncInMemoryContextStorage handles pairing attempt contexts correctly."""
    from uuid import uuid4
    from s2auth.common.models import PairingS2NodeId
    from s2auth.common.hmac import create_pairing_token

    storage = AsyncInMemoryContextStorage()

    pairing_id_1 = uuid4()
    pairing_id_2 = uuid4()

    test_uuid_1 = UUID("00000000-0000-0000-0000-000000000001")
    test_pairing_node_id = PairingS2NodeId(root="testnodeid123")
    test_token = create_pairing_token()

    # Pre-populate the storage
    storage._pairing_attempt_states[pairing_id_1] = PairingAttemptContext(  # type: ignore[reportPrivateUsage]
        state="pairing_1_state",
        client_node_id=test_uuid_1,
        pairing_attempt_id=pairing_id_1,
        pairing_node_id=test_pairing_node_id,
        pairing_token=test_token
    )  # type: ignore[attr-defined]
    storage._pairing_attempt_states[pairing_id_2] = PairingAttemptContext(  # type: ignore[reportPrivateUsage]
        state="pairing_2_state",
        pairing_attempt_id=pairing_id_2,
        pairing_node_id=test_pairing_node_id,
        pairing_token=test_token
    )  # type: ignore[attr-defined]

    # Get contexts
    ctx1 = await anext(storage.get_pairing_attempt_context(pairing_id_1))
    ctx2 = await anext(storage.get_pairing_attempt_context(pairing_id_2))

    # Verify contexts are different
    assert ctx1 is not ctx2
    assert ctx1.state == "pairing_1_state"
    assert ctx2.state == "pairing_2_state"
    assert ctx1.client_node_id == test_uuid_1
    assert ctx2.client_node_id is None

    # Verify contexts are persistent
    ctx1_again = await anext(storage.get_pairing_attempt_context(pairing_id_1))
    ctx2_again = await anext(storage.get_pairing_attempt_context(pairing_id_2))

    assert ctx1_again is ctx1
    assert ctx2_again is ctx2


@pytest.mark.skip_wire
async def test_async_in_memory_storage_pairing_keyerror_for_unknown_id():
    """Test that AsyncInMemoryContextStorage raises KeyError for unknown pairing IDs."""
    from uuid import uuid4

    storage = AsyncInMemoryContextStorage()
    unknown_pairing_id = uuid4()

    with pytest.raises(KeyError, match=f"No context known for {unknown_pairing_id}"):
        await anext(storage.get_pairing_attempt_context(unknown_pairing_id))


@pytest.mark.skip_wire
def test_sync_in_memory_storage_thread_safety():
    """Test that SyncInMemoryContextStorage properly handles concurrent thread access."""
    storage = SyncInMemoryContextStorage()
    test_uuid = UUID("00000000-0000-0000-0000-000000000001")

    # Pre-populate the storage
    storage._client_states[test_uuid] = ClientContext()  # type: ignore[attr-defined]

    results: list[int] = []

    def get_context() -> None:
        ctx = next(storage.get_client_context(test_uuid))
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

    # Pre-populate the storage
    storage._client_states[test_uuid_1] = ClientContext(state="state_1")  # type: ignore[attr-defined]
    storage._client_states[test_uuid_2] = ClientContext(state="state_2")  # type: ignore[attr-defined]

    ctx1 = next(storage.get_client_context(test_uuid_1))
    ctx2 = next(storage.get_client_context(test_uuid_2))

    # Verify contexts are different
    assert ctx1 is not ctx2
    assert ctx1.state == "state_1"
    assert ctx2.state == "state_2"

    # Verify contexts are persistent
    ctx1_again = next(storage.get_client_context(test_uuid_1))
    ctx2_again = next(storage.get_client_context(test_uuid_2))

    assert ctx1_again is ctx1
    assert ctx2_again is ctx2
    assert ctx1_again.state == "state_1"
    assert ctx2_again.state == "state_2"


@pytest.mark.skip_wire
def test_sync_in_memory_storage_keyerror_for_unknown_id():
    """Test that SyncInMemoryContextStorage raises KeyError for unknown IDs."""
    storage = SyncInMemoryContextStorage()
    unknown_uuid = UUID("00000000-0000-0000-0000-999999999999")

    with pytest.raises(KeyError, match=f"No context known for {unknown_uuid}"):
        next(storage.get_client_context(unknown_uuid))


@pytest.mark.skip_wire
def test_sync_in_memory_storage_pairing_attempt_contexts():
    """Test that SyncInMemoryContextStorage handles pairing attempt contexts correctly."""
    from uuid import uuid4
    from s2auth.common.models import PairingS2NodeId
    from s2auth.common.hmac import create_pairing_token

    storage = SyncInMemoryContextStorage()

    pairing_id_1 = uuid4()
    pairing_id_2 = uuid4()

    test_uuid_1 = UUID("00000000-0000-0000-0000-000000000001")
    test_pairing_node_id = PairingS2NodeId(root="testnodeid123")
    test_token = create_pairing_token()

    # Pre-populate the storage
    storage._pairing_attempt_states[pairing_id_1] = PairingAttemptContext(  # type: ignore[reportPrivateUsage]
        state="pairing_1_state",
        client_node_id=test_uuid_1,
        pairing_attempt_id=pairing_id_1,
        pairing_node_id=test_pairing_node_id,
        pairing_token=test_token
    )  # type: ignore[attr-defined]
    storage._pairing_attempt_states[pairing_id_2] = PairingAttemptContext(  # type: ignore[reportPrivateUsage]
        state="pairing_2_state",
        pairing_attempt_id=pairing_id_2,
        pairing_node_id=test_pairing_node_id,
        pairing_token=test_token
    )  # type: ignore[attr-defined]

    # Get contexts
    ctx1 = next(storage.get_pairing_attempt_context(pairing_id_1))
    ctx2 = next(storage.get_pairing_attempt_context(pairing_id_2))

    # Verify contexts are different
    assert ctx1 is not ctx2
    assert ctx1.state == "pairing_1_state"
    assert ctx2.state == "pairing_2_state"
    assert ctx1.client_node_id == test_uuid_1
    assert ctx2.client_node_id is None

    # Verify contexts are persistent
    ctx1_again = next(storage.get_pairing_attempt_context(pairing_id_1))
    ctx2_again = next(storage.get_pairing_attempt_context(pairing_id_2))

    assert ctx1_again is ctx1
    assert ctx2_again is ctx2


@pytest.mark.skip_wire
def test_sync_in_memory_storage_pairing_keyerror_for_unknown_id():
    """Test that SyncInMemoryContextStorage raises KeyError for unknown pairing IDs."""
    from uuid import uuid4

    storage = SyncInMemoryContextStorage()
    unknown_pairing_id = uuid4()

    with pytest.raises(KeyError, match=f"No context known for {unknown_pairing_id}"):
        next(storage.get_pairing_attempt_context(unknown_pairing_id))


@pytest.mark.skip_wire
def test_sync_storage_keyerror_behavior():
    """Test that SyncInMemoryContextStorage raises KeyError for unknown IDs consistently."""
    storage = SyncInMemoryContextStorage()
    test_uuid = UUID("00000000-0000-0000-0000-000000000042")

    # Should raise KeyError for unknown ID
    with pytest.raises(KeyError, match=f"No context known for {test_uuid}"):
        next(storage.get_client_context(test_uuid))

    # After pre-populating, it should work
    storage._client_states[test_uuid] = ClientContext(state="modified")  # type: ignore[attr-defined]
    ctx = next(storage.get_client_context(test_uuid))
    assert ctx.state == "modified"


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
    """Test that pairing_attempt_id provider returns UUID from contextvar when set."""
    from uuid import uuid4
    from s2auth.server.dependencies.context import (
        pairing_attempt_id_var,
        pairing_attempt_id as pairing_attempt_id_provider,
    )
    from s2auth.common.models import PairingAttemptId as S2PairingAttemptId

    test_pairing_id = uuid4()

    @inject
    def get_pairing_attempt_id(p_id: PairingAttemptId = Depends[pairing_attempt_id_provider]) -> PairingAttemptId:
        return p_id

    setup()

    # Set the contextvar with string representation of UUID
    token = pairing_attempt_id_var.set(S2PairingAttemptId(root=str(test_pairing_id)))
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

    from uuid import uuid4
    from s2auth.common.models import PairingS2NodeId
    from s2auth.common.hmac import create_pairing_token

    test_pairing_id = uuid4()

    @inject
    async def get_pairing_context(
        ctx: PairingAttemptContext = Depends[pairing_attempt_context_provider]
    ) -> PairingAttemptContext:
        return ctx

    setup()

    # Create a custom storage with pre-populated context
    test_storage = AsyncInMemoryContextStorage()
    test_uuid = UUID("00000000-0000-0000-0000-000000000099")
    test_pairing_node_id = PairingS2NodeId(root="testnodeid123")
    test_token = create_pairing_token()
    test_storage._pairing_attempt_states[test_pairing_id] = PairingAttemptContext(  # type: ignore[reportPrivateUsage]
        state="modified",
        client_node_id=test_uuid,
        pairing_attempt_id=test_pairing_id,
        pairing_node_id=test_pairing_node_id,
        pairing_token=test_token
    )  # type: ignore[attr-defined]

    def get_test_storage() -> AsyncContextStorage:
        return test_storage

    # Set the contextvar
    token = pairing_attempt_id_var.set(S2PairingAttemptId(root=str(test_pairing_id)))
    try:
        with provider_overrides({context_storage_singleton: get_test_storage}):
            # Should return the pre-populated context
            result = await get_pairing_context()
            assert result.state == "modified"
            assert result.client_node_id == test_uuid
    finally:
        # Clean up
        pairing_attempt_id_var.reset(token)


@pytest.mark.skip_wire
async def test_pairing_attempt_context_raises_keyerror_for_unknown_id():
    """Test that pairing_attempt_context raises KeyError when pairing_attempt_id is not known."""
    from uuid import uuid4
    from s2auth.server.dependencies.context import (
        pairing_attempt_id_var,
        pairing_attempt_context as pairing_attempt_context_provider,
    )
    from s2auth.common.models import PairingAttemptId as S2PairingAttemptId

    test_pairing_id = uuid4()

    # Create an empty test storage
    test_storage = AsyncInMemoryContextStorage()

    def test_context_storage() -> AsyncContextStorage:
        return test_storage

    @inject
    async def get_pairing_context(
        ctx: PairingAttemptContext = Depends[pairing_attempt_context_provider]
    ) -> PairingAttemptContext:
        return ctx

    setup()

    # Set the contextvar
    token = pairing_attempt_id_var.set(S2PairingAttemptId(root=str(test_pairing_id)))
    try:
        with provider_overrides({context_storage_singleton: test_context_storage}):
            # Should raise KeyError for unknown ID
            with pytest.raises(KeyError, match=f"No context known for {test_pairing_id}"):
                await get_pairing_context()
    finally:
        # Clean up
        pairing_attempt_id_var.reset(token)


@pytest.mark.skip_wire
async def test_async_fine_grained_locking_concurrent_different_contexts():
    """Test that AsyncInMemoryContextStorage allows concurrent access to DIFFERENT contexts.

    This test verifies that the fine-grained locking implementation allows
    multiple async tasks to access different client contexts simultaneously,
    without blocking each other.
    """
    storage = AsyncInMemoryContextStorage()

    test_uuid_1 = UUID("00000000-0000-0000-0000-000000000001")
    test_uuid_2 = UUID("00000000-0000-0000-0000-000000000002")
    test_uuid_3 = UUID("00000000-0000-0000-0000-000000000003")

    # Pre-populate the storage
    storage._client_states[test_uuid_1] = ClientContext()  # type: ignore[attr-defined]
    storage._client_states[test_uuid_2] = ClientContext()  # type: ignore[attr-defined]
    storage._client_states[test_uuid_3] = ClientContext()  # type: ignore[attr-defined]

    access_times: list[dict[str, Any]] = []

    async def access_context(client_id: UUID, delay: float) -> str:
        """Access a context, simulate work, record timing."""
        start_time = asyncio.get_event_loop().time()
        ctx = await anext(storage.get_client_context(client_id))
        # Simulate some work while holding the lock
        await asyncio.sleep(delay)
        ctx.state = f"accessed_{client_id}"
        end_time = asyncio.get_event_loop().time()
        access_times.append({
            'client_id': client_id,
            'start': start_time,
            'end': end_time
        })
        return ctx.state

    # Access three different contexts concurrently
    results = await asyncio.gather(
        access_context(test_uuid_1, 0.1),
        access_context(test_uuid_2, 0.1),
        access_context(test_uuid_3, 0.1)
    )

    # All should succeed
    assert len(results) == 3
    assert results[0] == f"accessed_{test_uuid_1}"
    assert results[1] == f"accessed_{test_uuid_2}"
    assert results[2] == f"accessed_{test_uuid_3}"

    # Verify that the accesses overlapped (concurrent execution)
    # If they were truly concurrent, the total time should be ~0.1s, not ~0.3s
    # We check that at least two of them had overlapping execution
    overlaps = 0
    for i in range(len(access_times)):
        for j in range(i+1, len(access_times)):
            # Check if time ranges overlap
            if (access_times[i]['start'] < access_times[j]['end'] and
                access_times[j]['start'] < access_times[i]['end']):
                overlaps += 1

    # With 3 concurrent accesses, we should have at least 1 overlap
    assert overlaps >= 1, "Different contexts should be accessible concurrently"


@pytest.mark.skip_wire
async def test_async_fine_grained_locking_same_context_returns_same_object():
    """Test that AsyncInMemoryContextStorage returns the SAME object for same context ID.

    This test verifies that when multiple async tasks access the same context,
    they all receive the same context object (get-or-create is properly synchronized).
    """
    storage = AsyncInMemoryContextStorage()
    test_uuid = UUID("00000000-0000-0000-0000-000000000001")

    # Pre-populate the storage
    storage._client_states[test_uuid] = ClientContext()  # type: ignore[attr-defined]

    context_ids: list[int] = []

    async def get_context() -> None:
        """Get context and record its object ID."""
        ctx = await anext(storage.get_client_context(test_uuid))
        context_ids.append(id(ctx))

    # Access the same context from multiple tasks concurrently
    await asyncio.gather(
        get_context(),
        get_context(),
        get_context(),
        get_context(),
        get_context()
    )

    # All tasks should have received the same context object
    assert len(set(context_ids)) == 1, f"All tasks should get the same context object, but got {len(set(context_ids))} different objects"

    # Verify the context was only created once
    assert len(storage._client_states) == 1  # type: ignore[attr-defined]
    assert test_uuid in storage._client_states  # type: ignore[attr-defined]


async def test_async_fine_grained_locking_same_context_serializes():
    """Test that concurrent access to the SAME context is serialized via DI.

    This verifies that when multiple tasks access the same context ID through
    the DI system, they wait for each other (serialized execution), and that
    modifications from one access are visible to the next.
    """
    from s2auth.server.dependencies.context import (
        client_context,
        client_node_id,
        context_storage_singleton,
    )
    from s2auth.server.dependencies import inject, provider_overrides, setup

    # Wire the DI system
    setup()

    test_uuid = UUID("00000000-0000-0000-0000-000000000001")
    access_times: list[dict[str, Any]] = []

    # Create storage with pre-populated context
    storage = AsyncInMemoryContextStorage()
    storage._client_states[test_uuid] = ClientContext(state="")  # type: ignore[attr-defined]

    # Override providers
    def test_client_id() -> UUID:
        return test_uuid

    async def test_storage() -> AsyncContextStorage:
        return storage

    @inject
    async def access_context(
        task_id: int,
        delay: float,
        ctx: ClientContext = Depends[client_context],
    ) -> str:
        """Access a context via DI, simulate work, record timing."""
        start_time = asyncio.get_event_loop().time()

        # Read current state
        current_state = ctx.state or ""

        # Simulate work while holding the lock
        await asyncio.sleep(delay)

        # Modify the context
        ctx.state = current_state + f"task_{task_id}|"

        end_time = asyncio.get_event_loop().time()
        access_times.append({
            'task_id': task_id,
            'start': start_time,
            'end': end_time,
            'state_after': ctx.state
        })
        return ctx.state

    # Access the same context from multiple tasks concurrently
    with provider_overrides({
        client_node_id: test_client_id,
        context_storage_singleton: test_storage,
    }):
        results = await asyncio.gather(
            access_context(1, 0.05),
            access_context(2, 0.05),
            access_context(3, 0.05)
        )

    # All should succeed
    assert len(results) == 3

    # Verify that accesses were serialized (NOT concurrent)
    # Sort by start time to get execution order
    access_times.sort(key=lambda x: x['start'])

    # Check that each task starts after the previous one ends
    for i in range(len(access_times) - 1):
        current_end = access_times[i]['end']
        next_start = access_times[i + 1]['start']
        assert next_start >= (current_end - 0.01), \
            f"Task {access_times[i+1]['task_id']} should start after task {access_times[i]['task_id']} ends. " \
            f"Current end: {current_end}, Next start: {next_start}"

    # Verify that each task saw the modifications from the previous task
    expected_states = [
        f"task_{access_times[0]['task_id']}|",
        f"task_{access_times[0]['task_id']}|task_{access_times[1]['task_id']}|",
        f"task_{access_times[0]['task_id']}|task_{access_times[1]['task_id']}|task_{access_times[2]['task_id']}|",
    ]
    actual_states = [t['state_after'] for t in access_times]
    assert actual_states == expected_states, \
        f"Each access should see modifications from previous accesses. Expected {expected_states}, got {actual_states}"

    # Total time should be ~0.15s (3 * 0.05s) if serialized
    total_duration = access_times[-1]['end'] - access_times[0]['start']
    assert total_duration >= 0.14, \
        f"Same context accesses should be serialized (total time ~0.15s), got {total_duration}s"


@pytest.mark.skip_wire
async def test_async_fine_grained_locking_pairing_attempts():
    """Test fine-grained locking for pairing attempt contexts."""
    from uuid import uuid4
    from s2auth.common.models import PairingS2NodeId
    from s2auth.common.hmac import create_pairing_token

    storage = AsyncInMemoryContextStorage()

    pairing_id_1 = uuid4()
    pairing_id_2 = uuid4()
    test_pairing_node_id = PairingS2NodeId(root="testnodeid123")
    test_token = create_pairing_token()

    # Pre-populate the storage
    storage._pairing_attempt_states[pairing_id_1] = PairingAttemptContext(  # type: ignore[reportPrivateUsage]
        pairing_attempt_id=pairing_id_1,
        pairing_node_id=test_pairing_node_id,
        pairing_token=test_token
    )  # type: ignore[attr-defined]
    storage._pairing_attempt_states[pairing_id_2] = PairingAttemptContext(  # type: ignore[reportPrivateUsage]
        pairing_attempt_id=pairing_id_2,
        pairing_node_id=test_pairing_node_id,
        pairing_token=test_token
    )  # type: ignore[attr-defined]

    access_times: list[dict[str, Any]] = []

    async def access_pairing_context(pairing_id: UUID, delay: float) -> str:
        """Access a pairing context, simulate work, record timing."""
        start_time = asyncio.get_event_loop().time()
        ctx = await anext(storage.get_pairing_attempt_context(pairing_id))
        await asyncio.sleep(delay)
        ctx.state = f"accessed_{pairing_id}"
        end_time = asyncio.get_event_loop().time()
        access_times.append({
            'pairing_id': pairing_id,
            'start': start_time,
            'end': end_time
        })
        return ctx.state

    # Access two different pairing contexts concurrently
    results = await asyncio.gather(
        access_pairing_context(pairing_id_1, 0.1),
        access_pairing_context(pairing_id_2, 0.1)
    )

    # Both should succeed
    assert len(results) == 2
    assert results[0] == f"accessed_{pairing_id_1}"
    assert results[1] == f"accessed_{pairing_id_2}"

    # Verify concurrent execution (time ranges should overlap)
    assert (access_times[0]['start'] < access_times[1]['end'] and
            access_times[1]['start'] < access_times[0]['end']), \
            "Different pairing contexts should be accessible concurrently"


@pytest.mark.skip_wire
def test_sync_fine_grained_locking_concurrent_different_contexts():
    """Test that SyncInMemoryContextStorage allows concurrent access to DIFFERENT contexts.

    This test verifies that the fine-grained locking implementation allows
    multiple threads to access different client contexts simultaneously.
    """
    storage = SyncInMemoryContextStorage()

    test_uuid_1 = UUID("00000000-0000-0000-0000-000000000001")
    test_uuid_2 = UUID("00000000-0000-0000-0000-000000000002")
    test_uuid_3 = UUID("00000000-0000-0000-0000-000000000003")

    # Pre-populate the storage
    storage._client_states[test_uuid_1] = ClientContext()  # type: ignore[attr-defined]
    storage._client_states[test_uuid_2] = ClientContext()  # type: ignore[attr-defined]
    storage._client_states[test_uuid_3] = ClientContext()  # type: ignore[attr-defined]

    import time
    access_times: list[dict[str, Any]] = []
    lock = threading.Lock()

    def access_context(client_id: UUID, delay: float) -> None:
        """Access a context, simulate work, record timing."""
        start_time = time.time()
        ctx = next(storage.get_client_context(client_id))
        # Simulate some work while holding the lock
        time.sleep(delay)
        ctx.state = f"accessed_{client_id}"
        end_time = time.time()

        with lock:
            access_times.append({
                'client_id': client_id,
                'start': start_time,
                'end': end_time
            })

    # Access three different contexts concurrently
    threads = [
        threading.Thread(target=access_context, args=(test_uuid_1, 0.1)),
        threading.Thread(target=access_context, args=(test_uuid_2, 0.1)),
        threading.Thread(target=access_context, args=(test_uuid_3, 0.1))
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # All should succeed
    assert len(access_times) == 3

    # Verify that the accesses overlapped (concurrent execution)
    overlaps = 0
    for i in range(len(access_times)):
        for j in range(i+1, len(access_times)):
            if (access_times[i]['start'] < access_times[j]['end'] and
                access_times[j]['start'] < access_times[i]['end']):
                overlaps += 1

    # With 3 concurrent accesses, we should have at least 1 overlap
    assert overlaps >= 1, "Different contexts should be accessible concurrently"


@pytest.mark.skip_wire
def test_sync_fine_grained_locking_same_context_returns_same_object():
    """Test that SyncInMemoryContextStorage returns the SAME object for same context ID.

    This test verifies that when multiple threads access the same context,
    they all receive the same context object (get-or-create is properly synchronized).
    """
    storage = SyncInMemoryContextStorage()
    test_uuid = UUID("00000000-0000-0000-0000-000000000001")

    # Pre-populate the storage
    storage._client_states[test_uuid] = ClientContext()  # type: ignore[attr-defined]

    context_ids: list[int] = []
    lock = threading.Lock()

    def get_context() -> None:
        """Get context and record its object ID."""
        ctx = next(storage.get_client_context(test_uuid))
        with lock:
            context_ids.append(id(ctx))

    # Access the same context from multiple threads concurrently
    threads = [
        threading.Thread(target=get_context)
        for _ in range(5)
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # All threads should have received the same context object
    assert len(set(context_ids)) == 1, f"All threads should get the same context object, but got {len(set(context_ids))} different objects"

    # Verify the context was only created once
    assert len(storage._client_states) == 1  # type: ignore[attr-defined]
    assert test_uuid in storage._client_states  # type: ignore[attr-defined]


def test_sync_fine_grained_locking_same_context_serializes():
    """Test that concurrent access to the SAME context is serialized via DI.

    This verifies that when multiple threads access the same context ID through
    the DI system, they wait for each other (serialized execution), and that
    modifications from one access are visible to the next.
    """
    import time
    from typing import Generator
    from s2auth.server.dependencies.context import (
        client_context,
        client_node_id,
        context_storage_singleton,
    )
    from s2auth.server.dependencies import inject, provider_overrides, setup

    # Wire the DI system
    setup()

    test_uuid = UUID("00000000-0000-0000-0000-000000000001")
    access_times: list[dict[str, Any]] = []
    lock = threading.Lock()

    # Create storage with pre-populated context
    storage = SyncInMemoryContextStorage()
    storage._client_states[test_uuid] = ClientContext(state="")  # type: ignore[attr-defined]

    # Override providers - sync versions for sync storage
    def test_client_id() -> UUID:
        return test_uuid

    def test_storage() -> SyncContextStorage:
        return storage

    @inject
    def test_client_context(
        cid: UUID = Depends[client_node_id],
        stor: SyncContextStorage = Depends[context_storage_singleton],
    ) -> Generator[ClientContext, None, None]:
        """Sync generator version of client_context for sync storage."""
        for ctx in stor.get_client_context(cid):
            yield ctx

    @inject
    def access_context(
        thread_id: int,
        delay: float,
        ctx: ClientContext = Depends[client_context],
    ) -> str:
        """Access a context via DI, simulate work, record timing."""
        start_time = time.time()

        # Read current state
        current_state = ctx.state or ""

        # Simulate work while holding the lock
        time.sleep(delay)

        # Modify the context
        ctx.state = current_state + f"thread_{thread_id}|"

        end_time = time.time()

        with lock:
            access_times.append({
                'thread_id': thread_id,
                'start': start_time,
                'end': end_time,
                'state_after': ctx.state
            })
        return ctx.state

    # Access the same context from multiple threads concurrently
    with provider_overrides({
        client_node_id: test_client_id,
        context_storage_singleton: test_storage,
        client_context: test_client_context,
    }):
        threads = [
            threading.Thread(target=access_context, args=(1, 0.05)),
            threading.Thread(target=access_context, args=(2, 0.05)),
            threading.Thread(target=access_context, args=(3, 0.05))
        ]

        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    # Verify that accesses were serialized (NOT concurrent)
    # Sort by start time to get execution order
    access_times.sort(key=lambda x: x['start'])

    # Check that each thread starts after the previous one ends
    for i in range(len(access_times) - 1):
        current_end = access_times[i]['end']
        next_start = access_times[i + 1]['start']
        assert next_start >= (current_end - 0.01), \
            f"Thread {access_times[i+1]['thread_id']} should start after thread {access_times[i]['thread_id']} ends. " \
            f"Current end: {current_end}, Next start: {next_start}"

    # Verify that each thread saw the modifications from the previous thread
    expected_states = [
        f"thread_{access_times[0]['thread_id']}|",
        f"thread_{access_times[0]['thread_id']}|thread_{access_times[1]['thread_id']}|",
        f"thread_{access_times[0]['thread_id']}|thread_{access_times[1]['thread_id']}|thread_{access_times[2]['thread_id']}|",
    ]
    actual_states = [t['state_after'] for t in access_times]
    assert actual_states == expected_states, \
        f"Each access should see modifications from previous accesses. Expected {expected_states}, got {actual_states}"

    # Total time should be ~0.15s (3 * 0.05s) if serialized
    total_duration = access_times[-1]['end'] - access_times[0]['start']
    assert total_duration >= 0.14, \
        f"Same context accesses should be serialized (total time ~0.15s), got {total_duration}s"


@pytest.mark.skip_wire
def test_sync_fine_grained_locking_pairing_attempts():
    """Test fine-grained locking for pairing attempt contexts in sync storage."""
    from uuid import uuid4
    from s2auth.common.models import PairingS2NodeId
    from s2auth.common.hmac import create_pairing_token

    storage = SyncInMemoryContextStorage()

    pairing_id_1 = uuid4()
    pairing_id_2 = uuid4()
    test_pairing_node_id = PairingS2NodeId(root="testnodeid123")
    test_token = create_pairing_token()

    # Pre-populate the storage
    storage._pairing_attempt_states[pairing_id_1] = PairingAttemptContext(  # type: ignore[reportPrivateUsage]
        pairing_attempt_id=pairing_id_1,
        pairing_node_id=test_pairing_node_id,
        pairing_token=test_token
    )  # type: ignore[attr-defined]
    storage._pairing_attempt_states[pairing_id_2] = PairingAttemptContext(  # type: ignore[reportPrivateUsage]
        pairing_attempt_id=pairing_id_2,
        pairing_node_id=test_pairing_node_id,
        pairing_token=test_token
    )  # type: ignore[attr-defined]

    import time
    access_times: list[dict[str, Any]] = []
    lock = threading.Lock()

    def access_pairing_context(pairing_id: UUID, delay: float) -> None:
        """Access a pairing context, simulate work, record timing."""
        start_time = time.time()
        ctx = next(storage.get_pairing_attempt_context(pairing_id))
        time.sleep(delay)
        ctx.state = f"accessed_{pairing_id}"
        end_time = time.time()

        with lock:
            access_times.append({
                'pairing_id': pairing_id,
                'start': start_time,
                'end': end_time
            })

    # Access two different pairing contexts concurrently
    threads = [
        threading.Thread(target=access_pairing_context, args=(pairing_id_1, 0.1)),
        threading.Thread(target=access_pairing_context, args=(pairing_id_2, 0.1))
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Both should succeed
    assert len(access_times) == 2

    # Verify concurrent execution (time ranges should overlap)
    assert (access_times[0]['start'] < access_times[1]['end'] and
            access_times[1]['start'] < access_times[0]['end']), \
            "Different pairing contexts should be accessible concurrently"
