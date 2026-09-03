# Client

The client package provides helpers for S2 pairing, connection initiation, and unpairing.

## Quick start

```python
import asyncio

from s2auth.client import ClientSettings, PairingClient


async def run_pairing_flow() -> None:
	settings = ClientSettings()
	client = PairingClient.from_settings(settings)

	pairing_result = await client.pair()
	connect_result = await client.connect(
		pairing_s2_node_id=pairing_result.pairing_s2_node_id
	)
	unpair_result = await client.unpair(
		pairing_s2_node_id=pairing_result.pairing_s2_node_id
	)

	print(pairing_result.pairing_s2_node_id)
	print(connect_result.success)
	print(unpair_result.success)


asyncio.run(run_pairing_flow())
```

## CLI

The reference client CLI is exposed as `client`.

```bash
client --help
```

Typical flow:

1. Run pairing to store connection details.
2. Run connect to request session details.
3. Run unpair when the pairing should be revoked.

## Configuration

Client configuration is loaded through `s2auth.client.settings.ClientSettings`.
Important settings include:

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

For full API details, see the Client section under API Reference.
