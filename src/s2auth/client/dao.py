from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import Select, String, create_engine, select
from sqlalchemy.orm import (Mapped, Session, declarative_base, mapped_column,
                            sessionmaker)

Base = declarative_base()


class ConnectionDetail(Base):
    __tablename__ = "connection_details"

    pairing_uri: Mapped[str] = mapped_column(String, nullable=False, index=True, primary_key=True)
    s2_node_id: Mapped[str] = mapped_column(String, nullable=False, index=True, primary_key=True)
    auth_token: Mapped[str] = mapped_column(String, nullable=False)


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
        self._session: Session = self._SessionLocal()

    def store_connection_details(self, pairing_uri: str, s2_node_id: str, token: str) -> None:
        """
        Insert or update a connection detail identified by s2_node_id
        """
        with self._session.begin():
            obj: ConnectionDetail = self._session.query(ConnectionDetail).filter(ConnectionDetail.pairing_uri == pairing_uri, ConnectionDetail.s2_node_id == s2_node_id).one_or_none()

            if obj:
                # Update existing record
                obj.auth_token = token
            else:
                # Insert new record
                obj = ConnectionDetail(
                    pairing_uri=pairing_uri,
                    s2_node_id=s2_node_id,
                    auth_token=token,
                )
                self._session.add(obj)

    def load_connection_details(self, pairing_uri: str, s2_node_id: str) -> Optional[str]:
        """
        Return the most recently inserted/updated auth_token for the given s2_node_id.
        (Uses id DESC to mimic the original intent to get the 'latest' record.)
        Returns None if nothing is found.
        """
        stmt: Select[Any] = (
            select(ConnectionDetail.auth_token)
            .where(ConnectionDetail.pairing_uri == pairing_uri,
                   ConnectionDetail.s2_node_id == s2_node_id)
            .limit(1)
        )
        return self._session.execute(stmt).scalars().first()

    def close(self) -> None:
        """Close the session and dispose the engine."""
        if self._session:
            self._session.close()
        if self._engine:
            self._engine.dispose()

    def __del__(self) -> None:
        # Best-effort cleanup (avoid exceptions during GC)
        try:
            self.close()
        except Exception:
            pass