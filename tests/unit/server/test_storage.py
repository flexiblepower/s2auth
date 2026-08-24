from typing import Any, AsyncGenerator, Callable, Coroutine
import json
from contextlib import AbstractAsyncContextManager, asynccontextmanager
import pytest
from base64 import b64decode, b64encode
from pydantic import AnyUrl, SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from s2auth.server.storage import store_object
from s2auth.server.models import Base, StoredObject
from s2auth.common.model.s2_connect_common import AccessToken
from s2auth.common.model.s2_connect_pairing import ConnectionDetails
from s2auth.server.config import Config, config
from s2auth.server.db import async_session
from wepositive_di import Depends, provider_overrides, setup


# Type alias for the test fixture return type
StorageDbFixture = tuple[
    Callable[[], Coroutine[Any, Any, Config]],  # test_config_provider
    Callable[..., AbstractAsyncContextManager[AsyncSession]],  # test_async_session_provider
    AsyncEngine,  # test_storage_engine
]


@pytest.fixture(scope="session")
async def test_storage_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Session-scoped fixture that creates a test database engine for storage tests."""
    import tempfile

    # Use a temporary file-based SQLite database
    # This ensures all connections see the same database
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", connect_args={})

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Cleanup
    await engine.dispose()
    import os

    os.unlink(db_path)


@pytest.fixture
async def test_storage_db(test_storage_engine: AsyncEngine) -> StorageDbFixture:
    """Fixture that provides clean database for each storage test."""
    # Clean up database before each test
    async with test_storage_engine.begin() as conn:
        await conn.execute(StoredObject.__table__.delete())

    # Create config pointing to the test database (not used, we override the session directly)
    test_config = Config(sqlalchemy_db_uri=SecretStr("sqlite+aiosqlite:///:memory:"))

    async def test_config_provider() -> Config:
        return test_config

    # Override async_session to use the shared test engine
    # This ensures all operations use the same database connection
    @asynccontextmanager
    async def test_async_session_provider(cfg: Config = Depends[config]):
        session = AsyncSession(test_storage_engine, expire_on_commit=False)
        try:
            yield session
            # If we get here, no exception was raised, so commit
            await session.commit()
        except Exception:
            # If an exception was raised, rollback
            await session.rollback()
            raise
        finally:
            # Always close the session
            await session.close()

    # Return both override functions and the engine
    return test_config_provider, test_async_session_provider, test_storage_engine


@pytest.mark.skip_wire
async def test_store_object(test_storage_db: StorageDbFixture) -> None:
    """Test that store_object correctly stores a pydantic object as JSON in the database."""
    test_config_provider, test_async_session_provider, engine = test_storage_db

    with provider_overrides(
        {config: test_config_provider, async_session: test_async_session_provider}
    ):
        setup()

        # Create a test object
        token = "sometoken"
        test_connection_details = ConnectionDetails(
            initiateSessionUrl=AnyUrl("http://test.com/1234"),
            accessToken=AccessToken(
                root=b64encode(token.encode("utf-8"))
            ),
        )

        # Store the object using the injected session
        await store_object(test_connection_details)

        # Verify it was stored in the database using a NEW session from the same engine
        # This ensures we're reading what was actually committed to the database
        async with AsyncSession(engine, expire_on_commit=False) as session:
            result = await session.execute(select(StoredObject))
            stored_objects = result.scalars().all()

            # Should have exactly one stored object
            assert len(stored_objects) == 1

            stored_obj = stored_objects[0]

            # Verify the object type
            assert str(stored_obj.object_type) == "ConnectionDetails"

            # Verify the timestamp is set
            assert stored_obj.timestamp_received is not None

            # Verify the UUID ID was generated
            assert str(stored_obj.id) is not None

            # Verify the data was stored correctly as JSON (stored as TEXT)
            assert stored_obj.data is not None
            assert isinstance(stored_obj.data, str), "Data should be stored as text"
            data_dict = json.loads(stored_obj.data)
            assert data_dict["initiateSessionUrl"] == "http://test.com/1234"
            assert b64decode(data_dict["accessToken"]).decode("utf-8") == token

            # Verify we can reconstruct the object from stored JSON
            reconstructed = ConnectionDetails.model_validate(data_dict)
            assert (
                reconstructed.initiateSessionUrl
                == test_connection_details.initiateSessionUrl
            )
            assert reconstructed.accessToken is not None
            assert test_connection_details.accessToken is not None
            assert (
                reconstructed.accessToken.root
                == test_connection_details.accessToken.root
            )
