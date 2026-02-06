from typing import Any, AsyncGenerator, Callable, Coroutine
import pytest
from pydantic import SecretStr
from sqlalchemy import Column, Integer, String, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base

from s2auth.server.config import Config, config
from s2auth.server.db import async_session
from s2auth.server.dependencies import Depends, inject, provider_overrides, setup

# Create a simple SQLAlchemy model for testing
Base = declarative_base()


class _TestUser(Base):
    __tablename__ = "test_users"
    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False)


# Type alias for the test fixture return type
DbConfigFixture = tuple[
    Callable[[], Coroutine[Any, Any, Config]],  # test_config_provider
    Callable[..., AsyncGenerator[AsyncSession, None]],  # test_async_session_provider
]


@pytest.fixture(scope="session")
async def test_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Session-scoped fixture that creates a test database engine."""
    import tempfile

    # Use a temporary file-based SQLite database
    # This ensures all connections see the same database
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        # Ensure proper transaction isolation
        # Note: Don't set isolation_level=None as that enables autocommit in SQLite
        connect_args={},  # Use default isolation (DEFERRED for SQLite)
    )

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Cleanup
    await engine.dispose()
    import os

    os.unlink(db_path)


@pytest.fixture
async def test_db_config(test_engine: AsyncEngine) -> DbConfigFixture:
    """Fixture that provides config and async_session provider override."""
    # Clean up database before each test
    async with test_engine.begin() as conn:
        await conn.execute(_TestUser.__table__.delete())

    # Create config pointing to the test database
    test_config = Config(sqlalchemy_db_uri=SecretStr("sqlite+aiosqlite:///:memory:"))

    async def test_config_provider() -> Config:
        return test_config

    # Override async_session to use the shared test engine
    async def test_async_session_provider(cfg: Config = Depends[config]):
        session = AsyncSession(test_engine, expire_on_commit=False)
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

    # Return both override functions
    return test_config_provider, test_async_session_provider


@pytest.mark.skip_wire
async def test_async_session_commits_on_success(
    test_db_config: DbConfigFixture,
) -> None:
    """Test that async_session commits when no exception is raised."""
    test_config_provider, test_async_session_provider = test_db_config

    # Override the config and async_session providers
    with provider_overrides(
        {config: test_config_provider, async_session: test_async_session_provider}
    ):
        setup()

        @inject
        async def insert_user(
            name: str, session: AsyncSession = Depends[async_session]
        ) -> int:
            """Insert a user and return their ID."""
            user = _TestUser(name=name)
            session.add(user)
            await session.flush()
            assert isinstance(user.id, int), "Expected user.id to be an int after flush"
            return user.id

        @inject
        async def get_user_count(session: AsyncSession = Depends[async_session]) -> int:
            """Count users in the database."""
            result = await session.execute(select(_TestUser))
            return len(result.scalars().all())

        # Insert a user - should commit automatically
        user_id = await insert_user("Alice")
        assert user_id is not None

        # Verify the user was committed to the database
        count = await get_user_count()
        assert count == 1


@pytest.mark.skip_wire
async def test_async_session_rollback_on_error(
    test_db_config: DbConfigFixture,
) -> None:
    """Test that async_session rolls back when an exception is raised."""
    test_config_provider, test_async_session_provider = test_db_config

    with provider_overrides(
        {config: test_config_provider, async_session: test_async_session_provider}
    ):
        setup()

        @inject
        async def insert_user_with_error(
            name: str, session: AsyncSession = Depends[async_session]
        ) -> None:
            """Insert a user but then raise an error."""
            user = _TestUser(name=name)
            session.add(user)
            await session.flush()
            # Simulate an error after the insert
            raise ValueError("Simulated error during transaction")

        @inject
        async def get_user_count(session: AsyncSession = Depends[async_session]) -> int:
            """Count users in the database."""
            result = await session.execute(select(_TestUser))
            return len(result.scalars().all())

        # Verify database starts empty
        initial_count = await get_user_count()
        assert initial_count == 0

        # Try to insert a user but encounter an error
        with pytest.raises(ValueError, match="Simulated error"):
            await insert_user_with_error("Bob")

        # Verify the transaction was rolled back - no user should be in the database
        final_count = await get_user_count()
        assert final_count == 0


@pytest.mark.skip_wire
async def test_async_session_runs_query_successfully(
    test_db_config: DbConfigFixture,
) -> None:
    """Test that a function can run a single query using async_session."""
    test_config_provider, test_async_session_provider = test_db_config

    with provider_overrides(
        {config: test_config_provider, async_session: test_async_session_provider}
    ):
        setup()

        @inject
        async def create_and_query_user(
            session: AsyncSession = Depends[async_session],
        ) -> str:
            """Create a user and query it back."""
            # Insert a user
            user = _TestUser(name="Charlie")
            session.add(user)
            await session.flush()

            # Query the user back
            result = await session.execute(
                select(_TestUser).where(_TestUser.name == "Charlie")
            )
            queried_user = result.scalar_one()
            return str(queried_user.name)

        # Run the function
        name = await create_and_query_user()
        assert name == "Charlie"

        # Verify it was committed
        @inject
        async def verify_user_exists(
            session: AsyncSession = Depends[async_session],
        ) -> bool:
            result = await session.execute(
                select(_TestUser).where(_TestUser.name == "Charlie")
            )
            return result.scalar_one_or_none() is not None

        assert await verify_user_exists()


@pytest.mark.skip_wire
async def test_async_session_multiple_operations(
    test_db_config: DbConfigFixture,
) -> None:
    """Test that multiple database operations work correctly within a session."""
    test_config_provider, test_async_session_provider = test_db_config

    with provider_overrides(
        {config: test_config_provider, async_session: test_async_session_provider}
    ):
        setup()

        @inject
        async def bulk_operations(
            session: AsyncSession = Depends[async_session],
        ) -> int:
            """Perform multiple operations in a single transaction."""
            # Insert multiple users
            for name in ["David", "Eve", "Frank"]:
                user = _TestUser(name=name)
                session.add(user)

            await session.flush()

            # Query all users
            result = await session.execute(select(_TestUser))
            users = result.scalars().all()
            return len(users)

        count = await bulk_operations()
        assert count == 3

        # Verify all were committed
        @inject
        async def get_all_names(
            session: AsyncSession = Depends[async_session],
        ) -> list[str]:
            result = await session.execute(
                select(_TestUser.name).order_by(_TestUser.name)
            )
            return list(result.scalars().all())

        names = await get_all_names()
        assert names == ["David", "Eve", "Frank"]
