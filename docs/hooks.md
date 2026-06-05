# Server Hooks

Server hooks provide extension points for customizing the behavior of the S2 authentication server. Each hook is managed by a `HookRegistry` that stores default implementations which can be overridden by custom code.

## Overview

Hooks are functions that:
- Have default implementations in `s2auth.server.hooks`
- Are registered in a singleton `HookRegistry`
- Can be overridden using the `@register_hook()` decorator
- Can use `@inject` to declare their own dependencies via `Depends[]`
- Receive context and configuration as parameters
- Can raise `S2ConnectError` exceptions to refuse operations

Each hook can only be overridden **once** - attempting to register a second override will raise a `RuntimeError`.

## Available Hooks

### `pairing_attempt_request`

**Purpose:** Called when a pairing request is received from a client. It decides whether the pairing attempt is allowed. Server endpoint and node descriptions are produced by separate hooks.

**Signature:**
```python
@inject
async def pairing_attempt_request(
    authentication_context: ReadOnlyAuthenticationContext,
    pairing_context: ReadOnlyPairingAttemptContext,
    # ... custom dependencies via Depends[] ...
) -> bool
```

**Parameters:**
- `authentication_context`: [`ReadOnlyAuthenticationContext`](../src/s2auth/server/context.py) - Read-only view of the authentication context. Attempting to modify will raise a `ValidationError`.
- `pairing_context`: [`ReadOnlyPairingAttemptContext`](../src/s2auth/server/context.py) - Read-only view of the pairing attempt context. Attempting to modify will raise a `ValidationError`.
- Additional dependencies can be declared using `Depends[]` (e.g., `Settings`, custom validators, etc.)

**Returns:**
`True` to allow the pairing attempt. Returning `False` refuses the attempt.

**Raises:**
- `S2ConnectError` (or subclasses): To refuse the pairing attempt. The error information will be returned to the client.

**Default Implementation:**
The default hook returns `True`.

**Important:** Context objects are read-only (frozen) to prevent accidental modification. You can read their fields but any attempt to modify them will raise a `ValidationError`.

### `get_server_endpoint_description`

**Purpose:** Called when the server needs its S2 endpoint description during pairing and connection initiation.

**Signature:**
```python
@inject
async def get_server_endpoint_description(
    client_node_id: NodeId,
    # ... custom dependencies via Depends[] ...
) -> EndpointDescription
```

**Parameters:**
- `client_node_id`: Node ID of the client for which the server endpoint description is requested.
- Additional dependencies can be declared using `Depends[]`.

**Returns:**
`EndpointDescription` for the server.

**Default Implementation:**
The default hook uses `Settings = Depends[settings]` and returns an endpoint description from server configuration.

### `get_server_node_description`

**Purpose:** Called when the server needs its S2 node description during pairing and connection initiation.

**Signature:**
```python
@inject
async def get_server_node_description(
    client_node_id: NodeId,
    # ... custom dependencies via Depends[] ...
) -> NodeDescription
```

**Parameters:**
- `client_node_id`: Node ID of the client for which the server node description is requested.
- Additional dependencies can be declared using `Depends[]`.

**Returns:**
`NodeDescription` for the server.

**Default Implementation:**
The default hook uses `Settings = Depends[settings]` and returns the server node description from configuration.

### `get_server_connection_initiation_endpoint`

**Purpose:** Called after the pairing challenge response has been verified, when returning connection details to the client.

**Signature:**
```python
@inject
async def get_server_connection_initiation_endpoint(
    authentication_context: ReadOnlyAuthenticationContext,
    # ... custom dependencies via Depends[] ...
) -> AnyUrl | None
```

**Parameters:**
- `authentication_context`: Read-only view of the authentication context.
- Additional dependencies can be declared using `Depends[]`.

**Returns:**
The URL the client should use to initiate the S2 connection, or `None`.

**Default Implementation:**
The default hook uses `Settings = Depends[settings]` and returns `server_settings.cem_url`.

## How to Override Hooks

To override a hook, use the `@register_hook()` decorator with a reference to the original hook function:

```python
from s2auth.server.hooks import pairing_attempt_request, register_hook
from wepositive_di import Depends, inject
from s2auth.common.exceptions import S2ConnectError
from s2auth.common.model.s2_connect_pairing import ErrorMessage
from s2auth.server.context import ReadOnlyAuthenticationContext, ReadOnlyPairingAttemptContext
from s2auth.server.settings import Settings, settings

class ClientNotAllowed(S2ConnectError):
    """Custom error for blocked clients."""
    error_type = ErrorMessage.NodeNotFound

@register_hook(pairing_attempt_request)
@inject
async def custom_pairing_request(
    authentication_context: ReadOnlyAuthenticationContext,
    pairing_context: ReadOnlyPairingAttemptContext,
    server_settings: Settings = Depends[settings],
) -> bool:
    """Custom pairing hook with validation."""
    # Custom validation
    if authentication_context.client_node_id in BLOCKED_CLIENTS:
        raise ClientNotAllowed("Client is not allowed")

    return True
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
    authentication_context: ReadOnlyAuthenticationContext,
    pairing_context: ReadOnlyPairingAttemptContext,
    validator: ClientValidator = Depends[my_client_validator],  # Different dependency!
) -> bool:
    """Hook that uses a custom validator service instead of settings."""
    # Use your custom service
    if not await validator.is_allowed(authentication_context.client_node_id):
        raise ClientNotAllowed("Client validation failed")

    return True
```

### Customizing Server Descriptions

Endpoint and node descriptions are customized with their own hooks:

```python
from s2auth.common.model.s2_connect_common import NodeId, Role
from s2auth.common.model.s2_connect_pairing import EndpointDescription, NodeDescription
from s2auth.server.hooks import (
    get_server_endpoint_description,
    get_server_node_description,
    register_hook,
)
from wepositive_di import inject

@register_hook(get_server_endpoint_description)
@inject
async def custom_endpoint_description(
    client_node_id: NodeId,
) -> EndpointDescription:
    return EndpointDescription(deployment="MyDeployment")

@register_hook(get_server_node_description)
@inject
async def custom_node_description(
    client_node_id: NodeId,
) -> NodeDescription:
    return NodeDescription(
        id=NodeId(root="my-node-id"),
        brand="MyBrand",
        role=Role.CEM,
        type="MyType",
        modelName="MyModel",
    )
```

## Best Practices

1. **Use `@inject` decorator**: Always decorate custom hooks with `@inject` so they can use dependency injection.

2. **Register early**: Call `@register_hook()` during application startup, before calling `setup()`.

3. **Single override only**: Each hook can only be overridden once. Attempting to register a second time raises `RuntimeError`.

4. **Use appropriate error types**: When refusing pairing, use or create appropriate `S2ConnectError` subclasses with correct `error_type` values.

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
allowed = await pairing_hook(auth_ctx, pairing_ctx)  # Call with args
```
