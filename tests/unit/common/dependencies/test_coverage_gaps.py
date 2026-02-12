"""Advanced Dependency Injection Patterns and Coverage Tests.

This test suite demonstrates advanced usage patterns of the dependency injection system
and ensures comprehensive code coverage of edge cases and complex scenarios.

## What You'll Learn

1. **Nested Dependencies**: How to inject dependencies that themselves have dependencies
2. **String-based Dependencies**: Using Depends["name"] syntax for dynamic resolution
3. **Generator Patterns**: Advanced cleanup patterns with try-finally blocks
4. **Override Patterns**: Testing with dependency overrides in complex scenarios
5. **Async/Sync Interop**: How async and sync dependencies interact
6. **Error Handling**: Cleanup behavior when exceptions occur

## Organization

Tests are grouped by pattern:
- **Dependency Resolution**: How Depends markers are resolved in different contexts
- **Generator Lifecycle**: Setup/teardown patterns with proper cleanup
- **Override Mechanisms**: Testing with provider_overrides
- **Cleanup & Error Handling**: What happens when things go wrong
- **Advanced Patterns**: Multi-dependency resolution, coroutine handling, etc.

## When To Use These Patterns

- **Nested dependencies**: When your database session needs injected config
- **String-based Depends**: When using dynamic provider selection
- **Generator patterns**: When managing resources (DB connections, file handles, etc.)
- **Override patterns**: When writing tests that need mock dependencies
- **Async/sync interop**: When calling async dependencies from sync code (or vice versa)

## Quick Example

```python
# Nested dependency pattern
@register_provider()
async def config() -> Config:
    return Config(db_url="postgresql://...")

@register_provider()
async def db_session(cfg: Config = Depends[config]) -> AsyncGenerator[Session, None]:
    engine = create_async_engine(cfg.db_url)
    session = AsyncSession(engine)
    try:
        yield session
        await session.commit()
    finally:
        await session.close()

@inject
async def my_handler(db: Session = Depends[db_session]) -> None:
    # Use db here
    pass
```
"""

import concurrent.futures
from typing import Any, AsyncGenerator, Generator

import pytest

from s2auth.common.dependencies import (
    Depends,
    clear_overrides,
    inject,
    provider_overrides,
    register_provider,
    registry,
)


# =============================================================================
# SECTION 1: String-based Dependency Resolution
# =============================================================================
# These tests demonstrate using Depends["name"] syntax for dynamic provider
# resolution. This is useful when you need to refer to providers by name
# instead of direct function reference.


@pytest.mark.skip_wire
def test_depends_with_string_name() -> None:
    """Test that Depends["string_name"] syntax works correctly."""
    # Register a provider
    @register_provider()
    def my_config() -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        return {"value": 42}

    # Use Depends with string name instead of function reference
    @inject
    def consumer(cfg: dict[str, Any] = Depends["my_config"]) -> int:
        return cfg["value"]

    result = consumer()
    assert result == 42

    clear_overrides()


@pytest.mark.skip_wire
async def test_async_generator_provider_resolves_internal_dependencies() -> None:
    """Test async generator provider that internally resolves Depends markers.

    Tests the code path in register_provider where an async generator
    wrapper resolves its own dependencies.
    """
    # Register a base dependency
    @register_provider()
    async def base_value() -> int:
        return 100

    # Register async generator that depends on base_value
    @register_provider()
    async def async_gen_with_dep(val: int = Depends[base_value]) -> AsyncGenerator[int, None]:
        # Setup
        result = val * 2
        try:
            yield result
        finally:
            # Cleanup
            pass

    # Use the generator provider
    @inject
    async def consumer(value: int = Depends[async_gen_with_dep]) -> int:
        return value

    result = await consumer()
    assert result == 200  # 100 * 2

    clear_overrides()


@pytest.mark.skip_wire
def test_sync_generator_provider_resolves_internal_dependencies() -> None:
    """Test sync generator provider that internally resolves Depends markers.

    Tests the code path in register_provider where a sync generator
    wrapper resolves its own dependencies.
    """
    # Register a base dependency
    @register_provider()
    def base_value() -> int:
        return 50

    # Register sync generator that depends on base_value
    @register_provider()
    def sync_gen_with_dep(val: int = Depends[base_value]) -> Generator[int, None, None]:
        # Setup
        result = val * 3
        try:
            yield result
        finally:
            # Cleanup
            pass

    # Use the generator provider
    @inject
    def consumer(value: int = Depends[sync_gen_with_dep]) -> int:
        return value

    result = consumer()
    assert result == 150  # 50 * 3

    clear_overrides()


