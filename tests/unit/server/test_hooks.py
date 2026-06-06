"""Tests for server hooks."""

from uuid import uuid4

import pytest
from pydantic import AnyUrl

from wepositive_di import Depends, inject, provider_overrides
from s2auth.common.exceptions import S2ConnectError
from s2auth.common.model.s2_connect_common import Deployment, NodeId, Role
from s2auth.common.model.s2_connect_pairing import (
    ErrorMessage,
    NodeIdAlias,
    EndpointDescription,
    NodeDescription,
)
from s2auth.server.context import (
    AuthenticationContext,
    ClientState,
    PairingAttemptContext,
    PairingState,
    ReadOnlyAuthenticationContext,
    ReadOnlyPairingAttemptContext,
)
from s2auth.server.hooks import (
    HookRegistry,
    get_server_connection_initiation_endpoint,
    get_server_endpoint_description,
    get_server_node_description,
    hook_registry,
    pairing_attempt_request,
    register_hook,
)
from s2auth.server.settings import Settings, settings


class CustomPairingError(S2ConnectError):
    """Custom error for testing."""

    error_type = ErrorMessage.NodeNotFound


async def test_pairing_attempt_request_default():
    """Test the default pairing_attempt_request hook allows pairing."""
    # Create test contexts
    client_id = uuid4()
    client_ctx = ReadOnlyAuthenticationContext(
        client_node_id=client_id, state=ClientState.PAIRING
    )
    pairing_ctx = ReadOnlyPairingAttemptContext(
        pairing_attempt_id=uuid4(),
        pairing_node_id=NodeIdAlias(root="PAIR123"),
        pairing_token="dGVzdF90b2tlbg==",  # base64 encoded "test_token"
        state=PairingState.INITIATED,
    )

    # Get the hook from registry and call it
    registry = HookRegistry()
    hook = registry.get(pairing_attempt_request)

    test_settings_obj = Settings(
        server_s2_node_id=uuid4(),
        cem_s2_node_id=uuid4(),
        cem_brand="TestBrand",
        cem_type="TestType",
        cem_model_name="TestModel",
        pairing_node_id="pairing123",
    )

    def test_settings_provider() -> Settings:
        return test_settings_obj

    with provider_overrides({settings: test_settings_provider}):
        assert await hook(client_ctx, pairing_ctx) is True


async def test_connection_initiation_endpoint_hook_default():
    """Test the default connection initiation endpoint hook returns cem_url."""
    client_ctx = ReadOnlyAuthenticationContext(
        client_node_id=uuid4(), state=ClientState.PAIRING
    )
    test_settings_obj = Settings(
        server_s2_node_id=uuid4(),
        cem_s2_node_id=uuid4(),
        cem_brand="TestBrand",
        cem_type="TestType",
        cem_model_name="TestModel",
        pairing_node_id="pairing123",
        cem_url=AnyUrl("https://cem.example.com/connection/"),
    )

    def test_settings_provider() -> Settings:
        return test_settings_obj

    registry = HookRegistry()
    hook = registry.get(get_server_connection_initiation_endpoint)

    with provider_overrides({settings: test_settings_provider}):
        assert await hook(client_ctx) == test_settings_obj.cem_url


async def test_server_description_hooks_default():
    """Test the default server description hooks return descriptions from settings."""
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

    registry = HookRegistry()
    endpoint_hook = registry.get(get_server_endpoint_description)
    node_hook = registry.get(get_server_node_description)

    def test_settings_provider() -> Settings:
        return test_settings_obj

    with provider_overrides({settings: test_settings_provider}):
        endpoint_desc = await endpoint_hook(NodeId(root=uuid4()))
        node_desc = await node_hook(NodeId(root=uuid4()))

    assert isinstance(endpoint_desc, EndpointDescription)
    assert endpoint_desc.name is None
    assert endpoint_desc.logoUrl is None
    assert endpoint_desc.deployment == Deployment.WAN

    assert isinstance(node_desc, NodeDescription)
    assert node_desc.id == NodeId(root=cem_node_id)
    assert node_desc.brand == "TestBrand"
    assert node_desc.type == "TestType"
    assert node_desc.modelName == "TestModel"
    assert node_desc.role == Role.CEM
    assert node_desc.logoUrl is None
    assert node_desc.userDefinedName is None


