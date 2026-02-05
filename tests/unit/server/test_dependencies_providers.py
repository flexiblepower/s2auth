"""Tests for provider registration with dependencies."""
from typing import Any, AsyncGenerator
import pytest
from pytest_mock import MockerFixture
from unittest.mock import MagicMock
from s2auth.server.dependencies import setup, Depends, inject, register_provider


@pytest.fixture
def mock_database_connection(mocker: MockerFixture) -> MagicMock:
    """Mock database connection object."""
    mock_conn = mocker.MagicMock()
    mock_conn.execute = mocker.AsyncMock(return_value="query_result")
    mock_conn.close = mocker.AsyncMock()
    return mock_conn


@pytest.fixture
def mock_config(mocker: MockerFixture) -> MagicMock:
    """Mock config object."""
    mock_cfg = mocker.MagicMock()
    mock_cfg.api_url = "https://api.example.com"
    mock_cfg.timeout = 30
    return mock_cfg


@pytest.mark.skip_wire
async def test_async_function_provider_with_dependency(
    mocker: MockerFixture, mock_config: MagicMock
) -> None:
    """Test async function provider that depends on another provider.

    This tests lines 83-91: async function wrapper with dependency resolution.
    """

    @register_provider()
    async def base_config() -> MagicMock:
        return mock_config

    @register_provider()
    async def api_client(cfg: Any = Depends[base_config]) -> dict[str, Any]:
        # This provider depends on base_config
        # Use a simple dict instead of MagicMock to avoid __anext__ issues
        return {
            "url": cfg.api_url,
            "timeout": cfg.timeout
        }

    @inject
    async def get_client(client: Any = Depends[api_client]) -> Any:
        return client

    setup()

    # Execute
    result = await get_client()

    # Verify the dependency was resolved correctly
    assert result["url"] == "https://api.example.com"
    assert result["timeout"] == 30


@pytest.mark.skip_wire
async def test_async_generator_provider_with_dependency(
    mocker: MockerFixture, mock_database_connection: MagicMock
) -> None:
    """Test async generator provider that depends on another provider.

    This tests lines 56-72: async generator wrapper with dependency resolution.
    """
    cleanup_called = False

    @register_provider()
    async def database_connection() -> MagicMock:
        return mock_database_connection

    @register_provider()
    async def database_session(conn: Any = Depends[database_connection]) -> AsyncGenerator[dict[str, Any], None]:
        # This generator provider depends on database_connection
        # Use a simple object instead of MagicMock
        session = {
            "connection": conn,
            "data": "session_data"
        }
        yield session

        # Cleanup code
        nonlocal cleanup_called
        cleanup_called = True
        await conn.close()

    @inject
    async def get_session(session: Any = Depends[database_session]) -> Any:
        return session

    setup()

    # Execute
    result = await get_session()

    # Verify the dependency was resolved correctly
    assert result["connection"] == mock_database_connection

    # Verify cleanup was called
    assert cleanup_called


@pytest.mark.skip_wire
async def test_multiple_chained_provider_dependencies(mocker: MockerFixture) -> None:
    """Test provider chain: A depends on B, B depends on C.

    This tests complex dependency resolution through multiple layers.
    """

    @register_provider()
    async def config_provider() -> dict[str, str]:
        return {"db_host": "localhost"}

    @register_provider()
    async def connection_provider(cfg: Any = Depends[config_provider]) -> dict[str, str]:
        return {"host": cfg["db_host"]}

    @register_provider()
    async def session_provider(conn: Any = Depends[connection_provider]) -> dict[str, Any]:
        return {"connection": conn, "data": ["data"]}

    @inject
    async def get_data(session: Any = Depends[session_provider]) -> list[str]:
        return session["data"]

    setup()

    # Execute
    result = await get_data()

    # Verify the entire chain worked
    assert result == ["data"]


@pytest.mark.skip_wire
async def test_provider_with_multiple_dependencies(mocker: MockerFixture) -> None:
    """Test provider that depends on multiple other providers.

    This tests dependency resolution with multiple Depends markers.
    """

    @register_provider()
    async def auth_provider() -> dict[str, str]:
        return {"token": "secret_token"}

    @register_provider()
    async def config_provider() -> dict[str, str]:
        return {"api_url": "https://api.example.com"}

    @register_provider()
    async def api_client_provider(
        auth: Any = Depends[auth_provider],
        cfg: Any = Depends[config_provider]
    ) -> dict[str, str]:
        return {
            "url": cfg["api_url"],
            "token": auth["token"]
        }

    @inject
    async def make_request(client: Any = Depends[api_client_provider]) -> dict[str, str]:
        return client

    setup()

    # Execute
    result = await make_request()

    # Verify both dependencies were resolved
    assert result["url"] == "https://api.example.com"
    assert result["token"] == "secret_token"


@pytest.mark.skip_wire
def test_sync_provider_with_sync_dependency(mocker: MockerFixture) -> None:
    """Test sync provider that depends on another sync provider.

    This tests sync provider dependency resolution.
    """

    @register_provider()
    def base_value() -> int:
        return 42

    @register_provider()
    def derived_value(base: Any = Depends[base_value]) -> int:
        return base * 2

    @inject
    def get_value(val: Any = Depends[derived_value]) -> int:
        return val

    setup()

    # Execute
    result = get_value()

    # Verify
    assert result == 84

    # Suppress unused parameter warning
    _ = mocker
