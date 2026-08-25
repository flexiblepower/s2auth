from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlparse
from uuid import UUID, uuid4

from s2auth.client.dao import Dao
from s2auth.client.pairing import (
    connect as low_level_connect,
    pair as low_level_pair,
    strip_pairing_url,
    unpair as low_level_unpair,
)
from s2auth.client.settings import ClientSettings
from s2auth.common.model.s2_connect_common import Deployment, NodeDescription, NodeId


@dataclass(frozen=True)
class PairingResult:
    success: bool
    pairing_s2_node_id: str
    client_s2_node_id: str
    connection_details: dict[str, object] | None


class PairingClient:
    """High-level orchestration wrapper around existing pairing functions."""

    def __init__(self, settings: ClientSettings, storage: Dao | None = None) -> None:
        self.settings = settings
        self.storage = storage if storage is not None else Dao(settings.storage_db_url)
        self._client_node_id = (
            UUID(settings.client_s2_node_id)
            if settings.client_s2_node_id is not None
            else uuid4()
        )

    @classmethod
    def from_settings(cls, settings: ClientSettings, storage: Dao | None = None) -> "PairingClient":
        return cls(settings=settings, storage=storage)

    async def pair(self) -> PairingResult:
        pairing_uri = strip_pairing_url(self.settings.server_url)
        deployment, domain_name = self._resolve_deployment_domain(pairing_uri)

        node_description = NodeDescription(
            id=NodeId(self._client_node_id),
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

        storage_key = self.settings.pairing_s2_node_id or str(self._client_node_id)
        details = self.storage.load_connection_details(storage_key)
        return PairingResult(
            success=success,
            pairing_s2_node_id=storage_key,
            client_s2_node_id=str(self._client_node_id),
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

    def _resolve_deployment_domain(self, pairing_uri: str) -> tuple[str, str | None]:
        deployment = self.settings.client_deployment
        domain_name = self.settings.domain_name

        if deployment is None:
            deployment = self._detect_deployment(pairing_uri, domain_name, self.settings.ssl_certfile)

        deployment_value = deployment.value.upper()

        if deployment_value == Deployment.WAN.value and domain_name is None:
            domain_name = urlparse(pairing_uri).hostname

        return deployment_value, domain_name

    @staticmethod
    def _detect_deployment(
        pairing_uri: str,
        domain_name: str | None,
        certificate_file: str | None,
    ) -> Deployment:
        if domain_name:
            return Deployment.WAN
        if certificate_file:
            return Deployment.LAN

        hostname = (urlparse(pairing_uri).hostname or "").lower()
        if hostname in {"", "localhost"} or hostname.endswith(".local"):
            return Deployment.LAN

        try:
            ip = ipaddress.ip_address(hostname)
        except ValueError:
            return Deployment.WAN

        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return Deployment.LAN
        return Deployment.WAN
