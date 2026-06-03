# Overriding Pairing Token Generation

This guide explains how to customize the pairing token generation in your S2 authentication implementation.

## Overview

By default, the S2 server generates random pairing tokens using a secure random generator with a default length of 9 bytes (resulting in a 12+ character base64-encoded string). However, you may want to override this behavior for various reasons:

- **Testing**: Use a static token for predictable test scenarios
- **Custom Length**: Use a different default token length
- **Custom Algorithm**: Implement your own token generation logic
- **Integration**: Generate tokens from an external system

The `create_pairing_token` function from `s2auth.common.hmac` is registered as a dependency provider and can be overridden using any of the standard dependency injection override methods.

## Default Behavior

The default implementation in `src/s2auth/common/hmac.py`:

```python
@register_provider()
def create_pairing_token(length: int = 9) -> PairingToken:
    """Generate a random pairing token."""
    if length < 9:
        raise ValueError("The pairing token needs to be at least 9 bytes.")
    token = secrets.token_bytes(length)
    return b64encode(token).decode("utf-8")
```

## How to Override

The `create_pairing_token` provider can be overridden using any of the four dependency injection methods. See **[Dependency Override Guide](./dependency_overrides.md)** for complete details on all methods.

### Example: Using the Decorator (Recommended)

```python
from s2auth.common.hmac import create_pairing_token, PairingToken

@override_provider(create_pairing_token)
def create_pairing_token(length: int = 16) -> PairingToken:
    """Custom token generator with different default length."""
    import secrets
    from base64 import b64encode

    if length < 9:
        raise ValueError("The pairing token needs to be at least 9 bytes.")
    token = secrets.token_bytes(length)
    return b64encode(token).decode("utf-8")

```

For other override methods (setup(), function call, context manager), see the [Dependency Override Guide](./dependency_overrides.md).

## Common Use Cases

### 1. Static Token for Testing

For predictable tests, use a static token:

```python
from wepositive_di import override_provider
from s2auth.common.hmac import create_pairing_token, PairingToken

@override_provider(create_pairing_token)
def create_pairing_token(length: int = 9) -> PairingToken:
    """Returns a static token for testing."""
    return "dGVzdF90b2tlbl8xMjM0NQ=="
```

### 2. Custom Token Length

Use longer tokens for increased security:

```python
from wepositive_di import override_provider
from s2auth.common.hmac import create_pairing_token, PairingToken

@override_provider(create_pairing_token)
def create_pairing_token(length: int = 32) -> PairingToken:
    """Generates 32-byte tokens by default (43+ chars base64)."""
    import secrets
    from base64 import b64encode

    if length < 9:
        raise ValueError("The pairing token needs to be at least 9 bytes.")
    token = secrets.token_bytes(length)
    return b64encode(token).decode("utf-8")
```

### 3. External Token Source

Fetch tokens from an external service or database:

```python
from wepositive_di import override_provider
from s2auth.common.hmac import create_pairing_token, PairingToken

@override_provider(create_pairing_token)
def create_pairing_token(length: int = 9) -> PairingToken:
    """Fetches tokens from external service."""
    import requests
    response = requests.post("https://token-service.example.com/generate")
    return response.json()["token"]
```

### 4. Token with Metadata Encoding

Encode additional metadata in the token:

```python
from wepositive_di import override_provider
from s2auth.common.hmac import create_pairing_token, PairingToken
import secrets
import json
from base64 import b64encode
from datetime import datetime, UTC

@override_provider(create_pairing_token)
def create_pairing_token(length: int = 9) -> PairingToken:
    """Generates tokens with embedded timestamp."""
    token_data = {
        "token": secrets.token_bytes(length).hex(),
        "created_at": datetime.now(UTC).isoformat(),
    }
    json_str = json.dumps(token_data)
    return b64encode(json_str.encode()).decode("utf-8")
```

## Important Notes

### Function Signature

Your override function **must have the same signature** as the original:

```python
def create_pairing_token(length: int = 9) -> PairingToken:
    ...
```

- **Parameter**: `length: int` with default value (can be changed)
- **Return type**: `PairingToken` (base64-encoded string)

The `length` parameter is optional in calls, but your implementation must accept it even if you ignore it (e.g., for static tokens).

### Token Format Requirements

Pairing tokens must meet these requirements:
- **Minimum length**: 12 characters (after base64 encoding)
- **Format**: Base64-encoded string (A-Za-z0-9+/=)
- **Pattern**: `^[A-Za-z0-9+/]{12,}={0,2}$`

The default implementation enforces a minimum of 9 bytes (12 chars base64), but your custom implementation must also respect these constraints.

### Security Considerations

When implementing custom token generators:

1. **Randomness**: Use cryptographically secure random sources (e.g., `secrets` module)
2. **Uniqueness**: Ensure tokens are sufficiently unique to prevent collisions
3. **Length**: Longer tokens provide better security (default 9 bytes is minimum)
4. **Testing Tokens**: Never use static tokens in production
5. **External Sources**: Validate and sanitize tokens from external services

## See Also

- **[Dependency Override Guide](./dependency_overrides.md)** - Complete guide to all four override methods
- **[Context Storage Override](./context_storage_override.md)** - Overriding context storage for multi-process deployments
- [`src/s2auth/common/hmac.py`](../src/s2auth/common/hmac.py) - Default token generation implementation
