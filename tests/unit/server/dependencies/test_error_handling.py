"""Tests for error handling scenarios in dependency injection."""
from typing import Any
import pytest
from pytest_mock import MockerFixture
from unittest.mock import MagicMock
from s2auth.server.dependencies import (
    setup,
    Depends,
    inject,
    register_provider,
    override_provider,
    clear_overrides,
)


@pytest.fixture
def mock_config(mocker: MockerFixture) -> MagicMock:
    """Mock config object."""
    config = mocker.MagicMock()
    config.value = "test_config"
    config.api_url = "https://api.example.com"
    return config


@pytest.mark.skip_wire
async def test_sync_provider_with_async_dependency_in_event_loop(
    mocker: MockerFixture, mock_config: MagicMock
) -> None:
    """Test error when sync provider tries to resolve async dependency with event loop running.

    This tests lines 108-114: RuntimeError when asyncio.get_running_loop() succeeds.
    """

    @register_provider()
    async def async_config() -> Any:
        return mock_config

    @register_provider()
    def sync_provider_needs_async(cfg: Any = Depends[async_config]) -> Any:
        # This sync provider depends on an async provider
        return cfg.value

    @inject
    async def use_sync_provider(value: Any = Depends[sync_provider_needs_async]) -> Any:
        return value

    setup()

    # Execute from async context (event loop is running)
    # This should raise an error because sync provider can't resolve async dependency
    # when called from an event loop context
    with pytest.raises(
        RuntimeError,
        match=r"Cannot resolve async dependency 'cfg' in sync provider 'sync_provider_needs_async'\. Sync providers cannot have async dependencies\. Make your provider async instead: async def sync_provider_needs_async\(\.\.\.\)"
    ):
        await use_sync_provider()


@pytest.mark.skip_wire
def test_sync_provider_with_async_dependency_no_event_loop(
    mocker: MockerFixture, mock_config: MagicMock
) -> None:
    """Test sync provider with async dependency raises error (no asyncio.run fallback).

    With the new behavior, sync providers cannot resolve async dependencies
    regardless of whether there's an event loop or not.
    """

    @register_provider()
    async def async_config() -> Any:
        return mock_config

    @register_provider()
    def sync_provider_needs_async(cfg: Any = Depends[async_config]) -> Any:
        # This sync provider depends on an async provider
        return cfg.value

    @inject
    def use_sync_provider(value: Any = Depends[sync_provider_needs_async]) -> Any:
        return value

    setup()

    # Should raise an error because sync provider can't resolve async dependency
    with pytest.raises(
        RuntimeError,
        match=r"Cannot resolve async dependency 'cfg' in sync provider 'sync_provider_needs_async'\. Sync providers cannot have async dependencies\. Make your provider async instead: async def sync_provider_needs_async\(\.\.\.\)",
    ):
        use_sync_provider()  # pyright: ignore[reportUnusedCoroutine]


@pytest.mark.skip_wire
async def test_override_provider_function(mocker: MockerFixture) -> None:
    """Test the override_provider function for permanent overrides.

    This tests line 170: override_provider function body.
    """

    @register_provider()
    async def original_provider() -> str:
        return "original_value"

    async def override_provider_func() -> str:
        return "overridden_value"

    @inject
    async def get_value(val: Any = Depends[original_provider]) -> Any:
        return val

    setup()

    # Before override
    clear_overrides()
    result = await get_value()
    assert result == "original_value"

    # Apply permanent override
    override_provider(original_provider, override_provider_func)

    # After override
    result = await get_value()
    assert result == "overridden_value"

    # Cleanup
    clear_overrides()


@pytest.mark.skip_wire
async def test_override_provider_by_string_name(mocker: MockerFixture) -> None:
    """Test override_provider using string name instead of function reference."""

    @register_provider()
    async def my_provider() -> str:
        return "original"

    async def my_override() -> str:
        return "override"

    @inject
    async def get_value(val: Any = Depends[my_provider]) -> Any:
        return val

    setup()

    # Override using string name
    override_provider("my_provider", my_override)

    result = await get_value()
    assert result == "override"

    # Cleanup
    clear_overrides()


