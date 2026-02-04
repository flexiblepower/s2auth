from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from s2auth.server.dependencies import inject, Depends
from s2auth.server.db import async_session


@inject
async def store_object(
    object: BaseModel, async_session: AsyncSession = Depends[async_session]
):
    pass