@pytest.mark.skip_wire
async def test_async_function_provider_resolves_internal_dependencies() -> None:
    """Test async function provider that internally resolves Depends markers.

    Tests the code path where an async function wrapper resolves
    its own dependencies.
    """
    # Register a base dependency
    @register_provider()
    async def base_config() -> dict[str, Any]:
        return {"multiplier": 5}

    # Register async function that depends on base_config
    @register_provider()
    async def computed_value(cfg: dict[str, Any] = Depends[base_config]) -> int:
        return cfg["multiplier"] * 10

    # Use the function provider
    @inject
    async def consumer(value: int = Depends[computed_value]) -> int:
        return value

    result = await consumer()
    assert result == 50  # 5 * 10

    clear_overrides()


@pytest.mark.skip_wire
def test_sync_function_provider_resolves_internal_dependencies() -> None:
    """Test sync function provider that internally resolves Depends markers.

    Tests the code path where a sync function wrapper resolves
    its own dependencies.
    """
    # Register a base dependency
    @register_provider()
    def base_config() -> dict[str, Any]:
        return {"multiplier": 7}

    # Register sync function that depends on base_config
    @register_provider()
    def computed_value(cfg: dict[str, Any] = Depends[base_config]) -> int:
        return cfg["multiplier"] * 10

    # Use the function provider
    @inject
    def consumer(value: int = Depends[computed_value]) -> int:
        return value

    result = consumer()
    assert result == 70  # 7 * 10

    clear_overrides()


@pytest.mark.skip_wire
async def test_coroutine_provider_wrapping_async_generator() -> None:
    """Test the code path where a Coroutine provider wraps an async generator.

    Tests the code path where we await a coroutine and then check
    if the result is a generator.
    """
    # Register an async generator provider (these are wrapped in Coroutine providers)
    @register_provider()
    async def my_async_gen() -> AsyncGenerator[str, None]:
        try:
            yield "from_generator"
        finally:
            pass

    # The provider is wrapped in Coroutine, so when we call it we get a coroutine
    # that returns the generator. The inject decorator should handle this.
    @inject
    async def consumer(value: str = Depends[my_async_gen]) -> str:
        return value

    result = await consumer()
    assert result == "from_generator"

    clear_overrides()


@pytest.mark.skip_wire
async def test_coroutine_provider_wrapping_sync_generator() -> None:
    """Test the edge case where a Coroutine provider somehow wraps a sync generator.

    Tests the code path where after awaiting a coroutine, we check
    if the result has __next__ (sync generator).
    """
    # Create a provider that returns a sync generator wrapped in a coroutine
    async def provider_returns_sync_gen() -> Generator[str, None, None]:
        def sync_gen() -> Generator[str, None, None]:
            try:
                yield "sync_from_async"
            finally:
                pass

        return sync_gen()

    # Manually register this unusual provider
    from dependency_injector import providers

    setattr(registry, "unusual_provider", providers.Coroutine(provider_returns_sync_gen))

    # Use it
    @inject
    async def consumer(value: str = Depends["unusual_provider"]) -> str:
        return value

    result = await consumer()
    assert result == "sync_from_async"

    clear_overrides()


@pytest.mark.skip_wire
async def test_override_async_generator_with_dependencies() -> None:
    """Test overriding an async generator provider that has dependencies."""

    @register_provider()
    async def base_value() -> int:
        return 10

    @register_provider()
    async def original_gen(val: int = Depends[base_value]) -> AsyncGenerator[int, None]:
        try:
            yield val
        finally:
            pass

    async def override_gen() -> AsyncGenerator[int, None]:
        try:
            yield 999
        finally:
            pass

    @inject
    async def consumer(value: int = Depends[original_gen]) -> int:
        return value

    # Test with override
    with provider_overrides({original_gen: override_gen}):
        result = await consumer()
        assert result == 999

    # Test without override
    result = await consumer()
    assert result == 10

    clear_overrides()


