#!/bin/bash
CUR_DIR="$(dirname "${BASH_SOURCE[0]}")"

if ! command -v pyenv >/dev/null 2>&1; then
    echo "Please install pyenv: https://github.com/pyenv/pyenv?tab=readme-ov-file#a-getting-pyenv"
fi
if command -v pipx >/dev/null 2>&1; then
    if ! command -v pyenv >/dev/null 2>&1; then
    	pipx install poetry
    fi
    pipx upgrade poetry
else
    curl -sSL https://install.python-poetry.org | python -
fi

./$CUR_DIR/install_dependencies.sh
poetry run pre-commit install
