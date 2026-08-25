"""One-time pairing token manager for interactive server use."""

from datetime import timezone, datetime, timedelta
from typing import TYPE_CHECKING
import threading
import logging

UTC = timezone.utc

if TYPE_CHECKING:
    from s2auth.server.settings import Settings

_lock = threading.Lock()
_pending_token: str | None = None
_pending_token_expires_at: datetime | None = None
log = logging.getLogger(__name__)


class ExpiredOneTimePairingTokenError(Exception):
    """Raised when a one-time pairing token has expired before use."""


def _normalize_token(token: str | None) -> str | None:
    """Treat empty or whitespace-only tokens as unset."""
    if token is None:
        return None
    normalized = token.strip()
    if normalized == "":
        return None
    return normalized


def set_pending_pairing_token(token: str, ttl_seconds: int | None = None) -> None:
    """Store a one-time pairing token to be consumed by the next new client."""
    global _pending_token, _pending_token_expires_at
    with _lock:
        _pending_token = token
        if ttl_seconds is None:
            _pending_token_expires_at = None
        else:
            _pending_token_expires_at = datetime.now(UTC) + timedelta(
                seconds=ttl_seconds
            )
    log.info("One-time pairing token: %s, expires at %s", _pending_token, _pending_token_expires_at)
    log.info("Press P + Enter to generate a new one-time pairing token for the next client.")


def consume_pending_pairing_token() -> str | None:
    """Return and clear the pending one-time pairing token, or None if not set."""
    token, _, _ = _consume_pending_pairing_token_with_state()
    return token


def _consume_pending_pairing_token_with_state() -> tuple[str | None, bool, bool]:
    """Consume pending token and return (token, expired_before_use, had_pending_token)."""
    global _pending_token, _pending_token_expires_at
    with _lock:
        had_pending_token = _pending_token is not None
        if (
            _pending_token_expires_at is not None
            and datetime.now(UTC) >= _pending_token_expires_at
        ):
            _pending_token = None
            _pending_token_expires_at = None
            return None, True, had_pending_token
        token = _pending_token
        _pending_token = None
        _pending_token_expires_at = None
        return token, False, had_pending_token


def prime_default_pairing_token(server_settings: "Settings") -> None:
    """Promote DEFAULT_PAIRING_TOKEN into the pending one-time token bucket.

    This is intended for server startup so token lifetime starts at startup
    rather than at first pairing request.
    """
    default_token = _normalize_token(server_settings.default_pairing_token)
    if default_token is None:
        return

    set_pending_pairing_token(
        default_token,
        ttl_seconds=server_settings.pairing_token_ttl_seconds,
    )
    server_settings.default_pairing_token = None


def resolve_pairing_token(
    server_settings: "Settings",
    generated_token: str,
) -> str:
    """Resolve the token to use for a new pairing attempt.

    Resolution order:
    1. Pending one-time token generated during runtime (if not expired)
    2. Startup DEFAULT_PAIRING_TOKEN (one-time, only if still within TTL)
    3. Generated fallback token
    """
    pending_token, pending_token_expired, had_pending_token = (
        _consume_pending_pairing_token_with_state()
    )
    if pending_token is not None:
        return pending_token
    if had_pending_token and pending_token_expired:
        log.warning("One-time pairing token expired before use.")
        raise ExpiredOneTimePairingTokenError(
            "One-time pairing token expired before use."
        )

    default_token = _normalize_token(server_settings.default_pairing_token)
    if default_token is not None:
        expires_at = server_settings.default_pairing_token_created_at + timedelta(
            seconds=server_settings.pairing_token_ttl_seconds
        )
        # Consume default token exactly once, regardless of expiration state.
        server_settings.default_pairing_token = None
        if datetime.now(UTC) < expires_at:
            return default_token
        log.warning("Default pairing token expired before use.")
        raise ExpiredOneTimePairingTokenError(
            "Default pairing token expired before use."
        )

    return generated_token
