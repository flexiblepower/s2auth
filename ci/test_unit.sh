#!/usr/bin/env sh

. .venv/bin/activate
PYTHONPATH="$PYTHONPATH:src/" pytest
