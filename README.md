# Setup dev environment
Requires: pyenv with python 3.10 installed on the system.
Shell scripts are linux compatible.

```bash
ci/setup_dev_environment.sh
```

# Install as regular python package
* `pip install .` or from pypi should just work

# Call the client
The pairing client is exposed as the Python module `s2auth.client.main`.

From a development checkout, run it by:
- first creating and activating a virtual environment: `python -m venv .venv` and `source .venv/bin/activate`
- installing all dependancies `ci/install_dependancies.sh` (you may need to run `ci/setup_dev_environment` if poetry is not yet installed)
- then calling `poetry run python -client --help`

There is also a helper script in the repository:

Client workflow:
1. Run pairing first (`poetry run client ...`) to store connection details for a target `--pairing_s2_node_id`.
2. After pairing is complete, run connect mode to initiate the S2 session and fetch communication details.
3. If needed, run unpair mode to terminate the pairing.


## 1. Run pairing
Typical WAN example:

```bash
poetry run client \
  --server_url https://localhost:8005/v1 \
  --domain s2connect.example.com \
  --pairing_token test \
  --skip_cert_verify \
  --deployment WAN \
  --pairing_s2_node_id ninechars \
  --s2_role RM \
  --verbose
```

Typical LAN example:

```bash
poetry run client \
  --server_url https://localhost:8005/v1 \
  --certificate_file tests/localhost.chain.pem \
  --pairing_token test \
  --pairing_s2_node_id ninechars \
  --s2_role RM \
  --verbose
```

Required input:
- Provide a `--pairing_token` to start the pairing flow.
- For WAN deployments, provide `--domain` or let the client auto-detect it from `--server_url`.
- For LAN deployments, provide `--certificate_file` if you want to verify against a specific local certificate bundle.

Useful optional arguments:
- `--server_url` defaults to `http://localhost`.
- `--client_S2_nodeId` and `--server_S2_nodeId` let you provide explicit node IDs instead of auto-generated ones.
- `--pairing_s2_node_id` can be used when the pairing code must include a target S2 node ID.
- `--certificate_file` points to a CA/certificate bundle file for TLS verification in local or test setups.
- `--skip_cert_verify` disables certificate verification for local or test setups.
- `-v` or `--verbose` enables debug logging.

Auto-detection behavior:
- If `--deployment` is not set, the client tries to auto-detect it.
- `--domain` set: deployment is treated as `WAN`.
- `--certificate_file` set: deployment is treated as `LAN`.
- Otherwise the client inspects `--server_url`.
- `localhost`, `.local`, and private/local IP addresses are treated as `LAN`.
- Public hostnames or public IP addresses are treated as `WAN`.
- When deployment is auto-detected as `WAN` and `--domain` is not set, the client also auto-detects the domain from the hostname in `--server_url`.
- The client logs a warning whenever deployment or domain is auto-detected.

Test certificate:
- For local testing, a test certificate bundle is available at `tests/localhost.chain.pem`.
- This file is intended for development and test scenarios only.

## 2. Connect after pairing:

```bash
poetry run client \
  --connect \
  --pairing_s2_node_id <pairing-node-id> \
  --verbose
```

`--connect` uses the previously stored pairing data, calls `/initiateSession`, confirms the returned pending token, and stores/prints details such as selected protocol/version and server descriptions.

## 3. Unpair after pairing:

```bash
poetry run client \
  --unpair \
  --pairing_s2_node_id <pairing-node-id> \
  --verbose
```

**Please note:** `--connect` and `--unpair` are dedicated modes and only accept `--pairing_s2_node_id` (or `--pairing_S2_nodeId`) plus optional `--verbose`.

# Run the FastAPI server
```bash
poetry run server
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
* `poetry run python`

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

Comprehensive documentation is available in the `docs/` directory:

- **[Dependency Override Guide](docs/dependency_overrides.md)** - How to override dependencies in the DI system (4 methods: decorator, setup(), function call, context manager)
- **[Context Storage Override](docs/context_storage_override.md)** - Specific guide for overriding context storage with Redis or other backends
- **[Pairing Token Override](docs/pairing_token_override.md)** - How to customize pairing token generation (static tokens for testing, custom lengths, external sources)
- **[Dependency Injection Deployment Models](docs/dependency_injection_deployment_models.md)** - How the DI system works in different deployment scenarios (async, threaded, hybrid)
