from s2auth.server.dependencies import register_provider, Depends
from pydantic import BaseModel


class ClientContext(BaseModel):
    state: str = "default"


ClientNodeId = int
_client_states: dict[ClientNodeId, ClientContext] = {}


@register_provider(singleton=True)
def context_singleton() -> dict[ClientNodeId, ClientContext]:
    """Singleton provider to maintain state dictionary."""
    return _client_states


@register_provider()
def client_node_id() -> int:
    """Returns a static client node ID."""
    return 42  # pragma: no cover  # TODO: Still to be implemented


@register_provider()
def client_context(
    client_node_id: int = Depends[client_node_id],
    context_singleton: dict[int, ClientContext] = Depends[context_singleton],
) -> ClientContext:
    """Retrieves or initializes the context for the specified client_node_id."""
    if client_node_id not in context_singleton:
        context_singleton[client_node_id] = ClientContext()
    return context_singleton[client_node_id]