@pytest.mark.skip_wire
def test_override_sync_generator_with_dependencies() -> None:
    """Test overriding a sync generator provider that has dependencies."""

    @register_provider()
    def base_value() -> int:
        return 20

    @register_provider()
    def original_gen(val: int = Depends[base_value]) -> Generator[int, None, None]:
        try:
            yield val
        finally:
            pass

    def override_gen() -> Generator[int, None, None]:
        try:
            yield 888
        finally:
            pass

    @inject
    def consumer(value: int = Depends[original_gen]) -> int:
        return value

    # Test with override
    with provider_overrides({original_gen: override_gen}):
        result = consumer()
        assert result == 888

    # Test without override
    result = consumer()
    assert result == 20

    clear_overrides()


@pytest.mark.skip_wire
async def test_async_generator_provider_with_override_in_wrapper() -> None:
    """Test async generator that resolves overridden dependencies internally.

    Tests the override path inside the async generator wrapper when dependencies
    are overridden using provider_overrides context manager.
    """

    @register_provider()
    async def base_value() -> int:
        return 100

    @register_provider()
    async def gen_with_dep(val: int = Depends[base_value]) -> AsyncGenerator[int, None]:
        try:
            yield val * 2
        finally:
            pass

    async def override_base() -> int:
        return 500

    @inject
    async def consumer(value: int = Depends[gen_with_dep]) -> int:
        return value

    # Override the base_value that gen_with_dep depends on
    with provider_overrides({base_value: override_base}):
        result = await consumer()
        assert result == 1000  # 500 * 2

    clear_overrides()


@pytest.mark.skip_wire
def test_sync_generator_provider_with_override_in_wrapper() -> None:
    """Test sync generator that resolves overridden dependencies internally.

    This tests the override path inside the sync generator wrapper (lines 188-192).
    """

    @register_provider()
    def base_value() -> int:
        return 100

    @register_provider()
    def gen_with_dep(val: int = Depends[base_value]) -> Generator[int, None, None]:
        try:
            yield val * 2
        finally:
            pass

    def override_base() -> int:
        return 300

    @inject
    def consumer(value: int = Depends[gen_with_dep]) -> int:
        return value

    # Override the base_value that gen_with_dep depends on
    with provider_overrides({base_value: override_base}):
        result = consumer()
        assert result == 600  # 300 * 2

    clear_overrides()


@pytest.mark.skip_wire
async def test_cleanup_warning_for_unexpected_exception_async(caplog: pytest.LogCaptureFixture) -> None:
    """Test that cleanup logs warning when an unexpected exception occurs in async generator.

    This tests line 554 where we log a warning if cleanup fails with an exception
    that's NOT our "yielded more than once" error.
    """

    @register_provider()
    async def broken_gen() -> AsyncGenerator[int, None]:
        try:
            yield 42
        finally:
            # Raise an unexpected exception during cleanup
            raise ValueError("Unexpected cleanup error")

    @inject
    async def consumer(value: int = Depends[broken_gen]) -> int:
        return value

    # The exception should be caught and logged, not raised
    result = await consumer()
    assert result == 42

    # Check that the warning was logged
    assert any(
        "Exception during cleanup of generator dependency" in record.message
        and "Unexpected cleanup error" in record.message
        for record in caplog.records
    )

    clear_overrides()


@pytest.mark.skip_wire
def test_cleanup_warning_for_unexpected_exception_sync(caplog: pytest.LogCaptureFixture) -> None:
    """Test that cleanup logs warning when an unexpected exception occurs in sync generator.

    Both sync and async cleanup should log warnings for exceptions during cleanup.
    """

    @register_provider()
    def broken_gen() -> Generator[int, None, None]:
        try:
            yield 42
        finally:
            # Raise an unexpected exception during cleanup
            raise ValueError("Unexpected sync cleanup error")

    @inject
    def consumer(value: int = Depends[broken_gen]) -> int:
        return value

    # The exception should be caught and logged, not raised
    result = consumer()
    assert result == 42

    # Check that the warning was logged
    assert any(
        "Exception during cleanup of generator dependency" in record.message
        and "Unexpected sync cleanup error" in record.message
        for record in caplog.records
    )

    clear_overrides()


@pytest.mark.skip_wire
async def test_async_generator_with_async_dependency_coroutine_resolution() -> None:
    """Test async generator resolving an async dependency that's a coroutine.

    This tests the branch in lines 134->132, 139->141 where we check if
    a dependency result is a coroutine and await it.
    """

    @register_provider()
    async def async_dep() -> int:
        # This returns a coroutine when called
        return 777

    @register_provider()
    async def gen_with_async_dep(val: int = Depends[async_dep]) -> AsyncGenerator[int, None]:
        try:
            yield val * 2
        finally:
            pass

    @inject
    async def consumer(value: int = Depends[gen_with_async_dep]) -> int:
        return value

    result = await consumer()
    assert result == 1554  # 777 * 2

    clear_overrides()


