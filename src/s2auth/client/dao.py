from __future__ import annotations

from typing import Any, Optional, cast

from sqlalchemy import Select, String, create_engine, select
from sqlalchemy.orm import (Mapped, declarative_base, mapped_column,
                            sessionmaker)

Base = declarative_base()


class ConnectionDetail(Base):
    __tablename__ = "connection_details"

    s2_node_id: Mapped[str] = mapped_column(String, nullable=False, index=True, primary_key=True)
    auth_token: Mapped[str] = mapped_column(String, nullable=False)
    pending_token: Mapped[str] = mapped_column(String, nullable=True)
    supported_s2_message_version: Mapped[str] = mapped_column(String, nullable=True)
    selected_communication_protocol: Mapped[str] = mapped_column(String, nullable=True)
    websocketToken: Mapped[str] = mapped_column(String, nullable=True)
    websocketUrl: Mapped[str] = mapped_column(String, nullable=True)



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

    def store_connection_details(self, s2_node_id: str, token: str) -> None:
        """
        Insert or update a connection detail identified by s2_node_id
        """
        with self._SessionLocal() as session:
            with session.begin():
                obj: ConnectionDetail = \
                    session.query(ConnectionDetail).filter(ConnectionDetail.s2_node_id == s2_node_id).one_or_none()

                if obj:
                    # Update existing record
                    obj.auth_token = token
                else:
                    # Insert new record
                    obj = ConnectionDetail(
                        s2_node_id=s2_node_id,
                        auth_token=token,
                    )
                    session.add(obj)

    def store_pending_token(self, s2_node_id: str, pending_token: str, supported_s2_message_version: str, selected_communication_protocol: str) -> None:
        """Store the pending token"""
        with self._SessionLocal() as session:
            with session.begin():
                obj: ConnectionDetail = \
                    session.query(ConnectionDetail).filter(ConnectionDetail.s2_node_id == s2_node_id).one()
                obj.pending_token = pending_token
                obj.supported_s2_message_version = supported_s2_message_version
                obj.selected_communication_protocol = selected_communication_protocol

    def store_ws_connection_details(self, s2_node_id: str, websocketToken: str, websocketUrl: str) -> None:
        """Store the pending token"""
        with self._SessionLocal() as session:
            with session.begin():
                obj: ConnectionDetail = \
                    session.query(ConnectionDetail).filter(ConnectionDetail.s2_node_id == s2_node_id).one()
                obj.websocketToken = websocketToken
                obj.websocketUrl = websocketUrl

    def load_token(self, s2_node_id: str) -> Optional[str]:
        """
        Return the most recently inserted/updated auth_token for the given s2_node_id.
        (Uses id DESC to mimic the original intent to get the 'latest' record.)
        Returns None if nothing is found.
        """
        stmt: Select[Any] = (
            select(ConnectionDetail.auth_token)
            .where(ConnectionDetail.s2_node_id == s2_node_id)
            .limit(1)
        )
        with self._SessionLocal() as session:
            return session.execute(stmt).scalars().first()

    def load_pending_token(self, s2_node_id: str) -> Optional[str]:
        """
        Return the most recently inserted/updated auth_token for the given s2_node_id.
        (Uses id DESC to mimic the original intent to get the 'latest' record.)
        Returns None if nothing is found.
        """
        stmt: Select[Any] = (
            select(ConnectionDetail.pending_token)
            .where(ConnectionDetail.s2_node_id == s2_node_id)
            .limit(1)
        )
        with self._SessionLocal() as session:
            return session.execute(stmt).scalars().first()

    def load_ws_connection_details(self, s2_node_id: str) -> tuple[str, str]:
        """
        Return the most recently inserted/updated auth_token for the given s2_node_id.
        (Uses id DESC to mimic the original intent to get the 'latest' record.)
        Returns None if nothing is found.
        """
        stmt: Select[Any] = (
            select(ConnectionDetail.websocketToken, ConnectionDetail.websocketUrl)
            .where(ConnectionDetail.s2_node_id == s2_node_id)
            .limit(1)
        )
        ws_token: str = ""
        ws_url: str = ""
        with self._SessionLocal() as session:
            row = session.execute(stmt).first()
            if row is not None:
                ws_token = cast(str, row[0])
                ws_url = cast(str, row[1])
        return ws_token, ws_url
