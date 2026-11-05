"""Local DNS-SD discovery helpers for S2 services.

This module wraps zeroconf browsing for ``_s2connect._tcp.local.`` and keeps
discovered ``ServiceInfo`` objects in a mutable mapping provided by
``S2Discovery``.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
from zeroconf import ServiceBrowser, ServiceInfo, ServiceListener, Zeroconf

from s2auth.client.pairing_core import HttpEventHooks, build_httpx_verify, resolve_http_hooks


ServiceCallback = Callable[[int, str, ServiceInfo], None]


@dataclass
class S2Discovery:
    """Owns zeroconf resources and tracks discovered S2 DNS-SD services.

    Keep an instance alive while browsing. Closing the instance stops discovery
    by closing the underlying ``Zeroconf`` client.
    """

    on_service: ServiceCallback | None = None
    services: dict[str, ServiceInfo] = field(default_factory=dict[str, ServiceInfo])

    def __post_init__(self) -> None:
        # Initialize zeroconf objects once and keep references on the instance.
        # Browsing starts immediately after ServiceBrowser creation.
        self._zeroconf = Zeroconf()
        self._listener = _DiscoveryListener(
            self.services,
            self.on_service,
        )
        self._browser = ServiceBrowser(
            self._zeroconf,
            "_s2connect._tcp.local.",
            self._listener,
        )

    def close(self) -> None:
        # Explicitly release network resources and stop mDNS browsing.
        self._zeroconf.close()

    def __enter__(self):
        # Context-manager support allows: ``with S2Discovery() as d: ... in order to keep the instance alive while browsing.``
        return self

    def __exit__(self, *args: Any) -> None:
        # Always clean up zeroconf resources when leaving context scope.
        self.close()

    @staticmethod
    async def fetch_nodes(
        base_url: str,
        timeout_seconds: float = 5.0,
        verify_tls: bool = True,
        ssl_certfile: str | None = None,
        http_event_hooks: HttpEventHooks | None = None,
    ) -> list[dict[str, Any]] :
        """Call ``<base_url>/v1/nodes`` and return the parsed JSON response."""

        httpx_verify = build_httpx_verify(verify_tls, ssl_certfile)
        event_hooks = resolve_http_hooks(http_event_hooks)

        nodes_url = base_url.rstrip("/")
        if not nodes_url.endswith("/v1/nodes"):
            if not nodes_url.endswith("/v1"):
                nodes_url += "/v1"
            nodes_url += "/nodes"

        async with httpx.AsyncClient(verify=httpx_verify, event_hooks=event_hooks) as client:
            response = await client.get(nodes_url, timeout=timeout_seconds)
        return response.json()


class _DiscoveryListener(ServiceListener):
    """Receives zeroconf events and keeps the shared service map in sync."""

    def __init__(
        self,
        services: dict[str, ServiceInfo],
        on_service: ServiceCallback | None = None,
    ) -> None:
        self.services = services
        self.on_service = on_service

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        # Resolve full ServiceInfo for newly discovered service names.
        info = zc.get_service_info(type_, name)

        if info is not None:
            self.services[name] = info

            if self.on_service:
                # Callback receives current index, service name, and ServiceInfo.
                self.on_service(list(self.services).index(name), name, info)

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        # Refresh stored data when zeroconf reports changed service metadata.
        info = zc.get_service_info(type_, name)

        if info is not None:
            self.services[name] = info

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        # Remove service from local cache when it disappears.
        self.services.pop(name, None)
