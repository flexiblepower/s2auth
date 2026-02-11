"""Dependency injection system with generator provider support.

This module provides a custom DI wrapper around dependency-injector that supports:
- Regular function providers (sync and async)
- Generator providers for resource management (sync and async)
- Dependency resolution via Depends[] markers
- Provider overrides for testing

## Generator Provider Patterns

Generator providers use the setup/yield/teardown pattern for resource management.
The system uses a HYBRID cleanup strategy:
- On SUCCESS: Calls next()/anext() to run cleanup normally
- On EXCEPTION: Calls throw()/athrow() to pass exception to generator

### CRITICAL: All generators MUST use try-finally or try-except

When throw() is called, the exception is raised AT the yield point.
Without try-finally, cleanup code after yield will NOT execute.

### Failure Behavior

If a generator provider's cleanup fails (e.g., missing try-finally), the DI system:
- Logs a warning with the exception details (enabling debugging of resource leaks)
- Continues cleanup of other providers (robust error handling)
- Does NOT break the DI system as a whole
- The cleanup code in that specific provider won't run (potential resource leak)

### ✅ CORRECT Pattern 1 - Simple cleanup (REQUIRED):
```python
@register_provider()
async def resource_provider():
    resource = await create_resource()
    try:
        yield resource
    finally:
        await resource.cleanup()  # Always runs, even with throw()
```

### ✅ CORRECT Pattern 2 - Exception-aware cleanup (for transactions):
```python
@register_provider()
async def async_session(cfg: Config = Depends[config]):
    engine = create_async_engine(cfg.sqlalchemy_db_uri.get_secret_value())
    session = AsyncSession(engine)
    try:
        yield session
        await session.commit()  # Success: runs with anext()
    except Exception:
        await session.rollback()  # Failure: runs with athrow()
        raise
```

### ❌ INCORRECT Pattern - Without try-finally (BROKEN):
```python
@register_provider()
async def broken_provider():
    resource = await create_resource()
    yield resource
    await resource.cleanup()  # WON'T run when throw() is called! ❌
```

### Rules:
1. Always use try-finally or try-except for cleanup in generator providers
2. Put cleanup code in the finally block or except block
3. Never rely on code after yield without try-finally
4. The try-finally pattern works for both success and failure cases
"""

from typing import (
    Any,
    Callable,
    Coroutine,
    Dict,
    List,
    Optional,
    Set,
    TypeVar,
    Union,
    overload,
)
from dependency_injector import containers, providers
from contextlib import contextmanager
import functools
import inspect
import logging

import asyncio

logger = logging.getLogger(__name__)

_registered_modules: Set[Any] = set()
_provider_overrides: Dict[str, Callable[..., Any]] = {}

registry = containers.DynamicContainer()