@pytest.mark.skip_wire
async def test_async_function_with_async_dependency_coroutine_resolution() -> None:
    """Test async function resolving an async dependency that's a coroutine.

    This tests the branch in lines 157->155, 162->164 where we check if
    a dependency result is a coroutine and await it in async function wrapper.
    """

    @register_provider()
    async def async_dep() -> int:
        return 555

    @register_provider()
    async def func_with_async_dep(val: int = Depends[async_dep]) -> int:
        return val * 3

    @inject
    async def consumer(value: int = Depends[func_with_async_dep]) -> int:
        return value

    result = await consumer()
    assert result == 1665  # 555 * 3

    clear_overrides()


@pytest.mark.skip_wire
async def test_sync_function_with_async_dependency_outside_event_loop() -> None:
    """Test sync function with async dependency raises error (no asyncio.run fallback).

    With the new behavior, sync providers cannot resolve async dependencies
    regardless of whether there's an event loop or not.
    """

    @register_provider()
    async def async_dep() -> int:
        return 999

    @register_provider()
    def sync_func_with_async_dep(val: int = Depends[async_dep]) -> int:
        return val * 2

    # Need to call this in a sync context (no event loop)
    # But we're already in an async test, so we need to run it in a thread
    def run_in_thread() -> None:
        # This will be called in a new thread with no event loop
        @inject
        def consumer(value: int = Depends[sync_func_with_async_dep]) -> int:
            return value

        with pytest.raises(
            RuntimeError,
            match=r"Cannot resolve async dependency 'val' in sync provider 'sync_func_with_async_dep'\. Sync providers cannot have async dependencies\. Make your provider async instead: async def sync_func_with_async_dep\(\.\.\.\)",
        ):
            consumer()

    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(run_in_thread)
        future.result()

    clear_overrides()


@pytest.mark.skip_wire
async def test_sync_gen_async_dep_error_in_async_context() -> None:
    """Test sync generator with async dep raises RuntimeError in async context (line 201)."""

    @register_provider()
    async def async_base() -> int:
        return 10

    @register_provider()
    def sync_gen(val: int = Depends[async_base]) -> Generator[int, None, None]:
        yield val

    @inject
    async def consumer(value: int = Depends[sync_gen]) -> int:
        return value

    with pytest.raises(RuntimeError, match="Cannot resolve async dependency"):
        await consumer()

    clear_overrides()


@pytest.mark.skip_wire
async def test_generator_yields_more_than_once_error() -> None:
    """Test that generator yielding more than once raises error (line 519, 536)."""

    @register_provider()
    async def broken_multi_yield_gen() -> AsyncGenerator[int, None]:
        yield 1
        yield 2  # This should trigger the error

    @inject
    async def consumer(value: int = Depends[broken_multi_yield_gen]) -> int:
        return value

    # Should raise RuntimeError because generator yields more than once
    with pytest.raises(RuntimeError, match="yielded more than once"):
        await consumer()

    clear_overrides()


@pytest.mark.skip_wire
async def test_async_gen_no_override_path() -> None:
    """Test async generator wrapper when NOT using overrides (lines 134->132, 139->141)."""

    @register_provider()
    async def base_dep() -> int:
        return 42

    # Register async generator WITHOUT using any overrides
    @register_provider()
    async def gen_no_override(val: int = Depends[base_dep]) -> AsyncGenerator[int, None]:
        try:
            yield val * 10
        finally:
            pass

    # Call WITHOUT using provider_overrides - this should hit the registry path
    @inject
    async def consumer(value: int = Depends[gen_no_override]) -> int:
        return value

    result = await consumer()
    assert result == 420

    clear_overrides()


@pytest.mark.skip_wire
async def test_async_func_no_override_path() -> None:
    """Test async function wrapper when NOT using overrides (lines 157->155, 159, 162->164)."""

    @register_provider()
    async def base_dep() -> int:
        return 99

    # Register async function WITHOUT using any overrides
    @register_provider()
    async def func_no_override(val: int = Depends[base_dep]) -> int:
        return val * 5

    # Call WITHOUT using provider_overrides
    @inject
    async def consumer(value: int = Depends[func_no_override]) -> int:
        return value

    result = await consumer()
    assert result == 495

    clear_overrides()


