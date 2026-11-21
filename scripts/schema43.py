"""Captura y comparación de metadatos MySQL sin leer filas de aplicación."""

import argparse
from getpass import getpass
import json
from pathlib import Path
import ssl

import pymysql
from pymysql.cursors import DictCursor


# Las identidades excluyen el nombre del esquema local. Las FK hacia otros
# esquemas conservan su nombre, para detectar una referencia externa real.
OBJECTS = {
    "tables": ("TABLES", "TABLE_SCHEMA", "TABLE_NAME",
               "TABLE_NAME, TABLE_TYPE, ENGINE, ROW_FORMAT, TABLE_COLLATION, CREATE_OPTIONS"),
    "columns": ("COLUMNS", "TABLE_SCHEMA", "TABLE_NAME, COLUMN_NAME",
                "TABLE_NAME, COLUMN_NAME, ORDINAL_POSITION, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT, "
                "CHARACTER_SET_NAME, COLLATION_NAME, EXTRA, GENERATION_EXPRESSION"),
    "indexes": ("STATISTICS", "TABLE_SCHEMA", "TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX",
                "TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX, COLUMN_NAME, NON_UNIQUE, COLLATION, SUB_PART, "
                "INDEX_TYPE, IS_VISIBLE, EXPRESSION"),
    "constraints": ("TABLE_CONSTRAINTS", "TABLE_SCHEMA", "TABLE_NAME, CONSTRAINT_NAME",
                    "TABLE_NAME, CONSTRAINT_NAME, CONSTRAINT_TYPE, ENFORCED"),
    "constraint_columns": (
        "KEY_COLUMN_USAGE", "TABLE_SCHEMA", "TABLE_NAME, CONSTRAINT_NAME, ORDINAL_POSITION",
        "TABLE_NAME, CONSTRAINT_NAME, ORDINAL_POSITION, COLUMN_NAME, POSITION_IN_UNIQUE_CONSTRAINT, "
        "IF(REFERENCED_TABLE_SCHEMA=DATABASE(), '<current>', REFERENCED_TABLE_SCHEMA) AS REFERENCED_SCHEMA, "
        "REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME",
    ),
    "foreign_keys": ("REFERENTIAL_CONSTRAINTS", "CONSTRAINT_SCHEMA", "TABLE_NAME, CONSTRAINT_NAME",
                     "TABLE_NAME, CONSTRAINT_NAME, UNIQUE_CONSTRAINT_NAME, REFERENCED_TABLE_NAME, "
                     "MATCH_OPTION, UPDATE_RULE, DELETE_RULE"),
    "checks": ("CHECK_CONSTRAINTS", "CONSTRAINT_SCHEMA", "CONSTRAINT_NAME",
               "CONSTRAINT_NAME, CHECK_CLAUSE"),
    "routines": (
        "ROUTINES", "ROUTINE_SCHEMA", "ROUTINE_NAME, ROUTINE_TYPE",
        "ROUTINE_NAME, ROUTINE_TYPE, DTD_IDENTIFIER, SQL_DATA_ACCESS, SECURITY_TYPE, IS_DETERMINISTIC, "
        "SQL_MODE, CHARACTER_SET_CLIENT, COLLATION_CONNECTION, DATABASE_COLLATION, "
        "SHA2(DEFINER, 256) AS DEFINER_HASH, "
        "SHA2(REPLACE(ROUTINE_DEFINITION, CHAR(13,10), CHAR(10)), 256) AS BODY_HASH",
    ),
    "parameters": ("PARAMETERS", "SPECIFIC_SCHEMA", "SPECIFIC_NAME, ROUTINE_TYPE, ORDINAL_POSITION",
                   "SPECIFIC_NAME, ROUTINE_TYPE, ORDINAL_POSITION, PARAMETER_MODE, PARAMETER_NAME, "
                   "DTD_IDENTIFIER, CHARACTER_SET_NAME, COLLATION_NAME"),
    "views": ("VIEWS", "TABLE_SCHEMA", "TABLE_NAME",
              "TABLE_NAME, CHECK_OPTION, IS_UPDATABLE, SECURITY_TYPE, SHA2(DEFINER, 256) AS DEFINER_HASH, "
              "SHA2(VIEW_DEFINITION, 256) AS BODY_HASH"),
    "triggers": ("TRIGGERS", "TRIGGER_SCHEMA", "TRIGGER_NAME",
                 "TRIGGER_NAME, EVENT_OBJECT_TABLE, EVENT_MANIPULATION, ACTION_ORDER, ACTION_TIMING, SQL_MODE, "
                 "SHA2(DEFINER, 256) AS DEFINER_HASH, SHA2(ACTION_STATEMENT, 256) AS BODY_HASH"),
    "events": ("EVENTS", "EVENT_SCHEMA", "EVENT_NAME",
               "EVENT_NAME, STATUS, EVENT_TYPE, INTERVAL_VALUE, INTERVAL_FIELD, TIME_ZONE, SQL_MODE, "
               "EXECUTE_AT, STARTS, ENDS, ON_COMPLETION, "
               "SHA2(DEFINER, 256) AS DEFINER_HASH, SHA2(EVENT_DEFINITION, 256) AS BODY_HASH"),
}


