from fastapi import Request
from pydantic import AnyUrl
from wepositive_di import Depends, inject

from s2auth.reference.server.context import current_request
from s2auth.server.context import ReadOnlyAuthenticationContext
from s2auth.server.hooks import (
    get_server_connection_initiation_endpoint,
    register_hook,
)


@register_hook(get_server_connection_initiation_endpoint)
@inject
async def reference_server_connection_initiation_endpoint(
    authentication_context: ReadOnlyAuthenticationContext,
    request: Request = Depends[current_request],
) -> AnyUrl:
    """Return the reference server connection initiation endpoint."""
    _ = authentication_context
    return AnyUrl(str(request.url_for("connection_root")))
