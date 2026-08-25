"""Tests for server provider defaults."""

from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from s2auth.server.config import Config, config
from s2auth.server.db import async_session
from s2auth.server.settings import settings


async def test_config_provider_returns_default_config() -> None:
    cfg = await config()

    assert cfg.domain_name == 's2connect.example.com'


def test_settings_provider_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAIRING_NODE_ID", "PAIR1234")
    monkeypatch.setenv("SERVER_S2_NODE_ID", str(uuid4()))
    monkeypatch.setenv("CEM_S2_NODE_ID", str(uuid4()))
    monkeypatch.setenv("CEM_TYPE", "CEM")
    monkeypatch.setenv("CEM_MODEL_NAME", "CEM-1")
    monkeypatch.setenv("CEM_BRAND", "TestBrand")

    server_settings = settings()

    assert server_settings.pairing_node_id == "PAIR1234"
    assert server_settings.cem_brand == "TestBrand"


async def test_async_session_provider_commits_successfully(tmp_path: Path) -> None:
    cfg = Config(sqlalchemy_db_uri=SecretStr(f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}"))

    async with async_session(cfg=cfg) as session:
        result = await session.execute(text("SELECT 1"))

    assert result.scalar_one() == 1


async def test_async_session_provider_rolls_back_and_reraises(tmp_path: Path) -> None:
    cfg = Config(sqlalchemy_db_uri=SecretStr(f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}"))

    with pytest.raises(ValueError, match="boom"):
        async with async_session(cfg=cfg):
            raise ValueError("boom")
