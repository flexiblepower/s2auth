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

import asyncio

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
        is_async = is_async_gen or is_async_func

        if is_async:
            if singleton:
                raise ValueError(
                    f"Async provider '{provider_name}' cannot be a singleton. "
                    f"The dependency-injector library doesn't support singleton caching for Coroutine providers. "
                    f"Make your provider a sync function instead: def {func.__name__}(...)"
                )

            if is_async_gen:
                # For async generators, we wrap them to return the first yielded value
                # This allows them to work as context managers (yield, then cleanup on exception)
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

                    # Call original generator and return the first yielded value
                    gen = func(**bound.arguments)
                    return await gen.__anext__()

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
                            try:
                                asyncio.get_running_loop()
                                raise RuntimeError(
                                    f"Cannot resolve async dependency '{param_name}' in sync provider "
                                    f"'{provider_name}' from an async context. "
                                    f"Make your provider async instead: async def {func.__name__}(...)"
                                )
                            except RuntimeError as e:
                                if "Cannot resolve async dependency" in str(e):
                                    raise
                                # No running event loop, safe to use asyncio.run()
                                result = asyncio.run(result)
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

                # If the provider returns a coroutine, await it
                if asyncio.iscoroutine(result):
                    result = await result

                # If the provider returns an async generator, get the first yielded value
                # and track it for cleanup
                if hasattr(result, "__anext__"):
                    generators_to_cleanup.append(result)
                    result = await result.__anext__()
                # If it's a regular generator, get the first yielded value
                elif hasattr(result, "__next__"):
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

                # If the provider returns a coroutine, handle it
                if asyncio.iscoroutine(result):
                    # Check if there's already a running event loop
                    try:
                        asyncio.get_running_loop()
                        # We're in an async context - this is not supported!
                        raise RuntimeError(
                            f"Cannot resolve async dependency '{param_name}' in sync function "
                            f"'{func.__name__}' from an async context. "
                            f"Make your function async instead: async def {func.__name__}(...)"
                        )
                    except RuntimeError as e:
                        # If it's our custom error, re-raise it
                        if "Cannot resolve async dependency" in str(e):
                            raise
                        # No running event loop, safe to use asyncio.run()
                        result = asyncio.run(result)

                # If it's a generator, get the first yielded value and track for cleanup
                if hasattr(result, "__next__"):
                    generators_to_cleanup.append(result)
                    result = result.__next__()

                bound.arguments[param_name] = result

        return bound.arguments, generators_to_cleanup

    async def _cleanup_generators_async(
        generators: List[Any], exception: Optional[Exception] = None
    ) -> None:
        """Clean up async and sync generators after function execution.

        Generators should yield exactly once for dependency injection.
        This function runs the cleanup code after the yield.

        If an exception occurred, it's sent to the generator via throw().
        """
        for gen in generators:
            try:
                if hasattr(gen, "__anext__"):
                    # Async generator
                    if exception:
                        # Send the exception into the generator
                        try:
                            await gen.athrow(
                                type(exception), exception, exception.__traceback__
                            )
                        except StopAsyncIteration:
                            # Generator handled the exception and finished
                            pass
                        except Exception:
                            # Generator raised a different exception during cleanup
                            pass
                    else:
                        # No exception, just continue the generator
                        try:
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
                    if exception:
                        # Send the exception into the generator
                        try:
                            gen.throw(
                                type(exception), exception, exception.__traceback__
                            )
                        except StopIteration:
                            # Generator handled the exception and finished
                            pass
                        except Exception:
                            # Generator raised a different exception during cleanup
                            pass
                    else:
                        # No exception, just continue the generator
                        try:
                            gen.__next__()
                            # If we get here, the generator yielded more than once - this is an error
                            raise RuntimeError(
                                "Dependency generator yielded more than once. "
                                "Generators used as dependencies should only yield once (setup, yield, teardown pattern)."
                            )
                        except StopIteration:
                            # This is the expected case - generator is exhausted after cleanup
                            pass
            except RuntimeError:
                # Re-raise our custom errors
                raise
            except Exception:
                # Ignore other cleanup errors (but maybe log them in production)
                pass

    def _cleanup_generators_sync(
        generators: List[Any], exception: Optional[Exception] = None
    ) -> None:
        """Clean up sync generators after function execution.

        Generators should yield exactly once for dependency injection.
        This function runs the cleanup code after the yield.

        If an exception occurred, it's sent to the generator via throw().
        """
        for gen in generators:
            try:
                if exception:
                    # Send the exception into the generator
                    try:
                        gen.throw(type(exception), exception, exception.__traceback__)
                    except StopIteration:
                        # Generator handled the exception and finished
                        pass
                    except Exception:
                        # Generator raised a different exception during cleanup
                        pass
                else:
                    # No exception, just continue the generator
                    try:
                        gen.__next__()
                        # If we get here, the generator yielded more than once - this is an error
                        raise RuntimeError(
                            "Dependency generator yielded more than once. "
                            "Generators used as dependencies should only yield once (setup, yield, teardown pattern)."
                        )
                    except StopIteration:
                        # This is the expected case - generator is exhausted after cleanup
                        pass
            except RuntimeError:
                # Re-raise our custom errors
                raise
            except Exception:
                # Ignore other cleanup errors (but maybe log them in production)
                pass

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
