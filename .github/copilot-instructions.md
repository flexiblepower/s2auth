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

## Architecture

### Project Structure
- **`src/s2auth/common/`** - Shared utilities (HMAC verification, models, exceptions)
- **`src/s2auth/client/`** - S2 client implementation
- **`src/s2auth/server/`** - S2 server implementation with FastAPI endpoints
- **`specification/`** - OpenAPI YAML specs for S2 protocol (connection-init, pairing, common)

### Dependency Injection System
This project uses a custom dependency injection wrapper around `dependency-injector`:

**Register providers** with `@register_provider()`:
```python
from s2auth.server.dependencies import register_provider

@register_provider()  # Default: creates new instance each time
async def my_provider() -> MyType:
    return MyType()

@register_provider(singleton=True)  # Singleton: caches instance (sync only)
def my_singleton() -> MyType:
    return MyType()
```

**Important**: Async providers cannot be singletons due to `dependency-injector` limitations.

**Inject dependencies** with `@inject` and `Depends[]`:
```python
from s2auth.server.dependencies import inject, Depends
from s2auth.server.config import config

@inject
async def my_function(cfg: Config = Depends[config]):
    # cfg is automatically injected
    pass
```

**Setup**: Call `setup()` from `s2auth.server.dependencies` to wire all registered modules before using injected functions.

### Database
- Uses SQLAlchemy async with PostgreSQL (via asyncpg)
- Connection configured via `Config` class (reads from `.env` or `.env.docker`)
- Default URI: `postgresql://postgres:postgres@localhost/s2auth`
- Session management: `async_session` provider yields sessions with auto-commit/rollback

### Testing
- Tests use pytest with `asyncio_mode = "auto"`
- Dependency injection is auto-wired in tests via `conftest.py` fixture
- Test coverage reports generated in `unit_test_coverage/`

**Override providers in tests**:
```python
from s2auth.server.dependencies import provider_overrides
from s2auth.server.config import config

async def test_config() -> Config:
    return Config(sqlalchemy_db_uri=SecretStr("sqlite:///:memory:"))

with provider_overrides({config: test_config}):
    # Your test code here - uses test_config instead of config
    pass
```

## Key Conventions

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
