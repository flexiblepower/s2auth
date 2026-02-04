from s2auth.server.config import Config, config
from s2auth.server.dependencies import Depends, register_provider
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


@register_provider()
async def async_session(cfg: Config = Depends[config]):
    engine = create_async_engine(cfg.sqlalchemy_db_uri.get_secret_value())
    session = AsyncSession(engine)
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
