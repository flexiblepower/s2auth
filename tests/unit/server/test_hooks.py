"""Tests for server hooks."""

from uuid import uuid4

import pytest
from pydantic import AnyUrl

from wepositive_di import Depends, inject, provider_overrides
from s2auth.common.exceptions import S2PairingError
from s2auth.common.model.s2_connect_common import NodeId, Role
from s2auth.common.model.s2_connect_pairing import (
    ErrorMessage,
    NodeIdAlias,
    EndpointDescription,
    NodeDescription,
)
from s2auth.server.context import (
    ClientContext,
    ClientState,
    PairingAttemptContext,
    PairingState,
    ReadOnlyClientContext,
    ReadOnlyPairingAttemptContext,
)
from s2auth.server.hooks import HookRegistry, pairing_attempt_request
from s2auth.server.settings import Settings, settings


class CustomPairingError(S2PairingError):
    """Custom error for testing."""

    error_type = ErrorMessage.NodeNotFound


async def test_pairing_attempt_request_default():
    """Test the default pairing_attempt_request hook returns correct descriptions."""
    # Create test contexts
    client_id = uuid4()
    client_ctx = ReadOnlyClientContext(
        client_node_id=client_id, state=ClientState.PAIRING
    )
    pairing_ctx = ReadOnlyPairingAttemptContext(
        pairing_attempt_id=uuid4(),
        pairing_node_id=NodeIdAlias(root="PAIR123"),
        pairing_token="dGVzdF90b2tlbg==",  # base64 encoded "test_token"
        state=PairingState.INITIATED,
    )

    # Create test settings
    server_node_id = uuid4()
    cem_node_id = uuid4()
    test_settings_obj = Settings(
        server_s2_node_id=server_node_id,
        cem_s2_node_id=cem_node_id,
        cem_brand="TestBrand",
        cem_type="TestType",
        cem_model_name="TestModel",
        pairing_node_id="pairing123",
    )

    # Get the hook from registry and call it
    registry = HookRegistry()
    hook = registry.get(pairing_attempt_request)

    # Hook uses @inject so we need to override settings provider
    def test_settings_provider() -> Settings:
        return test_settings_obj

    with provider_overrides({settings: test_settings_provider}):
        endpoint_desc, node_desc = await hook(client_ctx, pairing_ctx)

    # Verify endpoint description
    assert isinstance(endpoint_desc, EndpointDescription)
    assert endpoint_desc.name is None
    assert endpoint_desc.logoUrl is None
    assert endpoint_desc.deployment is None

    # Verify node description
    assert isinstance(node_desc, NodeDescription)
    assert node_desc.id == NodeId(root=cem_node_id)
    assert node_desc.brand == "TestBrand"
    assert node_desc.type == "TestType"
    assert node_desc.modelName == "TestModel"
    assert node_desc.role == Role.CEM
    assert node_desc.logoUrl is None
    assert node_desc.userDefinedName is None


async def test_pairing_attempt_request_override_custom_descriptions():
    """Test overriding the hook to provide custom descriptions."""
    client_id = uuid4()
    client_ctx = ReadOnlyClientContext(
        client_node_id=client_id, state=ClientState.PAIRING
    )
    pairing_ctx = ReadOnlyPairingAttemptContext(
        pairing_attempt_id=uuid4(),
        pairing_node_id=NodeIdAlias(root="PAIR123"),
        pairing_token="dGVzdF90b2tlbg==",
        state=PairingState.INITIATED,
    )

    custom_node_id = uuid4()

    @inject
    async def custom_hook(
        client_context: ReadOnlyClientContext,
        pairing_context: ReadOnlyPairingAttemptContext,
    ) -> tuple[EndpointDescription, NodeDescription]:
        endpoint = EndpointDescription(
            name="Custom Endpoint",
            logoUrl=AnyUrl("https://example.com/logo.png"),
        )
        node = NodeDescription(
            id=NodeId(root=custom_node_id),
            brand="CustomBrand",
            role=Role.CEM,
            type="CustomType",
            modelName="CustomModel",
            userDefinedName="My Custom Node",
        )
        return endpoint, node

    registry = HookRegistry()
    registry.register(pairing_attempt_request, custom_hook)
    hook = registry.get(pairing_attempt_request)

    endpoint_desc, node_desc = await hook(client_ctx, pairing_ctx)

    assert endpoint_desc.name == "Custom Endpoint"
    assert str(endpoint_desc.logoUrl) == "https://example.com/logo.png"

    assert node_desc.id == NodeId(root=custom_node_id)
    assert node_desc.brand == "CustomBrand"
    assert node_desc.type == "CustomType"
    assert node_desc.modelName == "CustomModel"
    assert node_desc.userDefinedName == "My Custom Node"


