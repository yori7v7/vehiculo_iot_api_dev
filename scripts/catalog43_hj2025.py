"""Ampliación acotada de capacidades del HJ2025-1D existente, sin DDL."""

import os
from pathlib import Path

from app.platform43.security import GUEST_CODES, all_rows, audit, one


MODEL, VEHICLE, OWNER, VERSION = 1, 1, 2, 2
BASE = GUEST_CODES | {16, 32}
ADDITIONS = {64: "DEMO_ORIGINAL", 128: "CLAXON"}
APPLIED = "catalogo_hj2025_ampliado"
REVERTED = "catalogo_hj2025_revertido"


def require(condition, message):
    if not condition:
        raise SystemExit(f"DETENER: {message}")


def inventory(cursor, *, locked):
    suffix = " FOR UPDATE" if locked else ""
    model = one(cursor, "SELECT sku,nombre,activo FROM iot_modelo WHERE id=%s" + suffix, (MODEL,))
    require(model and model["activo"] and "HJ2025-1D" in (model["sku"], model["nombre"]), "Modelo distinto.")
    linked = all_rows(cursor, """
        SELECT vehiculo,serie,propietario,version,estado FROM iot_unidad WHERE modelo=%s ORDER BY vehiculo
    """ + suffix, (MODEL,))
    require(list(linked) == [{"vehiculo": VEHICLE, "serie": "RC-IOT-001", "propietario": OWNER,
                             "version": VERSION, "estado": "vendida"}], "Unidades o titularidad distintas.")
    require(one(cursor, "SELECT id_vehiculo FROM vehiculos WHERE id_vehiculo=%s AND activo" + suffix, (VEHICLE,)),
            "No existe el vehículo activo esperado.")
    caps = {row["codigo"]: (row["nombre"], bool(row["invitado"])) for row in all_rows(
        cursor, "SELECT codigo,nombre,invitado FROM iot_capacidad WHERE modelo=%s" + suffix, (MODEL,))}
    require(set(caps) in (BASE, BASE | ADDITIONS.keys()), "Se esperaban 11 capacidades base o las 13 previstas.")
    for code, name in ADDITIONS.items():
        require(code not in caps or caps[code] == (name, False), "Capacidad adicional incompatible o pública.")
    commands = all_rows(cursor, "SELECT codigo,nombre,activo FROM comandos WHERE id_vehiculo=%s" + suffix, (VEHICLE,))
    for code, name in ({code: cap[0] for code, cap in caps.items()} | ADDITIONS).items():
        rows = [row for row in commands if row["codigo"] == code]
        require(len(rows) == 1 and rows[0]["activo"] and rows[0]["nombre"] == name,
                f"Se requiere un comando legado activo y único, exacto: {code} {name}.")
    return caps


def change(cursor, operation):
    caps = inventory(cursor, locked=operation != "inspect")
    expanded = set(caps) == BASE | ADDITIONS.keys()
    if operation == "inspect":
        legacy = all_rows(cursor, """
            SELECT d.id_demo,d.nombre,d.activo,p.orden,p.duracion_ms,p.pausa_ms,c.codigo
            FROM demos d LEFT JOIN demo_movimientos p ON p.id_demo=d.id_demo
            LEFT JOIN comandos c ON c.id_comando=p.id_comando AND c.id_vehiculo=d.id_vehiculo AND c.activo
            WHERE d.id_vehiculo=%s ORDER BY d.id_demo,p.orden
        """, (VEHICLE,))
        print(f"Capacidades verificadas: {len(caps)}. DEMOS históricas: {list(legacy)}")
        return
    if operation == "apply" and not expanded:
        cursor.executemany("INSERT INTO iot_capacidad(modelo,codigo,nombre,invitado) VALUES(%s,%s,%s,FALSE)",
                           [(MODEL, code, name) for code, name in ADDITIONS.items()])
        audit(cursor, APPLIED, vehicle=VEHICLE)
    elif operation == "rollback" and expanded:
        last = one(cursor, """
            SELECT accion FROM iot_auditoria WHERE vehiculo=%s AND accion IN (%s,%s) ORDER BY id DESC LIMIT 1
        """, (VEHICLE, APPLIED, REVERTED))
        require(last == {"accion": APPLIED}, "No hay constancia de alta por esta herramienta.")
        require(not one(cursor, """
            SELECT p.id FROM iot_paso p JOIN iot_demo d ON d.id=p.demo
            WHERE d.modelo=%s AND p.codigo IN (64,128) LIMIT 1 FOR UPDATE
        """, (MODEL,)), "Una DEMO depende de estas capacidades. Preserva la secuencia y corrige hacia adelante.")
        cursor.execute("DELETE FROM iot_capacidad WHERE modelo=%s AND codigo IN (64,128)", (MODEL,))
        require(cursor.rowcount == 2, "Número inesperado de filas retiradas.")
        audit(cursor, REVERTED, vehicle=VEHICLE)
    final = inventory(cursor, locked=True)
    expected = caps | {code: (name, False) for code, name in ADDITIONS.items()} if operation == "apply" else {
        code: cap for code, cap in caps.items() if code in BASE}
    require(final == expected, "El resultado no coincide con el catálogo previsto.")


def catalog(db, args):
    approval = {"apply": "AMPLIAR-HJ2025-4.3", "rollback": "REVERTIR-HJ2025-4.3"}
    require(args.operation == "inspect" or args.approve == approval[args.operation], "Falta autorización explícita.")
    if args.operation != "inspect" and not args.isolated:
        from scripts.cutover43 import production_settings

        # El mismo destino y TLS que valida el lanzador de producción.
        production_settings()
        require(os.environ.get("APP_ENV") == "production" and os.environ.get("PLATFORM43_ENABLED") == "true",
                "Usa el lanzador administrativo de producción 4.3.")
        require(not Path(r"C:\ProgramData\VehiculoIoT\Cutover43\dispatch.enabled").exists(),
                "Inhibe el despacho antes de cambiar el catálogo.")
    with db.transaction(read_only=args.operation == "inspect") as connection, connection.cursor() as cursor:
        change(cursor, args.operation)
    print(f"GO catálogo HJ2025-1D: {args.operation} verificado.")
