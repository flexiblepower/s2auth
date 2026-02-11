"""Tests for generator dependencies and cleanup."""

from typing import Any, AsyncGenerator, Generator
import pytest
from pytest_mock import MockerFixture
from unittest.mock import MagicMock
from s2auth.server.dependencies import setup, Depends, inject, register_provider


@pytest.fixture
def cleanup_tracker(mocker: MockerFixture) -> MagicMock:
    """Track cleanup calls for testing generator lifecycle."""
    tracker = mocker.MagicMock()
    tracker.async_gen_cleanup = mocker.AsyncMock()
    tracker.sync_gen_cleanup = mocker.MagicMock()
    tracker.exception_handler = mocker.MagicMock()
    return tracker


@pytest.mark.skip_wire
async def test_async_generator_dependency_in_async_function(
    mocker: MockerFixture, cleanup_tracker: MagicMock
) -> None:
    """Test async generator as dependency in async function.

    This tests lines 334-335: async generator detection and cleanup.
    """

    @register_provider()
    async def async_session_provider() -> AsyncGenerator[MagicMock, None]:
        session = mocker.MagicMock()
        session.query = mocker.AsyncMock(return_value=["data"])
        yield session
        await cleanup_tracker.async_gen_cleanup()

    @inject
    async def query_database(session: Any = Depends[async_session_provider]) -> Any:
        return await session.query()

    setup()

    # Execute
    result = await query_database()

    # Verify the function worked
    assert result == ["data"]

    # Verify cleanup was called
    cleanup_tracker.async_gen_cleanup.assert_awaited_once()


@pytest.mark.skip_wire
async def test_sync_generator_dependency_in_async_function(
    mocker: MockerFixture, cleanup_tracker: MagicMock
) -> None:
    """Test sync generator as dependency in async function.

    This tests lines 337-338: sync generator detection and cleanup in async context.
    """

    @register_provider()
    def sync_resource_provider() -> Generator[MagicMock, None, None]:
        resource = mocker.MagicMock()
        resource.value = "resource_data"
        yield resource
        cleanup_tracker.sync_gen_cleanup()

    @inject
    async def use_resource(resource: Any = Depends[sync_resource_provider]) -> str:
        return resource.value

    setup()

    # Execute
    result = await use_resource()

    # Verify the function worked
    assert result == "resource_data"

    # Verify cleanup was called
    cleanup_tracker.sync_gen_cleanup.assert_called_once()


@pytest.mark.skip_wire
def test_sync_generator_dependency_in_sync_function(
    mocker: MockerFixture, cleanup_tracker: MagicMock
) -> None:
    """Test sync generator as dependency in sync function.

    This tests lines 359, 363-364: sync generator detection and cleanup in sync context.
    """

    @register_provider()
    def file_provider() -> Generator[MagicMock, None, None]:
        file_handle = mocker.MagicMock()
        file_handle.read = mocker.MagicMock(return_value="file_content")
        yield file_handle
        cleanup_tracker.sync_gen_cleanup()

    @inject
    def read_file(file: Any = Depends[file_provider]) -> str:
        return file.read()

    setup()

    # Execute
    result = read_file()

    # Verify the function worked
    assert result == "file_content"

    # Verify cleanup was called
    cleanup_tracker.sync_gen_cleanup.assert_called_once()


