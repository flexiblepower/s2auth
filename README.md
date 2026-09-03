# S2 Pairing Protocol Python Wrapper

Python helpers for S2 Connect pairing, authentication, and connection initiation.

This package implements client and server building blocks for the S2 communication-layer flows described in the official S2 specification: <https://docs.s2standard.org/docs/communication-layer/discovery-pairing-authentication/>.

# Setup dev environment
Requires: pyenv with Python 3.10 installed on the system.
Shell scripts are Linux-compatible.

```bash
ci/setup_dev_environment.sh
```

# Install as regular python package
* `pip install .` should just work

# Use as a library
The package exposes a public client API, public protocol model re-exports, and HMAC helpers.

The CLI in this repository is a thin adapter around the same library API.

Pairing client API:

```python
import asyncio

from s2auth.client import ClientSettings, PairingClient

async def run_pairing_flow() -> None:
  settings = ClientSettings()
  client = PairingClient.from_settings(settings)

  pairing_result = await client.pair()
  print(pairing_result.pairing_s2_node_id)

  connect_result = await client.connect(pairing_s2_node_id=pairing_result.pairing_s2_node_id)
  print(connect_result.success)

  unpair_result = await client.unpair(pairing_s2_node_id=pairing_result.pairing_s2_node_id)
  print(unpair_result.success)


asyncio.run(run_pairing_flow())
```

`pair()` returns `PairingResult`, `connect()` returns `ConnectResult`, and `unpair()` returns `UnpairResult`.

Hooks:

```python
import logging

from s2auth.client import ClientSettings, PairingClient, PairingClientHooks

LOGGER = logging.getLogger(__name__)


def on_start(operation: str, pairing_s2_node_id: str | None) -> None:
  LOGGER.info(f"start operation={operation} pairing_s2_node_id={pairing_s2_node_id}")


def on_success(operation: str, result: object) -> None:
  LOGGER.info(f"success operation={operation} result_type={type(result).__name__}")


def on_error(operation: str, error: Exception) -> None:
  LOGGER.error(f"error operation={operation} error={error}")


async def on_http_request(request) -> None:
  LOGGER.debug(f"HTTP request {request.method} {request.url}")


async def on_http_response(response) -> None:
  LOGGER.debug(f"HTTP response {response.status_code} {response.request.url}")


settings = ClientSettings()
hooks = PairingClientHooks(
  on_operation_start=on_start,
  on_operation_success=on_success,
  on_operation_error=on_error,
  http_request=on_http_request,
  http_response=on_http_response,
)
client = PairingClient.from_settings(settings, hooks=hooks)
```

HTTP hook behavior contract:

- If you do not provide custom HTTP hooks, the library uses built-in request/response debug hooks.
- If you provide `http_request` and/or `http_response`, your hooks fully replace the built-in hooks.
- The library does not merge, wrap, or interfere with custom HTTP hooks.
- If you replace the defaults and still want HTTP debug output, add that logging in your own hooks.
- Default hooks log at DEBUG level only; you only see them when logging is configured to DEBUG.
- Keep DEBUG logging off in production, because request/response debug logs may include sensitive values such as tokens.

Storage abstraction:

`PairingClient` is typed against the `ConnectionStore` interface. If you do not
provide a store, it uses the built-in `Dao` by default.

```python
from s2auth.client import ClientSettings, ConnectionStore, PairingClient
from s2auth.client.dao import Dao
from typing import Any

settings = ClientSettings()

# Default storage (Dao)
client_default = PairingClient.from_settings(settings)

# Explicit Dao
client_with_dao = PairingClient.from_settings(settings, storage=Dao(settings.storage_db_url))

# Custom storage implementation can satisfy ConnectionStore
class MyCustomStorage:
  def __init__(self) -> None:
    self._data: dict[str, dict[str, Any]] = {}

  def store_connection_details(self, s2_node_id: str, details: dict[str, Any]) -> None:
    self._data[s2_node_id] = details

  def load_connection_details(self, s2_node_id: str) -> dict[str, Any] | None:
    return self._data.get(s2_node_id)

  def remove_connection_details(self, s2_node_id: str) -> bool:
    return self._data.pop(s2_node_id, None) is not None

client_with_custom_store = PairingClient.from_settings(settings, storage=MyCustomStorage())
```

Common protocol models:

```python
from s2auth.common.model import Deployment, Role, HmacHashingAlgorithm
```

You can also import generated model submodules directly from `s2auth.common.model`
to access all symbols in the spec, including names that may appear in multiple specs
(for example different `ErrorMessage` enums):

```python
from s2auth.common.model import s2_connect_common, s2_connect_pairing, s2_connect_session_init

pairing_error = s2_connect_pairing.ErrorMessage
session_error = s2_connect_session_init.ErrorMessage
```

HMAC helpers:

```python
from s2auth.common import (
  create_pairing_code,
  create_challenge,
  create_response,
  verify_response,
  get_supported_algorithms,
  select_algorithm,
)
```

# Call the client CLI
The pairing client is exposed as the Python module `s2auth.client.main`.

