import uvicorn
from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from pathlib import Path
import yaml
import re
from typing import Any


def merge_specs(base_path: Path) -> dict[str, Any]:
    """Merge openapi spec yaml files into a single OpenAPI specification"""

    # Find all YAML files in the directory
    yaml_files = list(base_path.glob("*.yml")) + list(base_path.glob("*.yaml"))

    if not yaml_files:
        raise ValueError(f"No YAML files found in {base_path}")

    # Parse all YAML files
    specs: dict[str, Any] = {}
    for yaml_file in yaml_files:
        with open(yaml_file, "r") as f:
            specs[yaml_file.name] = yaml.safe_load(f)

    # Initialize merged spec with a base structure
    merged_spec: dict[str, Any] = {
        "openapi": "3.0.3",
        "info": {},
        "servers": [],
        "tags": [],
        "paths": {},
        "components": {"schemas": {}, "securitySchemes": {}},
    }

    # Merge all specs
    for _filename, spec in specs.items():
        if not spec:
            continue

        # Use info from the first full spec we encounter
        if "info" in spec and not merged_spec["info"]:
            merged_spec["info"] = spec["info"]

        # Merge servers (avoid duplicates)
        if "servers" in spec:
            for server in spec["servers"]:
                if server not in merged_spec["servers"]:
                    merged_spec["servers"].append(server)

        # Merge tags (avoid duplicates)
        if "tags" in spec:
            for tag in spec["tags"]:
                if tag not in merged_spec["tags"]:
                    merged_spec["tags"].append(tag)

        # Merge paths
        if "paths" in spec:
            merged_spec["paths"].update(spec["paths"])

        # Merge components
        if "components" in spec:
            if "schemas" in spec["components"]:
                merged_spec["components"]["schemas"].update(
                    spec["components"]["schemas"]
                )
            if "securitySchemes" in spec["components"]:
                merged_spec["components"]["securitySchemes"].update(
                    spec["components"]["securitySchemes"]
                )

    # Resolve external $ref references (e.g., "s2-over-ip-common.yml#/..." -> "#/...")
    def resolve_refs(obj: Any) -> Any:
        """Recursively resolve external file references to internal references"""
        if isinstance(obj, dict):
            result: dict[str, Any] = {}
            for k, v in obj.items():  # type: ignore[attr-defined]
                if k == "$ref" and isinstance(v, str):
                    # Replace references like "s2-over-ip-common.yml#/components/..." with "#/components/..."
                    result[k] = re.sub(r"^[^#]+#", "#", v)
                else:
                    result[k] = resolve_refs(v)
            return result
        elif isinstance(obj, list):
            return [resolve_refs(item) for item in obj]  # type: ignore[misc]
        return obj

    # Apply reference resolution to the entire merged spec
    merged_spec = resolve_refs(merged_spec)

    return merged_spec


spec = merge_specs(Path(__file__).parent)

# Create FastAPI app
app = FastAPI(
    docs_url=None,
    redoc_url=None,
    title="S2 Discovery and Pairing OpenAPI Docs",
)


# Override the openapi method to return our merged spec
def custom_openapi():
    return spec


app.openapi = custom_openapi


@app.get("/", include_in_schema=False)
def docs():
    return get_swagger_ui_html(
        openapi_url="/openapi.json", title=spec.get("info", {}).get("title", "API Docs")
    )


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=5000)
