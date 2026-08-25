from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable
from urllib.parse import urlparse
from uuid import UUID, uuid4

import httpx

from s2auth.client import pairing_core
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

LOGGER = logging.getLogger(__name__)

HttpRequestHook = Callable[[httpx.Request], Awaitable[None]]
HttpResponseHook = Callable[[httpx.Response], Awaitable[None]]
HttpEventHooks = pairing_core.HttpEventHooks


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


@dataclass(frozen=True)
class ConnectResult:
    success: bool
    pairing_s2_node_id: str
    connection_details: dict[str, object] | None


@dataclass(frozen=True)
class UnpairResult:
    success: bool
    pairing_s2_node_id: str
    previous_connection_details: dict[str, object] | None


@dataclass(frozen=True)
class PairingClientHooks:
    on_operation_start: Callable[[str, str | None], None] | None = None
    on_operation_success: Callable[[str, object], None] | None = None
    on_operation_error: Callable[[str, Exception], None] | None = None
    http_request: HttpRequestHook | None = None
    http_response: HttpResponseHook | None = None

    def http_event_hooks(self) -> HttpEventHooks | None:
        if self.http_request is None and self.http_response is None:
            return None

        event_hooks: HttpEventHooks = {
            "request": [],
            "response": [],
        }
        if self.http_request is not None:
            event_hooks["request"].append(self.http_request)
        if self.http_response is not None:
            event_hooks["response"].append(self.http_response)
        return event_hooks


class PairingClient:
    """High-level orchestration wrapper around existing pairing functions."""

    def __init__(
        self,
        settings: ClientSettings,
        storage: ConnectionStore | None = None,
        hooks: PairingClientHooks | None = None,
    ) -> None:
        self.settings = settings
        self.storage = storage if storage is not None else Dao(settings.storage_db_url)
        self.hooks = hooks if hooks is not None else PairingClientHooks()
        self._http_event_hooks = self.hooks.http_event_hooks()
        # Keep a generated fallback id for non-pairing flows where client id is not required.
        self._client_node_id = uuid4()

    @classmethod
    def from_settings(
        cls,
        settings: ClientSettings,
        storage: ConnectionStore | None = None,
        hooks: PairingClientHooks | None = None,
    ) -> "PairingClient":
        return cls(settings=settings, storage=storage, hooks=hooks)

    async def pair(self) -> PairingResult:
        self._emit_operation_start("pair", self.settings.pairing_s2_node_id)
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

        try:
            if self._http_event_hooks is None:
                success = await pairing_core.perform_pairing(
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
            else:
                success = await pairing_core.perform_pairing(
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
                    http_event_hooks=self._http_event_hooks,
                )
        except Exception as exc:
            self._emit_operation_error("pair", exc)
            raise

        storage_key = self.settings.pairing_s2_node_id or str(client_node_id)
        details = self.storage.load_connection_details(storage_key)
        result = PairingResult(
            success=success,
            pairing_s2_node_id=storage_key,
            client_s2_node_id=str(client_node_id),
            connection_details=details,
        )
        self._emit_operation_success("pair", result)
        return result

    async def connect(self, pairing_s2_node_id: str | None = None) -> ConnectResult:
        """Initiate a session and return an operation result with stored details."""

        resolved_pairing_s2_node_id = self._resolve_pairing_node_id(pairing_s2_node_id)
        self._emit_operation_start("connect", resolved_pairing_s2_node_id)

        try:
            if self._http_event_hooks is None:
                success = await pairing_core.connect(
                    storage=self.storage,
                    pairing_s2_node_id=resolved_pairing_s2_node_id,
                )
            else:
                success = await pairing_core.connect(
                    storage=self.storage,
                    pairing_s2_node_id=resolved_pairing_s2_node_id,
                    http_event_hooks=self._http_event_hooks,
                )
        except Exception as exc:
            self._emit_operation_error("connect", exc)
            raise

        result = ConnectResult(
            success=success,
            pairing_s2_node_id=resolved_pairing_s2_node_id,
            connection_details=self.storage.load_connection_details(resolved_pairing_s2_node_id),
        )
        self._emit_operation_success("connect", result)
        return result

    async def unpair(self, pairing_s2_node_id: str | None = None) -> UnpairResult:
        """Terminate pairing and return an operation result with pre-unpair details."""

        resolved_pairing_s2_node_id = self._resolve_pairing_node_id(pairing_s2_node_id)
        self._emit_operation_start("unpair", resolved_pairing_s2_node_id)
        previous_connection_details = self.storage.load_connection_details(resolved_pairing_s2_node_id)

        try:
            if self._http_event_hooks is None:
                success = await pairing_core.unpair(
                    storage=self.storage,
                    pairing_s2_node_id=resolved_pairing_s2_node_id,
                )
            else:
                success = await pairing_core.unpair(
                    storage=self.storage,
                    pairing_s2_node_id=resolved_pairing_s2_node_id,
                    http_event_hooks=self._http_event_hooks,
                )
        except Exception as exc:
            self._emit_operation_error("unpair", exc)
            raise

        result = UnpairResult(
            success=success,
            pairing_s2_node_id=resolved_pairing_s2_node_id,
            previous_connection_details=previous_connection_details,
        )
        self._emit_operation_success("unpair", result)
        return result

    def _emit_operation_start(self, operation: str, pairing_s2_node_id: str | None) -> None:
        if self.hooks.on_operation_start is None:
            return
        try:
            self.hooks.on_operation_start(operation, pairing_s2_node_id)
        except Exception as exc:  # pragma: no cover
            LOGGER.warning(f"on_operation_start hook failed: {exc}")

    def _emit_operation_success(self, operation: str, result: object) -> None:
        if self.hooks.on_operation_success is None:
            return
        try:
            self.hooks.on_operation_success(operation, result)
        except Exception as exc:  # pragma: no cover
            LOGGER.warning(f"on_operation_success hook failed: {exc}")

    def _emit_operation_error(self, operation: str, error: Exception) -> None:
        if self.hooks.on_operation_error is None:
            return
        try:
            self.hooks.on_operation_error(operation, error)
        except Exception as exc:  # pragma: no cover
            LOGGER.warning(f"on_operation_error hook failed: {exc}")

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