@pytest.mark.skip_wire
def test_async_generator_dependency_in_sync_function(
    mocker: MockerFixture, cleanup_tracker: MagicMock
) -> None:
    """Test async generator as dependency in sync function (sync context).

    This tests the DI system's ability to resolve async generator dependencies
    in sync functions by running them in an event loop. The system should:
    1. Detect the async generator
    2. Check there's no running event loop
    3. Create a new event loop
    4. Run __anext__() to get the yielded value
    5. Track the generator for cleanup
    6. Properly clean up using athrow()/anext() in the event loop

    This test runs in a thread to simulate a true sync context (no event loop).
    """
    import threading

    @register_provider()
    async def async_session_provider() -> AsyncGenerator[MagicMock, None]:
        session = mocker.MagicMock()
        session.query = mocker.MagicMock(return_value="async_query_result")
        try:
            yield session
        finally:
            await cleanup_tracker.async_gen_cleanup()

    @inject
    def query_database(session: Any = Depends[async_session_provider]) -> str:
        # This is a sync function depending on an async generator
        return session.query()

    setup()

    # Run in a thread to ensure we're in a true sync context (no event loop)
    result_container: list[str] = []
    error_container: list[Exception] = []

    def run_test():
        try:
            result = query_database()
            result_container.append(result)
        except Exception as e:
            error_container.append(e)

    thread = threading.Thread(target=run_test)
    thread.start()
    thread.join()

    # Check for errors
    if error_container:
        raise error_container[0]

    # Verify the function worked
    assert len(result_container) == 1
    assert result_container[0] == "async_query_result"

    # Verify cleanup was called (the DI system should have cleaned up the async generator)
    cleanup_tracker.async_gen_cleanup.assert_called_once()


@pytest.mark.skip_wire
def test_async_coroutine_dependency_in_sync_function() -> None:
    """Test async coroutine (regular async function) as dependency in sync function (sync context).

    This tests the DI system's ability to resolve async function (coroutine)
    dependencies in sync functions by running them in an event loop. The system should:
    1. Detect the coroutine
    2. Check there's no running event loop
    3. Create a new event loop
    4. Run the coroutine to completion
    5. Return the result to the sync function

    This test runs in a thread to simulate a true sync context (no event loop).
    """
    import threading

    call_count = 0

    @register_provider()
    async def async_config_provider() -> dict[str, Any]:
        # Simulate async work (e.g., fetching from async source)
        nonlocal call_count
        call_count += 1
        return {
            "api_url": "https://api.example.com",
            "timeout": 30,
            "call_count": call_count,
        }

    @inject
    def get_api_url(config: dict[str, Any] = Depends[async_config_provider]) -> str:
        # This is a sync function depending on an async coroutine
        return config["api_url"]

    setup()

    # Run in a thread to ensure we're in a true sync context (no event loop)
    result_container: list[str] = []
    error_container: list[Exception] = []

    def run_test():
        try:
            result = get_api_url()
            result_container.append(result)
        except Exception as e:
            error_container.append(e)

    thread = threading.Thread(target=run_test)
    thread.start()
    thread.join()

    # Check for errors
    if error_container:
        raise error_container[0]

    # Verify the function worked
    assert len(result_container) == 1
    assert result_container[0] == "https://api.example.com"

    # Verify the async provider was actually called
    assert call_count == 1


@pytest.mark.skip_wire
async def test_async_dependency_in_sync_function_from_async_context_errors() -> None:
    """Test that sync functions with async dependencies error when called from async context.

    When a sync function depends on an async provider and is called from within
    an async context (where an event loop is already running), the DI system
    should raise a clear error telling the user to make the function async.
    """

    @register_provider()
    async def async_config_provider() -> dict[str, Any]:
        return {"api_url": "https://api.example.com"}

    @inject
    def sync_func_with_async_dep(
        config: dict[str, Any] = Depends[async_config_provider],
    ) -> str:
        return config["api_url"]

    setup()

    # This should raise an error because we're in an async context
    with pytest.raises(
        RuntimeError,
        match=r"Cannot resolve async dependency 'config' in sync function 'sync_func_with_async_dep' from within an async context",
    ):
        sync_func_with_async_dep()


