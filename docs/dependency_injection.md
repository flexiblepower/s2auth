# Dependency Injection

This project uses [`wepositive-di`](https://wepositive-di.readthedocs.io/) for dependency injection, provider overrides, context-manager providers, and typed context storage.

The s2auth-specific code only defines project providers and context models, such as authentication context, pairing attempt context, and pairing token generation. For DI usage, override patterns, setup, and context storage behavior, see the [`wepositive-di` documentation](https://wepositive-di.readthedocs.io/).
