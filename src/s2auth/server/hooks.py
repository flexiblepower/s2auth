"""Server hooks for customizing S2 authentication behavior.

This module provides hooks that can be overridden to customize the behavior
of the S2 authentication server. Each hook is registered in a HookRegistry
and can be replaced by client code.

See docs/hooks.md for detailed documentation on each hook and how to override them.
"""

from typing import Any, Callable

from pydantic import AnyUrl

from wepositive_di import Depends, inject, register_provider
from s2auth.common.model.s2_connect_common import NodeId, Role
from s2auth.common.model.s2_connect_pairing import (
    EndpointDescription,
    NodeDescription,
)
from s2auth.server.context import (
    ReadOnlyAuthenticationContext,
    ReadOnlyPairingAttemptContext,
)
from s2auth.server.settings import Settings, settings


@inject
async def get_server_endpoint(
    authentication_context: ReadOnlyAuthenticationContext,
    server_settings: Settings = Depends[settings],
) -> AnyUrl | None:
    """Default hook implementation to get the server endpoint.

    This hook is called during the pairing phase to retrieve the server's endpoint
    so the S2 Client Node can connect to the server side to establish an S2 connection.

    Args:
        authentication_context: Read-only view of the authentication context (contains client_node_id, state, etc.)
        server_settings: Server configuration settings
    """
    return server_settings.cem_url


@inject
async def pairing_attempt_request(
    authentication_context: ReadOnlyAuthenticationContext,
    pairing_context: ReadOnlyPairingAttemptContext,
    server_settings: Settings = Depends[settings],
) -> tuple[EndpointDescription, NodeDescription]:
    """Default hook implementation for pairing request.

    This hook is called during the pairing request phase to generate the server's
    S2 endpoint and node descriptions. Override this hook to customize the server's
    identity or to refuse pairing by raising an S2PairingError.

    Args:
        authentication_context: Read-only view of the authentication context (contains client_node_id, state, etc.)
        pairing_context: Read-only view of the pairing attempt context (contains pairing_attempt_id, pairing_token, etc.)
        server_settings: Server configuration settings

    Returns:
        A tuple of (EndpointDescription, NodeDescription) for the server

    Raises:
        S2PairingError: To refuse the pairing attempt with a specific error message
    """
    # Default implementation: return basic server descriptions from settings
    endpoint_description = EndpointDescription()
    node_description = NodeDescription(
        id=NodeId(root=server_settings.cem_s2_node_id),
        brand=server_settings.cem_brand,
        role=Role.CEM,
        type=server_settings.cem_type,
        modelName=server_settings.cem_model_name,
    )
    return endpoint_description, node_description


class HookRegistry:
    """Registry for server hooks that can be overridden by client code."""

    def __init__(self) -> None:
        # Initialize with default hook implementations
        self._hooks: dict[Callable[..., Any], Callable[..., Any]] = {
            pairing_attempt_request: pairing_attempt_request,
        }

    def register(
        self, original_hook: Callable[..., Any], custom_hook: Callable[..., Any]
    ) -> None:
        """Register a custom hook implementation.

        Args:
            original_hook: The original hook function to override
            custom_hook: The custom hook implementation function

        Raises:
            RuntimeError: If a custom implementation is already registered for this hook
            KeyError: If the original hook is not recognized
        """
        if original_hook not in self._hooks:
            raise KeyError(
                f"Unknown hook function. Available hooks: {list(self._hooks.keys())}"
            )
        if self._hooks[original_hook] is not original_hook:
            raise RuntimeError(
                "Hook already has a custom implementation registered. "
                "Each hook can only be overridden once."
            )
        self._hooks[original_hook] = custom_hook

    def get(self, hook: Callable[..., Any]) -> Callable[..., Any]:
        """Get a hook implementation (default or custom).

        Args:
            hook: The hook function reference

        Returns:
            The hook implementation function (either default or custom)

        Raises:
            KeyError: If the hook is not registered
        """
        if hook not in self._hooks:
            raise KeyError("Hook is not registered")
        return self._hooks[hook]


@register_provider(singleton=True)
def hook_registry() -> HookRegistry:
    """Provider for the hook registry singleton."""
    return HookRegistry()


def register_hook(
    original_hook: Callable[..., Any],
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator to register a custom hook implementation.

    This decorator allows client code to override default hook implementations.
    Each hook can only be overridden once.

    Args:
        original_hook: The original hook function to override

    Returns:
        Decorator function

    Raises:
        RuntimeError: If the hook is already registered by custom code
        KeyError: If the hook is not recognized

    Example:
        ```python
        from s2auth.server import hooks
        from wepositive_di import Depends, inject

        @register_hook(hooks.pairing_attempt_request)
        @inject
        async def my_pairing_hook(
            authentication_context: AuthenticationContext,
            pairing_context: PairingAttemptContext,
            server_settings: Settings = Depends[settings],
        ) -> tuple[EndpointDescription, NodeDescription]:
            # Custom implementation
            ...
        ```
    """

    def decorator(custom_hook: Callable[..., Any]) -> Callable[..., Any]:
        # Get the singleton registry instance by calling the provider
        registry = hook_registry()
        registry.register(original_hook, custom_hook)
        return custom_hook

    return decorator
