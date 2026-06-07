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

| Environment variable | Purpose |
| --- | --- |
| `PAIRING_NODE_ID` | Short pairing node ID alias, 8-12 characters |
| `SERVER_S2_NODE_ID` | UUID for the communication server node |
| `CEM_S2_NODE_ID` | UUID returned in the default CEM node description |
| `CEM_TYPE` | Node type returned in default server node description |
| `CEM_MODEL_NAME` | Model name returned in default server node description |
| `CEM_BRAND` | Brand returned in default server node description |
| `CEM_URL` | Connection initiation URL returned after pairing |

Example:

```env
SQLALCHEMY_DB_URI=postgresql://postgres:postgres@localhost/s2auth
HMAC_SALT=s2.example.com

PAIRING_NODE_ID=pairnode1
SERVER_S2_NODE_ID=00000000-0000-0000-0000-000000000001
CEM_S2_NODE_ID=00000000-0000-0000-0000-000000000002
CEM_TYPE=server
CEM_MODEL_NAME=default
CEM_BRAND=s2auth
CEM_URL=https://example.com/connection
```

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
