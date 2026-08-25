from collections.abc import Iterable
from importlib import import_module

import wepositive_di


def setup(additional_hook_modules: Iterable[str] | None = None) -> None:
    """Import hook modules and initialize wepositive-di."""
    import_module("s2auth.server.hooks")
    for module_name in additional_hook_modules or ():
        import_module(module_name)
    wepositive_di.setup()
