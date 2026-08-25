from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import logging
import select
import sys
import threading

from fastapi import FastAPI

import s2auth
from s2auth.common.hmac import create_pairing_code
from s2auth.reference.server.connection import router as connection_router
from s2auth.reference.server.logging import setupLogging, LogLevel
from s2auth.reference.server.pairing import router as pairing_router
from s2auth.server.config import Config
from s2auth.server import setup as setup_s2auth_server
from s2auth.server.settings import Settings, settings as get_settings
from s2auth.server.token_manager import set_pending_pairing_token

log = logging.getLogger(__name__)


def _startup_base_url(server_settings: Settings, cfg: Config) -> str:
    _ = server_settings
    return f"https://{cfg.domain_name}:8000"


def _primary_s2_connect_version(server_settings: Settings) -> str:
    supported_versions = server_settings.supported_s2_connect_versions
    if not supported_versions:
        return "v1"
    return supported_versions[0]

def _keyboard_watcher(stop_event: threading.Event) -> None:
    """Background thread: press P (+ Enter) to generate a one-time pairing token."""
    while not stop_event.is_set():
        try:
            if select.select([sys.stdin], [], [], 0.2)[0]:
                line = sys.stdin.readline()
                if line.strip().lower() == "p":
                    token = create_pairing_code()
                    set_pending_pairing_token(token)
                    log.info("One-time pairing token generated: %s", token)
                    log.info("Press P + Enter to generate a new one-time pairing token for the next client.")
        except Exception:
            break


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Initialize reference server hooks and dependency injection."""
    _ = app
    setupLogging(default_log_level=LogLevel.DEBUG, logger_config={})
    setup_s2auth_server(additional_hook_modules=["s2auth.reference.server.hooks"])
    server_settings = get_settings()
    cfg = Config()
    log.info(
        "Server startup config: DOMAIN_NAME=%s, PAIRING_NODE_ID=%s, SERVER_S2_NODE_ID=%s",
        cfg.domain_name,
        server_settings.pairing_node_id,
        server_settings.server_s2_node_id,
    )
    base_url = _startup_base_url(server_settings, cfg)
    s2_connect_version = _primary_s2_connect_version(server_settings)
    log.info(
        "Uvicorn binds to https://0.0.0.0:8000, but clients should connect to %s",
        base_url,
    )
    log.info(
        "Pairing endpoints: requestPairing=%s/pairing/%s/requestPairing finalizePairing=%s/pairing/%s/finalizePairing (or use https://localhost:8000 if domain name doesn't resolve)",
        base_url,
        s2_connect_version,
        base_url,
        s2_connect_version,
    )
    if server_settings.default_pairing_token:
        log.info("Default one time pairing token (from DEFAULT_PAIRING_TOKEN): %s", server_settings.default_pairing_token)
    log.info("Press P + Enter to generate a new one-time pairing token for the next client.")
    stop_event = threading.Event()
    watcher = threading.Thread(target=_keyboard_watcher, args=(stop_event,), daemon=True)
    watcher.start()
    yield
    stop_event.set()


app = FastAPI(
    version=s2auth.__version__,
    title="s2-over-ip pairing and connection initiation",
    description="The HTTP API specification of the pairing process for S2 over IP connections, as well as initiating connections. For more information, please find the specification at [S2 documentation](https://docs.s2standard.org).",
    license={
        "name": "Apache-2.0",
        "url": "https://raw.githubusercontent.com/flexiblepower/s2-ws-json/refs/heads/main/LICENSE",
    },
    lifespan=lifespan,
)

app.include_router(pairing_router, prefix="/pairing")
app.include_router(connection_router, prefix="/connection")
