"""Public re-exports for S2 common data models.

Library users can import frequently used protocol models directly from
`s2auth.common.model` instead of importing from each generated submodule.
"""

from __future__ import annotations

from types import ModuleType
from typing import Annotated, cast

from pydantic import BaseModel, Field

from . import s2_connect_common as _s2_connect_common
from . import s2_connect_pairing as _s2_connect_pairing
from . import s2_connect_session_init as _s2_connect_session_init
from . import s2_connect_wan_endpoint_registry as _s2_connect_wan_endpoint_registry
from .s2_connect_wan_endpoint_registry import CountryCode, Status

# Also expose generated submodules so users can access every symbol, including
# names that collide across files (for example multiple ErrorMessage enums).
s2_connect_common = _s2_connect_common
s2_connect_pairing = _s2_connect_pairing
s2_connect_session_init = _s2_connect_session_init
s2_connect_wan_endpoint_registry = _s2_connect_wan_endpoint_registry


def _collect_module_exports(module: ModuleType) -> dict[str, object]:
    exports: dict[str, object] = {}
    module_vars = cast(dict[str, object], vars(module))
    for name, value in module_vars.items():
        if name.startswith("_"):
            continue
        if getattr(value, "__module__", None) == module.__name__:
            exports[name] = value
    return exports


_reexports: dict[str, object] = {}
for _module in (
    _s2_connect_common,
    _s2_connect_pairing,
    _s2_connect_session_init,
    _s2_connect_wan_endpoint_registry,
):
    _reexports.update(_collect_module_exports(_module))

globals().update(_reexports)


class EndpointGetParametersQuery(BaseModel):
    region: list[CountryCode] | None = None
    status: Status | None = Status.public
    cem: bool | None = None
    rm: bool | None = None
    limit: Annotated[int | None, Field(ge=1)] = None
    offset: Annotated[int | None, Field(ge=0)] = None


del _reexports
