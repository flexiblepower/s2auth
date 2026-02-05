"""Run the S2Auth FastAPI server with uvicorn."""
import sys


def main() -> None:
    """Start the FastAPI server with uvicorn."""
    try:
        import uvicorn
    except ImportError:
        print(
            "Error: uvicorn is not installed. "
            "Install with: pip install s2auth[server]",
            file=sys.stderr,
        )
        sys.exit(1)

    uvicorn.run(
        "s2auth.server.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    main()
