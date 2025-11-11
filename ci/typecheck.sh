#!/usr/bin/env sh

. .venv/bin/activate
echo "Running mypy"
mypy --config-file mypy.ini src/ ./tests/unit/

echo ""
echo "Running pyright"
pyright
