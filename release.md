# Release Notes

## v0.1.0

First public release of the S2 Pairing Protocol Python Wrapper

### Highlights

- Adds a high-level S2 client API for pairing and connection initiation flows.
- Adds server-side S2 endpoints and orchestration components for authentication and pairing.
- Includes shared protocol models and helpers for S2 message handling.
- Provides reference client/server entry points for local testing and integration.
- Adds async SQLAlchemy-based persistence components for connection and pairing state.

### Compatibility

- Python: 3.10, 3.11, 3.12, 3.13, 3.14
- Package name: s2auth
- License: Apache-2.0

### Included Tooling

- Type checking with pyright
- Linting with ruff
- Unit and end-to-end tests with pytest
- Documentation via MkDocs

### Known Limitations

- This release does not include long-polling and mDNS discovery of available devices
- This is the first public release; API ergonomics and extension points may evolve in future releases.
- Production deployment details (for example, runtime hardening and observability defaults) should be validated per environment.
