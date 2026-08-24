#!/bin/bash

. .venv/bin/activate
export PYTHONPATH="src/"

python3 -m s2auth.reference.server.run
