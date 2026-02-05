import pytest
from s2auth.server.config import config, Config
from s2auth.server.dependencies import setup, Depends, inject, register_provider


@pytest.mark.skip_wire
async def test_dependency_injection():
    default_config = Config()

    @inject
    def my_test_function(config: Config = Depends[config]):
        print(f"Inside function, cfg type: {type(config)}")
        print(f"cfg value: {config}")
        return config.sqlalchemy_db_uri.get_secret_value()

    @inject
    async def my_test_function2(config: Config = Depends[config]):
        print(f"Inside function, cfg type: {type(config)}")
        print(f"cfg value: {config}")
        return config.sqlalchemy_db_uri.get_secret_value()

    setup()

    print(f"Function type: {type(my_test_function)}")
    print(f"Function name: {my_test_function.__name__}")

    with pytest.raises(
        RuntimeError,
        match="Cannot resolve async dependency 'config' in sync function 'my_test_function' from an async context. Make your function async instead: async def my_test_function(...)",
    ):
        assert my_test_function() == default_config.sqlalchemy_db_uri

    assert (
        await my_test_function2() == default_config.sqlalchemy_db_uri.get_secret_value()
    )


@pytest.mark.skip_wire
def test_singleton_works_for_sync():
    """Test that sync functions with singleton=True cache the result."""
    call_count = 0

    @register_provider(singleton=True)
    def counter() -> int:
        nonlocal call_count
        call_count += 1
        return call_count

    @inject
    def get_counter(c: int = Depends[counter]) -> int:
        return c

    setup()

    # First call - creates instance
    result1 = get_counter()
    assert result1 == 1

    # Second call - returns cached instance
    result2 = get_counter()
    assert result2 == 1  # Still 1, proving it's cached!

    # Provider was only called once
    assert call_count == 1


@pytest.mark.skip_wire
def test_singleton_raises_error_for_async():
    """Test that async functions cannot use singleton=True."""
    with pytest.raises(ValueError, match="cannot be a singleton"):

        @register_provider(singleton=True)
        async def async_counter() -> int:
            return 42

        async_counter()


@pytest.mark.skip_wire
async def test_provider_overrides_context_manager():
    """Test that provider overrides work with context manager."""

    @register_provider()
    async def original_provider() -> str:
        return "original"

    async def override_provider() -> str:
        return "overridden"

    @inject
    async def get_value(val: str = Depends[original_provider]) -> str:
        return val

    setup()

    # Without override, get original value
    from s2auth.server.dependencies import clear_overrides

    clear_overrides()
    result = await get_value()
    assert result == "original"

    # With override, get overridden value
    from s2auth.server.dependencies import provider_overrides

    with provider_overrides({original_provider: override_provider}):
        result = await get_value()
        assert result == "overridden"

    # After context, back to original
    result = await get_value()
    assert result == "original"
