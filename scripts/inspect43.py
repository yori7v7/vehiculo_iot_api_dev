"""Inventario local a partir del OpenAPI de FastAPI."""
import argparse
from json import dumps

from app.config.settings import Settings
import app.main as entry


def schema_name(value):
    if "$ref" in value:
        return value["$ref"].rsplit("/", 1)[-1]
    if "items" in value:
        return f"lista[{schema_name(value['items'])}]"
    if "anyOf" in value:
        return " o ".join(schema_name(item) for item in value["anyOf"])
    return value.get("type", "ver OpenAPI")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    entry.get_settings = lambda: Settings(platform43_enabled=args.platform)
    schema = entry.create_app().openapi()
    if args.json:
        print(dumps(schema, ensure_ascii=True, indent=2))
        return
    print("| Método | Ruta | Función | Credencial declarada | Entrada | Respuesta |")
    print("| --- | --- | --- | --- | --- | --- |")
    for path, methods in schema["paths"].items():
        for method, operation in methods.items():
            security = ", ".join(key for scheme in operation.get("security", []) for key in scheme) or "Pública"
            body = operation.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
            success = ", ".join(f"{code} {schema_name(item.get('content', {}).get('application/json', {}).get('schema', {}))}"
                                for code, item in operation["responses"].items() if code.startswith("2"))
            print(f"| {method.upper()} | {path} | {operation['summary']} | {security} | "
                  f"{schema_name(body) if body else '—'} | {success} |")


if __name__ == "__main__":
    main()
