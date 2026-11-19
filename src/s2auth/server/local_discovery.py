"""Local DNS-SD broadcaster for the reference S2 server.

Spec notes (S2 Connect 1.0.0):
- Base DNS-SD service type is ``_s2connect._tcp.local.``.
- Role filtering is done via subtypes like ``_cem`` and ``_rm``.

Interoperability note:
- Some third-party clients browse the CEM subtype directly
    (``_cem._sub._s2connect._tcp.local.``) instead of browsing the base service
    type and filtering by subtype.
- To maximize interoperability, we advertise both records:
    1) spec-compliant base service type
    2) compatibility CEM subtype record
"""

from __future__ import annotations

import logging
import socket
from dataclasses import dataclass
from typing import Any

from zeroconf import ServiceInfo, Zeroconf

from s2auth.server.config import Config
from s2auth.server.settings import Settings

LOGGER = logging.getLogger(__name__)

SERVICE_TYPE = "_s2connect._tcp.local."
# Compatibility advertisement for clients browsing subtype directly.
SERVICE_SUBTYPE_CEM = "_cem._sub._s2connect._tcp.local."
SERVICE_NAME_POSTFIX = "._s2connect._tcp.local."


def _local_ipv4() -> str:
    """Best-effort local IPv4 selection for mDNS service registration."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # No packets are sent; this selects the outbound interface address.
        sock.connect(("8.8.8.8", 80))
        return str(sock.getsockname()[0])
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


@dataclass
class LocalDiscoveryRegistration:
    zeroconf: Zeroconf
    service_infos: list[ServiceInfo]

    def close(self) -> None:
        """Unregister and release Zeroconf resources."""
        try:
            for service_info in self.service_infos:
                self.zeroconf.unregister_service(service_info)
        finally:
            self.zeroconf.close()


def send_local_discover(
    cfg: Config,
    server_settings: Settings
) -> LocalDiscoveryRegistration:
    """Register a LAN discovery DNS-SD service for S2 clients.

    Returns a handle that should be closed on application shutdown.
    """
    port = server_settings.server_port
    domain_name = cfg.domain_name
    hostname = server_settings.server_hostname
    server = f"{hostname}.{domain_name}"
    service_name = f"{server}.{SERVICE_TYPE}"
    subtype_service_name = f"{server}.{SERVICE_SUBTYPE_CEM}"
    base_url = f"https://{server}:{port}/pairing/"

    properties: dict[str, Any] = {
        "pairingUrl": base_url,
        "deployment": "LAN",
        "e_name": "Example reference server",
        "txtver": "1",
    }

    service_info = ServiceInfo(
        type_=SERVICE_TYPE,
        name=f"{hostname}{SERVICE_NAME_POSTFIX}",
        addresses=[socket.inet_aton(_local_ipv4())],
        port=port,
        properties=properties,
        server=server,
    )

    # Compatibility advertisement for clients browsing the subtype directly.
    subtype_service_info = ServiceInfo(
        type_=SERVICE_SUBTYPE_CEM,
        name=f"{hostname}-cem{SERVICE_NAME_POSTFIX}",
        addresses=[socket.inet_aton(_local_ipv4())],
        port=port,
        properties=properties,
        server=server,
    )

    zeroconf = Zeroconf()
    zeroconf.register_service(service_info)
    zeroconf.register_service(subtype_service_info)
    LOGGER.info(
        "Registered DNS-SD services %s and %s with pairingUrl=%s (pairing_node_id=%s)",
        service_name,
        subtype_service_name,
        base_url,
        server_settings.pairing_node_id,
    )
    return LocalDiscoveryRegistration(
        zeroconf=zeroconf,
        service_infos=[service_info, subtype_service_info],
    )