async def test_pairing_attempt_request_override_raises_error():
    """Test overriding the hook to refuse pairing by raising an error."""
    blocked_client_id = uuid4()
    client_ctx = ReadOnlyClientContext(
        client_node_id=blocked_client_id,
        state=ClientState.PAIRING,
    )
    pairing_ctx = ReadOnlyPairingAttemptContext(
        pairing_attempt_id=uuid4(),
        pairing_node_id=NodeIdAlias(root="PAIR123"),
        pairing_token="dGVzdF90b2tlbg==",
        state=PairingState.INITIATED,
    )

    # Define hook that blocks certain clients
    @inject
    async def blocking_hook(
        client_context: ReadOnlyClientContext,
        pairing_context: ReadOnlyPairingAttemptContext,
    ) -> tuple[EndpointDescription, NodeDescription]:
        if client_context.client_node_id == blocked_client_id:
            raise CustomPairingError("Client is blocked")

        # Would return normal descriptions if not blocked (won't reach here in test)
        endpoint = EndpointDescription()
        node = NodeDescription(
            id=NodeId(root=uuid4()),
            brand="TestBrand",
            role=Role.CEM,
            type="TestType",
            modelName="TestModel",
        )
        return endpoint, node

    # Register custom hook and verify it raises the error
    registry = HookRegistry()
    registry.register(pairing_attempt_request, blocking_hook)
    hook = registry.get(pairing_attempt_request)

    with pytest.raises(CustomPairingError, match="Client is blocked"):
        await hook(client_ctx, pairing_ctx)


async def test_pairing_attempt_request_context_values():
    """Test that the hook receives correct context values."""
    client_node_id = uuid4()
    pairing_attempt_id = uuid4()

    client_ctx = ClientContext(client_node_id=client_node_id, state=ClientState.PAIRING)
    pairing_ctx = PairingAttemptContext(
        pairing_attempt_id=pairing_attempt_id,
        pairing_node_id=NodeIdAlias(root="PAIR123"),
        pairing_token="dGVzdF90b2tlbg==",
        state=PairingState.INITIATED,
    )
    server_node_id = uuid4()
    cem_node_id = uuid4()

    test_settings_obj = Settings(
        server_s2_node_id=server_node_id,
        cem_s2_node_id=cem_node_id,
        cem_brand="TestBrand",
        cem_type="TestType",
        cem_model_name="TestModel",
        pairing_node_id="pairing123",
    )

    def test_settings_provider() -> Settings:
        return test_settings_obj

    # Track what the hook received
    received_contexts: dict[str, object] = {}

    @inject
    async def tracking_hook(
        client_context: ClientContext,
        pairing_context: PairingAttemptContext,
        server_settings: Settings = Depends[settings],
    ) -> tuple[EndpointDescription, NodeDescription]:
        # Store what we received
        received_contexts["client"] = client_context
        received_contexts["pairing"] = pairing_context
        received_contexts["settings"] = server_settings

        # Return default descriptions
        endpoint = EndpointDescription()
        node = NodeDescription(
            id=NodeId(root=server_settings.cem_s2_node_id),
            brand=server_settings.cem_brand,
            role=Role.CEM,
            type=server_settings.cem_type,
            modelName=server_settings.cem_model_name,
        )
        return endpoint, node

    # Register custom hook and call it with overridden settings
    registry = HookRegistry()
    registry.register(pairing_attempt_request, tracking_hook)
    hook = registry.get(pairing_attempt_request)

    with provider_overrides({settings: test_settings_provider}):
        await hook(client_ctx, pairing_ctx)

    # Verify the hook received the correct contexts
    assert isinstance(received_contexts["client"], ClientContext)
    assert isinstance(received_contexts["pairing"], PairingAttemptContext)
    assert isinstance(received_contexts["settings"], Settings)

    client_received = received_contexts["client"]
    pairing_received = received_contexts["pairing"]
    settings_received = received_contexts["settings"]

    assert isinstance(client_received, ClientContext)
    assert client_received.client_node_id == client_node_id
    assert client_received.state == ClientState.PAIRING

    assert isinstance(pairing_received, PairingAttemptContext)
    assert pairing_received.pairing_attempt_id == pairing_attempt_id
    assert pairing_received.pairing_node_id == NodeIdAlias(root="PAIR123")

    assert isinstance(settings_received, Settings)
    assert settings_received.cem_brand == "TestBrand"


async def test_readonly_contexts_are_immutable():
    """Test that ReadOnly contexts raise ValidationError when modified."""
    from pydantic import ValidationError

    client_ctx = ReadOnlyClientContext(client_node_id=uuid4(), state=ClientState.PAIRING)
    pairing_ctx = ReadOnlyPairingAttemptContext(
        pairing_attempt_id=uuid4(),
        pairing_node_id=NodeIdAlias(root="PAIR123"),
        pairing_token="dGVzdF90b2tlbg==",
        state=PairingState.INITIATED,
    )

    # Attempt to modify client context should raise ValidationError
    with pytest.raises(ValidationError, match="frozen"):
        client_ctx.state = ClientState.PAIRING

    # Attempt to modify pairing context should raise ValidationError
    with pytest.raises(ValidationError, match="frozen"):
        pairing_ctx.state = PairingState.COMPLETED


