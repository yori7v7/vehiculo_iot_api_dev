"""Aprovisionamiento fuera de HTTP. Ejecutar con una cuenta MySQL autorizada."""
import argparse
from getpass import getpass
from pathlib import Path
from secrets import token_urlsafe

from app.config.settings import get_settings
from app.database.connection import MySQLDatabase
from app.platform43.demos import save
from app.platform43.models import Client, Demo
from app.platform43.security import PASSWORDS, all_rows, audit, digest, login_email, one, unit


def administrator(db, args):
    password = getpass("Contraseña de administrador: ")
    if password != getpass("Repite la contraseña: "):
        raise SystemExit("Las contraseñas no coinciden.")
    data = Client(email=args.email, nombre=args.name, password=password)
    with db.transaction() as connection, connection.cursor() as cursor:
        cursor.execute("INSERT INTO iot_usuario(email,nombre,clave,rol) VALUES(%s,%s,%s,'administrador')",
                       (login_email(data.email), data.nombre, PASSWORDS.hash(password)))
        audit(cursor, "administrador_aprovisionado", user=cursor.lastrowid)


def device(db, args):
    header = Path(args.header)
    if header.name != "Platform43Secrets.h":
        raise SystemExit("El archivo debe llamarse Platform43Secrets.h.")
    key = token_urlsafe(32)
    setup_password = token_urlsafe(18)
    # 'x' evita sobrescribir un encabezado con credenciales vigentes.
    with header.open("x", encoding="ascii") as output:
        with db.transaction() as connection, connection.cursor() as cursor:
            unit(cursor, args.vehicle, lock=True)
            cursor.execute("UPDATE iot_unidad SET dispositivo=%s WHERE vehiculo=%s", (digest(key), args.vehicle))
            output.write(f'#define IOT43_DEVICE_ID {args.vehicle}\n#define IOT43_DEVICE_TOKEN "{key}"\n')
            output.write(f'#define IOT43_AP_PASSWORD "{setup_password}"\n')
            output.flush()
            audit(cursor, "credencial_dispositivo_rotada", vehicle=args.vehicle)


def revoke_device(db, args):
    with db.transaction() as connection, connection.cursor() as cursor:
        unit(cursor, args.vehicle, lock=True)
        cursor.execute("UPDATE iot_unidad SET dispositivo=NULL WHERE vehiculo=%s", (args.vehicle,))
        audit(cursor, "credencial_dispositivo_revocada", vehicle=args.vehicle)


def import_demo(db, args):
    with db.transaction() as connection, connection.cursor() as cursor:
        source = one(cursor, "SELECT id_vehiculo,nombre,descripcion,activo FROM demos WHERE id_demo=%s", (args.demo,))
        if not source:
            raise SystemExit("DEMO histórica inexistente.")
        model = one(cursor, "SELECT id FROM iot_modelo WHERE id=%s AND activo FOR UPDATE", (args.model,))
        if not model:
            raise SystemExit("Modelo de destino inexistente o inactivo.")
        rows = all_rows(cursor, """
            SELECT c.codigo,p.duracion_ms,p.pausa_ms FROM demo_movimientos p JOIN comandos c USING(id_comando)
            WHERE p.id_demo=%s AND c.id_vehiculo=%s AND c.activo ORDER BY p.orden
        """, (args.demo, source["id_vehiculo"]))
        count = one(cursor, "SELECT COUNT(*) n FROM demo_movimientos WHERE id_demo=%s", (args.demo,))["n"]
        if count != len(rows):
            raise SystemExit("La secuencia contiene comandos cruzados o inactivos.")
        data = Demo(nombre=source["nombre"], descripcion=source["descripcion"], activo=False, pasos=rows)
        new_id = save(cursor, data, args.model)
        audit(cursor, "demo_historica_importada")
    print(f"DEMO de fábrica importada e inactiva, ID {new_id}.")


def main():
    from scripts.catalog43_hj2025 import catalog

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--isolated", action="store_true")
    commands = parser.add_subparsers(required=True)
    admin = commands.add_parser("admin")
    admin.add_argument("email")
    admin.add_argument("name")
    admin.set_defaults(action=administrator)
    hardware = commands.add_parser("device")
    hardware.add_argument("vehicle", type=int)
    hardware.add_argument("header")
    hardware.set_defaults(action=device)
    revocation = commands.add_parser("revoke-device", help="Invalida la credencial sin generar un reemplazo.")
    revocation.add_argument("vehicle", type=int)
    revocation.set_defaults(action=revoke_device)
    migration = commands.add_parser("import-demo")
    migration.add_argument("demo", type=int)
    migration.add_argument("model", type=int)
    migration.set_defaults(action=import_demo)
    capacity = commands.add_parser("catalog-hj2025", help="Comprueba o amplía el catálogo de la unidad vinculada.")
    capacity.add_argument("operation", choices=("inspect", "apply", "rollback"))
    capacity.add_argument("--approve")
    capacity.set_defaults(action=catalog)
    args = parser.parse_args()
    if args.isolated:
        from scripts.local43 import IsolatedDatabase
        db = IsolatedDatabase()
    else:
        db = MySQLDatabase(get_settings())
    args.action(db, args)


if __name__ == "__main__":
    main()
