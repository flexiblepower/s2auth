from __future__ import annotations

from typing import Any, Protocol


class ConnectionStore(Protocol):
    """Storage interface used by pairing client flows."""

    def store_connection_details(self, s2_node_id: str, details: dict[str, Any]) -> None:
        ...

    def load_connection_details(self, s2_node_id: str) -> dict[str, Any] | None:
        ...

    def remove_connection_details(self, s2_node_id: str) -> bool:
        ...
