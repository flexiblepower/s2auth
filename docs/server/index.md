# Server

The server package contains building blocks for an S2 Connect pairing server and communication server.

The official protocol description is here:

<https://docs.s2standard.org/docs/communication-layer/discovery-pairing-authentication/>

## Responsibilities

The server helpers cover:

- creating a pairing attempt and pairing token;
- handling `/requestPairing`;
- validating the client's HMAC response in `/requestConnectionDetails`;
- returning connection details;
- handling `/initiateConnection`;
- confirming pending access tokens;
- validating the one-time token for the S2 communication channel.

The functions in `s2auth.server.pairing` and `s2auth.server.connection_initiation` are designed to be called from your web framework endpoints.

## Configuration

Server configuration is split into two Pydantic settings classes.

### Runtime config

`s2auth.server.config.Config` contains runtime infrastructure settings:

| Environment variable | Purpose | Default |
| --- | --- | --- |
| `SQLALCHEMY_DB_URI` | SQLAlchemy database URI | `postgresql://postgres:postgres@localhost/s2auth` |
| `HMAC_SALT` | Salt used for HMAC challenge-response calculation | `s2.example.com` |

### Server settings

`s2auth.server.settings.Settings` contains identity and endpoint metadata used by default hooks:

| Environment variable | Purpose | Default |
| --- | --- | --- |
| `PAIRING_NODE_ID` | Short pairing node ID alias, 8-12 characters | Required |
| `SERVER_S2_NODE_ID` | UUID for the communication server node | Required |
| `SUPPORTED_COMMUNICATION_PROTOCOLS` | Communication protocols supported by the server | `["WebSocket"]` |
| `SUPPORTED_S2_VERSIONS` | Supported S2 message versions, most recent first | `["v0.02-beta"]` |
| `SUPPORTED_S2_CONNECT_VERSIONS` | Supported S2 Connect versions, most recent first | `["v1.0-beta-2"]` |
| `CEM_S2_NODE_ID` | UUID returned in the default CEM node description | Required |
| `CEM_TYPE` | Node type returned in default server node description | Required |
| `CEM_MODEL_NAME` | Model name returned in default server node description | Required |
| `CEM_BRAND` | Brand returned in default server node description | Required |
| `CEM_URL` | Connection initiation URL returned after pairing | `None` |
| `CEM_DEPLOYMENT_TYPE` | Deployment type returned for the CEM | `WAN` |

Example:

```env
SQLALCHEMY_DB_URI=postgresql://postgres:postgres@localhost/s2auth
HMAC_SALT=s2.example.com

PAIRING_NODE_ID=pairnode1
SERVER_S2_NODE_ID=00000000-0000-0000-0000-000000000001
SUPPORTED_COMMUNICATION_PROTOCOLS='["WebSocket"]'
SUPPORTED_S2_VERSIONS='["v0.02-beta"]'
SUPPORTED_S2_CONNECT_VERSIONS='["v1.0-beta-2"]'
CEM_S2_NODE_ID=00000000-0000-0000-0000-000000000002
CEM_TYPE=server
CEM_MODEL_NAME=default
CEM_BRAND=s2auth
CEM_URL=https://example.com/connection
CEM_DEPLOYMENT_TYPE=WAN
```

## Getting started with the reference server

Install the server dependencies, copy the example environment file, and start the reference server:

```bash
poetry install --all-extras
cp .env.example .env
poetry run server
```

The reference server starts on port `8000`. The first communication is with the user, not another S2 node: use the existing `/pairing/userBeginPairing` endpoint to communicate the pairing token between the user and the S2 Connect server. This step is technically outside the S2 Connect protocol, but the server needs it so a later S2 Connect pairing request can prove knowledge of the same pairing token.

The reference server accepts HTTP Basic credentials `alice:alice` and `bob:bob`:

```bash
curl -X POST http://localhost:8000/pairing/userBeginPairing \
  -u alice:alice \
  -H 'Content-Type: application/json' \
  -d '"pairingToken123"'
```

After this request succeeds, the server has stored the pairing token for the authenticated user's client node. The S2 Connect pairing client can then call `/pairing/{s2_connect_version}/requestPairing` with the matching `nodeIdAlias` and complete the challenge-response flow.

## Pairing flow

Use `s2auth.server.pairing` for the server side of the pairing flow:

1. `initiate_pairing()` creates and stores a `PairingAttemptContext`.
2. `request_pairing()` handles the client's pairing request, stores an `AuthenticationContext`, selects the HMAC algorithm, computes the response to the client's challenge, and returns server descriptions.
3. `handle_client_response()` validates the client's response to the server challenge, stores the active access token, marks the pairing attempt as completed, and returns connection details.
4. `finalize_pairing()` marks the authentication context as paired after the client confirms it stored the returned connection details.

`requestConnectionDetails` and `finalizePairing` only need the `pairingAttemptId` header. The server resolves the matching `AuthenticationContext` through the `PairingAttemptContext.client_node_id`.

## Connection initiation flow

Use `s2auth.server.connection_initiation` after pairing:

1. `initiateConnection()` verifies the current access token, negotiates S2 message version and communication protocol, and generates a pending access token.
2. `validate_access_token()` confirms the pending token and promotes it to the current active access token.
3. `validate_s2_connection_token()` validates the one-time token used to authenticate the actual communication channel.

`initiateConnection()` receives a newly generated access token from DI as `new_access_token`; the injected value is an `AccessToken`, not a generator function.

## Reference server

The reference server initializes server hooks and dependency injection in FastAPI lifespan with:

```python
from s2auth.server import setup


setup(additional_hook_modules=["s2auth.reference.server.hooks"])
```

Its connection initiation endpoint hook uses the active FastAPI request to return `request.url_for("connection_root")`, so the connection URL always points at the mounted connection router.

## Customization

- [Hooks](hooks.md) describes how to customize pairing decisions and server descriptions.
- [Dependency Injection](dependency_injection.md) explains this project's use of `wepositive-di`.
- [Pairing Tokens](pairing_token_override.md) explains how to override pairing token generation.
