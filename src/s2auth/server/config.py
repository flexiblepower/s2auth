from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from s2auth.common.dependencies import register_provider


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=[".env", ".env.docker"], extra="ignore", env_nested_delimiter="__"
    )
    sqlalchemy_db_uri: SecretStr = SecretStr(
        "postgresql://postgres:postgres@localhost/s2auth"
    )


@register_provider()
async def config() -> Config:
    return Config()