def register_provider(name: Optional[str] = None, singleton: bool = False):
    def decorator(func: Callable[..., Any]):
        """Register a provider function (sync or async) in the registry.
        Args:
            name: Optional name for the provider (defaults to function name)
            singleton: If True, caches and reuses the first created instance.
                      If False (default), creates a new instance on each call.
                      Singleton is not supported on async functions.
        """
        provider_name = name or func.__name__

        # Wrap the function to resolve Depends markers
        sig = inspect.signature(func)
        is_async_gen = inspect.isasyncgenfunction(func)
        is_async_func = inspect.iscoroutinefunction(func)
        is_sync_gen = inspect.isgeneratorfunction(func)
        is_async = is_async_gen or is_async_func

        if is_async:
            if singleton:
                raise ValueError(
                    f"Async provider '{provider_name}' cannot be a singleton. "
                    f"The dependency-injector library doesn't support singleton caching for Coroutine providers. "
                    f"Make your provider a sync function instead: def {func.__name__}(...)"
                )

            if is_async_gen:
                # For async generators, we wrap them to return the generator itself
                # The @inject decorator will manage the generator lifecycle
                async def async_gen_wrapper():
                    # Resolve Depends markers
                    bound = sig.bind_partial()
                    bound.apply_defaults()

                    for param_name in list(bound.arguments.keys()):
                        value = bound.arguments[param_name]
                        if isinstance(value, _DependsMarker):
                            if value.name in _provider_overrides:
                                result = _provider_overrides[value.name]()
                            else:
                                result = getattr(registry, value.name)()
                            if asyncio.iscoroutine(result):
                                result = await result
                            bound.arguments[param_name] = result

                    # Return the generator itself, not the first yielded value
                    # The @inject decorator will call __anext__() and handle cleanup
                    return func(**bound.arguments)

                setattr(registry, provider_name, providers.Coroutine(async_gen_wrapper))
            else:
                # Create a regular async function wrapper
                async def async_func_wrapper():
                    # Resolve Depends markers
                    bound = sig.bind_partial()
                    bound.apply_defaults()

                    for param_name in list(bound.arguments.keys()):
                        value = bound.arguments[param_name]
                        if isinstance(value, _DependsMarker):
                            if value.name in _provider_overrides:
                                result = _provider_overrides[value.name]()
                            else:
                                result = getattr(registry, value.name)()
                            if asyncio.iscoroutine(result):
                                result = await result
                            bound.arguments[param_name] = result

                    # Call original async function
                    return await func(**bound.arguments)

                setattr(
                    registry, provider_name, providers.Coroutine(async_func_wrapper)
                )
        else:
            # Sync providers (functions or generators)
            if is_sync_gen:
                # For sync generators, we wrap them to return the generator itself
                # The @inject decorator will manage the generator lifecycle
                def sync_gen_wrapper():
                    # Resolve Depends markers
                    bound = sig.bind_partial()
                    bound.apply_defaults()

                    for param_name in list(bound.arguments.keys()):
                        value = bound.arguments[param_name]
                        if isinstance(value, _DependsMarker):
                            if value.name in _provider_overrides:
                                result = _provider_overrides[value.name]()
                            else:
                                result = getattr(registry, value.name)()
                            if asyncio.iscoroutine(result):
                                # Close the coroutine to avoid RuntimeWarning about unawaited coroutine
                                result.close()
                                raise RuntimeError(
                                    f"Cannot resolve async dependency '{param_name}' in sync provider "
                                    f"'{provider_name}'. Sync providers cannot have async dependencies. "
                                    f"Make your provider async instead: async def {func.__name__}(...)"
                                )
                            bound.arguments[param_name] = result

                    # Return the generator itself, not the first yielded value
                    # The @inject decorator will call __next__() and handle cleanup
                    return func(**bound.arguments)

                if singleton:
                    setattr(
                        registry, provider_name, providers.Singleton(sync_gen_wrapper)
                    )
                else:
                    setattr(
                        registry, provider_name, providers.Factory(sync_gen_wrapper)
                    )  # type:ignore[reportArgumentType]
            else:
                # Create a sync wrapper that resolves dependencies
                def sync_wrapper():
                    # Resolve Depends markers
                    bound = sig.bind_partial()
                    bound.apply_defaults()

                    for param_name in list(bound.arguments.keys()):
                        value = bound.arguments[param_name]
                        if isinstance(value, _DependsMarker):
                            if value.name in _provider_overrides:
                                result = _provider_overrides[value.name]()
                            else:
                                result = getattr(registry, value.name)()
                            if asyncio.iscoroutine(result):
                                # Close the coroutine to avoid RuntimeWarning about unawaited coroutine
                                result.close()
                                raise RuntimeError(
                                    f"Cannot resolve async dependency '{param_name}' in sync provider "
                                    f"'{provider_name}'. Sync providers cannot have async dependencies. "
                                    f"Make your provider async instead: async def {func.__name__}(...)"
                                )
                            bound.arguments[param_name] = result

                    # Call original sync function
                    return func(**bound.arguments)

                if singleton:
                    setattr(registry, provider_name, providers.Singleton(sync_wrapper))
                else:
                    setattr(registry, provider_name, providers.Factory(sync_wrapper))  # type:ignore[reportArgumentType]

        module = inspect.getmodule(func)
        if module is not None:
            _registered_modules.add(module)
        return func

    return decorator


def setup():
    registry.wire(modules=list(_registered_modules))


def override_provider(
    original: Union[Callable[..., Any], str],
    override: Callable[..., Any],
) -> None:
    """Permanently override a provider with a new implementation.

    Args:
        original: The original provider function or its name
        override: The new provider function to use instead

    Example:
        @register_provider()
        async def config() -> Config:
            return Config()

        # Override in tests
        async def test_config() -> Config:
            return Config(sqlalchemy_db_uri=SecretStr("sqlite:///:memory:"))

        override_provider(config, test_config)
    """
    provider_name = original if isinstance(original, str) else original.__name__
    _provider_overrides[provider_name] = override


def clear_overrides() -> None:
    """Clear all provider overrides."""
    _provider_overrides.clear()