From a development checkout, run it by:
- first creating and activating a virtual environment: `python -m venv .venv` and `source .venv/bin/activate`
- installing all dependencies: `ci/install_dependencies.sh` (you may need to run `ci/setup_dev_environment.sh` if poetry is not yet installed)
- then calling `client --help`

There is also a helper script in the repository:

```bash
./run_client.sh
```

Client workflow:
1. Run pairing first (`client ...`) to store connection details for a target `--pairing_s2_node_id`.
2. After pairing is complete, run connect mode to initiate the S2 session and fetch communication details.
3. If needed, run unpair mode to terminate the pairing.

Client configuration is loaded from `.env` by `s2auth.client.settings.ClientSettings`.
The CLI reads those values first and then lets you override them with command-line arguments.

Relevant client settings in `.env` are:
- `SERVER_URL`
- `PAIRING_TOKEN`
- `PAIRING_S2_NODE_ID`
- `CLIENT_S2_NODE_ID`
- `CLIENT_ROLE`
- `CLIENT_DEPLOYMENT`
- `DOMAIN_NAME`
- `VERIFY_TLS`
- `SSL_CERTFILE`
- `STORAGE_DB_URL`
- `SUPPORTED_S2_VERSIONS`
- `SUPPORTED_COMMUNICATION_PROTOCOLS`
- `SUPPORTED_HMAC_HASHING_ALGORITHMS`
- `CLEINT_BRAND`
- `CLIENT_DEVICE_TYPE`
- `CLIENT_MODEL_NAME`


## 1. Run pairing
If you have configured `.env`, the simplest invocation is:

```bash
client
```

The examples below keep the same behavior but explicitly override values from `.env` on the command line.

WAN override example:

```bash
client \
  --server_url https://localhost:8005/v1 \
  --domain s2connect.example.com \
  --pairing_token test \
  --skip_cert_verify \
  --deployment WAN \
  --pairing_s2_node_id ninechars \
  --s2_role RM \
  --verbose
```

LAN override example:

```bash
client \
  --server_url https://localhost:8005/v1 \
  --deployment LAN \
  --pairing_token test \
  --pairing_s2_node_id ninechars \
  --s2_role RM \
  --verbose
```

Required input:
- Provide a `PAIRING_TOKEN` in `.env` or pass `--pairing_token` to start the pairing flow.
- `CLIENT_DEPLOYMENT` in `.env` or `--deployment` on the CLI is optional.
- For WAN deployments, provide `DOMAIN_NAME` in `.env` or pass `--domain`, or let the client auto-detect the domain from `--server_url`.
- For LAN deployments, a local certificate file is optional. The client computes the fingerprint from the TLS peer certificate in the pairing response.
- Set `SSL_CERTFILE` in `.env` or pass `--certificate_file` only when you want to use an explicit CA/certificate bundle for TLS verification.

LAN security note:
- In LAN mode, pairing HMAC is bound to the certificate of the TLS peer seen by the client.
- This is a security feature: if a TLS-terminating proxy presents a different certificate, HMAC verification can fail with a signature mismatch.
- For LAN pairing behind intermediaries, prefer TLS passthrough so the client sees the endpoint certificate directly.

Useful optional arguments:
- `--server_url` defaults to the value from `SERVER_URL`, or `http://localhost` if not configured.
- `--client_S2_nodeId` and `--pairing_S2_nodeId` let you provide explicit node IDs instead of auto-generated ones.
- `--pairing_s2_node_id` defaults to `PAIRING_S2_NODE_ID` when set and can be overridden on the CLI.
- `--certificate_file` points to a CA/certificate bundle file for TLS verification in local or test setups (optional).
- `--skip_cert_verify` disables certificate verification for local or test setups.
- `-v` or `--verbose` enables debug logging.

Auto-detection behavior:
- `CLIENT_DEPLOYMENT` or `--deployment` takes priority when set and disables deployment auto-detection.
- If deployment is not set, the client infers it from the other effective settings.
- `DOMAIN_NAME` or `--domain` set: deployment is treated as `WAN`.
- `SSL_CERTFILE` or `--certificate_file` set: deployment is treated as `LAN`.
- If both domain and certificate settings are provided while deployment is unset, the client treats the connection as `WAN` because domain is checked first.
- Otherwise the client inspects `SERVER_URL` or `--server_url`.
- `localhost`, `.local`, and private/local IP addresses are treated as `LAN`.
- Public hostnames or public IP addresses are treated as `WAN`.
- When deployment is auto-detected as `WAN` and no domain is set, the client also auto-detects the domain from the hostname in `SERVER_URL` or `--server_url`.
- The client logs a warning whenever deployment or domain is auto-detected.

Test certificate:
- For local testing, a test certificate bundle is available at `tests/localhost.chain.pem`.
- This file is optional for LAN pairing fingerprinting and mainly useful when you want to force TLS verification against a specific local bundle.
- This file is intended for development and test scenarios only.

## 2. Connect after pairing:

```bash
client \
  --connect \
  --pairing_s2_node_id <pairing-node-id> \
  --verbose
```

