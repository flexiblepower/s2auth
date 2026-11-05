"""Local DNS-SD broadcaster for the reference S2 server."""

from __future__ import annotations

import logging
import socket
from dataclasses import dataclass

from zeroconf import ServiceInfo, Zeroconf

from s2auth.server.config import Config
from s2auth.server.settings import Settings

LOGGER = logging.getLogger(__name__)

SERVICE_TYPE = "_s2connect._tcp.local."


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
    service_info: ServiceInfo

    def close(self) -> None:
        """Unregister and release Zeroconf resources."""
        try:
            self.zeroconf.unregister_service(self.service_info)
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
    hostname = cfg.domain_name
    service_name = f"{hostname}.{SERVICE_TYPE}"
    _ = cfg
    base_url = f"https://{hostname}:{port}/pairing"

    properties: dict[str, str] = {
        "pairingUrl": base_url,
        "longpollingUrl": base_url,
        "deployment": "LAN",
        "e_name": "Example reference server",
        "txtver": "1",
    }

    service_info = ServiceInfo(
        type_=SERVICE_TYPE,
        name=service_name,
        addresses=[socket.inet_aton(_local_ipv4())],
        port=port,
        properties=properties,
        server=hostname,
    )

    zeroconf = Zeroconf()
    zeroconf.register_service(service_info)
    LOGGER.info(
        "Registered DNS-SD service %s with pairingUrl=%s (pairing_node_id=%s)",
        service_name,
        base_url,
        server_settings.pairing_node_id,
    )
    return LocalDiscoveryRegistration(zeroconf=zeroconf, service_info=service_info)
