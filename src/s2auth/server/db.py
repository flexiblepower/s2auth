from contextlib import asynccontextmanager

from s2auth.server.config import Config, config
from wepositive_di import Depends, register_provider
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


@register_provider(context_manager=True)
@asynccontextmanager
async def async_session(cfg: Config = Depends[config]):
    engine = create_async_engine(cfg.sqlalchemy_db_uri.get_secret_value())
    session = AsyncSession(engine)
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