`--connect` uses the previously stored pairing data, calls `/initiateSession`, confirms the returned pending token, and stores/prints details such as selected protocol/version and server descriptions.

## 3. Unpair after pairing:

```bash
client \
  --unpair \
  --pairing_s2_node_id <pairing-node-id> \
  --verbose
```

**Please note:** `--connect` and `--unpair` are dedicated modes and only accept `--pairing_s2_node_id` (or `--pairing_S2_nodeId`) plus optional `--verbose`.

# Run the FastAPI server

The supported server entry point is the `server` console script defined in
`pyproject.toml` under `[project.scripts]`.

### 1. Install dependencies

```bash
poetry install --all-extras
```

### 2. Create a `.env` file

An example file is provided at `.env.example` — copy it and fill in your values:

```bash
cp .env.example .env
```

The server reads its configuration from a `.env` file in the project root. All fields below are required:

```dotenv
PAIRING_NODE_ID=PAIR1234          # 8–12 character pairing node identifier
SERVER_S2_NODE_ID=<uuid>          # UUID for the server-side S2 node
CEM_S2_NODE_ID=<uuid>             # UUID for the CEM S2 node
CEM_TYPE=CEM
CEM_MODEL_NAME=My CEM
CEM_BRAND=MyBrand
HMAC_SALT=<your-domain-or-secret> # Salt used for HMAC verification
```

Optional fields:

```dotenv
CEM_URL=https://your-cem-host/connection/   # Exposed connection endpoint URL
DEFAULT_PAIRING_TOKEN=yourtoken             # One-time startup pairing token; expires after PAIRING_TOKEN_TTL_SECONDS or first use
PAIRING_TOKEN_TTL_SECONDS=300               # Pairing token validity window (default: 5 minutes)
```

Pairing token behavior:
- Pairing tokens are one-time use tokens.
- A token is consumed by the next successful new pairing attempt and is then no longer valid.
- Pairing tokens expire after `PAIRING_TOKEN_TTL_SECONDS` (default: 300 seconds / 5 minutes).
- `DEFAULT_PAIRING_TOKEN` is the optional startup token. It is also one-time and TTL-bound.
- If a one-time token has already expired, the server rejects pairing with an authentication error instead of silently accepting.
- If you want to start without a fixed startup token, set this in `.env`:

```dotenv
DEFAULT_PAIRING_TOKEN=
```

When `DEFAULT_PAIRING_TOKEN` is empty, the server uses a generated pairing token flow.
You can still press `P + Enter` in the server console to override the next one-time token manually.

### 3. Start the server

After installation, run the configured console script directly:

```bash
server
```

This starts the development server with auto-reload enabled at `http://0.0.0.0:8000`.

The API documentation is available at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

**Note**: Requires the `server` optional dependencies. Install with:
```bash
# For development (with Poetry)
poetry install --extras server

# Or install from PyPI
pip install s2auth[server]
```

# Readding OpenAPI specs through swagger docs
```bash
./serve_specs.sh
```

# Run Developer tooling
```bash
ci/lint.sh
ci/test_unit.sh
ci/typecheck.sh
```

# Run python
* `python` (with your virtual environment activated)

_or_

* `poetry shell`
* `python`

# Update dependencies
* `poetry add <dependency>`

or for a dev dependency

* `poetry add -G dev <dependency>`

or for the server optional dependencies

* `poetry add --optional=server <dependency>`

# View installed dependencies
```bash
# List all installed packages
poetry show

# Show dependency tree
poetry show --tree

# Show specific package details
poetry show <package-name>
```


# What to do on pre-commit errors

* If the error is auto fixed, you can just `git add` the changed files, and commit again.
* If they are ruff errors, see https://docs.astral.sh/ruff/rules/ for the rule explanation
* If they are pyright errors, fix your typing
* If they are pytest errors, fix your code or the tests.
* Last case resort to skip the checks:
  * `git commit --no-verify`
  * `git push --no-verify`


# Generate openapi client and server
```bash
ci/generate_s2_auth.sh
```
Relevant code is under `src/s2auth/gen_protocol/{client,server}/{connection_init,pairing}`
Code here is not moved automatically so moving the generated code to a usable location is manual for now.

# Documentation

Comprehensive documentation is available in the `docs/` directory. To browse it locally:

```bash
poetry run mkdocs serve
```

Start with:
- `docs/index.md` for the project overview
- `docs/server/index.md` for server integration
- `docs/client/index.md` for client usage
- `docs/api/` for API reference pages
- `docs/Development.md` for development setup and maintenance notes

Key reference docs:
- **[Dependency Override Guide](docs/dependency_overrides.md)** - How to override dependencies in the DI system (4 methods: decorator, setup(), function call, context manager)
- **[Context Storage Override](docs/context_storage_override.md)** - Specific guide for overriding context storage with Redis or other backends
- **[Pairing Token Override](docs/pairing_token_override.md)** - How to customize pairing token generation (static tokens for testing, custom lengths, external sources)
- **[Dependency Injection Deployment Models](docs/dependency_injection_deployment_models.md)** - How the DI system works in different deployment scenarios (async, threaded, hybrid)