def capture(connection):
    with connection.cursor() as cursor:
        cursor.execute("SELECT DATABASE() AS schema_name, VERSION() AS server_version")
        snapshot = cursor.fetchone()
        if not snapshot["schema_name"]:
            raise ValueError("Selecciona un esquema antes de capturar metadatos.")
        objects = {}
        for name, (table, schema_column, key, columns) in OBJECTS.items():
            cursor.execute(
                f"SELECT {columns} FROM information_schema.{table} "
                f"WHERE {schema_column}=DATABASE() ORDER BY {key}"
            )
            objects[name] = cursor.fetchall()
        snapshot["objects"] = objects
        return snapshot


def connect_readonly(args):
    if args.isolated_schema:
        from scripts.local43 import IsolatedDatabase

        connection = IsolatedDatabase()._connect()
        try:
            connection.select_db(args.isolated_schema)
        except BaseException:
            connection.close()
            raise
        return connection
    tls = ssl.create_default_context(cafile=args.ca)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    return pymysql.connect(
        host=args.host, port=args.port, database=args.schema, user=args.user,
        password=getpass("Contraseña MySQL de solo lectura: "), ssl=tls, cursorclass=DictCursor,
        charset="utf8mb4", local_infile=False, autocommit=False,
        connect_timeout=8, read_timeout=30, write_timeout=8,
    )


def compare(reference, observed):
    differences = []
    incomplete = []
    for section, (_, _, key_spec, _) in OBJECTS.items():
        keys = key_spec.split(", ")
        left, right = [
            {tuple(row[key] for key in keys): row for row in snapshot["objects"][section]}
            for snapshot in (reference, observed)
        ]
        for key in sorted(set(left) | set(right)):
            label = f"{section} / {' / '.join(map(str, key))}"
            for row in (left.get(key), right.get(key)):
                if row is not None and "BODY_HASH" in row and row["BODY_HASH"] is None:
                    incomplete.append(label)
                    break
            if key not in left:
                differences.append(f"Adicional: {label}")
            elif key not in right:
                differences.append(f"Ausente o no visible: {label}")
            else:
                changed = sorted(field for field in left[key].keys() | right[key].keys()
                                 if left[key].get(field) != right[key].get(field))
                if changed:
                    differences.append(f"Distinto: {label} ({', '.join(changed)})")
    return differences, incomplete


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    collect = commands.add_parser("snapshot")
    collect.add_argument("--output", type=Path, required=True)
    target = collect.add_mutually_exclusive_group(required=True)
    target.add_argument("--host")
    target.add_argument("--isolated-schema")
    collect.add_argument("--port", type=int, default=3306)
    collect.add_argument("--schema")
    collect.add_argument("--user")
    collect.add_argument("--ca")
    diff = commands.add_parser("compare")
    diff.add_argument("reference", type=Path)
    diff.add_argument("observed", type=Path)
    args = parser.parse_args()
    if args.command == "snapshot":
        if args.host and not all((args.schema, args.user, args.ca)):
            collect.error("--host requiere --schema, --user y --ca")
        connection = connect_readonly(args)
        try:
            with connection.cursor() as cursor:
                cursor.execute("START TRANSACTION READ ONLY")
            snapshot = capture(connection)
        finally:
            connection.close()
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(snapshot, output, ensure_ascii=False, indent=2, default=str)
            output.write("\n")
        return 0
    reference, observed = [json.loads(path.read_text(encoding="utf-8"))
                           for path in (args.reference, args.observed)]
    differences, incomplete = compare(reference, observed)
    for item in differences:
        print(item)
    for item in incomplete:
        print(f"Definición no visible: {item}")
    print(f"Diferencias: {len(differences)}. Definiciones no verificables: {len(incomplete)}.")
    return 2 if incomplete else int(bool(differences))


if __name__ == "__main__":
    raise SystemExit(main())
