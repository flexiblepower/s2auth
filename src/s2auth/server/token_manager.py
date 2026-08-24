"""One-time pairing token manager for interactive server use."""

import threading

_lock = threading.Lock()
_pending_token: str | None = None


def set_pending_pairing_token(token: str) -> None:
    """Store a one-time pairing token to be consumed by the next new client."""
    global _pending_token
    with _lock:
        _pending_token = token


def consume_pending_pairing_token() -> str | None:
    """Return and clear the pending one-time pairing token, or None if not set."""
    global _pending_token
    with _lock:
        token = _pending_token
        _pending_token = None
        return token
