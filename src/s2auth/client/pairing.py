from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse
from uuid import UUID, uuid4

from s2auth.client.connection_store import ConnectionStore
from s2auth.client.dao import Dao
from s2auth.client.settings import ClientSettings
from s2auth.common.model.s2_connect_common import (
    CommunicationProtocol,
    Deployment,
    NodeDescription,
    NodeId,
    Role,
)
from s2auth.common.model.s2_connect_pairing import HmacHashingAlgorithm


async def low_level_pair(
    pairing_uri: str,
    pairing_code: str | None,
    storage: ConnectionStore,
    role: str,
    deployment: str,
    supported_s2_message_versions: list[str],
    supported_communication_protocols: list[str],
    supportedHmacHashingAlgorithms: list[str],
    s2_client_description: NodeDescription,
    domain_name: str | None,
    pairingS2NodeId: Optional[str] = None,
    verify_tls: bool = True,
    ssl_certfile: str | None = None,
) -> bool:
    from s2auth.client.pairing_core import pair

    return await pair(
        pairing_uri=pairing_uri,
        pairing_code=pairing_code,
        storage=storage,
        role=role,
        deployment=deployment,
        supported_s2_message_versions=supported_s2_message_versions,
        supported_communication_protocols=supported_communication_protocols,
        supportedHmacHashingAlgorithms=supportedHmacHashingAlgorithms,
        s2_client_description=s2_client_description,
        domain_name=domain_name,
        pairingS2NodeId=pairingS2NodeId,
        verify_tls=verify_tls,
        ssl_certfile=ssl_certfile,
    )


async def low_level_connect(storage: ConnectionStore, pairing_s2_node_id: str) -> bool:
    from s2auth.client.pairing_core import connect

    return await connect(storage=storage, pairing_s2_node_id=pairing_s2_node_id)


async def low_level_unpair(storage: ConnectionStore, pairing_s2_node_id: str) -> bool:
    from s2auth.client.pairing_core import unpair

    return await unpair(storage=storage, pairing_s2_node_id=pairing_s2_node_id)


def strip_pairing_url(url_str: str) -> str:
    """Normalize a pairing URL by stripping known endpoint suffixes."""

    endpoint_suffixes = (
        "/requestPairing",
        "/initiateSession",
        "/requestConnectionDetails",
        "/postConnectionDetails",
        "/finalizePairing",
        "/confirmToken",
    )
    url_str = url_str.rstrip("/")

    for suffix in endpoint_suffixes:
        if url_str.endswith(suffix):
            url_str = url_str[: -len(suffix)]
            break
    return url_str.rstrip("/")


def detect_deployment(
    pairing_url: str,
    domain_name: str | None,
    certificate_file: str | None,
) -> tuple[Deployment, str]:
    """Infer deployment mode from domain/certificate/host heuristics."""

    if domain_name:
        return Deployment.WAN, "domain provided"
    if certificate_file:
        return Deployment.LAN, "certificate_file provided"

    hostname = (urlparse(pairing_url).hostname or "").lower()
    if hostname in {"", "localhost"} or hostname.endswith(".local"):
        return Deployment.LAN, f"host '{hostname or '<empty>'}' looked local"

    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return Deployment.LAN, f"host '{hostname}' is private/local IP"
        return Deployment.WAN, f"host '{hostname}' is public IP"
    except ValueError:
        # Non-IP hostname: treat as WAN by default.
        return Deployment.WAN, f"host '{hostname}' looked public"


def build_pairing_settings(
    base_settings: ClientSettings,
    *,
    server_url: str,
    pairing_token: str | None,
    pairing_s2_node_id: str | None,
    client_s2_node_id: str,
    role: str,
    deployment: str | None,
    domain_name: str | None,
    verify_tls: bool,
    ssl_certfile: str | None,
    supported_s2_message_versions: list[str] | None,
    communication_protocols: list[str] | None,
    supported_hmac_hashing_algorithms: list[str] | None,
    brand: str,
    client_device_type: str,
    client_model_name: str,
) -> tuple[ClientSettings, list[str]]:
    """Resolve effective pairing settings from defaults plus overrides."""

    warnings: list[str] = []

    effective_supported_s2_versions = supported_s2_message_versions or base_settings.supported_s2_versions
    effective_communication_protocols = communication_protocols or [
        protocol.value for protocol in base_settings.supported_communication_protocols
    ]
    effective_supported_hmac_hashing_algorithms = supported_hmac_hashing_algorithms or [
        algorithm.value for algorithm in base_settings.supported_hmac_hashing_algorithms
    ]

    normalized_server_url = strip_pairing_url(server_url)
    effective_domain = domain_name

    if deployment is None:
        effective_deployment, reason = detect_deployment(
            normalized_server_url,
            effective_domain,
            ssl_certfile,
        )
        warnings.append(f"Auto-detected deployment={effective_deployment.value} ({reason})")
        if reason.startswith("host '"):
            warnings.append(
                "Deployment was inferred heuristically from server_url host; set --deployment explicitly to override."
            )
    else:
        effective_deployment = Deployment(deployment.upper())

    if effective_deployment == Deployment.WAN and effective_domain is None:
        effective_domain = urlparse(server_url).hostname
        if effective_domain is None:
            raise ValueError("Could not auto-detect domain from --server_url; set --domain explicitly for WAN deployment.")
        warnings.append(f"Auto-detected domain='{effective_domain}' from server_url")

    runtime_settings = base_settings.model_copy(
        update={
            "server_url": server_url,
            "pairing_token": pairing_token,
            "pairing_s2_node_id": pairing_s2_node_id,
            "client_s2_node_id": client_s2_node_id,
            "client_role": Role(role),
            "client_deployment": effective_deployment,
            "domain_name": effective_domain,
            "verify_tls": verify_tls,
            "ssl_certfile": ssl_certfile,
            "supported_s2_versions": effective_supported_s2_versions,
            "supported_communication_protocols": list(map(CommunicationProtocol, effective_communication_protocols)),
            "supported_hmac_hashing_algorithms": list(
                map(HmacHashingAlgorithm, effective_supported_hmac_hashing_algorithms)
            ),
            "cleint_brand": brand,
            "client_device_type": client_device_type,
            "client_model_name": client_model_name,
        }
    )
    return runtime_settings, warnings


