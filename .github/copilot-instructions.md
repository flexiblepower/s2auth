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

#### Generator Provider Patterns

The dependency injection system supports generator providers for resource management (setup/teardown pattern). **CRITICAL**: All generator providers MUST use `try-finally` or `try-except` blocks for cleanup.

**Why this matters**: The DI system uses a hybrid cleanup strategy:
- On success: Calls `next()`/`anext()` to run cleanup code normally
- On exception: Calls `throw()`/`athrow()` to pass the exception to the generator

When `throw()` is called, the exception is raised **at the yield point**. Without try-finally, cleanup code after the yield will NOT execute.

**Failure behavior**: If a generator provider's cleanup fails (e.g., missing try-finally), the DI system:
- Logs a warning with the exception details (enabling debugging of resource leaks)
- Continues cleanup of other providers (robust error handling)
- Does NOT break the DI system as a whole
- The cleanup code in that specific provider won't run (potential resource leak)

**✅ CORRECT Pattern 1 - Simple cleanup with try-finally** (REQUIRED):
```python
@register_provider()
async def resource_provider():
    resource = await create_resource()
    try:
        yield resource
    finally:
        await resource.cleanup()  # Always runs, even with throw()
```

**✅ CORRECT Pattern 2 - Exception-aware cleanup** (for transaction management):
```python
@register_provider()
async def async_session(cfg: Config = Depends[config]):
    engine = create_async_engine(cfg.sqlalchemy_db_uri.get_secret_value())
    session = AsyncSession(engine)
    try:
        yield session
        await session.commit()  # Success path - only runs with anext()
    except Exception:
        await session.rollback()  # Failure path - runs with athrow()
        raise
```

**❌ INCORRECT Pattern - Simple without try-finally** (BROKEN):
```python
@register_provider()
async def broken_provider():
    resource = await create_resource()
    yield resource
    await resource.cleanup()  # WON'T run when throw() is called! ❌
```

**Key Rules**:
1. **Always use try-finally or try-except** for cleanup in generator providers
2. Put cleanup code in the `finally` block or `except` block
3. Never rely on code immediately after `yield` to run without try-finally
4. The try-finally pattern works for both success and failure cases

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
