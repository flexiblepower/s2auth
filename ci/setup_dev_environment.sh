#!/bin/bash
CUR_DIR="$(dirname "${BASH_SOURCE[0]}")"

if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "Error: Neither python3 nor python found in PATH." >&2
  exit 1
fi

echo $PY

if ! command -v pyenv >/dev/null 2>&1; then
    echo "Please install pyenv: https://github.com/pyenv/pyenv?tab=readme-ov-file#a-getting-pyenv"
fi
if command -v pipx >/dev/null 2>&1; then
    if ! command -v poetry >/dev/null 2>&1; then
    	pipx install poetry
    fi
    pipx upgrade poetry
else
    curl -sSL https://install.python-poetry.org | $PY -
fi

./$CUR_DIR/install_dependencies.sh
poetry run pre-commit install
