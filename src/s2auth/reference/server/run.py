"""Run the S2Auth FastAPI server with uvicorn."""

from pathlib import Path
import sys


def main() -> None:
    """Start the FastAPI server with uvicorn."""
    try:
        import uvicorn
    except ImportError:
        print(
            "Error: uvicorn is not installed. Install with: pip install s2auth[server]",
            file=sys.stderr,
        )
        sys.exit(1)

    from s2auth.server.settings import settings as get_settings

    s = get_settings()
    if not s.ssl_certfile or not s.ssl_keyfile:
        raise RuntimeError(
            "SSL is required: both SSL_CERTFILE and SSL_KEYFILE must be configured."
        )

    cert_path = Path(s.ssl_certfile)
    key_path = Path(s.ssl_keyfile)
    if not cert_path.exists() or not key_path.exists():
        raise RuntimeError(
            "SSL is required: certificate or key file does not exist "
            f"(cert={cert_path}, key={key_path})."
        )

    uvicorn.run(
        "s2auth.reference.server.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        ssl_certfile=s.ssl_certfile,
        ssl_keyfile=s.ssl_keyfile,
    )


if __name__ == "__main__":
    main()
