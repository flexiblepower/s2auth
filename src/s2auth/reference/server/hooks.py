from pydantic import AnyUrl

from s2auth.server.context import ReadOnlyAuthenticationContext
from s2auth.server.hooks import (
    get_server_connection_initiation_endpoint,
    register_hook,
)


@register_hook(get_server_connection_initiation_endpoint)
async def reference_server_connection_initiation_endpoint(
    authentication_context: ReadOnlyAuthenticationContext,
) -> AnyUrl:
    """Return the reference server connection initiation endpoint."""
    _ = authentication_context
    return AnyUrl("http://localhost:8000/connection/")