@pytest.mark.skip_wire
async def test_dependency_resolution_without_overrides(mocker: MockerFixture) -> None:
    """Test dependency resolution without any overrides active.

    This tests lines 314-315: getting provider from registry and calling it.
    """

    @register_provider()
    async def base_provider() -> dict[str, str]:
        return {"data": "from_registry"}

    @inject
    async def get_data(data: Any = Depends[base_provider]) -> Any:
        return data

    setup()

    # Make sure no overrides are active
    clear_overrides()

    # Execute - should get value from registry
    result = await get_data()
    assert result == {"data": "from_registry"}


@pytest.mark.skip_wire
async def test_sync_dependency_error_handling_in_event_loop(mocker: MockerFixture) -> None:
    """Test error handling when sync function resolves async dependency in event loop.

    This tests lines 392-401: error handling in _resolve_dependencies_sync.
    """

    @register_provider()
    async def async_dep() -> str:
        return "async_value"

    @inject
    def sync_func_with_async_dep(val: Any = Depends[async_dep]) -> Any:
        return val

    # Call from async context to trigger the error
    async def caller() -> Any:
        return sync_func_with_async_dep()

    with pytest.raises(
        RuntimeError,
        match=r"Cannot resolve async dependency 'val' in sync function 'sync_func_with_async_dep'\. Sync functions cannot have async dependencies\. Make your function async instead: async def sync_func_with_async_dep\(\.\.\.\)"
    ):
        await caller()


@pytest.mark.skip_wire
async def test_exception_propagation_through_dependency_chain(mocker: MockerFixture) -> None:
    """Test that exceptions propagate correctly through dependency chains."""

    @register_provider()
    async def failing_provider() -> Any:
        raise ValueError("Provider failed")

    @inject
    async def function_with_failing_dep(val: Any = Depends[failing_provider]) -> Any:
        return val

    setup()

    # Exception from provider should propagate
    with pytest.raises(ValueError, match="Provider failed"):
        await function_with_failing_dep()


@pytest.mark.skip_wire
async def test_call_provider_helper_with_async_function(mocker: MockerFixture) -> None:
    """Test _call_provider helper with async function.

    This tests line 227: _call_provider function execution.
    """
    from s2auth.server.dependencies import _call_provider  # type: ignore[reportPrivateUsage]

    async def async_provider() -> str:
        return "async_result"

    # Call the helper directly
    result = await _call_provider(async_provider)  # type: ignore[reportPrivateUsage]
    assert result == "async_result"


@pytest.mark.skip_wire
async def test_call_provider_helper_with_sync_function(mocker: MockerFixture) -> None:
    """Test _call_provider helper with sync function."""
    from s2auth.server.dependencies import _call_provider  # type: ignore[reportPrivateUsage]

    def sync_provider() -> str:
        return "sync_result"

    # Call the helper directly
    result = await _call_provider(sync_provider)  # type: ignore[reportPrivateUsage]
    assert result == "sync_result"


@pytest.mark.skip_wire
async def test_async_generator_with_exception_in_athrow(mocker: MockerFixture) -> None:
    """Test async generator cleanup when function raises exception.

    With the hybrid cleanup approach, exceptions are propagated to generators
    via athrow() when an exception occurs. Generators should use try-finally
    or try-except patterns to ensure cleanup code runs properly.
    """
    cleanup_called = False

    @register_provider()
    async def generator_with_exception_handler() -> Any:
        resource: Any = mocker.MagicMock()
        try:
            yield resource
        finally:
            # Cleanup code in finally block runs even when athrow() is called
            nonlocal cleanup_called
            cleanup_called = True

    @inject
    async def failing_function(resource: Any = Depends[generator_with_exception_handler]) -> None:
        raise ValueError("Function error")

    setup()

    # Execute and verify exception is propagated from function
    with pytest.raises(ValueError, match="Function error"):
        await failing_function()

    # Verify the generator's cleanup code ran via finally block
    assert cleanup_called


