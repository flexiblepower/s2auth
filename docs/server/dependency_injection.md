# Dependency Injection

The server uses [`wepositive-di`](https://wepositive-di.readthedocs.io/) for dependency injection, provider overrides, context-manager providers, and typed context storage.

The `s2auth` code defines project-specific providers and context models, such as:

- `AuthenticationContext`
- `PairingAttemptContext`
- `settings`
- `config`
- pairing code and access token providers
- hook registry providers

For provider registration, overrides, setup, and context storage behavior, use the upstream [`wepositive-di` documentation](https://wepositive-di.readthedocs.io/).

## Server-specific contexts

The server stores authentication and pairing state in `wepositive-di` context storage:

- `AuthenticationContext` tracks the paired client, stored node and endpoint descriptions, active access token, pending access token, and one-time connection token.
- `PairingAttemptContext` tracks the active pairing attempt, selected HMAC algorithm, pairing code, and server challenge.

Use distributed context storage for multi-process deployments. See the upstream `wepositive-di` context storage documentation for implementation patterns.

## Server-specific overrides

Server customizations are regular `wepositive-di` provider overrides. Common examples are:

- overriding [server hooks](hooks.md) with `@register_hook()`;
- overriding [pairing code generation](pairing_token_override.md);
- overriding context storage for a distributed deployment;
- overriding `settings` or `config` in tests.

Register production overrides during application startup before calling `setup()`. Tests should prefer scoped `provider_overrides(...)` blocks.