@dataclass(frozen=True)
class PairingResult:
    success: bool
    pairing_s2_node_id: str
    client_s2_node_id: str
    connection_details: dict[str, object] | None


class PairingClient:
    """High-level orchestration wrapper around existing pairing functions."""

    def __init__(self, settings: ClientSettings, storage: ConnectionStore | None = None) -> None:
        self.settings = settings
        self.storage = storage if storage is not None else Dao(settings.storage_db_url)
        # Keep a generated fallback id for non-pairing flows where client id is not required.
        self._client_node_id = uuid4()

    @classmethod
    def from_settings(cls, settings: ClientSettings, storage: ConnectionStore | None = None) -> "PairingClient":
        return cls(settings=settings, storage=storage)

    async def pair(self) -> PairingResult:
        pairing_uri = strip_pairing_url(self.settings.server_url)
        deployment, domain_name = self._resolve_deployment_domain(pairing_uri)
        client_node_id = self._resolve_client_node_id_for_pairing()

        node_description = NodeDescription(
            id=NodeId(client_node_id),
            brand=self.settings.cleint_brand,
            type=self.settings.client_device_type,
            modelName=self.settings.client_model_name,
            role=self.settings.client_role,
        )

        success = await low_level_pair(
            pairing_uri=pairing_uri,
            pairing_code=self.settings.pairing_token,
            storage=self.storage,
            role=self.settings.client_role,
            deployment=deployment,
            supported_s2_message_versions=self.settings.supported_s2_versions,
            supported_communication_protocols=[
                protocol.value for protocol in self.settings.supported_communication_protocols
            ],
            supportedHmacHashingAlgorithms=[
                algorithm.value for algorithm in self.settings.supported_hmac_hashing_algorithms
            ],
            s2_client_description=node_description,
            domain_name=domain_name,
            pairingS2NodeId=self.settings.pairing_s2_node_id,
            verify_tls=self.settings.verify_tls,
            ssl_certfile=self.settings.ssl_certfile,
        )

        storage_key = self.settings.pairing_s2_node_id or str(client_node_id)
        details = self.storage.load_connection_details(storage_key)
        return PairingResult(
            success=success,
            pairing_s2_node_id=storage_key,
            client_s2_node_id=str(client_node_id),
            connection_details=details,
        )

    async def connect(self, pairing_s2_node_id: str | None = None) -> bool:
        return await low_level_connect(
            storage=self.storage,
            pairing_s2_node_id=self._resolve_pairing_node_id(pairing_s2_node_id),
        )

    async def unpair(self, pairing_s2_node_id: str | None = None) -> bool:
        return await low_level_unpair(
            storage=self.storage,
            pairing_s2_node_id=self._resolve_pairing_node_id(pairing_s2_node_id),
        )

    def _resolve_pairing_node_id(self, pairing_s2_node_id: str | None) -> str:
        if pairing_s2_node_id is not None:
            return pairing_s2_node_id
        if self.settings.pairing_s2_node_id is not None:
            return self.settings.pairing_s2_node_id
        return str(self._client_node_id)

    def _resolve_client_node_id_for_pairing(self) -> UUID:
        configured_client_node_id = self.settings.client_s2_node_id
        if configured_client_node_id is None:
            return self._client_node_id

        try:
            return UUID(configured_client_node_id)
        except ValueError as exc:
            raise ValueError("client_s2_node_id must be a valid UUID for pairing mode") from exc

    def _resolve_deployment_domain(self, pairing_uri: str) -> tuple[str, str | None]:
        deployment = self.settings.client_deployment
        domain_name = self.settings.domain_name

        if deployment is None:
            deployment, _ = detect_deployment(pairing_uri, domain_name, self.settings.ssl_certfile)

        deployment_value = deployment.value.upper()

        if deployment_value == Deployment.WAN.value and domain_name is None:
            domain_name = urlparse(pairing_uri).hostname

        return deployment_value, domain_name