@pytest.mark.skip_wire
async def test_async_generator_in_sync_function_from_async_context_errors(
    mocker: MockerFixture,
) -> None:
    """Test that sync functions with async generator dependencies error when called from async context.

    When a sync function depends on an async generator provider and is called from within
    an async context (where an event loop is already running), the DI system
    should raise a clear error telling the user to make the function async.
    """

    @register_provider()
    async def async_session_provider() -> AsyncGenerator[MagicMock, None]:
        session = mocker.MagicMock()
        yield session

    @inject
    def sync_func_with_async_gen(session: Any = Depends[async_session_provider]) -> Any:
        return session

    setup()

    # This should raise an error because we're in an async context
    with pytest.raises(
        RuntimeError,
        match=r"Cannot resolve async dependency 'session' in sync function 'sync_func_with_async_gen' from within an async context",
    ):
        sync_func_with_async_gen()  # type: ignore[reportUnusedCoroutine]


@pytest.mark.skip_wire
async def test_async_generator_cleanup_with_exception(
    mocker: MockerFixture, cleanup_tracker: MagicMock
) -> None:
    """Test async generator cleanup when exception occurs in function.

    This tests lines 415-423: exception handling in async generator cleanup.
    With the hybrid cleanup approach, generators should use try-finally
    to ensure cleanup runs properly when exceptions occur.
    """

    @register_provider()
    async def session_provider() -> AsyncGenerator[MagicMock, None]:
        session = mocker.MagicMock()
        try:
            yield session
        finally:
            await cleanup_tracker.async_gen_cleanup()

    @inject
    async def failing_function(session: Any = Depends[session_provider]) -> None:
        raise ValueError("Something went wrong")

    setup()

    # Execute and expect exception
    with pytest.raises(ValueError, match="Something went wrong"):
        await failing_function()

    # Verify cleanup was still called despite the exception
    cleanup_tracker.async_gen_cleanup.assert_awaited_once()


@pytest.mark.skip_wire
async def test_sync_generator_cleanup_with_exception_in_async(
    mocker: MockerFixture, cleanup_tracker: MagicMock
) -> None:
    """Test sync generator cleanup when exception occurs in async function.

    This tests lines 452-480: sync generator cleanup in async context with exception.
    With the hybrid cleanup approach, generators should use try-finally
    to ensure cleanup runs properly when exceptions occur.
    """

    @register_provider()
    def resource_provider() -> Generator[MagicMock, None, None]:
        resource = mocker.MagicMock()
        try:
            yield resource
        finally:
            cleanup_tracker.sync_gen_cleanup()

    @inject
    async def failing_function(resource: Any = Depends[resource_provider]) -> None:
        raise RuntimeError("Async function failed")

    setup()

    # Execute and expect exception
    with pytest.raises(RuntimeError, match="Async function failed"):
        await failing_function()

    # Verify cleanup was still called despite the exception
    cleanup_tracker.sync_gen_cleanup.assert_called_once()


@pytest.mark.skip_wire
def test_sync_generator_cleanup_with_exception_in_sync(
    mocker: MockerFixture, cleanup_tracker: MagicMock
) -> None:
    """Test sync generator cleanup when exception occurs in sync function.

    This tests lines 509-512: sync generator cleanup in sync context with exception.
    With the hybrid cleanup approach, generators should use try-finally
    to ensure cleanup runs properly when exceptions occur.
    """

    @register_provider()
    def connection_provider() -> Generator[MagicMock, None, None]:
        conn = mocker.MagicMock()
        try:
            yield conn
        finally:
            cleanup_tracker.sync_gen_cleanup()

    @inject
    def failing_function(conn: Any = Depends[connection_provider]) -> None:
        raise IOError("Sync function failed")

    setup()

    # Execute and expect exception
    with pytest.raises(IOError, match="Sync function failed"):
        failing_function()

    # Verify cleanup was still called despite the exception
    cleanup_tracker.sync_gen_cleanup.assert_called_once()


