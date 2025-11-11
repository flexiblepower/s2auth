#!/bin/bash

. .venv/bin/activate
PYTHONPATH="src/" python3 -m s2auth.client.main
