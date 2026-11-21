"""Ensayo aditivo en un esquema nuevo de la instancia MySQL de loopback."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
from secrets import token_hex
from subprocess import run

import pymysql

from scripts.local43 import DATA, ROOT, IsolatedDatabase
from scripts.schema43 import capture, compare


EXPECTED = "6378091a759ade267ee6e19f7f6dfe4788c3f30ad5f01036c74930b86f25f7d9"
TABLES = ("vehiculos", "comandos", "estado_vehiculo", "historial_comandos", "demos", "demo_movimientos")
NEW_TABLES = {
    "iot_usuario", "iot_modelo", "iot_capacidad", "iot_unidad", "iot_titularidad", "iot_sesion",
    "iot_reserva", "iot_intento", "iot_ticket", "iot_demo", "iot_paso", "iot_auditoria",
}
EXTRA_ROWS = """
INSERT INTO vehiculos(id_vehiculo,nombre) VALUES(81357,'Unidad adicional');
INSERT INTO comandos(id_comando,id_vehiculo,nombre,codigo) VALUES(81358,81357,'DETENER',0);
INSERT INTO estado_vehiculo(id_estado,id_vehiculo,id_comando,conectado) VALUES(81359,81357,NULL,FALSE);
INSERT INTO historial_comandos(id_historial,id_vehiculo,id_comando,origen)
VALUES(9000000043,81357,NULL,'FIXTURE');
INSERT INTO demos(id_demo,id_vehiculo,nombre) VALUES(81360,81357,'Secuencia adicional');
INSERT INTO demo_movimientos(id_demo_movimiento,id_demo,id_comando,orden,duracion_ms,pausa_ms)
VALUES(81361,81360,81358,1,50,30);
"""


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", required=True, type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--mysql", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    original, reference = args.original.read_bytes(), args.reference.read_bytes()
    require(sha256(original).hexdigest() == EXPECTED, "No coincide el SHA-256 esperado del original.")
    require(original == reference, "Los archivos difieren byte a byte.")
    require(not args.output.exists(), "La ruta de salida ya existe.")
    database = IsolatedDatabase()
    with database._connect() as guard:
        with guard.cursor() as cursor:
            cursor.execute("SELECT @@port AS port")
            require(cursor.fetchone()["port"] == 33343, "Puerto inesperado.")

    def sql(statement, schema=None):
        command = [
            str(args.mysql.resolve()), "--no-defaults", "--host=127.0.0.1", "--port=33343", "--protocol=TCP",
            "--user=root", "--ssl-mode=VERIFY_CA", f"--ssl-ca={DATA / 'ca.pem'}", "--default-character-set=utf8mb4",
            "--binary-mode", "--batch", "--skip-column-names",
        ]
        if schema:
            command.append(schema)
        result = run(command, input=statement.encode("utf-8"), capture_output=True, check=False, timeout=120)
        if result.returncode:
            raise SystemExit(result.stderr.decode("utf-8", errors="replace"))
        return result.stdout.decode("utf-8")

    require(Path(sql("SELECT @@datadir;").strip()).resolve() == DATA.resolve(), "Instancia MySQL inesperada.")

    def load(source, schema):
        create, create_count = re.subn(r"(?im)^CREATE DATABASE IF NOT EXISTS vehiculo_iot\b",
                                       f"CREATE DATABASE {schema}", source.decode("utf-8-sig"))
        source, use_count = re.subn(r"(?im)^USE vehiculo_iot;", f"USE {schema};", create)
        require((create_count, use_count) == (1, 1), "El volcado no tiene los selectores de esquema esperados.")
        sql(source)

    suffix = token_hex(5)
    baseline_name, trial_name = f"iot43_ref_{suffix}", f"iot43_orig_{suffix}"
    load(reference, baseline_name)
    load(original, trial_name)
    with database._connect() as connection:
        connection.select_db(baseline_name)
        baseline = capture(connection)
        connection.select_db(trial_name)
        original_schema = capture(connection)
    require(compare(baseline, original_schema) == ([], []), "Los catálogos importados difieren o están incompletos.")
    procedures = original_schema["objects"]["routines"]
    require(len(procedures) == 21 and all(item["ROUTINE_TYPE"] == "PROCEDURE" for item in procedures),
            "Se esperaban 21 procedimientos.")
    require({item["TABLE_NAME"] for item in original_schema["objects"]["tables"]} == set(TABLES),
            "Conjunto de tablas históricas inesperado.")
    require(sql(" UNION ALL ".join(f"SELECT COUNT(*) FROM {table}" for table in TABLES), trial_name).splitlines()
            == ["0"] * len(TABLES), "El volcado no está vacío.")

    fixture = ROOT / "tests" / "fixtures" / "platform43_legacy.sql"
    sql(fixture.read_text(encoding="utf-8") + EXTRA_ROWS, trial_name)
    show_tables = "".join(f"SHOW CREATE TABLE {table};SELECT * FROM {table} ORDER BY 1;" for table in TABLES)
    show_routines = "".join(f"SHOW CREATE PROCEDURE {item['ROUTINE_NAME']};" for item in procedures)
    before = sql(show_tables + show_routines, trial_name)
    scripts = ROOT / "scripts" / "migrations"
    for name in ("000_preflight", "001_plataforma_schema", "002_plataforma_data", "003_verify"):
        result = sql((scripts / f"{name}.sql").read_text(encoding="utf-8"), trial_name)
        if name == "000_preflight":
            require(result.splitlines()[-8:] == ["0", "0", "0"] + [f"{table}\t0" for table in TABLES[1:]],
                    "Hay vínculos cruzados o filas huérfanas.")
        if name == "002_plataforma_data":
            require(result.strip() == "2", "Deben quedar dos unidades históricas sin alta comercial.")
        if name == "003_verify":
            require(result.splitlines() == ["12", "0", "0", "0", "0"], "Fallaron los controles posteriores.")
    require(before == sql(show_tables + show_routines, trial_name),
            "Cambió alguna definición histórica o el contenido de las tablas.")

    with database._connect() as connection:
        connection.select_db(trial_name)
        current = capture(connection)
        require({row["TABLE_NAME"] for row in current["objects"]["tables"]} == set(TABLES) | NEW_TABLES,
                "Inventario de tablas posterior inesperado.")
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO iot_modelo (sku,nombre) VALUES ('ENSAYO','Modelo de ensayo')")
            model = cursor.lastrowid
            enroll = "INSERT INTO iot_unidad(vehiculo,serie,modelo,estado) VALUES(%s,%s,%s,'inventario')"
            cursor.execute(enroll, (81357, "ENSAYO-1", model))
            try:
                cursor.execute(enroll, (2147483647, "ENSAYO-2", model))
            except pymysql.err.IntegrityError as error:
                require(error.args[0] == 1452, "No se obtuvo el rechazo de la FK histórica.")
            else:
                raise SystemExit("La FK aceptó un ID inexistente.")
            connection.rollback()
    require("9000000043" in sql("CALL sp_obtener_historial(81357);", trial_name), "Se perdió el BIGINT histórico.")
    for procedure in ("sp_obtener_vehiculo(81243)", "sp_obtener_comandos_vehiculo(81243)",
                      "sp_obtener_estado(81243)", "sp_obtener_demos(81243)", "sp_obtener_movimientos_demo(81243)"):
        require("81243" in sql(f"CALL {procedure};", trial_name), f"Falló {procedure}.")
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(original_schema, output, ensure_ascii=False, indent=2, default=str)
        output.write("\n")
    print(f"MySQL {original_schema['server_version']}. Esquema de ensayo: {trial_name}.")
    print("0 diferencias en los catálogos importados. Seis tablas, 12 filas e IDs, y 21 procedimientos preservados.")
    print("12 tablas nuevas, 6 llamadas de lectura, BIGINT 9000000043 y FK comprobada con rollback.")


if __name__ == "__main__":
    main()
