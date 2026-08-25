from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class StoredObject(Base):
    """Database model for storing pydantic objects as JSON."""

    __tablename__ = "stored_objects"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    timestamp_received = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    object_type = Column(String, nullable=False, index=True)
    data = Column(Text, nullable=False)  # JSON stored as TEXT for SQLite compatibility
