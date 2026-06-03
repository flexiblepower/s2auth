# Server Hooks

Server hooks provide extension points for customizing the behavior of the S2 authentication server. Each hook is managed by a `HookRegistry` that stores default implementations which can be overridden by custom code.

## Overview

Hooks are functions that:
- Have default implementations in `s2auth.server.hooks`
- Are registered in a singleton `HookRegistry`
- Can be overridden using the `@register_hook()` decorator
- Can use `@inject` to declare their own dependencies via `Depends[]`
- Receive context and configuration as parameters
- Can raise `S2PairingError` exceptions to refuse operations

Each hook can only be overridden **once** - attempting to register a second override will raise a `RuntimeError`.

## Available Hooks

### `pairing_attempt_request`

**Purpose:** Called when a pairing request is received from a client. Generates the server's S2 endpoint and node descriptions.

**Signature:**
```python
@inject
async def pairing_attempt_request(
    client_context: ReadOnlyClientContext,
    pairing_context: ReadOnlyPairingAttemptContext,
    # ... custom dependencies via Depends[] ...
) -> tuple[S2EndpointDescription, S2NodeDescription]
```

**Parameters:**
- `client_context`: [`ReadOnlyClientContext`](../src/s2auth/server/context.py) - Read-only view of the client's context. Attempting to modify will raise a `ValidationError`.
- `pairing_context`: [`ReadOnlyPairingAttemptContext`](../src/s2auth/server/context.py) - Read-only view of the pairing attempt context. Attempting to modify will raise a `ValidationError`.
- Additional dependencies can be declared using `Depends[]` (e.g., `Settings`, custom validators, etc.)

**Returns:**
A tuple containing:
1. `S2EndpointDescription`: Description of the server endpoint
2. `S2NodeDescription`: Description of the server S2 node

**Raises:**
- `S2PairingError` (or subclasses): To refuse the pairing attempt. The error information will be returned to the client.

**Default Implementation:**
The default hook uses `Settings = Depends[settings]` and returns basic server descriptions from configuration.

**Important:** Context objects are read-only (frozen) to prevent accidental modification. You can read their fields but any attempt to modify them will raise a `ValidationError`.

## How to Override Hooks

To override a hook, use the `@register_hook()` decorator with a reference to the original hook function:

```python
from s2auth.server.hooks import pairing_attempt_request, register_hook
from wepositive_di import Depends, inject
from s2auth.common.exceptions import S2PairingError
from s2auth.common.model.s2_over_ip_pairing import ErrorMessage
from s2auth.server.context import ReadOnlyClientContext, ReadOnlyPairingAttemptContext
from s2auth.server.settings import Settings, settings

class ClientNotAllowed(S2PairingError):
    """Custom error for blocked clients."""
    error_type = ErrorMessage.S2NodeNotFound

@register_hook(pairing_attempt_request)
@inject
async def custom_pairing_request(
    client_context: ReadOnlyClientContext,
    pairing_context: ReadOnlyPairingAttemptContext,
    server_settings: Settings = Depends[settings],
) -> tuple[S2EndpointDescription, S2NodeDescription]:
    """Custom pairing hook with validation and custom descriptions."""
    # Custom validation
    if client_context.client_node_id in BLOCKED_CLIENTS:
        raise ClientNotAllowed("Client is not allowed")

    # Custom descriptions
    endpoint = S2EndpointDescription(name="My System")
    node = S2NodeDescription(
        id=S2NodeId(root=server_settings.cem_s2_node_id),
        brand="MyBrand",
        role=S2Role.CEM,
        type="MyType",
        modelName="MyModel",
    )
    return endpoint, node
```

### Using Different Dependencies

Your custom hook can declare **different dependencies** than the default implementation:

```python
from s2auth.server.hooks import pairing_attempt_request, register_hook
from wepositive_di import Depends, inject, register_provider

# Your custom service
@register_provider()
async def my_client_validator() -> ClientValidator:
    return ClientValidator()

@register_hook(pairing_attempt_request)
@inject
async def custom_pairing_with_validator(
    client_context: ReadOnlyClientContext,
    pairing_context: ReadOnlyPairingAttemptContext,
    validator: ClientValidator = Depends[my_client_validator],  # Different dependency!
) -> tuple[S2EndpointDescription, S2NodeDescription]:
    """Hook that uses a custom validator service instead of settings."""
    # Use your custom service
    if not await validator.is_allowed(client_context.client_node_id):
        raise ClientNotAllowed("Client validation failed")

    # Return custom descriptions
    ...
```

## Best Practices

1. **Use `@inject` decorator**: Always decorate custom hooks with `@inject` so they can use dependency injection.

2. **Register early**: Call `@register_hook()` during application startup, before calling `setup()`.

3. **Single override only**: Each hook can only be overridden once. Attempting to register a second time raises `RuntimeError`.

4. **Use appropriate error types**: When refusing pairing, use or create appropriate `S2PairingError` subclasses with correct `error_type` values.

5. **Keep hooks focused**: Each hook should have a single responsibility.

6. **Handle async properly**: All hooks are async functions - ensure you use `await` when calling async dependencies.

7. **Don't modify contexts**: Hooks receive context objects but should not modify them unless specifically documented to do so.

## How Hooks Work

The hook system uses a singleton `HookRegistry`:

1. **Default registration**: Default hook implementations are registered when `HookRegistry` is instantiated
2. **Custom registration**: Use `@register_hook(original_hook)` to override with custom implementation
3. **Retrieval**: Server code calls `registry.get(hook)` to get the current implementation (default or custom)
4. **Execution**: The hook function is called with its arguments; `@inject` handles dependency resolution

```python
# In server code (e.g., pairing.py)
hooks = Depends[hook_registry]  # Get the singleton registry
pairing_hook = hooks.get(pairing_attempt_request)  # Get current implementation
result = await pairing_hook(client_ctx, pairing_ctx)  # Call with args
```