@contextmanager
def provider_overrides(
    overrides: Dict[Union[Callable[..., Any], str], Callable[..., Any]],
):
    """Context manager to temporarily override providers for testing.

    Args:
        overrides: Dictionary mapping original providers to their overrides

    Example:
        async def test_config() -> Config:
            return Config(sqlalchemy_db_uri=SecretStr("sqlite:///:memory:"))

        with provider_overrides({config: test_config}):
            # Code here uses test_config instead of config
            result = await my_function()
    """
    # Save current state
    old_overrides = _provider_overrides.copy()

    # Apply new overrides
    for original, override in overrides.items():
        provider_name = original if isinstance(original, str) else original.__name__
        _provider_overrides[provider_name] = override

    try:
        yield
    finally:
        # Restore previous state
        _provider_overrides.clear()
        _provider_overrides.update(old_overrides)


class _DependsMarker:
    """Marker class for lazy dependency injection."""

    def __init__(self, name: str):
        self.name = name


class _DependsType:
    """Subscriptable type for Depends[func] syntax."""

    def __getitem__(self, func: Union[Callable[..., Any], str]) -> Any:
        """Create a dependency marker using subscript notation.

        Usage: def my_func(config: Config = Depends[config]):
        """
        if isinstance(func, str):
            name = func
        else:
            name = func.__name__

        return _DependsMarker(name)


Depends = _DependsType()

T = TypeVar("T", bound=Callable[..., Any])


async def _call_provider(provider_func: Callable[..., Any]) -> Any:
    """Call a provider function and await if it's a coroutine."""
    result = provider_func()
    if asyncio.iscoroutine(result):
        result = await result
    return result


@overload
def inject(
    func: Callable[..., Coroutine[Any, Any, Any]],
) -> Callable[..., Coroutine[Any, Any, Any]]: ...


@overload
def inject(func: Callable[..., Any]) -> Callable[..., Any]: ...


