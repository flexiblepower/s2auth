from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from s2auth.common.dependencies import Depends, inject
from s2auth.server.db import async_session
from s2auth.server.models import StoredObject


@inject
async def store_object(
    object: BaseModel, async_session: AsyncSession = Depends[async_session]
) -> None:
    """Store a pydantic object in the database as JSON.

    Args:
        object: Any pydantic BaseModel instance to store
        async_session: Database session (injected via dependency injection)
    """
    # Get the object type name
    object_type = type(object).__name__

    # Convert pydantic object to JSON string
    json_data = object.model_dump_json()

    # Create database record (ID will be auto-generated)
    stored_obj = StoredObject(
        object_type=object_type,
        data=json_data,
    )

    # Add to session (will be committed by the async_session provider)
    async_session.add(stored_obj)