async def test_description_hooks_override_custom_descriptions():
    """Test overriding description hooks to provide custom descriptions."""
    client_id = uuid4()
    custom_node_id = uuid4()

    @inject
    async def custom_endpoint_hook(client_node_id: NodeId) -> EndpointDescription:
        assert client_node_id == NodeId(root=client_id)
        return EndpointDescription(
            name="Custom Endpoint",
            logoUrl=AnyUrl("https://example.com/logo.png"),
        )

    @inject
    async def custom_node_hook(client_node_id: NodeId) -> NodeDescription:
        assert client_node_id == NodeId(root=client_id)
        return NodeDescription(
            id=NodeId(root=custom_node_id),
            brand="CustomBrand",
            role=Role.CEM,
            type="CustomType",
            modelName="CustomModel",
            userDefinedName="My Custom Node",
        )

    registry = HookRegistry()
    registry.register(get_server_endpoint_description, custom_endpoint_hook)
    registry.register(get_server_node_description, custom_node_hook)
    endpoint_hook = registry.get(get_server_endpoint_description)
    node_hook = registry.get(get_server_node_description)

    endpoint_desc = await endpoint_hook(NodeId(root=client_id))
    node_desc = await node_hook(NodeId(root=client_id))

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
    client_ctx = ReadOnlyAuthenticationContext(
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
        authentication_context: ReadOnlyAuthenticationContext,
        pairing_context: ReadOnlyPairingAttemptContext,
    ) -> bool:
        if authentication_context.client_node_id == blocked_client_id:
            raise CustomPairingError("Client is blocked")

        return True

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

    client_ctx = AuthenticationContext(client_node_id=client_node_id, state=ClientState.PAIRING)
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
        authentication_context: AuthenticationContext,
        pairing_context: PairingAttemptContext,
        server_settings: Settings = Depends[settings],
    ) -> bool:
        # Store what we received
        received_contexts["client"] = authentication_context
        received_contexts["pairing"] = pairing_context
        received_contexts["settings"] = server_settings

        return True

    # Register custom hook and call it with overridden settings
    registry = HookRegistry()
    registry.register(pairing_attempt_request, tracking_hook)
    hook = registry.get(pairing_attempt_request)

    with provider_overrides({settings: test_settings_provider}):
        await hook(client_ctx, pairing_ctx)

    # Verify the hook received the correct contexts
    assert isinstance(received_contexts["client"], AuthenticationContext)
    assert isinstance(received_contexts["pairing"], PairingAttemptContext)
    assert isinstance(received_contexts["settings"], Settings)

    client_received = received_contexts["client"]
    pairing_received = received_contexts["pairing"]
    settings_received = received_contexts["settings"]

    assert isinstance(client_received, AuthenticationContext)
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

    client_ctx = ReadOnlyAuthenticationContext(client_node_id=uuid4(), state=ClientState.PAIRING)
    pairing_ctx = ReadOnlyPairingAttemptContext(
        pairing_attempt_id=uuid4(),
        pairing_node_id=NodeIdAlias(root="PAIR123"),
        pairing_token="dGVzdF90b2tlbg==",
        state=PairingState.INITIATED,
    )

    # Attempt to modify authentication context should raise ValidationError
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
        authentication_context: ReadOnlyAuthenticationContext,
        pairing_context: ReadOnlyPairingAttemptContext,
    ) -> bool:
        return True

    registry.register(pairing_attempt_request, first_custom_hook)

    # Second registration should raise RuntimeError
    @inject
    async def second_custom_hook(
        authentication_context: ReadOnlyAuthenticationContext,
        pairing_context: ReadOnlyPairingAttemptContext,
    ) -> bool:
        return True

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
        authentication_context: ReadOnlyAuthenticationContext,
        pairing_context: ReadOnlyPairingAttemptContext,
    ) -> bool:
        return authentication_context.client_node_id == custom_node_id

    # Register using the test registry's register method
    test_registry.register(pairing_attempt_request, decorated_hook)

    # Verify it was registered
    hook = test_registry.get(pairing_attempt_request)
    assert hook is decorated_hook

    # Call it to verify it works
    client_ctx = ReadOnlyAuthenticationContext(client_node_id=custom_node_id, state=ClientState.PAIRING)
    pairing_ctx = ReadOnlyPairingAttemptContext(
        pairing_attempt_id=uuid4(),
        pairing_node_id=NodeIdAlias(root="PAIR123"),
        pairing_token="dGVzdF90b2tlbg==",
        state=PairingState.INITIATED,
    )

    assert await hook(client_ctx, pairing_ctx) is True


async def test_register_hook_decorator_with_singleton_registry():
    """Test that @register_hook decorator works and returns the function unchanged."""
    from s2auth.server.hooks import register_hook

    @inject
    async def test_hook(
        authentication_context: ReadOnlyAuthenticationContext,
        pairing_context: ReadOnlyPairingAttemptContext,
    ) -> bool:
        return True

    # The decorator should be callable and return a decorator function
    decorator = register_hook(pairing_attempt_request)
    result = decorator(test_hook)

    # The decorator should return the function unchanged
    assert result is test_hook


async def test_register_hook_decorator_registers_hook_in_resolved_registry() -> None:
    test_registry = HookRegistry()

    def test_hook_registry() -> HookRegistry:
        return test_registry

    with provider_overrides({hook_registry: test_hook_registry}):

        @register_hook(get_server_connection_initiation_endpoint)
        async def custom_connection_endpoint(
            authentication_context: ReadOnlyAuthenticationContext,
        ) -> AnyUrl:
            _ = authentication_context
            return AnyUrl("https://example.com/connection/")

        @inject
        def get_registered_hook(
            registry: HookRegistry = Depends[hook_registry],
        ):
            return registry.get(get_server_connection_initiation_endpoint)

        assert get_registered_hook() is custom_connection_endpoint