@pytest.mark.skip_wire
def test_sync_generator_with_exception_in_throw(mocker: MockerFixture) -> None:
    """Test sync generator cleanup when function raises exception.

    With the hybrid cleanup approach, exceptions are propagated to generators
    via throw() when an exception occurs. Generators should use try-finally
    or try-except patterns to ensure cleanup code runs properly.
    """
    cleanup_called = False

    @register_provider()
    def generator_with_exception_handler() -> Any:
        resource: Any = mocker.MagicMock()
        try:
            yield resource
        finally:
            # Cleanup code in finally block runs even when throw() is called
            nonlocal cleanup_called
            cleanup_called = True

    @inject
    def failing_function(resource: Any = Depends[generator_with_exception_handler]) -> None:
        raise IOError("Function error")

    setup()

    # Execute and verify exception is propagated from function
    with pytest.raises(IOError, match="Function error"):
        failing_function()

    # Verify the generator's cleanup code ran via finally block
    assert cleanup_called


@pytest.mark.skip_wire
async def test_async_generator_raises_different_exception_during_cleanup(
    mocker: MockerFixture,
) -> None:
    """Test when async generator raises a different exception during cleanup.

    This tests lines 424-426: exception handling in cleanup.
    """

    @register_provider()
    async def generator_that_fails_cleanup() -> Any:
        resource: Any = mocker.MagicMock()
        try:
            yield resource
        except ValueError:
            # Raise a different exception during cleanup
            raise RuntimeError("Cleanup error")

    @inject
    async def failing_function(resource: Any = Depends[generator_that_fails_cleanup]) -> None:
        raise ValueError("Function error")

    setup()

    # The original exception should be raised, cleanup exception is swallowed
    with pytest.raises(ValueError, match="Function error"):
        await failing_function()


@pytest.mark.skip_wire
def test_sync_generator_raises_different_exception_during_cleanup(
    mocker: MockerFixture,
) -> None:
    """Test when sync generator raises a different exception during cleanup.

    This tests exception handling in sync generator cleanup.
    """

    @register_provider()
    def generator_that_fails_cleanup() -> Any:
        resource: Any = mocker.MagicMock()
        try:
            yield resource
        except IOError:
            # Raise a different exception during cleanup
            raise RuntimeError("Cleanup error")

    @inject
    def failing_function(resource: Any = Depends[generator_that_fails_cleanup]) -> None:
        raise IOError("Function error")

    setup()

    # The original exception should be raised, cleanup exception is swallowed
    with pytest.raises(IOError, match="Function error"):
        failing_function()


@pytest.mark.skip_wire
async def test_mixed_sync_async_generators_cleanup(mocker: MockerFixture) -> None:
    """Test cleanup of both sync and async generators in same function.

    With the hybrid cleanup approach, generators should use try-finally
    to ensure cleanup runs properly when exceptions occur.
    """
    cleanup_order: list[str] = []

    @register_provider()
    async def async_gen() -> Any:
        try:
            yield "async"
        finally:
            cleanup_order.append("async")

    @register_provider()
    def sync_gen() -> Any:
        try:
            yield "sync"
        finally:
            cleanup_order.append("sync")

    @inject
    async def use_both(a: Any = Depends[async_gen], s: Any = Depends[sync_gen]) -> None:
        raise ValueError("Test error")

    setup()

    # Both should be cleaned up despite exception
    with pytest.raises(ValueError, match="Test error"):
        await use_both()

    # Verify both were cleaned up
    assert "async" in cleanup_order
    assert "sync" in cleanup_order
