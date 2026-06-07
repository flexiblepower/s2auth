# Dependency Injection

The server uses [`wepositive-di`](https://wepositive-di.readthedocs.io/) for dependency injection, provider overrides, context-manager providers, and typed context storage.

The `s2auth` code defines project-specific providers and context models, such as:

- `AuthenticationContext`
- `PairingAttemptContext`
- `authentication_context`
- `authentication_context_by_pairing_attempt_context`
- `pairing_attempt_context`
- `pairing_attempt_context_by_client_node_id`
- `settings`
- `config`
- pairing code and access token providers
- hook registry providers

For provider registration, overrides, setup, and context storage behavior, use the upstream [`wepositive-di` documentation](https://wepositive-di.readthedocs.io/).

## Server-specific contexts

The server stores authentication and pairing state in `wepositive-di` context storage:

- `AuthenticationContext` tracks the paired client, stored node and endpoint descriptions, active access token, pending access token, and one-time connection token.
- `PairingAttemptContext` tracks the active pairing attempt, selected HMAC algorithm, pairing code, server challenge, and the paired `client_node_id` once it is known.

Use distributed context storage for multi-process deployments. See the upstream `wepositive-di` context storage documentation for implementation patterns.

### Context lookup providers

Most server helpers receive context through `wepositive-di` providers instead of passing context through endpoint call stacks:

- `authentication_context` loads an `AuthenticationContext` from the current `client_node_id` context variable.
- `pairing_attempt_context` loads a `PairingAttemptContext` from the current `pairing_attempt_id` context variable.
- `pairing_attempt_context_by_client_node_id` finds the active pairing attempt for the current client node.
- `authentication_context_by_pairing_attempt_context` is used by pairing endpoints that only have a `pairingAttemptId`. It first loads the `PairingAttemptContext`, reads its `client_node_id`, releases the pairing context lock, and then loads the matching `AuthenticationContext`.

This lets endpoints such as `requestConnectionDetails` and `finalizePairing` work with only a `pairingAttemptId` header while still resolving the matching authentication context safely.

## Server-specific overrides

Server customizations are regular `wepositive-di` provider overrides. Common examples are:

- overriding [server hooks](hooks.md) with `@register_hook()`;
- overriding [pairing code generation](pairing_token_override.md);
- overriding context storage for a distributed deployment;
- overriding `settings` or `config` in tests.

Register production overrides during application startup before calling `setup()`. Tests should prefer scoped `provider_overrides(...)` blocks.

For applications that use hooks, call `s2auth.server.setup(additional_hook_modules=[...])` during startup. It imports the built-in hook module, imports any custom hook modules so their `@register_hook(...)` decorators run, and then initializes `wepositive-di`.

```python
from s2auth.server import setup


setup(additional_hook_modules=["my_app.s2_hooks"])
```

## FastAPI context bridges

The reference server uses small FastAPI dependencies to copy request data into context variables that `wepositive-di` providers can read later. Header/body dependencies set values such as `clientNodeId` and `pairingAttemptId`; `set_request()` stores the current FastAPI `Request` so hooks can depend on a `current_request` provider.

These dependencies are `async def` on purpose. FastAPI runs synchronous dependencies in a threadpool, and context variable writes from those threads do not propagate back to the async request task where `wepositive-di` resolves dependencies.

## Access token provider semantics

`s2auth.common.hmac.generate_access_token` is a value provider: when injected with `Depends[generate_access_token]`, the receiving function gets a newly generated `AccessToken`, not a callable factory. Server functions name this injected value `new_access_token` and use it directly.

When tests need deterministic tokens, override the provider with a function that returns the desired `AccessToken`:

```python
from wepositive_di import provider_overrides

from s2auth.common.hmac import generate_access_token
from s2auth.common.model.s2_connect_common import AccessToken


def fixed_access_token() -> AccessToken:
    return AccessToken(root=b"deterministic-token-deterministic")


with provider_overrides({generate_access_token: fixed_access_token}):
    ...
```
