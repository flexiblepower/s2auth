#!/bin/bash


. .venv/bin/activate
# datamodel-codegen  --input ./specification/s2-over-ip-connection-init.yml --input-file-type openapi --output-model-type pydantic_v2.BaseModel --output src/s2auth/gen_protocol/connection_init.py --use-one-literal-as-default --use-subclass-enum --output-datetime-class AwareDatetime --use-double-quotes
cd ./specification
fastapi-codegen --input s2-over-ip-connection-init.yml --input s2-over-ip-pairing.yml --output-model-type pydantic_v2.BaseModel --output ../src/s2auth/gen_protocol/
