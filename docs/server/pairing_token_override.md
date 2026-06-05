# Pairing Code Generation

This guide explains how to customize pairing code generation in an S2 authentication server.

The server generates pairing codes with `s2auth.common.hmac.create_pairing_code`. It is registered as a `wepositive-di` provider, so applications can override it with the standard provider override mechanisms documented at <https://wepositive-di.readthedocs.io/>.

## Overview

You may want to override pairing code generation for:

- predictable test scenarios;
- longer or differently formatted codes;
- integration with an external reservation or display system;
- embedding metadata that your own deployment understands.

## Default behavior

The default provider is:

```python
@register_provider()
def create_pairing_code(s2_node_id: str | None = None, length: int = 9) -> PairingToken:
    if length < 9:
        raise ValueError("The pairing token needs to be at least 9 bytes.")

    token_str = "".join(random.choice(CHARS) for _ in range(length))

    if s2_node_id:
        return f"{s2_node_id}-{token_str}"
    return token_str
```

The generated token is alphanumeric. If `s2_node_id` is provided, the returned pairing code is `[pairing S2 node ID]-[pairing token]`.

## Override example

```python
import secrets
import string

from wepositive_di import override_provider

from s2auth.common.hmac import PairingToken, create_pairing_code


@override_provider(create_pairing_code)
def custom_pairing_code(
    s2_node_id: str | None = None,
    length: int = 16,
) -> PairingToken:
    if length < 9:
        raise ValueError("The pairing token needs to be at least 9 bytes.")

    alphabet = string.ascii_letters + string.digits
    token = "".join(secrets.choice(alphabet) for _ in range(length))
    if s2_node_id:
        return f"{s2_node_id}-{token}"
    return token
```

## Common use cases

### Static code for tests

```python
from wepositive_di import override_provider

from s2auth.common.hmac import PairingToken, create_pairing_code


@override_provider(create_pairing_code)
def static_pairing_code(
    s2_node_id: str | None = None,
    length: int = 9,
) -> PairingToken:
    token = "testtoken"
    if s2_node_id:
        return f"{s2_node_id}-{token}"
    return token
```

### External code source

```python
import requests
from wepositive_di import override_provider

from s2auth.common.hmac import PairingToken, create_pairing_code


@override_provider(create_pairing_code)
def external_pairing_code(
    s2_node_id: str | None = None,
    length: int = 9,
) -> PairingToken:
    response = requests.post(
        "https://token-service.example.com/generate",
        json={"s2_node_id": s2_node_id, "length": length},
        timeout=5,
    )
    response.raise_for_status()
    return response.json()["token"]
```

## Requirements

Your override must be compatible with the original provider signature:

```python
def create_pairing_code(s2_node_id: str | None = None, length: int = 9) -> PairingToken:
    ...
```

The current `PairingToken` type accepts strings with at least four characters matching `^[A-Za-z0-9+/]{4,}={0,2}$`. The default implementation also enforces a minimum generated token length of 9 characters.

For production implementations:

1. Use a cryptographically strong random source or a trusted external code source.
2. Keep generated codes unique enough to prevent collisions.
3. Avoid static codes outside tests.
4. Validate and surface external service failures explicitly.

## See also

- [Dependency Injection](dependency_injection.md)
- [`wepositive-di` documentation](https://wepositive-di.readthedocs.io/)
