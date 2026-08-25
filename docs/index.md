# s2-python-auth

`s2-python-auth` provides Python helpers for implementing S2 Connect pairing, authentication, and connection initiation.

The official S2 communication-layer specification is the normative reference:

<https://docs.s2standard.org/docs/communication-layer/discovery-pairing-authentication/>

## What is included

- **Client helpers** for pairing with an S2 pairing server, storing connection details, and initiating a connection.
- **Server helpers** for pairing requests, HMAC challenge-response verification, access token rotation, and hook-based customization.
- **Common utilities** for HMAC challenge-response handling, access-token generation, compatibility selection, and S2 Connect exceptions.

## Documentation map

- [Server](server/index.md): integrate server-side pairing and connection initiation.
- [Client](client/index.md): use the client-side pairing and connection helpers.
- [API Reference](api/common/hmac.md): generated API reference for public modules.
- [Development](Development.md): local development setup, commands, and maintenance notes.

## Protocol flow

At a high level, S2 Connect uses:

1. **Pairing**: nodes verify a pairing token through an HMAC challenge-response exchange.
2. **Connection details exchange**: the future communication server issues an access token.
3. **Connection initiation**: the communication client uses the current access token to obtain a new pending access token.
4. **Access token confirmation**: the pending access token is promoted after the client confirms it was persisted.
5. **S2 communication**: the previous token is used once to authenticate the actual communication channel.

For protocol details, see the official S2 specification linked above.
