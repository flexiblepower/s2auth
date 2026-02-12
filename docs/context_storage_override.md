# Context Storage Guide

## Overview

The s2auth server uses dependency injection to manage context storage for client and pairing attempt state. The system provides a **unified `InMemoryContextStorage`** implementation that uses `aiologic.RLock` for synchronization, making it work seamlessly across:

- **Async servers** (FastAPI with Uvicorn): Non-blocking async synchronization
- **Threaded servers** (Flask with Gunicorn): Thread-safe synchronization
- **Hybrid environments**: Multiple threads each with their own event loop

**No configuration changes needed** between deployment types - the same storage works everywhere!

---

## Default Configuration (Works Everywhere!)

The system automatically provides the unified storage:

```python
from s2auth.server.dependencies import inject, Depends
from s2auth.server.context import (
    client_context,
    pairing_attempt_context,
    ClientContext,
    PairingAttemptContext,
)

# Async endpoint (FastAPI) - works automatically
@inject
async def my_async_endpoint(
    client_ctx: ClientContext = Depends[client_context],
    pairing_ctx: PairingAttemptContext = Depends[pairing_attempt_context],
):
    print(f"Client state: {client_ctx.state}")
    client_ctx.state = "authenticated"

# Sync endpoint (Flask) - also works automatically!
# The DI system handles calling the async storage from sync context
@inject
def my_sync_endpoint(
    client_ctx: ClientContext = Depends[client_context],
    pairing_ctx: PairingAttemptContext = Depends[pairing_attempt_context],
):
    print(f"Client state: {client_ctx.state}")
    client_ctx.state = "authenticated"
```

---

## How It Works

### aiologic.RLock: The Secret Sauce

The storage uses `aiologic.RLock` (reentrant lock) which:

- ✅ Works from async tasks (like `asyncio.Lock`)
- ✅ Works from threads (like `threading.Lock`)
- ✅ Works across threads with different event loops
- ✅ Is reentrant (same task/thread can acquire multiple times)
- ✅ Prevents deadlocks in mixed async/thread environments

### DI System Integration

The dependency injection system:
1. Detects that `client_context` and `pairing_attempt_context` are async generators
2. In async contexts: Calls them directly with `await`
3. In sync contexts: Creates an event loop and uses `asyncio.run()`

This means sync Flask endpoints can depend on async providers seamlessly!

---

## Multi-Process Considerations

**Important**: `InMemoryContextStorage` is **single-process only**. Each worker process has its own independent storage instance.

### Implications

```
Worker 1 (PID 1001)
├── Storage Instance A
├── Client ABC → state="authenticated"
└── Client XYZ → state="pending"

Worker 2 (PID 1002)
├── Storage Instance B  (separate from A!)
├── Client ABC → state="default"  (different from Worker 1!)
└── Client DEF → state="active"
```

Requests for the same client may hit different workers with different state.

### Solutions for Shared State

#### Option 1: Use Sticky Sessions (Load Balancer)

Configure your load balancer to route requests from the same client to the same worker:

```nginx
# nginx.conf
upstream app {
    ip_hash;  # Same client IP → same worker
    server localhost:8000;
    server localhost:8001;
    server localhost:8002;
}
```

#### Option 2: Use Distributed Storage (Redis)

Implement a Redis-based storage backend:

```python
import redis
from s2auth.server.dependencies import register_provider
from s2auth.server.context import (
    ContextStorage,
    ClientContext,
    PairingAttemptContext,
    ClientNodeId,
    PairingAttemptId,
)

class RedisContextStorage(ContextStorage):
    """Distributed context storage using Redis."""

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self.redis = redis.from_url(redis_url)

    async def get_client_context(self, client_node_id: ClientNodeId):
        key = f"client:{client_node_id}"
        data = self.redis.get(key)

        if not data:
            raise KeyError(f"No context known for {client_node_id}")

        ctx = ClientContext.model_validate_json(data)
        try:
            yield ctx
        finally:
            # Save changes back to Redis
            self.redis.set(key, ctx.model_dump_json())

    async def get_pairing_attempt_context(
        self, pairing_attempt_id: PairingAttemptId
    ):
        key = f"pairing:{pairing_attempt_id}"
        data = self.redis.get(key)

        if not data:
            raise KeyError(f"No context known for {pairing_attempt_id}")

        ctx = PairingAttemptContext.model_validate_json(data)
        try:
            yield ctx
        finally:
            self.redis.set(key, ctx.model_dump_json())


@register_provider(singleton=True)
def context_storage_singleton() -> RedisContextStorage:
    return RedisContextStorage()
```

Register this before calling `setup()` and it will override the default in-memory storage.

#### Option 3: Use Single Worker

For development or low-traffic scenarios:

```bash
gunicorn app:app --workers 1 --threads 8
```

---

## Testing with Custom Storage

You can override the storage for testing:

```python
import pytest
from uuid import UUID
from s2auth.server.dependencies import provider_overrides, setup
from s2auth.server.context import (
    context_storage_singleton,
    InMemoryContextStorage,
    s2_client_node_id_var,
    ClientContext,
)
from s2auth.common.models import S2NodeId

@pytest.fixture
def test_storage():
    """Create test storage with pre-populated data."""
    storage = InMemoryContextStorage()
    test_uuid = UUID("00000000-0000-0000-0000-000000000001")

    # Pre-populate
    storage._client_states[test_uuid] = ClientContext(state="test_authenticated")
    return storage

def test_my_endpoint(test_storage):
    """Test endpoint with custom storage."""

    def test_storage_provider():
        return test_storage

    with provider_overrides({context_storage_singleton: test_storage_provider}):
        # Your test code here
        # The injected contexts will use test_storage
        pass
```

---

## Context Variable Setup

Both async and sync deployments require setting context variables in middleware:

### FastAPI

```python
from starlette.middleware.base import BaseHTTPMiddleware
from s2auth.server.context import s2_client_node_id_var
from s2auth.common.models import S2NodeId
from uuid import UUID

class ClientContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Extract client ID from request
        client_id = request.headers.get('X-Client-Node-Id')

        if client_id:
            s2_client_node_id_var.set(S2NodeId(UUID(client_id)))

        response = await call_next(request)
        return response
```

### Flask

```python
from flask import request
from s2auth.server.context import s2_client_node_id_var
from s2auth.common.models import S2NodeId
from uuid import UUID

@app.before_request
def set_client_context():
    client_id = request.headers.get('X-Client-Node-Id')

    if client_id:
        s2_client_node_id_var.set(S2NodeId(UUID(client_id)))
```

---

## Summary

| Deployment | Storage Type | Configuration Needed? |
|------------|-------------|----------------------|
| FastAPI + Uvicorn | InMemoryContextStorage | ❌ No - works by default |
| Flask + Gunicorn (threaded) | InMemoryContextStorage | ❌ No - works by default |
| Multi-process (any framework) | InMemoryContextStorage | ⚠️ Consider Redis for shared state |

The unified storage with aiologic.RLock eliminates the need for deployment-specific configuration while maintaining thread safety and async compatibility!