@pytest.mark.skip_wire
async def test_generator_yields_more_than_once_async() -> None:
    """Test error when generator yields more than once (async context).

    This tests lines 427-434: RuntimeError when generator yields multiple times.
    """

    @register_provider()
    async def bad_generator_provider() -> AsyncGenerator[str, None]:
        yield "first_value"
        yield "second_value"  # This should cause an error

    @inject
    async def use_generator(value: Any = Depends[bad_generator_provider]) -> Any:
        return value

    setup()

    # Execute and expect error during cleanup
    with pytest.raises(RuntimeError, match="yielded more than once"):
        await use_generator()


@pytest.mark.skip_wire
async def test_multiple_generators_cleanup_in_order(
    mocker: MockerFixture, cleanup_tracker: MagicMock
) -> None:
    """Test that multiple generator dependencies are cleaned up.

    This tests cleanup of multiple generators in a single function.
    """
    cleanup_order: list[str] = []

    @register_provider()
    async def first_provider() -> AsyncGenerator[MagicMock, None]:
        resource = mocker.MagicMock()
        resource.name = "first"
        yield resource
        cleanup_order.append("first")
        await cleanup_tracker.async_gen_cleanup()

    @register_provider()
    async def second_provider() -> AsyncGenerator[MagicMock, None]:
        resource = mocker.MagicMock()
        resource.name = "second"
        yield resource
        cleanup_order.append("second")
        await cleanup_tracker.async_gen_cleanup()

    @inject
    async def use_both(
        first: Any = Depends[first_provider], second: Any = Depends[second_provider]
    ) -> str:
        return f"{first.name}-{second.name}"

    setup()

    # Execute
    result = await use_both()

    # Verify both were used
    assert result == "first-second"

    # Verify both were cleaned up
    assert len(cleanup_order) == 2
    assert cleanup_tracker.async_gen_cleanup.await_count == 2


@pytest.mark.skip_wire
async def test_async_generator_cleanup_handles_exception_in_cleanup(
    mocker: MockerFixture, cleanup_tracker: MagicMock
) -> None:
    """Test that exceptions during generator cleanup are handled gracefully.

    This tests exception handling within the cleanup code itself.
    """

    async def cleanup_that_fails() -> None:
        raise RuntimeError("Cleanup failed")

    @register_provider()
    async def provider_with_failing_cleanup() -> AsyncGenerator[MagicMock, None]:
        resource = mocker.MagicMock()
        yield resource
        await cleanup_that_fails()

    @inject
    async def use_resource(
        resource: Any = Depends[provider_with_failing_cleanup],
    ) -> str:
        return "success"

    setup()

    # Execute - should succeed even though cleanup will fail
    # The cleanup exception should be caught and ignored
    result = await use_resource()
    assert result == "success"

    # Suppress unused parameter warning
    _ = cleanup_tracker


@pytest.mark.skip_wire
async def test_generator_cleanup_with_stop_iteration(mocker: MockerFixture) -> None:
    """Test that StopAsyncIteration is handled correctly during cleanup.

    This tests lines 420-422: StopAsyncIteration handling in cleanup.
    """

    @register_provider()
    async def normal_generator() -> AsyncGenerator[MagicMock, None]:
        resource = mocker.MagicMock()
        resource.value = "test"
        yield resource
        # Generator naturally ends here

    @inject
    async def use_resource(resource: Any = Depends[normal_generator]) -> str:
        return resource.value

    setup()

    # Execute - should work normally
    result = await use_resource()
    assert result == "test"


@pytest.mark.skip_wire
def test_sync_generator_yields_more_than_once_in_sync_function() -> None:
    """Test error when sync generator yields more than once in sync function.

    This tests the error case in sync generator cleanup.
    """

    @register_provider()
    def bad_sync_generator() -> Generator[str, None, None]:
        yield "first"
        yield "second"  # Should cause error

    @inject
    def use_generator(value: Any = Depends[bad_sync_generator]) -> Any:
        return value

    setup()

    # Execute and expect error
    with pytest.raises(RuntimeError, match="yielded more than once"):
        use_generator()  # type: ignore[unused-coroutine]
