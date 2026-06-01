import pytest
import asyncio
import threading
from base64 import b64encode
from typing import Any, AsyncGenerator
from contextlib import asynccontextmanager
from uuid import UUID
from s2auth.common.dependencies import setup, Depends, inject, provider_overrides
from s2auth.server.context import (
    ClientState,
    client_node_id,
    context_storage_singleton,
    client_context,
    ClientContext,
    ClientNodeId,
    ContextStorage,
    InMemoryContextStorage,
    PairingAttemptContext,
    PairingAttemptId,
    PairingState,
)


@asynccontextmanager
async def get_context_once(
    storage: ContextStorage,
    context_id: UUID,
    is_pairing: bool = False
) -> AsyncGenerator[ClientContext | PairingAttemptContext, None]:
    """Helper to properly manage async generator lifecycle for single-use access."""
    if is_pairing:
        gen = storage.get_pairing_attempt_context(context_id)
    else:
        gen = storage.get_client_context(context_id)
    try:
        ctx = await anext(gen)
        yield ctx
    finally:
        await gen.aclose()


class MockContextStorage(ContextStorage):
    """Test implementation of ContextStorage with pre-populated data."""

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

    async def store_client_context(self, context: ClientContext) -> None:
        """Store a client context in the mock storage."""
        if context.client_node_id is None:
            raise ValueError("ClientContext must have client_node_id set")
        self.client_contexts[context.client_node_id] = context

    async def store_pairing_attempt_context(self, context: PairingAttemptContext) -> None:
        """Store a pairing attempt context in the mock storage."""
        self.pairing_contexts[context.pairing_attempt_id] = context



@pytest.mark.skip_wire
async def test_client_context_with_multiple_clients():
    """Test that client_context returns the correct context for multiple clients."""
    # Create a test storage with pre-populated data
    test_uuid_1 = UUID("00000000-0000-0000-0000-000000000001")
    test_uuid_2 = UUID("00000000-0000-0000-0000-000000000002")
    test_uuid_3 = UUID("00000000-0000-0000-0000-000000000003")

    test_storage = MockContextStorage(
        client_contexts={
            test_uuid_1: ClientContext(state=ClientState.PAIRING),
            test_uuid_2: ClientContext(state=ClientState.PAIRED),
            test_uuid_3: ClientContext(state=ClientState.CONNECTED),
        }
    )

    def test_context_storage() -> ContextStorage:
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
        assert result.state == ClientState.PAIRING

    # Test client 2
    with provider_overrides(
        {
            context_storage_singleton: test_context_storage,
            client_node_id: test_client_node_id_2,
        }
    ):
        result = await get_context()
        assert result.state == ClientState.PAIRED

    # Test client 3
    with provider_overrides(
        {
            context_storage_singleton: test_context_storage,
            client_node_id: test_client_node_id_3,
        }
    ):
        result = await get_context()
        assert result.state == ClientState.CONNECTED


@pytest.mark.skip_wire
async def test_context_storage_singleton_is_singleton():
    """Test that context_storage_singleton is instantiated only once and changes persist."""

    @inject
    async def get_storage(
        storage: ContextStorage = Depends[context_storage_singleton],
    ) -> ContextStorage:
        return storage

    @inject
    async def modify_storage(
        storage: ContextStorage = Depends[context_storage_singleton],
    ) -> None:
        test_uuid = UUID("00000000-0000-0000-0000-000000000999")
        # Create and modify the storage
        storage._client_states[test_uuid] = ClientContext(state=ClientState.CONNECTED)  # type: ignore[attr-defined]

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
    async with get_context_once(storage2, test_uuid) as ctx:
        assert ctx.state == ClientState.CONNECTED, "Modified state should be preserved"


@pytest.mark.skip_wire
async def test_client_context_returns_existing_context():
    """Test that client_context returns existing context when client_node_id already exists."""
    test_uuid = UUID("00000000-0000-0000-0000-00000000002a")

    # Create a test storage with pre-populated data
    existing_context = ClientContext(state=ClientState.PAIRED)
    test_storage = MockContextStorage(
        client_contexts={test_uuid: existing_context}
    )

    def test_context_storage() -> ContextStorage:
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
        assert result.state == ClientState.PAIRED

        # Verify the context is the same object from the storage
        assert result is existing_context


