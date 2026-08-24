"""Tests for reference server runner SSL enforcement."""

from dataclasses import dataclass
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from s2auth.reference.server import run as reference_run


@dataclass
class _FakeSettings:
    ssl_certfile: str
    ssl_keyfile: str


def _install_fake_uvicorn(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    called: dict[str, Any] = {}

    def fake_run(*args: Any, **kwargs: Any) -> None:
        called["args"] = args
        called["kwargs"] = kwargs

    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=fake_run))
    return called


def test_main_raises_when_ssl_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = _install_fake_uvicorn(monkeypatch)

    def fake_settings() -> _FakeSettings:
        return _FakeSettings(ssl_certfile="", ssl_keyfile="")

    monkeypatch.setattr("s2auth.server.settings.settings", fake_settings)

    with pytest.raises(RuntimeError, match="SSL is required"):
        reference_run.main()

    assert called == {}


def test_main_raises_when_ssl_files_do_not_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = _install_fake_uvicorn(monkeypatch)

    def fake_settings() -> _FakeSettings:
        return _FakeSettings(
            ssl_certfile="/tmp/does-not-exist-cert.pem",
            ssl_keyfile="/tmp/does-not-exist-key.pem",
        )

    monkeypatch.setattr("s2auth.server.settings.settings", fake_settings)

    with pytest.raises(RuntimeError, match="does not exist"):
        reference_run.main()

    assert called == {}


def test_main_starts_uvicorn_when_ssl_files_exist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    called = _install_fake_uvicorn(monkeypatch)

    cert_path = tmp_path / "localhost.chain.pem"
    key_path = tmp_path / "localhost.key"
    cert_path.write_text("cert", encoding="utf-8")
    key_path.write_text("key", encoding="utf-8")

    def fake_settings() -> _FakeSettings:
        return _FakeSettings(ssl_certfile=str(cert_path), ssl_keyfile=str(key_path))

    monkeypatch.setattr("s2auth.server.settings.settings", fake_settings)

    reference_run.main()

    assert called["args"] == ("s2auth.reference.server.main:app",)
    assert called["kwargs"]["host"] == "0.0.0.0"
    assert called["kwargs"]["port"] == 8000
    assert called["kwargs"]["reload"] is True
    assert called["kwargs"]["ssl_certfile"] == str(cert_path)
    assert called["kwargs"]["ssl_keyfile"] == str(key_path)
