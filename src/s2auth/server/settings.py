from datetime import timezone, datetime
from typing import Annotated
from pydantic import Field
from pydantic import AnyUrl, StringConstraints
from pydantic.types import UUID4
from pydantic_settings import BaseSettings, SettingsConfigDict

from wepositive_di import register_provider

from s2auth.common.model.s2_connect_common import CommunicationProtocol, Deployment

UTC = timezone.utc

SERVER_PROCESS_STARTED_AT = datetime.now(UTC)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=[".env", ".env.docker"], extra="ignore", env_nested_delimiter="__"
    )

    pairing_node_id: Annotated[str, StringConstraints(min_length=8, max_length=12)]
    server_s2_node_id: UUID4
    supported_communication_protocols: list[CommunicationProtocol] = [
        CommunicationProtocol.WebSocket
    ]
    supported_s2_versions: list[str] = ["v1"]  # most recent first
    supported_s2_connect_versions: list[str] = ["v1"]  # most recent first
    cem_s2_node_id: UUID4
    cem_type: str
    cem_model_name: str
    cem_brand: str
    cem_url: AnyUrl | None = None
    cem_deployment_type: Deployment = Deployment.WAN
    # If unset/empty, pairing starts with generated one-time tokens.
    default_pairing_token: str | None = None
    default_pairing_token_created_at: datetime = Field(
        default=SERVER_PROCESS_STARTED_AT,
        exclude=True,
    )
    pairing_token_ttl_seconds: int = Field(default=300, gt=0)
    ssl_certfile: str = ""
    ssl_keyfile: str = ""


@register_provider(singleton=True)
def settings() -> Settings:
    return Settings()  # pyright:ignore[reportCallIssue]