@pytest.mark.skip_wire
async def test_client_context_raises_keyerror_for_unknown_id():
    """Test that client_context raises KeyError when client_node_id is not known."""
    test_uuid = UUID("00000000-0000-0000-0000-000000000063")

    # Create an empty test storage
    test_storage = InMemoryContextStorage()

    def test_context_storage() -> ContextStorage:
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
    """Test that InMemoryContextStorage properly handles concurrent async access."""
    storage = InMemoryContextStorage()
    test_uuid = UUID("00000000-0000-0000-0000-000000000001")

    # Pre-populate the storage
    storage._client_states[test_uuid] = ClientContext()  # type: ignore[attr-defined]

    async def get_context() -> int:
        async with get_context_once(storage, test_uuid) as ctx:
            return id(ctx)

    # Create multiple async tasks that try to get the same context
    results = await asyncio.gather(*[get_context() for _ in range(10)])

    # All tasks should get the same context instance
    assert len(set(results)) == 1, "All async tasks should get the same context instance"


@pytest.mark.skip_wire
async def test_async_in_memory_storage_multiple_contexts():
    """Test that InMemoryContextStorage maintains separate contexts for different IDs."""
    storage = InMemoryContextStorage()

    test_uuid_1 = UUID("00000000-0000-0000-0000-000000000001")
    test_uuid_2 = UUID("00000000-0000-0000-0000-000000000002")

    # Pre-populate the storage
    storage._client_states[test_uuid_1] = ClientContext(state=ClientState.PAIRING)  # type: ignore[attr-defined]
    storage._client_states[test_uuid_2] = ClientContext(state=ClientState.DISCONNECTED)  # type: ignore[attr-defined]

    async with get_context_once(storage, test_uuid_1) as ctx1:
        async with get_context_once(storage, test_uuid_2) as ctx2:
            # Verify contexts are different
            assert ctx1 is not ctx2
            assert ctx1.state == ClientState.PAIRING
            assert ctx2.state == ClientState.DISCONNECTED

    # Verify contexts are persistent
    async with get_context_once(storage, test_uuid_1) as ctx1_again:
        async with get_context_once(storage, test_uuid_2) as ctx2_again:
            assert ctx1_again is ctx1
            assert ctx2_again is ctx2
            assert ctx1_again.state == ClientState.PAIRING
            assert ctx2_again.state == ClientState.DISCONNECTED


@pytest.mark.skip_wire
async def test_async_in_memory_storage_keyerror_for_unknown_id():
    """Test that InMemoryContextStorage raises KeyError for unknown IDs."""
    storage = InMemoryContextStorage()
    unknown_uuid = UUID("00000000-0000-0000-0000-999999999999")

    with pytest.raises(KeyError, match=f"No context known for {unknown_uuid}"):
        async with get_context_once(storage, unknown_uuid) as _:
            pass


@pytest.mark.skip_wire
async def test_async_in_memory_storage_pairing_attempt_contexts():
    """Test that InMemoryContextStorage handles pairing attempt contexts correctly."""
    from uuid import uuid4
    from s2auth.common.model.s2_connect_pairing import NodeIdAlias
    from s2auth.common.hmac import create_pairing_code

    storage = InMemoryContextStorage()

    pairing_id_1 = uuid4()
    pairing_id_2 = uuid4()

    test_uuid_1 = UUID("00000000-0000-0000-0000-000000000001")
    test_pairing_node_id = NodeIdAlias(root="testnodeid123")
    test_token = create_pairing_code()

    # Pre-populate the storage
    storage._pairing_attempt_states[pairing_id_1] = PairingAttemptContext(  # type: ignore[reportPrivateUsage]
        state=PairingState.INITIATED,
        client_node_id=test_uuid_1,
        pairing_attempt_id=pairing_id_1,
        pairing_node_id=test_pairing_node_id,
        pairing_token=test_token
    )  # type: ignore[attr-defined]
    storage._pairing_attempt_states[pairing_id_2] = PairingAttemptContext(  # type: ignore[reportPrivateUsage]
        state=PairingState.COMPLETED,
        pairing_attempt_id=pairing_id_2,
        pairing_node_id=test_pairing_node_id,
        pairing_token=test_token
    )  # type: ignore[attr-defined]

    # Get contexts
    async with get_context_once(storage, pairing_id_1, is_pairing=True) as ctx1:
        async with get_context_once(storage, pairing_id_2, is_pairing=True) as ctx2:
            # Verify contexts are different
            assert ctx1 is not ctx2
            assert ctx1.state == PairingState.INITIATED
            assert ctx2.state == PairingState.COMPLETED
            assert ctx1.client_node_id == test_uuid_1
            assert ctx2.client_node_id is None

    # Verify contexts are persistent
    async with get_context_once(storage, pairing_id_1, is_pairing=True) as ctx1_again:
        async with get_context_once(storage, pairing_id_2, is_pairing=True) as ctx2_again:
            assert ctx1_again is ctx1
            assert ctx2_again is ctx2


