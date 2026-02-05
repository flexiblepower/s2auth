import pytest
from s2auth.server.dependencies import setup, Depends, inject, provider_overrides
from s2auth.server.dependencies.context import (
    client_node_id,
    context_singleton,
    client_context,
    ClientContext,
    ClientNodeId,
)


@pytest.mark.skip_wire
async def test_client_context_with_multiple_clients():
    """Test that client_context returns the correct context for multiple clients."""
    # Create a test context singleton with pre-populated data
    test_contexts: dict[ClientNodeId, ClientContext] = {
        1: ClientContext(state="client_1_state"),
        2: ClientContext(state="client_2_state"),
        3: ClientContext(state="client_3_state"),
    }

    def test_context_singleton() -> dict[ClientNodeId, ClientContext]:
        return test_contexts

    # Override client_node_id to return different values
    def test_client_node_id_1() -> int:
        return 1

    def test_client_node_id_2() -> int:
        return 2

    def test_client_node_id_3() -> int:
        return 3

    @inject
    def get_context(ctx: ClientContext = Depends[client_context]) -> ClientContext:
        return ctx

    setup()

    # Test client 1
    with provider_overrides(
        {
            context_singleton: test_context_singleton,
            client_node_id: test_client_node_id_1,
        }
    ):
        result = get_context()
        assert result.state == "client_1_state"

    # Test client 2
    with provider_overrides(
        {
            context_singleton: test_context_singleton,
            client_node_id: test_client_node_id_2,
        }
    ):
        result = get_context()
        assert result.state == "client_2_state"

    # Test client 3
    with provider_overrides(
        {
            context_singleton: test_context_singleton,
            client_node_id: test_client_node_id_3,
        }
    ):
        result = get_context()
        assert result.state == "client_3_state"


@pytest.mark.skip_wire
def test_context_singleton_is_singleton():
    """Test that context_singleton is instantiated only once and changes persist."""

    @inject
    def get_singleton(
        ctx_dict: dict[ClientNodeId, ClientContext] = Depends[context_singleton],
    ) -> dict[ClientNodeId, ClientContext]:
        return ctx_dict

    @inject
    def modify_singleton(
        ctx_dict: dict[ClientNodeId, ClientContext] = Depends[context_singleton],
    ) -> None:
        ctx_dict[999] = ClientContext(state="modified_state")

    setup()

    # Get the singleton
    singleton1 = get_singleton()
    initial_id = id(singleton1)

    # Modify the singleton
    modify_singleton()

    # Get the singleton again
    singleton2 = get_singleton()

    # Verify it's the same object
    assert id(singleton2) == initial_id, "Singleton should be the same instance"

    # Verify the modification persisted
    assert 999 in singleton2, "Modification should persist in singleton"
    assert singleton2[999].state == "modified_state", (
        "Modified state should be preserved"
    )


@pytest.mark.skip_wire
def test_client_context_returns_existing_context():
    """Test that client_context returns existing context when client_node_id already exists."""
    # Create a test context singleton with pre-populated data
    test_contexts: dict[ClientNodeId, ClientContext] = {
        42: ClientContext(state="existing_state"),
    }

    def test_context_singleton() -> dict[ClientNodeId, ClientContext]:
        return test_contexts

    def test_client_node_id() -> int:
        return 42

    @inject
    def get_context(ctx: ClientContext = Depends[client_context]) -> ClientContext:
        return ctx

    setup()

    # Test that existing context is returned
    with provider_overrides(
        {
            context_singleton: test_context_singleton,
            client_node_id: test_client_node_id,
        }
    ):
        result = get_context()
        assert result.state == "existing_state"

        # Verify the context is the same object from the dictionary
        assert result is test_contexts[42]


@pytest.mark.skip_wire
def test_client_context_creates_then_returns_context():
    """Test that client_context creates a new context and then returns the same context on subsequent calls."""
    # Create an empty test context singleton
    test_contexts: dict[ClientNodeId, ClientContext] = {}

    def test_context_singleton() -> dict[ClientNodeId, ClientContext]:
        return test_contexts

    def test_client_node_id() -> int:
        return 99

    @inject
    def get_context(ctx: ClientContext = Depends[client_context]) -> ClientContext:
        return ctx

    setup()

    with provider_overrides(
        {
            context_singleton: test_context_singleton,
            client_node_id: test_client_node_id,
        }
    ):
        # First call - should create a new context
        result1 = get_context()
        assert result1.state == "default"
        assert 99 in test_contexts

        # Second call - should return the existing context (line 32)
        result2 = get_context()
        assert result2.state == "default"
        assert result2 is result1  # Same object
        assert result2 is test_contexts[99]  # Same object from dictionary
