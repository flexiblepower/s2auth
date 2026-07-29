from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import Boolean, Select, String, create_engine, select
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import (Mapped, declarative_base, mapped_column,
                            sessionmaker)

Base = declarative_base()


class ConnectionDetail(Base):
    __tablename__ = "connection_details"

    s2_node_id: Mapped[str] = mapped_column(String, nullable=False, index=True, primary_key=True)
    client_s2_node_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    pairing_server_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    verify_tls: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    ca_cert_file: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    initiateSessionUrl: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    accessToken: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    supportedS2MessageVersion: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    selectedCommunicationProtocol: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    serverNodeDescription: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    serverEndpointDescription: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    websocketToken: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    websocketUrl: Mapped[Optional[str]] = mapped_column(String, nullable=True)

class Dao:
    """
    SQLAlchemy-backed data access object for storing/loading connection details.
    Default database is SQLite file 'connection_details.db'.
    """

    def __init__(self, db_url: str = "sqlite:///connection_details.db") -> None:
        # Create engine & session factory
        self._engine = create_engine(db_url, future=True)
        Base.metadata.create_all(self._engine)

        self._SessionLocal = sessionmaker(
            bind=self._engine,
            autoflush=False,
            autocommit=False,
            future=True,
        )

    def store_connection_details(self, s2_node_id: str, details: dict[str, Any]) -> None:
        """
        Insert or overwrite a connection detail identified by s2_node_id.
        """
        with self._SessionLocal() as session:
            with session.begin():
                obj = session.query(ConnectionDetail).filter(ConnectionDetail.s2_node_id == s2_node_id).one_or_none()

                if obj is None:
                    obj = ConnectionDetail(s2_node_id=s2_node_id)
                    session.add(obj)

                for detail_key, model_attr in details.items():
                    setattr(obj, detail_key, model_attr)

    def load_connection_details(self, s2_node_id: str) -> Optional[dict[str, Any]]:
        """Load the full connection details object for the given node ID."""
        stmt: Select[Any] = (
            select(ConnectionDetail)
            .where(ConnectionDetail.s2_node_id == s2_node_id)
            .limit(1)
        )
        with self._SessionLocal() as session:
            obj = session.execute(stmt).scalars().first()
            if obj is None:
                return None
            return {c.key: getattr(obj, c.key) for c in inspect(obj).mapper.column_attrs}

    def remove_connection_details(self, s2_node_id: str) -> bool:
        """Remove connection details for the given node ID.

        Returns True when an entry was deleted, otherwise False.
        """
        stmt: Select[Any] = (
            select(ConnectionDetail)
            .where(ConnectionDetail.s2_node_id == s2_node_id)
            .limit(1)
        )
        with self._SessionLocal() as session:
            with session.begin():
                obj = session.execute(stmt).scalars().first()
                if obj is None:
                    return False
                session.delete(obj)
            return True
