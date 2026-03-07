from typing import Annotated
from pydantic import AnyUrl, StringConstraints
from pydantic.types import UUID4
from pydantic_settings import BaseSettings

from s2auth.common.dependencies import register_provider


class Settings(BaseSettings):
    pairing_node_id: Annotated[str, StringConstraints(min_length=8, max_length=12)]
    server_s2_node_id: UUID4
    cem_s2_node_id: UUID4
    cem_type: str
    cem_model_name: str
    cem_brand: str
    cem_url: AnyUrl


@register_provider(singleton=True)
def settings() -> Settings:
    return Settings()  # pyright:ignore[reportCallIssue]
