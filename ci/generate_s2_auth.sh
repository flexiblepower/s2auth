#!/bin/bash

# Verify script is run from the workspace root (invoked as ./ci/...)
if [[ "$0" != ./ci/* ]]; then
	echo "Error: please run this script from the repository root as ./ci/$(basename \"$0\")" >&2
	exit 1
fi

. .venv/bin/activate

mkdir -p src/s2auth/gen_protocol/server/{connection_init,pairing}
mkdir -p src/s2auth/gen_protocol/client/{connection_init,pairing}

# Default: generate everything
GEN_MODELS=true
GEN_CLIENT=true

usage() {
	cat <<EOF
Usage: ./ci/$(basename "$0") [OPTIONS]

Options:
	-m, --models   Generate only models
	-c, --client   Generate only client
	-a, --all      Generate both models and client (default)
	-h, --help     Show this help message
EOF
}

# Parse args
if [[ $# -gt 0 ]]; then
	while [[ $# -gt 0 ]]; do
		case "$1" in
			-m|--models)
				GEN_MODELS=true; GEN_CLIENT=false; shift ;;
			-c|--client)
				GEN_CLIENT=true; GEN_MODELS=false; shift ;;
			-a|--all)
				GEN_MODELS=true; GEN_CLIENT=true; shift ;;
			-h|--help)
				usage; exit 0 ;;
			*)
				echo "Unknown option: $1" >&2; usage; exit 1 ;;
		esac
	done
fi

if [ "$GEN_MODELS" = true ]; then
    # files other than the spec yml cause the generator to fall over so we temporarily move them out of the way
    timestamp="$(date +%Y%m%d_%H%M%S)"
    tmpdir_path="_moved_${timestamp}_$$"
    mkdir -p -- "$tmpdir_path"
    mv specification/s2-connect/.[!.]* "$tmpdir_path/."
    mv specification/s2-connect/* "$tmpdir_path/."
    mv "$tmpdir_path"/*.yml specification/s2-connect/.

    # generate
	poetry run datamodel-codegen --type-mappings "string+byte=pydantic.Base64Bytes" --additional-imports "pydantic.Base64Bytes" --input specification/s2-connect/ --input-file-type openapi --output-model-type pydantic_v2.BaseModel --output src/s2auth/common/model/ --formatters=ruff-format --use-annotated --use-exact-imports  --openapi-scopes schemas parameters paths --use-subclass-enum

    # restore files
    mv "$tmpdir_path"/.[!.]* specification/s2-connect/.
    mv "$tmpdir_path"/* specification/s2-connect/.
    rm -rf "$tmpdir_path"

    # Replace Base64Str -> Base64Bytes and ensure import exists
    grep -Rl --include='*.py' '\bBase64Str\b' src/s2auth/common/model | xargs sed -i 's/\bBase64Str\b/Base64Bytes/g'
fi

# TODO: replace by another way to generate fastAPI server stubs; fastapi-codegen is unmaintained
#fastapi-codegen --input s2-over-ip-connection-init.yml --output-model-type pydantic_v2.BaseModel --output ../src/s2auth/gen_protocol/server/connection_init/
#fastapi-codegen --input s2-over-ip-pairing.yml --output-model-type pydantic_v2.BaseModel --output ../src/s2auth/gen_protocol/server/pairing/

if [ "$GEN_CLIENT" = true ]; then
	mkdir -p src/s2auth/gen_protocol/client/{connection_init,pairing}
	docker run --rm --user "$UID" -v "$PWD/src/s2auth/gen_protocol/client/:/local/client/" -v "$PWD/specification/s2-connect/:/local/specification/s2-connect" openapitools/openapi-generator-cli generate -i /local/specification/s2-connect/s2-over-ip-connection-init.yml -g python -o /local/client/connection_init --additional-properties="library=httpx"
	docker run --rm --user "$UID" -v "$PWD/src/s2auth/gen_protocol/client/:/local/client/" -v "$PWD/specification/s2-connect/:/local/specification/s2-connect" openapitools/openapi-generator-cli generate -i /local/specification/s2-connect/s2-over-ip-pairing.yml -g python -o /local/client/pairing --additional-properties="library=httpx"

    # Replace Base64Str -> Base64Bytes and ensure import exists
    grep -Rl --include='*.py' '\bBase64Str\b' src/s2auth/common/model | xargs sed -i 's/\bBase64Str\b/Base64Bytes/g'
fi
