from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from s2auth.common.model.s2_connect_common import CommunicationProtocol, Deployment, Role
from s2auth.common.model.s2_connect_pairing import HmacHashingAlgorithm


class ClientSettings(BaseSettings):
    """Settings for the high-level S2 pairing client API.

    Values can be provided directly or loaded from environment variables/.env files.
    """

    model_config = SettingsConfigDict(
        env_file=[".env", ".env.docker"],
        extra="ignore",
        env_nested_delimiter="__",
    )

    server_url: str = "http://localhost"
    pairing_token: str | None = None
    pairing_s2_node_id: str | None = None
    client_s2_node_id: str | None = None

    client_role: Role = Role.RM
    client_deployment: Deployment | None = None
    domain_name: str | None = None

    verify_tls: bool = True
    ssl_certfile: str | None = Field(default=None)
    storage_db_url: str = "sqlite:///connection_details.db"

    supported_s2_versions: list[str] = Field(default_factory=lambda: ["v1"])
    supported_communication_protocols: list[CommunicationProtocol] = Field(
        default_factory=lambda: [CommunicationProtocol.WebSocket]
    )
    supported_hmac_hashing_algorithms: list[HmacHashingAlgorithm] = Field(
        default_factory=lambda: [HmacHashingAlgorithm.SHA256]
    )

    cleint_brand: str = "ExampleHeatCo"
    client_device_type: str = "Heatpump"
    client_model_name: str = "SmartHeatPump X200"
