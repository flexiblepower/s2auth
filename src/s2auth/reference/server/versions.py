from fastapi import Depends

from s2auth.common.exceptions import NoCompatibleS2ConnectVersionError
from s2auth.server.settings import Settings, settings


def get_supported_s2_connect_versions(
    server_settings: Settings = Depends(settings),
) -> list[str]:
    """Return the S2 Connect API versions supported by this server."""
    return server_settings.supported_s2_connect_versions


def check_s2_connect_version(
    s2_connect_version: str,
    server_settings: Settings = Depends(settings),
) -> str:
    """Return the requested S2 Connect API version when it is supported."""
    supported_versions = server_settings.supported_s2_connect_versions
    if s2_connect_version not in supported_versions:
        raise NoCompatibleS2ConnectVersionError(
            f"S2 Connect version {s2_connect_version} is not compatible "
            f"with any of {supported_versions}",
            additional_info=f"Supported s2 connect versions: {supported_versions}",
        )
    return s2_connect_version
