# s2auth - S2 Protocol Python Wrapper

## Build, Test, and Lint Commands

### Setup
```bash
poetry install --all-extras
```

### Run Commands
```bash
# Linting
poetry run ruff check .      # Direct command

# Type checking
poetry run pyright           # Direct command

# Testing
poetry run pytest            # Direct command (includes coverage)

# Run specific test file
poetry run pytest tests/unit/server/test_storage.py

# Run specific test function
poetry run pytest tests/unit/server/test_storage.py::test_function_name
```

### Pre-commit Hooks
The repository uses pre-commit hooks that run ruff, pyright, poetry checks, and pytest on commit. These can auto-fix many issues. To skip checks if needed: `git commit --no-verify`

### Code Quality Workflow
**IMPORTANT**: After making ANY code changes (especially to tests or source files), you MUST run the following commands to ensure code quality:

```bash
# 1. Run type checking
poetry run pyright <path-to-modified-files>

# 2. Run linting
poetry run ruff check <path-to-modified-files>

# 3. Run tests (if applicable)
poetry run pytest <path-to-modified-tests>
```

**Do not skip these checks!** Type errors and linting issues must be fixed before completing any task. This applies to:
- New files you create
- Existing files you modify
- Test files you add or update

If you create a new file without running these checks, you may introduce type errors that break the build.

## Architecture

### Project Structure
- **`src/s2auth/common/`** - Shared utilities (HMAC verification, models, exceptions)
- **`src/s2auth/client/`** - S2 client implementation
- **`src/s2auth/server/`** - S2 server implementation with FastAPI endpoints
- **`specification/`** - OpenAPI YAML specs for S2 protocol (connection-init, pairing, common)

### Dependency Injection System
This project uses the `wepositive-di` package for dependency injection, provider overrides, context-manager providers, and typed context storage. Do not duplicate DI behavior locally; follow the upstream documentation at https://wepositive-di.readthedocs.io/.

### Context Storage

The server uses the `wepositive-di` context storage implementation. s2auth only defines project-specific context models and providers (`AuthenticationContext`, `PairingAttemptContext`, `authentication_context`, `pairing_attempt_context`, and store helpers).

**Basic usage:**
```python
from wepositive_di import inject, Depends
from s2auth.server.context import (
    authentication_context,
    store_authentication_context,
    AuthenticationContext,
)

@inject
async def my_endpoint(
    ctx: AuthenticationContext = Depends[authentication_context],
    store_ctx: Callable[[AuthenticationContext], Awaitable[None]] = Depends[store_authentication_context],
):
    # Read/modify existing context
    print(f"Current state: {ctx.state}")
    ctx.state = "authenticated"

    # Store new context
    new_ctx = AuthenticationContext(client_node_id=some_uuid, state="active")
    await store_ctx(new_ctx)
```

See https://wepositive-di.readthedocs.io/ for context storage behavior and override patterns.

### Database
- Uses SQLAlchemy async with PostgreSQL (via asyncpg)
- Connection configured via `Config` class (reads from `.env` or `.env.docker`)
- Default URI: `postgresql://postgres:postgres@localhost/s2auth`
- Session management: `async_session` provider yields sessions with auto-commit/rollback

### Testing
- Tests use pytest with `asyncio_mode = "auto"`
- Dependency injection is auto-wired in tests via `conftest.py` fixture
- Use `@pytest.mark.skip_wire` marker to skip auto-wiring when you need custom dependencies in a test
- Test coverage reports generated in `unit_test_coverage/`
- Context storage tests are in `tests/unit/server/test_context.py`

**Override providers in tests** (use context manager for temporary overrides):
```python
from wepositive_di import provider_overrides
from s2auth.server.config import config

def test_config() -> Config:
    return Config(sqlalchemy_db_uri=SecretStr("sqlite:///:memory:"))

with provider_overrides({config: test_config}):
    # Your test code here - uses test_config instead of config
    pass
```

**Note:** For permanent overrides (production config), use the decorator or setup() method. See "Overriding Providers" section above.

## Key Conventions

### Code Style

**Import Organization**:
- **All imports must be at the top of the file** unless there's a specific technical reason (e.g., circular import resolution, conditional imports)
- Never add imports inside functions just for convenience
- Group imports in this order:
  1. Standard library imports
  2. Third-party imports
  3. Local/project imports
- Use absolute imports, not relative imports

**Example:**
```python
# ✅ CORRECT
import hashlib
import hmac
from unittest.mock import MagicMock

import pytest
from pydantic import TypeAdapter

from s2auth.common.exceptions import VerificationError
from s2auth.common.hmac import create_challenge

# ❌ INCORRECT
def my_test():
    import hashlib  # Don't do this!
    from unittest.mock import MagicMock  # Don't do this!
```

### Poetry Dependency Management
- Runtime deps: `poetry add <package>`
- Dev deps: `poetry add -G dev <package>`
- Optional deps: `poetry add --optional=<extra> <package>`

### Generated Code Exclusions
Files excluded from type-checking and linting:
- `src/s2auth/common/models.py` (generated from OpenAPI specs)
- `typings/*` directory

### Python Version
Supports Python 3.10-3.13, configured in `pyproject.toml` and `.python-version`

### Configuration
Uses `pydantic-settings` with environment variables. Config reads from `.env` and `.env.docker` files. Nested env vars use double underscore: `SECTION__KEY`

## Documentation

For more detailed information, see:
- **`docs/dependency_injection.md`** - How this project uses `wepositive-di`
- **https://wepositive-di.readthedocs.io/** - Dependency injection, provider overrides, and context storage
