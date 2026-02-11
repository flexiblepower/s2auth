# Context Storage Override Guide for Synchronous Deployments

## Overview

The s2auth server uses dependency injection to manage context storage for client and pairing attempt state. By default, the system uses **async-based storage** with `asyncio.Lock`, which is optimized for async frameworks like FastAPI.

For **synchronous/threaded deployments** (e.g., Flask with Gunicorn using threading workers), you must override three dependency providers to use thread-safe synchronous storage instead.

---

## When to Override

Override the context storage providers when:

- ✅ Using **Flask** with Gunicorn (threaded workers)
- ✅ Using **Flask** with uWSGI (threading mode)
- ✅ Using any **synchronous web framework** with threading
- ✅ Your endpoints are **synchronous functions** (not `async def`)

Do NOT override when:

- ❌ Using **FastAPI** with Uvicorn
- ❌ Using **FastAPI** with Gunicorn + UvicornWorker
- ❌ Your endpoints are **async functions** (`async def`)

---

## What Needs to Be Overridden

You must override **three dependency providers**:

1. **`context_storage_singleton`** - Change from `AsyncInMemoryContextStorage` to `SyncInMemoryContextStorage`
2. **`client_context`** - Change from async (`async def`) to sync (`def`)
3. **`pairing_attempt_context`** - Change from async (`async def`) to sync (`def`)

---

## Step-by-Step Override Guide

### Step 1: Import Required Components

```python
from s2auth.server.dependencies import (
    setup,
    override_provider,
    Depends,
    inject,
)
from s2auth.server.dependencies.context import (
    # Import the sync storage class
    SyncInMemoryContextStorage,

    # Import the providers we'll override
    context_storage_singleton,
    client_context,
    pairing_attempt_context,

    # Import the ID providers (these work for both async and sync)
    client_node_id,
    pairing_attempt_id,

    # Import types
    ClientNodeId,
    PairingAttemptId,
    ClientContext,
    PairingAttemptContext,

    # Import context variables for setting values in middleware
    s2_client_node_id_var,
    pairing_attempt_id_var,
)
from s2auth.common.models import S2NodeId, PairingAttemptId as S2PairingAttemptId
from uuid import UUID
```

### Step 2: Create Sync Override Functions

```python
def sync_context_storage() -> SyncInMemoryContextStorage:
    """Sync storage override using threading.Lock.

    This storage uses threading.Lock for thread-safe synchronization,
    making it suitable for Flask with threaded Gunicorn workers.
    """
    return SyncInMemoryContextStorage()


def sync_client_context(
    cid: ClientNodeId = Depends[client_node_id],
    storage: SyncInMemoryContextStorage = Depends[context_storage_singleton],
) -> ClientContext:
    """Synchronous version of client_context provider.

    Returns the context for the current client (identified by context variable).
    This is a regular function (not async) so it can be used in sync endpoints.
    """
    return storage.get_client_context(cid)


def sync_pairing_attempt_context(
    pid: PairingAttemptId = Depends[pairing_attempt_id],
    storage: SyncInMemoryContextStorage = Depends[context_storage_singleton],
) -> PairingAttemptContext:
    """Synchronous version of pairing_attempt_context provider.

    Returns the context for the current pairing attempt (identified by context variable).
    This is a regular function (not async) so it can be used in sync endpoints.
    """
    return storage.get_pairing_attempt_context(pid)
```

### Step 3: Override the Providers

```python
# Override the three providers BEFORE calling setup()
override_provider(context_storage_singleton, sync_context_storage)
override_provider(client_context, sync_client_context)
override_provider(pairing_attempt_context, sync_pairing_attempt_context)
```

### Step 4: Call setup() After Overrides

```python
# Wire all providers (must be called after overriding)
setup()
```

---

## Multi-Process Considerations

**Important**: `SyncInMemoryContextStorage` is **single-process only**. Each Gunicorn worker process has its own independent storage instance.

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
upstream flask_app {
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
import json
from s2auth.server.dependencies import override_provider

class RedisContextStorage:
    """Distributed context storage using Redis."""

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self.redis = redis.from_url(redis_url)

    def get_client_context(self, client_node_id: ClientNodeId) -> ClientContext:
        key = f"client:{client_node_id}"
        data = self.redis.get(key)

        if data:
            return ClientContext.model_validate_json(data)
        else:
            ctx = ClientContext()
            self.redis.set(key, ctx.model_dump_json())
            return ctx

    def get_pairing_attempt_context(
        self, pairing_attempt_id: PairingAttemptId
    ) -> PairingAttemptContext:
        key = f"pairing:{pairing_attempt_id}"
        data = self.redis.get(key)

        if data:
            return PairingAttemptContext.model_validate_json(data)
        else:
            ctx = PairingAttemptContext()
            self.redis.set(key, ctx.model_dump_json())
            return ctx


def redis_context_storage() -> RedisContextStorage:
    """Use Redis storage for multi-process deployments."""
    return RedisContextStorage()


# Override to use Redis
override_provider(context_storage_singleton, redis_context_storage)
setup()
```

#### Option 3: Use Single Worker

For development or low-traffic scenarios:

```bash
gunicorn app:app --workers 1 --threads 8
```

---

## Testing with Overrides

When writing unit tests, you can use the context manager to temporarily override the storage:

```python
# test_app.py
import pytest
from uuid import UUID
from s2auth.server.dependencies import provider_overrides, setup
from s2auth.server.dependencies.context import (
    context_storage_singleton,
    SyncInMemoryContextStorage,
    s2_client_node_id_var,
    pairing_attempt_id_var,
)
from s2auth.common.models import S2NodeId, PairingAttemptId as S2PairingAttemptId
from app import app


@pytest.fixture
def client():
    """Create Flask test client."""
    with app.test_client() as client:
        yield client


@pytest.fixture
def test_storage():
    """Create test storage with pre-populated data."""
    storage = SyncInMemoryContextStorage()

    # Pre-populate with test data
    test_uuid = UUID("00000000-0000-0000-0000-000000000001")
    ctx = storage.get_client_context(test_uuid)
    ctx.state = "test_authenticated"

    return storage


def test_client_status_with_override(client, test_storage):
    """Test client status endpoint with overridden storage."""

    def test_storage_provider():
        return test_storage

    with provider_overrides({context_storage_singleton: test_storage_provider}):
        response = client.get(
            '/client-status',
            headers={'X-Client-Node-Id': '00000000-0000-0000-0000-000000000001'}
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['state'] == 'test_authenticated'
```

---

## Summary

To use context storage in synchronous (Flask) applications:

1. **Create sync override functions** for the three providers
2. **Use `override_provider()`** to override them BEFORE calling `setup()`
3. **Call `setup()`** after overriding
4. **Set context variables** in Flask's `@app.before_request` handler
5. **Use `@inject`** decorator on routes that need context
6. **Consider distributed storage** (Redis) for multi-process deployments

The complete example in this guide provides a working starting point for Flask applications with Gunicorn.