@pytest.mark.skip_wire
def test_sync_gen_no_override_path() -> None:
    """Test sync generator wrapper when NOT using overrides (lines 184->182)."""

    @register_provider()
    def base_dep() -> int:
        return 33

    @register_provider()
    def gen_no_override(val: int = Depends[base_dep]) -> Generator[int, None, None]:
        try:
            yield val * 3
        finally:
            pass

    @inject
    def consumer(value: int = Depends[gen_no_override]) -> int:
        return value

    result = consumer()
    assert result == 99

    clear_overrides()




@pytest.mark.skip_wire
async def test_inject_with_override_path() -> None:
    """Test inject decorator with override (line 458->456)."""

    @register_provider()
    async def original() -> int:
        return 100

    async def override() -> int:
        return 999

    @inject
    async def consumer(value: int = Depends[original]) -> int:
        return value

    # Use override
    with provider_overrides({original: override}):
        result = await consumer()
        assert result == 999

    clear_overrides()


@pytest.mark.skip_wire
def test_inject_asyncio_run_path() -> None:
    """Test inject decorator using asyncio.run when no event loop (line 489)."""

    @register_provider()
    async def async_dep() -> int:
        return 555

    @inject
    async def async_consumer(value: int = Depends[async_dep]) -> int:
        return value

    # Call from thread with no event loop - this will use asyncio.run()
    def call_in_thread() -> int:
        # The @inject decorator should handle calling asyncio.run() when there's no event loop
        import asyncio
        return asyncio.run(async_consumer())

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(call_in_thread)
        result = future.result()

    assert result == 555

    clear_overrides()



@pytest.mark.skip_wire
async def test_async_gen_with_multiple_dependencies() -> None:
    """Test async generator with multiple dependencies to hit loop continuation (134->132)."""

    @register_provider()
    async def dep1() -> int:
        return 10

    @register_provider()
    async def dep2() -> int:
        return 20

    @register_provider()
    async def gen_with_multiple_deps(
        val1: int = Depends[dep1], val2: int = Depends[dep2]
    ) -> AsyncGenerator[int, None]:
        try:
            yield val1 + val2
        finally:
            pass

    @inject
    async def consumer(value: int = Depends[gen_with_multiple_deps]) -> int:
        return value

    result = await consumer()
    assert result == 30

    clear_overrides()


@pytest.mark.skip_wire
async def test_async_func_with_multiple_dependencies() -> None:
    """Test async function with multiple dependencies to hit loop continuation (157->155)."""

    @register_provider()
    async def dep1() -> int:
        return 5

    @register_provider()
    async def dep2() -> int:
        return 15

    @register_provider()
    async def func_with_multiple_deps(val1: int = Depends[dep1], val2: int = Depends[dep2]) -> int:
        return val1 * val2

    @inject
    async def consumer(value: int = Depends[func_with_multiple_deps]) -> int:
        return value

    result = await consumer()
    assert result == 75

    clear_overrides()


@pytest.mark.skip_wire
def test_sync_gen_with_multiple_dependencies() -> None:
    """Test sync generator with multiple dependencies to hit loop continuation (184->182)."""

    @register_provider()
    def dep1() -> int:
        return 3

    @register_provider()
    def dep2() -> int:
        return 7

    @register_provider()
    def gen_with_multiple_deps(
        val1: int = Depends[dep1], val2: int = Depends[dep2]
    ) -> Generator[int, None, None]:
        try:
            yield val1 + val2
        finally:
            pass

    @inject
    def consumer(value: int = Depends[gen_with_multiple_deps]) -> int:
        return value

    result = consumer()
    assert result == 10

    clear_overrides()


@pytest.mark.skip_wire
def test_inject_sync_func_with_async_dep_no_event_loop() -> None:
    """Test @inject decorator on sync function with async dep works in sync context.

    Sync functions can resolve async dependencies when called from a sync context
    (no event loop running). The DI system creates a new event loop to resolve
    the async dependency.
    """

    @register_provider()
    async def async_dep() -> int:
        return 888

    @inject
    def sync_consumer(value: int = Depends[async_dep]) -> int:
        return value * 2

    # Call from thread with no event loop - should work
    result_container: list[int] = []

    def call_in_thread() -> None:
        result = sync_consumer()
        result_container.append(result)

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(call_in_thread)
        future.result()

    # Verify it worked
    assert len(result_container) == 1
    assert result_container[0] == 888 * 2

    clear_overrides()
