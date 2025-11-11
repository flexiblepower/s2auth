#!/bin/bash


. .venv/bin/activate
mkdir -p src/s2auth/gen_protocol/server/{connection_init,pairing}
mkdir -p src/s2auth/gen_protocol/client/{connection_init,pairing}

cd ./specification
fastapi-codegen --input s2-over-ip-connection-init.yml --output-model-type pydantic_v2.BaseModel --output ../src/s2auth/gen_protocol/server/connection_init/
fastapi-codegen --input s2-over-ip-pairing.yml --output-model-type pydantic_v2.BaseModel --output ../src/s2auth/gen_protocol/server/pairing/
echo "Please manually move the models.py over from each generated folder's model.py to src/s2auth/gen_protocol/server/models.py and move the Fastapi endpoints in their main.py's to src/s2auth/server/main.py"
cd ..

docker run --rm --user "$UID" -v "$PWD/src/s2auth/gen_protocol/client/:/local/client/" -v "$PWD/specification/:/local/specification" openapitools/openapi-generator-cli generate -i /local/specification/s2-over-ip-connection-init.yml -g python -o /local/client/connection_init --additional-properties="library=httpx"
docker run --rm --user "$UID" -v "$PWD/src/s2auth/gen_protocol/client/:/local/client/" -v "$PWD/specification/:/local/specification" openapitools/openapi-generator-cli generate -i /local/specification/s2-over-ip-pairing.yml -g python -o /local/client/pairing --additional-properties="library=httpx"
