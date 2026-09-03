#!/usr/bin/env sh

set -e

# Poetry currently installs the root package with the placeholder version in this setup.
# Install dependencies via Poetry, then install the project via pip so the dynamic backend
# resolves the version from git tags.
poetry install --all-extras --no-root
poetry run pip install -e .
