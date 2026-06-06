from typing import Any, Annotated, cast
from uuid import UUID

from fastapi import Header, Request

from s2auth.common.model.s2_connect_common import NodeId
from s2auth.common.model.s2_connect_pairing import PairingAttemptId
from s2auth.server.context import (
    pairing_attempt_id_var,
    s2_client_node_id_var,
)


def set_client_node_id(client_node_id: NodeId) -> None:
    """Set the client node context for the current request."""
    s2_client_node_id_var.set(client_node_id)


def set_pairing_attempt_id(pairing_attempt_id: PairingAttemptId) -> None:
    """Set the pairing attempt context for the current request."""
    pairing_attempt_id_var.set(pairing_attempt_id)


def _root_value(value: Any) -> Any:
    if isinstance(value, dict):
        value_dict = cast(dict[str, Any], value)
        return value_dict.get("root")
    return value


async def _json_body(request: Request) -> Any:
    return await request.json()


async def set_client_node_id_from_body_variable(request: Request) -> None:
    """Set client node context from a top-level clientNodeId body field."""
    body = await _json_body(request)
    set_client_node_id(NodeId(root=_root_value(body["clientNodeId"])))


async def set_client_node_id_from_body_node_description(request: Request) -> None:
    """Set client node context from a top-level clientNodeDescription.id field."""
    body = await _json_body(request)
    set_client_node_id(NodeId(root=_root_value(body["clientNodeDescription"]["id"])))


async def set_client_node_id_from_first_body_item(request: Request) -> None:
    """Set client node context from clientNodeId on the first item in a list body."""
    body = await _json_body(request)
    if body:
        set_client_node_id(NodeId(root=_root_value(body[0]["clientNodeId"])))


def set_client_node_id_from_headers(
    client_node_id: Annotated[str, Header(alias="clientNodeId")],
) -> None:
    """Set client node context from the clientNodeId header."""
    set_client_node_id(NodeId(root=UUID(client_node_id)))


def set_pairing_attempt_id_from_headers(
    pairing_attempt_id: Annotated[str, Header(alias="pairingAttemptId")],
) -> None:
    """Set pairing attempt context from the pairingAttemptId header."""
    set_pairing_attempt_id(PairingAttemptId(root=pairing_attempt_id.encode("utf-8")))
