#!/bin/bash


. .venv/bin/activate
datamodel-codegen  --input ./specification/s2-over-ip-common.yml --input-file-type openapi --output-model-type pydantic_v2.BaseModel --output src/s2-auth/gen_protocol/gen_s2_auth.py --use-one-literal-as-default --use-subclass-enum --output-datetime-class AwareDatetime --use-double-quotes
