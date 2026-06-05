# Server Hooks

Server hooks provide extension points for customizing S2 authentication server behavior. Hooks are async callables managed by `HookRegistry`, and custom hooks can use `wepositive-di` dependencies through `@inject` and `Depends[]`.

Each hook has a default implementation in `s2auth.server.hooks`. You can override each hook once with `@register_hook()`.

## Available hooks

### `pairing_attempt_request`

Called during `/requestPairing` after the client description has been stored, an HMAC algorithm has been selected, and read-only context views have been created.

```python
@inject
async def pairing_attempt_request(
    authentication_context: ReadOnlyAuthenticationContext,
    pairing_context: ReadOnlyPairingAttemptContext,
    server_settings: Settings = Depends[settings],
) -> bool:
    ...
```

Return `True` to allow the pairing attempt. Return `False` or raise an `S2ConnectError` subclass to refuse it.

The contexts passed to this hook are frozen `ReadOnlyAuthenticationContext` and `ReadOnlyPairingAttemptContext` instances, so custom hook code cannot accidentally mutate server state.

### `get_server_endpoint_description`

Called during pairing and connection initiation when the server needs to describe its endpoint to a specific client.

```python
@inject
async def get_server_endpoint_description(
    client_node_id: NodeId,
    server_settings: Settings = Depends[settings],
) -> EndpointDescription:
    ...
```

The default implementation returns an `EndpointDescription` using `settings.cem_deployment_type`.

### `get_server_node_description`

Called during pairing and connection initiation when the server needs to describe its S2 node to a specific client.

```python
@inject
async def get_server_node_description(
    client_node_id: NodeId,
    server_settings: Settings = Depends[settings],
) -> NodeDescription:
    ...
```

The default implementation returns a CEM `NodeDescription` using the configured CEM node ID, brand, type, and model name.

### `get_server_connection_initiation_endpoint`

Called after the client proves it knows the pairing code and requests connection details.

```python
@inject
async def get_server_connection_initiation_endpoint(
    authentication_context: ReadOnlyAuthenticationContext,
    server_settings: Settings = Depends[settings],
) -> AnyUrl | None:
    ...
```

The default implementation returns `settings.cem_url`. Return `None` if the server should not provide a connection initiation URL.

## Overriding hooks

Use `@register_hook()` with the hook you want to replace. Hooks must be async functions because server flows run in an async context and async dependencies require async call sites.

```python
from wepositive_di import Depends, inject, register_provider

from s2auth.common.exceptions import S2ConnectError
from s2auth.common.model.s2_connect_pairing import ErrorMessage
from s2auth.server.context import (
    ReadOnlyAuthenticationContext,
    ReadOnlyPairingAttemptContext,
)
from s2auth.server.hooks import pairing_attempt_request, register_hook


class ClientNotAllowed(S2ConnectError):
    error_type = ErrorMessage.NodeNotFound


@register_provider()
async def client_validator() -> ClientValidator:
    return ClientValidator()


@register_hook(pairing_attempt_request)
@inject
async def custom_pairing_request(
    authentication_context: ReadOnlyAuthenticationContext,
    pairing_context: ReadOnlyPairingAttemptContext,
    validator: ClientValidator = Depends[client_validator],
) -> bool:
    if not await validator.is_allowed(authentication_context.client_node_id):
        raise ClientNotAllowed("Client is not allowed")
    return True
```

### Customizing server descriptions

Endpoint and node descriptions are separate hooks, so you can customize either independently.

```python
from wepositive_di import inject

from s2auth.common.model.s2_connect_common import NodeId, Role
from s2auth.common.model.s2_connect_pairing import EndpointDescription, NodeDescription
from s2auth.server.hooks import (
    get_server_endpoint_description,
    get_server_node_description,
    register_hook,
)


@register_hook(get_server_endpoint_description)
@inject
async def custom_endpoint_description(client_node_id: NodeId) -> EndpointDescription:
    return EndpointDescription(deployment="MyDeployment")


@register_hook(get_server_node_description)
@inject
async def custom_node_description(client_node_id: NodeId) -> NodeDescription:
    return NodeDescription(
        id=NodeId(root="my-node-id"),
        brand="MyBrand",
        role=Role.CEM,
        type="MyType",
        modelName="MyModel",
    )
```

## Best practices

1. Register hook overrides during application startup, before calling `setup()`.
2. Decorate hooks that use dependencies with `@inject`.
3. Keep hook functions async.
4. Use specific `S2ConnectError` subclasses when refusing protocol operations.
5. Treat hook contexts as read-only snapshots.
6. Keep each hook focused on one decision or piece of server metadata.

## How hooks work

`HookRegistry` stores a mapping from default hook functions to their active implementation. Server code retrieves and awaits the active hook:

```python
hooks = Depends[hook_registry]
pairing_hook = hooks.get(pairing_attempt_request)
allowed = await pairing_hook(auth_ctx, pairing_ctx)
```

`register_hook(original_hook)` updates the singleton registry by replacing the default implementation for `original_hook` with your custom implementation.