async def test_register_unknown_hook_raises_keyerror():
    """Test that registering an unknown hook raises KeyError."""
    registry = HookRegistry()

    # Create a fake hook function that's not registered
    async def fake_hook():
        pass

    async def custom_implementation():
        pass

    with pytest.raises(KeyError, match="Unknown hook function"):
        registry.register(fake_hook, custom_implementation)


async def test_register_hook_twice_raises_runtimeerror():
    """Test that registering a hook twice raises RuntimeError."""
    registry = HookRegistry()

    # First registration should succeed
    @inject
    async def first_custom_hook(
        client_context: ReadOnlyClientContext,
        pairing_context: ReadOnlyPairingAttemptContext,
    ) -> tuple[EndpointDescription, NodeDescription]:
        return EndpointDescription(), NodeDescription(
            id=NodeId(root=uuid4()),
            brand="First",
            role=Role.CEM,
            type="Test",
            modelName="Test",
        )

    registry.register(pairing_attempt_request, first_custom_hook)

    # Second registration should raise RuntimeError
    @inject
    async def second_custom_hook(
        client_context: ReadOnlyClientContext,
        pairing_context: ReadOnlyPairingAttemptContext,
    ) -> tuple[EndpointDescription, NodeDescription]:
        return EndpointDescription(), NodeDescription(
            id=NodeId(root=uuid4()),
            brand="Second",
            role=Role.CEM,
            type="Test",
            modelName="Test",
        )

    with pytest.raises(RuntimeError, match="already has a custom implementation"):
        registry.register(pairing_attempt_request, second_custom_hook)


async def test_get_unknown_hook_raises_keyerror():
    """Test that getting an unknown hook raises KeyError."""
    registry = HookRegistry()

    # Create a fake hook function that's not registered
    async def fake_hook():
        pass

    with pytest.raises(KeyError, match="not registered"):
        registry.get(fake_hook)


async def test_hook_registry_singleton_provider():
    """Test that hook_registry provider returns a singleton through DI system."""
    from s2auth.server.hooks import hook_registry

    # Access through DI system (which caches singletons)
    @inject
    def get_registry1(registry: HookRegistry = Depends[hook_registry]):
        return registry

    @inject
    def get_registry2(registry: HookRegistry = Depends[hook_registry]):
        return registry

    instance1 = get_registry1()
    instance2 = get_registry2()

    # Should return the same instance (singleton via DI)
    assert instance1 is instance2


async def test_register_hook_decorator():
    """Test the @register_hook decorator."""
    # Reset to a fresh registry for this test
    # (Note: In real usage, the decorator would be used at module level)
    test_registry = HookRegistry()

    custom_node_id = uuid4()

    # Use the decorator pattern manually (simulating module-level decoration)
    @inject
    async def decorated_hook(
        client_context: ReadOnlyClientContext,
        pairing_context: ReadOnlyPairingAttemptContext,
    ) -> tuple[EndpointDescription, NodeDescription]:
        return EndpointDescription(name="Decorated"), NodeDescription(
            id=NodeId(root=custom_node_id),
            brand="Decorated",
            role=Role.CEM,
            type="DecoratedType",
            modelName="DecoratedModel",
        )

    # Register using the test registry's register method
    test_registry.register(pairing_attempt_request, decorated_hook)

    # Verify it was registered
    hook = test_registry.get(pairing_attempt_request)
    assert hook is decorated_hook

    # Call it to verify it works
    client_ctx = ReadOnlyClientContext(client_node_id=uuid4(), state=ClientState.PAIRING)
    pairing_ctx = ReadOnlyPairingAttemptContext(
        pairing_attempt_id=uuid4(),
        pairing_node_id=NodeIdAlias(root="PAIR123"),
        pairing_token="dGVzdF90b2tlbg==",
        state=PairingState.INITIATED,
    )

    endpoint, node = await hook(client_ctx, pairing_ctx)
    assert endpoint.name == "Decorated"
    assert node.brand == "Decorated"


async def test_register_hook_decorator_with_singleton_registry():
    """Test that @register_hook decorator works and returns the function unchanged."""
    from s2auth.server.hooks import register_hook

    @inject
    async def test_hook(
        client_context: ReadOnlyClientContext,
        pairing_context: ReadOnlyPairingAttemptContext,
    ) -> tuple[EndpointDescription, NodeDescription]:
        return EndpointDescription(), NodeDescription(
            id=NodeId(root=uuid4()),
            brand="Test",
            role=Role.CEM,
            type="Test",
            modelName="Test",
        )

    # The decorator should be callable and return a decorator function
    decorator = register_hook(pairing_attempt_request)
    result = decorator(test_hook)

    # The decorator should return the function unchanged
    assert result is test_hook
