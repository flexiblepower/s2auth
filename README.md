# Setup dev environment
Requires: pyenv with python 3.9 installed on the system.
Shell scripts are linux compatible.

```bash
ci/setup_dev_environment.sh
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

# Commit without running pre-commit checks
* `git commit --no-verify`
* `git push --no-verify`

# Generate openapi client and server
```bash
ci/generate_s2_auth.sh
```
Relevant code is under `src/s2auth/gen_protocol/{client,server}/{connection_init,pairing}`
Code here is not moved automatically so moving the generated code to a usable location is manual for now.
