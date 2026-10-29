from pathlib import Path

from .main import app

METHOD_ORDER = ("get", "post", "put", "patch", "delete")


def _schema_label(schema: dict) -> str:
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    schema_type = schema.get("type", "object")
    if schema_type == "array":
        return f"array of {_schema_label(schema.get('items', {}))}"
    return schema_type


def render_api_markdown() -> str:
    specification = app.openapi()
    lines = [
        "# API reference",
        "",
        f"Generated from the FastAPI OpenAPI schema (version {specification['info']['version']}).",
        "",
        "All routes are under `/api`. Protected routes require the access-token cookie. "
        "Unsafe requests also require the `X-CSRF-Token` header matching the CSRF cookie.",
        "The central role and permission matrix is in `backend/app/permissions.py`.",
        "",
    ]
    for path, operations in sorted(specification["paths"].items()):
        for method in METHOD_ORDER:
            operation = operations.get(method)
            if not operation:
                continue
            lines.extend([
                f"## {method.upper()} `{path}`",
                "",
                operation.get("summary", operation.get("operationId", "API operation")),
                "",
            ])
            description = operation.get("description")
            if description:
                lines.extend([description, ""])
            parameters = operation.get("parameters", [])
            if parameters:
                lines.extend(["Parameters:", ""])
                for parameter in parameters:
                    schema = parameter.get("schema", {})
                    required = "required" if parameter.get("required") else "optional"
                    lines.append(
                        f"- `{parameter['in']}` `{parameter['name']}` "
                        f"({required}, {_schema_label(schema)})"
                    )
                lines.append("")
            body_schema = (
                operation.get("requestBody", {})
                .get("content", {})
                .get("application/json", {})
                .get("schema")
            )
            if body_schema:
                lines.extend([
                    f"JSON request body: `{_schema_label(body_schema)}`.",
                    "",
                ])
            responses = ", ".join(
                f"`{status}` {response.get('description', '').strip()}"
                for status, response in operation.get("responses", {}).items()
            )
            if responses:
                lines.extend([f"Responses: {responses}.", ""])
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    destination = Path(__file__).resolve().parents[2] / "docs" / "API.md"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_api_markdown(), encoding="utf-8")
    print(f"Wrote {destination}")


if __name__ == "__main__":
    main()
