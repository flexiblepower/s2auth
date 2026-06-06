from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

import s2auth
from s2auth.reference.server.connection import router as connection_router
from s2auth.reference.server.pairing import router as pairing_router
from s2auth.reference.server.logging import setupLogging, LogLevel
from s2auth.server import setup as setup_s2auth_server


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Initialize reference server hooks and dependency injection."""
    _ = app
    setupLogging(default_log_level=LogLevel.DEBUG, logger_config={})
    setup_s2auth_server(additional_hook_modules=["s2auth.reference.server.hooks"])
    yield


app = FastAPI(
    version=s2auth.__version__,
    title="s2-over-ip pairing and connection initiation",
    description="The HTTP API specification of the pairing process for S2 over IP connections, as well as initiating connections. For more information, please find the specification at [S2 documentation](https://docs.s2standard.org).",
    license={
        "name": "Apache-2.0",
        "url": "https://raw.githubusercontent.com/flexiblepower/s2-ws-json/refs/heads/main/LICENSE",
    },
    servers=[{"url": "/v1"}],
    lifespan=lifespan,
)

app.include_router(pairing_router, prefix="/pairing")
app.include_router(connection_router, prefix="/connection")