def inject(func: T) -> T:
    """Decorator that resolves Depends markers in function arguments.

    Works with both sync and async functions. The decorator:
    1. Inspects the function signature for _DependsMarker defaults
    2. At call time, resolves each marker by calling the registry provider
    3. Properly handles generators (sync and async) for resource cleanup
    4. Returns the appropriate wrapper (async or sync) based on the function type

    Generator dependencies should yield exactly once (setup, yield, teardown pattern).

    Example:
        @inject
        def my_func(config: Config = Depends[config]):
            return config.value

        @inject
        async def my_async_func(session: AsyncSession = Depends[async_session]):
            # async_session yields a session, then commits/rollbacks after this function completes
            return session.query(...)
    """
    sig = inspect.signature(func)
    is_async = inspect.iscoroutinefunction(func)

    async def _resolve_dependencies_async(
        args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> tuple[dict[str, Any], List[Any]]:
        """Helper to resolve Depends markers (async version).

        Returns: (resolved_arguments, generators_to_cleanup)
        """
        bound = sig.bind_partial(*args, **kwargs)
        bound.apply_defaults()
        generators_to_cleanup: List[Any] = []

        for param_name in list(bound.arguments.keys()):
            value = bound.arguments[param_name]
            if isinstance(value, _DependsMarker):
                # Check if there's an override for this provider
                if value.name in _provider_overrides:
                    override_func = _provider_overrides[value.name]
                    result = await _call_provider(override_func)
                else:
                    provider = getattr(registry, value.name)
                    result = provider()

                # Check for generators first (before checking iscoroutine)
                # because asyncio.iscoroutine() can incorrectly identify generators as coroutines
                if hasattr(result, "__anext__"):
                    # Async generator - get the first yielded value and track for cleanup
                    generators_to_cleanup.append(result)
                    result = await result.__anext__()
                elif hasattr(result, "__next__"):
                    # Sync generator - get the first yielded value and track for cleanup
                    generators_to_cleanup.append(result)
                    result = result.__next__()
                elif asyncio.iscoroutine(result):
                    # If the provider returns a coroutine, await it first
                    # (this handles Coroutine providers that wrap generators)
                    result = await result

                    # After awaiting, check if we got a generator
                    if hasattr(result, "__anext__"):
                        # Async generator - get the first yielded value and track for cleanup
                        generators_to_cleanup.append(result)
                        result = await result.__anext__()
                    elif hasattr(result, "__next__"):
                        # Sync generator - get the first yielded value and track for cleanup
                        generators_to_cleanup.append(result)
                        result = result.__next__()

                bound.arguments[param_name] = result

        return bound.arguments, generators_to_cleanup

    def _resolve_dependencies_sync(
        args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> tuple[dict[str, Any], List[Any]]:
        """Helper to resolve Depends markers (sync version).

        Returns: (resolved_arguments, generators_to_cleanup)
        """
        bound = sig.bind_partial(*args, **kwargs)
        bound.apply_defaults()
        generators_to_cleanup: List[Any] = []

        for param_name in list(bound.arguments.keys()):
            value = bound.arguments[param_name]
            if isinstance(value, _DependsMarker):
                # Check if there's an override for this provider
                if value.name in _provider_overrides:
                    override_func = _provider_overrides[value.name]
                    result = override_func()
                else:
                    provider = getattr(registry, value.name)
                    result = provider()

                # Check for generators first (before checking for coroutines)
                # to avoid treating generators as coroutines
                if hasattr(result, "__next__"):
                    # Sync generator - get the first yielded value and track for cleanup
                    generators_to_cleanup.append(result)
                    result = result.__next__()
                elif hasattr(result, "__anext__"):
                    # Async generator in sync function - need event loop
                    logger.debug(
                        f"Resolving async generator dependency '{param_name}' in sync function"
                    )

                    # Check if we're already in an async context
                    has_running_loop = False
                    try:
                        asyncio.get_running_loop()
                        has_running_loop = True
                    except RuntimeError:
                        # No running loop - this is fine
                        pass

                    if has_running_loop:
                        # Can't use run_until_complete in an already-running loop
                        raise RuntimeError(
                            f"Cannot resolve async dependency '{param_name}' in sync function "
                            f"'{func.__name__}' from within an async context. "
                            f"Either make '{func.__name__}' async or call it from a sync context."
                        )

                    # No running loop - create one for this sync context
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                    # Get first yielded value and track for cleanup
                    generators_to_cleanup.append(result)
                    result = loop.run_until_complete(result.__anext__())
                    logger.debug(f"Resolved async generator to: {result}")
                elif asyncio.iscoroutine(result):
                    # Async coroutine in sync function - need event loop
                    logger.debug(
                        f"Resolving async coroutine dependency '{param_name}' in sync function"
                    )

                    # Check if we're already in an async context
                    has_running_loop = False
                    try:
                        asyncio.get_running_loop()
                        has_running_loop = True
                    except RuntimeError:
                        # No running loop - this is fine
                        pass

                    if has_running_loop:
                        # Can't use run_until_complete in an already-running loop
                        raise RuntimeError(
                            f"Cannot resolve async dependency '{param_name}' in sync function "
                            f"'{func.__name__}' from within an async context. "
                            f"Either make '{func.__name__}' async or call it from a sync context."
                        )

                    # No running loop - create one for this sync context
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                    result = loop.run_until_complete(result)
                    logger.debug(f"Resolved async coroutine to: {result}")

                    # The coroutine might have returned an async generator
                    if hasattr(result, "__anext__"):
                        logger.debug(
                            "Coroutine returned async generator, extracting value"
                        )
                        generators_to_cleanup.append(result)
                        result = loop.run_until_complete(result.__anext__())

                bound.arguments[param_name] = result

        return bound.arguments, generators_to_cleanup

    async def _cleanup_generators_async(
        generators: List[Any], exception: Optional[Exception] = None
    ) -> None:
        """Clean up async and sync generators after function execution.

        Generators should yield exactly once for dependency injection.
        This function runs the cleanup code after the yield.

            If an exception occurred, it's sent to the generator via throw()/athrow()
            so exception-aware generators (like async_session) can handle rollback.
            If no exception occurred, generators are continued normally with next()/anext().
        """
        for gen in generators:
            try:
                if hasattr(gen, "__anext__"):
                    # Async generator
                    try:
                        if exception is not None:
                            # Send exception to generator so it can handle rollback
                            await gen.athrow(
                                type(exception), exception, exception.__traceback__
                            )
                        else:
                            # No exception - continue normally
                            await gen.__anext__()
                        # If we get here, the generator yielded more than once - this is an error
                        raise RuntimeError(
                            "Dependency generator yielded more than once. "
                            "Generators used as dependencies should only yield once (setup, yield, teardown pattern)."
                        )
                    except StopAsyncIteration:
                        # This is the expected case - generator is exhausted after cleanup
                        pass
                else:
                    # Sync generator
                    try:
                        if exception is not None:
                            # Send exception to generator so it can handle rollback
                            gen.throw(
                                type(exception), exception, exception.__traceback__
                            )
                        else:
                            # No exception - continue normally
                            gen.__next__()
                        # If we get here, the generator yielded more than once - this is an error
                        raise RuntimeError(
                            "Dependency generator yielded more than once. "
                            "Generators used as dependencies should only yield once (setup, yield, teardown pattern)."
                        )
                    except StopIteration:
                        # This is the expected case - generator is exhausted after cleanup
                        pass
            except RuntimeError as e:
                # Only re-raise our specific "yielded more than once" error
                if "yielded more than once" in str(e):
                    raise
                # Log warning for other RuntimeErrors during cleanup
                logger.warning(
                    f"RuntimeError during cleanup of generator dependency: {e}",
                    exc_info=True,
                )
            except Exception as e:
                # Log warning for other cleanup errors to help debug resource leaks
                logger.warning(
                    f"Exception during cleanup of generator dependency: {e}",
                    exc_info=True,
                )

    def _cleanup_generators_sync(
        generators: List[Any], exception: Optional[Exception] = None
    ) -> None:
        """Clean up sync and async generators after sync function execution.

        Generators should yield exactly once for dependency injection.
        This function runs the cleanup code after the yield.

        If an exception occurred, it's sent to the generator via throw()
        so exception-aware generators can handle it appropriately.
        If no exception occurred, generators are continued normally with next().

        Async generators are cleaned up by running them in an event loop.
        """
        for gen in generators:
            try:
                if hasattr(gen, "__anext__"):
                    # Async generator - need to run in event loop
                    has_running_loop = False
                    try:
                        loop = asyncio.get_running_loop()
                        has_running_loop = True
                    except RuntimeError:
                        # No running loop
                        pass

                    if has_running_loop:
                        # Can't use run_until_complete in an already-running loop
                        logger.warning(
                            "Cannot clean up async generator in sync function from async context. "
                            "Async generator cleanup skipped."
                        )
                        continue

                    # Use the event loop we created earlier
                    loop = asyncio.get_event_loop()

                    try:
                        if exception is not None:
                            # Send exception to async generator
                            loop.run_until_complete(
                                gen.athrow(
                                    type(exception), exception, exception.__traceback__
                                )
                            )
                        else:
                            # No exception - continue normally
                            loop.run_until_complete(gen.__anext__())
                        # If we get here, the generator yielded more than once
                        raise RuntimeError(
                            "Dependency generator yielded more than once. "
                            "Generators used as dependencies should only yield once (setup, yield, teardown pattern)."
                        )
                    except StopAsyncIteration:
                        # This is the expected case - generator is exhausted after cleanup
                        pass
                else:
                    # Sync generator
                    try:
                        if exception is not None:
                            # Send exception to generator so it can handle it
                            gen.throw(
                                type(exception), exception, exception.__traceback__
                            )
                        else:
                            # No exception - continue normally
                            gen.__next__()
                        # If we get here, the generator yielded more than once - this is an error
                        raise RuntimeError(
                            "Dependency generator yielded more than once. "
                            "Generators used as dependencies should only yield once (setup, yield, teardown pattern)."
                        )
                    except StopIteration:
                        # This is the expected case - generator is exhausted after cleanup
                        pass
            except RuntimeError as e:
                # Only re-raise our specific "yielded more than once" error
                if "yielded more than once" in str(e):
                    raise
                # Log warning for other RuntimeErrors during cleanup
                logger.warning(
                    f"RuntimeError during cleanup of generator dependency: {e}",
                    exc_info=True,
                )
            except Exception as e:
                # Log warning for other cleanup errors to help debug resource leaks
                logger.warning(
                    f"Exception during cleanup of generator dependency: {e}",
                    exc_info=True,
                )

    if is_async:

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            resolved_args, generators = await _resolve_dependencies_async(args, kwargs)
            exception_occurred = None
            try:
                result = await func(**resolved_args)
                return result
            except Exception as e:
                # Capture the exception to pass to generators
                exception_occurred = e
                raise
            finally:
                # Always clean up generators, passing any exception that occurred
                await _cleanup_generators_async(generators, exception_occurred)

        return async_wrapper  # type: ignore
    else:

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            resolved_args, generators = _resolve_dependencies_sync(args, kwargs)
            exception_occurred = None
            try:
                result = func(**resolved_args)
                return result
            except Exception as e:
                # Capture the exception to pass to generators
                exception_occurred = e
                raise
            finally:
                # Always clean up generators, passing any exception that occurred
                _cleanup_generators_sync(generators, exception_occurred)

        return sync_wrapper  # type: ignore
