# Setup dev environment
Requires: python3.8 with virtualenv installed on system.
Shell scripts are linux compatible.

```bash
ci/setup_dev_environment.sh
ci/install_dependencies.sh
```

# Run Developer tooling
```bash
ci/lint.sh
ci/test_unit.sh
ci/typecheck.sh
```

# Update dependencies
Change the dependency list in pyproject.toml. Then:

```bash
ci/update_dependencies.sh
ci/install_dependencies.sh
```
This changes the locked versions in `dev-requirements.txt` and installs the new dependencies.

# Generate openapi client and server
```bash
ci/generate_s2_auth.sh
```
Relevant code is under `src/s2auth/gen_protocol/{client,server}/{connection_init,pairing}`
Code here is not moved automatically so moving the generated code to a usable location is manual for now.