@pytest.mark.skip_wire
async def test_async_in_memory_storage_pairing_keyerror_for_unknown_id():
    """Test that InMemoryContextStorage raises KeyError for unknown pairing IDs."""
    from uuid import uuid4

    storage = InMemoryContextStorage()
    unknown_pairing_id = uuid4()

    with pytest.raises(KeyError, match=f"No context known for {unknown_pairing_id}"):
        async with get_context_once(storage, unknown_pairing_id, is_pairing=True) as _:
            pass


@pytest.mark.skip_wire
async def test_sync_in_memory_storage_thread_safety():
    """Test that InMemoryContextStorage properly handles concurrent thread access."""
    storage = InMemoryContextStorage()
    test_uuid = UUID("00000000-0000-0000-0000-000000000001")

    # Pre-populate the storage
    storage._client_states[test_uuid] = ClientContext()  # type: ignore[attr-defined]

    results: list[int] = []

    def get_context() -> None:
        async def async_work():
            ctx_gen = storage.get_client_context(test_uuid)
            ctx = await anext(ctx_gen)
            results.append(id(ctx))
            await ctx_gen.aclose()
        asyncio.run(async_work())

    # Create multiple threads that try to get the same context
    threads = [threading.Thread(target=get_context) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # All threads should get the same context instance
    assert len(set(results)) == 1, "All threads should get the same context instance"


@pytest.mark.skip_wire
async def test_sync_in_memory_storage_multiple_contexts():
    """Test that InMemoryContextStorage maintains separate contexts for different IDs."""
    storage = InMemoryContextStorage()

    test_uuid_1 = UUID("00000000-0000-0000-0000-000000000001")
    test_uuid_2 = UUID("00000000-0000-0000-0000-000000000002")

    # Pre-populate the storage
    storage._client_states[test_uuid_1] = ClientContext(state=ClientState.PAIRING)  # type: ignore[attr-defined]
    storage._client_states[test_uuid_2] = ClientContext(state=ClientState.DISCONNECTED)  # type: ignore[attr-defined]

    async with get_context_once(storage, test_uuid_1) as ctx1:
        async with get_context_once(storage, test_uuid_2) as ctx2:
            # Verify contexts are different
            assert ctx1 is not ctx2
            assert ctx1.state == ClientState.PAIRING
            assert ctx2.state == ClientState.DISCONNECTED

    # Verify contexts are persistent
    async with get_context_once(storage, test_uuid_1) as ctx1_again:
        async with get_context_once(storage, test_uuid_2) as ctx2_again:
            assert ctx1_again is ctx1
            assert ctx2_again is ctx2
            assert ctx1_again.state == ClientState.PAIRING
            assert ctx2_again.state == ClientState.DISCONNECTED


@pytest.mark.skip_wire
async def test_sync_in_memory_storage_keyerror_for_unknown_id():
    """Test that InMemoryContextStorage raises KeyError for unknown IDs."""
    storage = InMemoryContextStorage()
    unknown_uuid = UUID("00000000-0000-0000-0000-999999999999")

    with pytest.raises(KeyError, match=f"No context known for {unknown_uuid}"):
        async with get_context_once(storage, unknown_uuid) as _:
            pass


@pytest.mark.skip_wire
async def test_sync_in_memory_storage_pairing_attempt_contexts():
    """Test that InMemoryContextStorage handles pairing attempt contexts correctly."""
    from uuid import uuid4
    from s2auth.common.model.s2_connect_pairing import NodeIdAlias
    from s2auth.common.hmac import create_pairing_code

    storage = InMemoryContextStorage()

    pairing_id_1 = uuid4()
    pairing_id_2 = uuid4()

    test_uuid_1 = UUID("00000000-0000-0000-0000-000000000001")
    test_pairing_node_id = NodeIdAlias(root="testnodeid123")
    test_token = create_pairing_code()

    # Pre-populate the storage
    storage._pairing_attempt_states[pairing_id_1] = PairingAttemptContext(  # type: ignore[reportPrivateUsage]
        state=PairingState.INITIATED,
        client_node_id=test_uuid_1,
        pairing_attempt_id=pairing_id_1,
        pairing_node_id=test_pairing_node_id,
        pairing_token=test_token
    )  # type: ignore[attr-defined]
    storage._pairing_attempt_states[pairing_id_2] = PairingAttemptContext(  # type: ignore[reportPrivateUsage]
        state=PairingState.COMPLETED,
        pairing_attempt_id=pairing_id_2,
        pairing_node_id=test_pairing_node_id,
        pairing_token=test_token
    )  # type: ignore[attr-defined]

    # Get contexts
    async with get_context_once(storage, pairing_id_1, is_pairing=True) as ctx1:
        async with get_context_once(storage, pairing_id_2, is_pairing=True) as ctx2:
            # Verify contexts are different
            assert ctx1 is not ctx2
            assert ctx1.state == PairingState.INITIATED
            assert ctx2.state == PairingState.COMPLETED
            assert ctx1.client_node_id == test_uuid_1
            assert ctx2.client_node_id is None

    # Verify contexts are persistent
    async with get_context_once(storage, pairing_id_1, is_pairing=True) as ctx1_again:
        async with get_context_once(storage, pairing_id_2, is_pairing=True) as ctx2_again:
            assert ctx1_again is ctx1
            assert ctx2_again is ctx2


@pytest.mark.skip_wire
async def test_sync_in_memory_storage_pairing_keyerror_for_unknown_id():
    """Test that InMemoryContextStorage raises KeyError for unknown pairing IDs."""
    from uuid import uuid4

    storage = InMemoryContextStorage()
    unknown_pairing_id = uuid4()

    with pytest.raises(KeyError, match=f"No context known for {unknown_pairing_id}"):
        async with get_context_once(storage, unknown_pairing_id, is_pairing=True) as _:
            pass


@pytest.mark.skip_wire
async def test_sync_storage_keyerror_behavior():
    """Test that InMemoryContextStorage raises KeyError for unknown IDs consistently."""
    storage = InMemoryContextStorage()
    test_uuid = UUID("00000000-0000-0000-0000-000000000042")

    # Should raise KeyError for unknown ID
    with pytest.raises(KeyError, match=f"No context known for {test_uuid}"):
        async with get_context_once(storage, test_uuid) as _:
            pass

    # After pre-populating, it should work
    storage._client_states[test_uuid] = ClientContext(state=ClientState.CONNECTED)  # type: ignore[attr-defined]
    async with get_context_once(storage, test_uuid) as ctx:
        assert ctx.state == ClientState.CONNECTED


@pytest.mark.skip_wire
async def test_client_node_id_provider_with_contextvar_set():
    """Test that client_node_id provider returns UUID from contextvar when set."""
    from s2auth.server.context import (
        s2_client_node_id_var,
        client_node_id as client_node_id_provider,
    )
    from s2auth.common.model.s2_connect_common import NodeId

    test_uuid = UUID("00000000-0000-0000-0000-000000000042")

    @inject
    def get_client_node_id(node_id: ClientNodeId = Depends[client_node_id_provider]) -> ClientNodeId:
        return node_id

    setup()

    # Set the contextvar
    token = s2_client_node_id_var.set(NodeId(root=test_uuid))
    try:
        result = get_client_node_id()
        assert result == test_uuid
    finally:
        # Clean up
        s2_client_node_id_var.reset(token)


@pytest.mark.skip_wire
async def test_client_node_id_provider_without_contextvar():
    """Test that client_node_id provider raises ValueError when contextvar is not set."""
    from s2auth.server.context import (
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
    from s2auth.server.context import (
        pairing_attempt_id_var,
        pairing_attempt_id as pairing_attempt_id_provider,
    )
    from s2auth.common.model.s2_connect_pairing import PairingAttemptId as S2PairingAttemptId

    test_pairing_id = uuid4()

    @inject
    def get_pairing_attempt_id(p_id: PairingAttemptId = Depends[pairing_attempt_id_provider]) -> PairingAttemptId:
        return p_id

    setup()

    # Set the contextvar with base64-encoded UUID
    token = pairing_attempt_id_var.set(S2PairingAttemptId(root=b64encode(str(test_pairing_id).encode('utf-8'))))
    try:
        result = get_pairing_attempt_id()
        assert result == test_pairing_id
    finally:
        # Clean up
        pairing_attempt_id_var.reset(token)


@pytest.mark.skip_wire
async def test_pairing_attempt_id_provider_without_contextvar():
    """Test that pairing_attempt_id provider raises ValueError when contextvar is not set."""
    from s2auth.server.context import (
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
    from s2auth.server.context import (
        pairing_attempt_id_var,
        pairing_attempt_context as pairing_attempt_context_provider,
    )
    from s2auth.common.model.s2_connect_pairing import PairingAttemptId as S2PairingAttemptId

    from uuid import uuid4
    from s2auth.common.model.s2_connect_pairing import NodeIdAlias
    from s2auth.common.hmac import create_pairing_code

    test_pairing_id = uuid4()

    @inject
    async def get_pairing_context(
        ctx: PairingAttemptContext = Depends[pairing_attempt_context_provider]
    ) -> PairingAttemptContext:
        return ctx

    setup()

    # Create a custom storage with pre-populated context
    test_storage = InMemoryContextStorage()
    test_uuid = UUID("00000000-0000-0000-0000-000000000099")
    test_pairing_node_id = NodeIdAlias(root="testnodeid123")
    test_token = create_pairing_code()
    test_storage._pairing_attempt_states[test_pairing_id] = PairingAttemptContext(  # type: ignore[reportPrivateUsage]
        state=PairingState.INITIATED,
        client_node_id=test_uuid,
        pairing_attempt_id=test_pairing_id,
        pairing_node_id=test_pairing_node_id,
        pairing_token=test_token
    )  # type: ignore[attr-defined]

    def get_test_storage() -> ContextStorage:
        return test_storage

    # Set the contextvar with base64-encoded UUID
    token = pairing_attempt_id_var.set(S2PairingAttemptId(root=b64encode(str(test_pairing_id).encode('utf-8'))))
    try:
        with provider_overrides({context_storage_singleton: get_test_storage}):
            # Should return the pre-populated context
            result = await get_pairing_context()
            assert result.state == PairingState.INITIATED
            assert result.client_node_id == test_uuid
    finally:
        # Clean up
        pairing_attempt_id_var.reset(token)


@pytest.mark.skip_wire
async def test_pairing_attempt_context_raises_keyerror_for_unknown_id():
    """Test that pairing_attempt_context raises KeyError when pairing_attempt_id is not known."""
    from uuid import uuid4
    from s2auth.server.context import (
        pairing_attempt_id_var,
        pairing_attempt_context as pairing_attempt_context_provider,
    )
    from s2auth.common.model.s2_connect_pairing import PairingAttemptId as S2PairingAttemptId

    test_pairing_id = uuid4()

    # Create an empty test storage
    test_storage = InMemoryContextStorage()

    def test_context_storage() -> ContextStorage:
        return test_storage

    @inject
    async def get_pairing_context(
        ctx: PairingAttemptContext = Depends[pairing_attempt_context_provider]
    ) -> PairingAttemptContext:
        return ctx

    setup()

    # Set the contextvar with base64-encoded UUID
    token = pairing_attempt_id_var.set(S2PairingAttemptId(root=b64encode(str(test_pairing_id).encode('utf-8'))))
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
    """Test that InMemoryContextStorage allows concurrent access to DIFFERENT contexts.

    This test verifies that the fine-grained locking implementation allows
    multiple async tasks to access different client contexts simultaneously,
    without blocking each other.

    CRITICAL: This test verifies that _locks_lock doesn't cause serialization.
    If _locks_lock was held during fine-grained lock acquisition, all accesses
    would be serialized and total time would be 5 × 0.1s = 0.5s instead of ~0.1s.
    """
    storage = InMemoryContextStorage()

    # Create 5 different contexts to test parallel access
    test_uuids = [UUID(f"00000000-0000-0000-0000-00000000000{i}") for i in range(1, 6)]

    # Pre-populate the storage
    for uuid in test_uuids:
        storage._client_states[uuid] = ClientContext()  # type: ignore[attr-defined]

    start_times: list[float] = []
    end_times: list[float] = []

    async def access_context(client_id: UUID, delay: float) -> str:
        """Access a context, simulate work, record timing."""
        start_time = asyncio.get_event_loop().time()
        start_times.append(start_time)
        async with get_context_once(storage, client_id):
            # Simulate some work while holding the lock
            await asyncio.sleep(delay)
            end_time = asyncio.get_event_loop().time()
            end_times.append(end_time)
            return f"accessed_{client_id}"

    # Access all 5 different contexts concurrently with 0.1s delay each
    overall_start = asyncio.get_event_loop().time()
    results = await asyncio.gather(*[access_context(uuid, 0.1) for uuid in test_uuids])
    overall_end = asyncio.get_event_loop().time()
    total_time = overall_end - overall_start

    # All should succeed
    assert len(results) == 5
    for i, uuid in enumerate(test_uuids):
        assert results[i] == f"accessed_{uuid}"

    # CRITICAL TEST: If _locks_lock caused serialization, total time would be ~0.5s
    # If truly concurrent, total time should be ~0.1s
    assert total_time < 0.25, \
        f"Access to different contexts should be concurrent (expected ~0.1s, got {total_time:.3f}s). " \
        f"This suggests _locks_lock is causing serialization!"

    # Verify all tasks started roughly at the same time (within 50ms)
    first_start = min(start_times)
    last_start = max(start_times)
    start_spread = last_start - first_start
    assert start_spread < 0.05, \
        f"All tasks should start nearly simultaneously, but spread was {start_spread:.3f}s"


@pytest.mark.skip_wire
async def test_async_fine_grained_locking_same_context_returns_same_object():
    """Test that InMemoryContextStorage returns the SAME object for same context ID.

    This test verifies that when multiple async tasks access the same context,
    they all receive the same context object (get-or-create is properly synchronized).
    """
    storage = InMemoryContextStorage()
    test_uuid = UUID("00000000-0000-0000-0000-000000000001")

    # Pre-populate the storage
    storage._client_states[test_uuid] = ClientContext()  # type: ignore[attr-defined]

    context_ids: list[int] = []

    async def get_context() -> None:
        """Get context and record its object ID."""
        async with get_context_once(storage, test_uuid) as ctx:
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
    from s2auth.server.context import (
        client_context,
        client_node_id,
        context_storage_singleton,
    )
    from s2auth.common.dependencies import inject, provider_overrides, setup

    # Wire the DI system
    setup()

    test_uuid = UUID("00000000-0000-0000-0000-000000000001")
    access_times: list[dict[str, Any]] = []

    # Create storage with pre-populated context
    storage = InMemoryContextStorage()
    storage._client_states[test_uuid] = ClientContext()  # type: ignore[attr-defined]

    # Override providers
    def test_client_id() -> UUID:
        return test_uuid

    async def test_storage() -> ContextStorage:
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
        #current_state = ctx.state or ""

        # Simulate work while holding the lock
        await asyncio.sleep(delay)

        # Modify the context
        ctx.state = ClientState.CONNECTED if ctx.state != ClientState.CONNECTED else ClientState.PAIRED # type: ignore[attr-defined]

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
    expected_states = [ClientState.CONNECTED, ClientState.PAIRED, ClientState.CONNECTED]

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
    from s2auth.common.model.s2_connect_pairing import NodeIdAlias
    from s2auth.common.hmac import create_pairing_code

    storage = InMemoryContextStorage()

    pairing_id_1 = uuid4()
    pairing_id_2 = uuid4()
    test_pairing_node_id = NodeIdAlias(root="testnodeid123")
    test_token = create_pairing_code()

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
        async with get_context_once(storage, pairing_id, is_pairing=True):
            await asyncio.sleep(delay)
            end_time = asyncio.get_event_loop().time()
            access_times.append({
                'pairing_id': pairing_id,
                'start': start_time,
                'end': end_time
            })
            return f"accessed_{pairing_id}"

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
async def test_sync_fine_grained_locking_concurrent_different_contexts():
    """Test that InMemoryContextStorage allows concurrent access to DIFFERENT contexts.

    This test verifies that the fine-grained locking implementation allows
    multiple threads to access different client contexts simultaneously.

    CRITICAL: This test verifies that _locks_lock doesn't cause serialization.
    If _locks_lock was held during fine-grained lock acquisition, all accesses
    would be serialized and total time would be 5 × 0.1s = 0.5s instead of ~0.1s.
    """
    storage = InMemoryContextStorage()

    # Create 5 different contexts to test parallel access
    test_uuids = [UUID(f"00000000-0000-0000-0000-00000000000{i}") for i in range(1, 6)]

    # Pre-populate the storage
    for uuid in test_uuids:
        storage._client_states[uuid] = ClientContext()  # type: ignore[attr-defined]

    import time
    start_times: list[float] = []
    end_times: list[float] = []
    lock = threading.Lock()

    def access_context(client_id: UUID, delay: float) -> None:
        """Access a context, simulate work, record timing."""
        async def async_work():
            start_time = time.time()
            with lock:
                start_times.append(start_time)

            ctx_gen = storage.get_client_context(client_id)
            ctx = await anext(ctx_gen)
            ctx.state = ClientState.CONNECTED  # Simulate some modification to ensure lock is held
            # Simulate some work while holding the lock
            time.sleep(delay)

            end_time = time.time()
            with lock:
                end_times.append(end_time)

            await ctx_gen.aclose()
        asyncio.run(async_work())

    # Access all 5 different contexts concurrently from different threads
    overall_start = time.time()
    threads = [threading.Thread(target=access_context, args=(uuid, 0.1)) for uuid in test_uuids]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    overall_end = time.time()
    total_time = overall_end - overall_start

    # All should succeed
    assert len(start_times) == 5
    assert len(end_times) == 5

    # CRITICAL TEST: If _locks_lock caused serialization, total time would be ~0.5s
    # If truly concurrent, total time should be ~0.1s
    assert total_time < 0.25, \
        f"Access to different contexts should be concurrent (expected ~0.1s, got {total_time:.3f}s). " \
        f"This suggests _locks_lock is causing serialization!"

    # Verify threads started roughly at the same time (within 50ms)
    first_start = min(start_times)
    last_start = max(start_times)
    start_spread = last_start - first_start
    assert start_spread < 0.05, \
        f"All threads should start nearly simultaneously, but spread was {start_spread:.3f}s"


@pytest.mark.skip_wire
async def test_sync_fine_grained_locking_same_context_returns_same_object():
    """Test that InMemoryContextStorage returns the SAME object for same context ID.

    This test verifies that when multiple threads access the same context,
    they all receive the same context object (get-or-create is properly synchronized).
    """
    storage = InMemoryContextStorage()
    test_uuid = UUID("00000000-0000-0000-0000-000000000001")

    # Pre-populate the storage
    storage._client_states[test_uuid] = ClientContext()  # type: ignore[attr-defined]

    context_ids: list[int] = []
    lock = threading.Lock()

    def get_context() -> None:
        """Get context and record its object ID."""
        async def async_work():
            ctx_gen = storage.get_client_context(test_uuid)
            ctx = await anext(ctx_gen)
            with lock:
                context_ids.append(id(ctx))
            await ctx_gen.aclose()
        asyncio.run(async_work())

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


async def test_sync_fine_grained_locking_same_context_serializes():
    """Test that concurrent access to the SAME context is serialized via DI.

    This verifies that when multiple threads access the same context ID through
    the DI system, they wait for each other (serialized execution), and that
    modifications from one access are visible to the next.
    """
    import time
    from typing import AsyncGenerator
    from s2auth.server.context import (
        client_context,
        client_node_id,
        context_storage_singleton,
    )
    from s2auth.common.dependencies import inject, provider_overrides, setup

    # Wire the DI system
    setup()

    test_uuid = UUID("00000000-0000-0000-0000-000000000001")
    access_times: list[dict[str, Any]] = []
    lock = threading.Lock()

    # Create storage with pre-populated context
    storage = InMemoryContextStorage()
    storage._client_states[test_uuid] = ClientContext()  # type: ignore[attr-defined]

    # Override providers - async versions for async storage
    def test_client_id() -> UUID:
        return test_uuid

    def test_storage() -> ContextStorage:
        return storage

    @inject
    async def test_client_context(
        cid: UUID = Depends[client_node_id],
        stor: ContextStorage = Depends[context_storage_singleton],
    ) -> AsyncGenerator[ClientContext, None]:
        """Async generator version of client_context for async storage."""
        async for ctx in stor.get_client_context(cid):
            yield ctx

    @inject
    async def access_context(
        thread_id: int,
        delay: float,
        ctx: ClientContext = Depends[client_context],
    ) -> str:
        """Access a context via DI, simulate work, record timing."""
        start_time = time.time()

        # Simulate work while holding the lock
        time.sleep(delay)

        # Modify the context
        ctx.state = ClientState.CONNECTED if ctx.state != ClientState.CONNECTED else ClientState.PAIRED # type: ignore[attr-defined]

        end_time = time.time()

        with lock:
            access_times.append({
                'thread_id': thread_id,
                'start': start_time,
                'end': end_time,
                'state_after': ctx.state
            })
        return f"thread_{thread_id}|"

    def thread_func(thread_id: int, delay: float) -> None:
        """Thread function that runs async code."""
        asyncio.run(access_context(thread_id, delay))

    # Access the same context from multiple threads concurrently
    with provider_overrides({
        client_node_id: test_client_id,
        context_storage_singleton: test_storage,
        client_context: test_client_context,
    }):
        threads = [
            threading.Thread(target=thread_func, args=(1, 0.05)),
            threading.Thread(target=thread_func, args=(2, 0.05)),
            threading.Thread(target=thread_func, args=(3, 0.05))
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
    expected_states = [ClientState.CONNECTED, ClientState.PAIRED, ClientState.CONNECTED]
    actual_states = [t['state_after'] for t in access_times]
    assert actual_states == expected_states, \
        f"Each access should see modifications from previous accesses. Expected {expected_states}, got {actual_states}"

    # Total time should be ~0.15s (3 * 0.05s) if serialized
    total_duration = access_times[-1]['end'] - access_times[0]['start']
    assert total_duration >= 0.14, \
        f"Same context accesses should be serialized (total time ~0.15s), got {total_duration}s"


@pytest.mark.skip_wire
async def test_sync_fine_grained_locking_pairing_attempts():
    """Test fine-grained locking for pairing attempt contexts in sync storage."""
    from uuid import uuid4
    from s2auth.common.model.s2_connect_pairing import NodeIdAlias
    from s2auth.common.hmac import create_pairing_code

    storage = InMemoryContextStorage()

    pairing_id_1 = uuid4()
    pairing_id_2 = uuid4()
    test_pairing_node_id = NodeIdAlias(root="testnodeid123")
    test_token = create_pairing_code()

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
        async def async_work():
            start_time = time.time()
            ctx_gen = storage.get_pairing_attempt_context(pairing_id)
            ctx = await anext(ctx_gen)
            ctx.state = PairingState.INITIATED  # Simulate some modification to ensure lock is held
            time.sleep(delay)
            end_time = time.time()

            with lock:
                access_times.append({
                    'pairing_id': pairing_id,
                    'start': start_time,
                    'end': end_time
                })
            await ctx_gen.aclose()
        asyncio.run(async_work())

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
