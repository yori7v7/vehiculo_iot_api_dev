"""CRUD DEMO con SP simulados y HTTP ASGI, sin .env, sockets ni RDS."""

from contextlib import contextmanager
from copy import deepcopy
import json
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI
from pydantic import ValidationError

from app.database.procedures import ProcedureResult, StoredProcedureExecutor
from app.dependencies import get_database
from app.errors.database import (
    DatabaseConflictError,
    DatabaseResultError,
    DatabaseTransactionError,
    DatabaseUnavailableError,
    StoredProcedureExecutionError,
)
from app.errors.domain import ResourceConflictError, ResourceNotFoundError
from app.errors.handlers import register_exception_handlers
from app.models.common import INT_MAX, INT_MIN
from app.models.demos import (
    DemoCreate, DemoMovementCreate, DemoMovementResponse, DemoMovementUpdate,
    DemoResponse, DemoUpdate, UINT_MAX,
)
from app.repositories.demos import DemoMovementRepository, DemoRepository
from app.routers.demos import router
from app.services.demos import DemoMovementService, DemoService


def result(*rows):
    return ProcedureResult((tuple(rows),))


class DemoModelTests(unittest.TestCase):
    def test_demo_create_accepts_sql_lengths_nullable_description_and_preserves_name(self):
        self.assertIsNone(DemoCreate(nombre="Demo").descripcion)
        data = DemoCreate(nombre="n" * 80, descripcion="d" * 255)
        self.assertEqual(len(data.nombre), 80)
        self.assertEqual(DemoCreate(nombre="  Secuencia  ").nombre, "  Secuencia  ")

    def test_demo_create_rejects_blank_long_names_and_extra_fields(self):
        for values in (
            {}, {"nombre": ""}, {"nombre": " \t"}, {"nombre": "n" * 81},
            {"nombre": "Demo", "descripcion": "d" * 256},
            {"nombre": "Demo", "activo": True}, {"nombre": "Demo", "id_vehiculo": 3},
        ):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                DemoCreate(**values)

    def test_demo_update_requires_strict_active_and_clears_omitted_description(self):
        data = DemoUpdate(nombre="Demo", activo=False)
        self.assertIsNone(data.descripcion)
        for values in ({"nombre": "Demo"}, *(
            {"nombre": "Demo", "activo": value} for value in (1, 0, "true", None)
        )):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                DemoUpdate(**values)

    def test_demo_response_converts_only_mysql_boolean_values(self):
        values = {"id_demo": 10, "id_vehiculo": 3, "nombre": "Demo", "descripcion": None}
        self.assertIs(DemoResponse(**values, activo=0).activo, False)
        self.assertIs(DemoResponse(**values, activo=1).activo, True)
        for active in (2, "1", "true", None):
            with self.subTest(active=active), self.assertRaises(ValidationError):
                DemoResponse(**values, activo=active)

    def test_movement_create_accepts_zero_times_and_signed_parameter_upper_limit(self):
        minimal = DemoMovementCreate(id_comando=1, orden=1, duracion_ms=0)
        self.assertEqual(minimal.pausa_ms, 0)
        maximum = DemoMovementCreate(
            id_comando=INT_MAX, orden=INT_MAX, duracion_ms=INT_MAX, pausa_ms=INT_MAX
        )
        self.assertEqual(maximum.duracion_ms, INT_MAX)

    def test_movement_inputs_reject_coercion_negative_times_nonpositive_order_and_overflow(self):
        valid = {"id_comando": 7, "orden": 3, "duracion_ms": 0, "pausa_ms": 0}
        for field in valid:
            invalid_values = (True, "1", 1.0, None, INT_MAX + 1, -1)
            if field in ("id_comando", "orden"):
                invalid_values += (0,)
            for value in invalid_values:
                with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                    DemoMovementCreate(**{**valid, field: value})

    def test_movement_put_requires_all_four_fields_and_rejects_sql_absent_fields(self):
        valid = {"id_comando": 7, "orden": 3, "duracion_ms": 0, "pausa_ms": 0}
        for field in valid:
            with self.subTest(field=field), self.assertRaises(ValidationError):
                DemoMovementUpdate(**{key: value for key, value in valid.items() if key != field})
        for extra in ("id_demo", "id_demo_movimiento", "codigo", "comando", "activo"):
            with self.subTest(extra=extra), self.assertRaises(ValidationError):
                DemoMovementCreate(**valid, **{extra: 1})

    def test_movement_response_matches_select_and_accepts_existing_unsigned_times(self):
        values = {
            "id_demo_movimiento": 30, "orden": INT_MIN, "id_comando": 7,
            "comando": "AVANZAR", "codigo": INT_MIN,
            "duracion_ms": UINT_MAX, "pausa_ms": INT_MAX + 1,
        }
        response = DemoMovementResponse(**values)
        self.assertEqual(response.model_dump(), values)
        self.assertNotIn("id_demo", DemoMovementResponse.model_fields)
        for field in ("duracion_ms", "pausa_ms"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                DemoMovementResponse(**{**values, field: UINT_MAX + 1})


class DemoRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.executor = Mock(spec=StoredProcedureExecutor)
        self.demos = DemoRepository(self.executor)
        self.movements = DemoMovementRepository(self.executor)

    def test_create_demo_uses_exact_sql_order_and_generated_id(self):
        self.executor.execute.return_value = result({"id_demo": 12})
        self.assertEqual(self.demos.create(3, DemoCreate(nombre="Demo")), 12)
        self.executor.execute.assert_called_once_with("sp_crear_demo", (3, "Demo", None))

    def test_list_demo_uses_parent_id_and_parses_complete_columns(self):
        self.executor.execute.return_value = result(
            {"id_demo": 12, "id_vehiculo": 3, "nombre": "Demo", "descripcion": None, "activo": 0}
        )
        self.assertIs(self.demos.list_for_vehicle(3)[0].activo, False)
        self.executor.execute.assert_called_once_with("sp_obtener_demos", (3,))

    def test_update_demo_passes_all_fields_including_null_and_active(self):
        self.demos.update(12, DemoUpdate(nombre="Demo", activo=False))
        self.executor.execute.assert_called_once_with("sp_actualizar_demo", (12, "Demo", None, False))

    def test_delete_demo_uses_only_demo_id(self):
        self.demos.delete(12)
        self.executor.execute.assert_called_once_with("sp_eliminar_demo", (12,))

    def test_create_movement_does_not_expect_an_id_from_its_procedure(self):
        self.executor.execute.return_value = ProcedureResult(())
        self.assertIsNone(self.movements.create(12, DemoMovementCreate(id_comando=7, orden=3, duracion_ms=100)))
        self.executor.execute.assert_called_once_with("sp_agregar_movimiento_demo", (12, 7, 3, 100, 0))

    def test_list_movement_uses_only_demo_id_and_empty_list_is_valid(self):
        self.executor.execute.return_value = result()
        self.assertEqual(self.movements.list_for_demo(12), [])
        self.executor.execute.assert_called_once_with("sp_obtener_movimientos_demo", (12,))

    def test_update_movement_passes_exact_five_sql_parameters(self):
        self.movements.update(30, DemoMovementUpdate(id_comando=7, orden=3, duracion_ms=0, pausa_ms=10))
        self.executor.execute.assert_called_once_with("sp_actualizar_movimiento_demo", (30, 7, 3, 0, 10))

    def test_delete_movement_uses_only_movement_id(self):
        self.movements.delete(30)
        self.executor.execute.assert_called_once_with("sp_eliminar_movimiento_demo", (30,))

    def test_bad_created_id_or_malformed_movement_row_is_sanitized(self):
        self.executor.execute.return_value = result({"id_demo": True})
        with self.assertRaises(DatabaseResultError):
            self.demos.create(3, DemoCreate(nombre="Demo"))
        self.executor.execute.return_value = result({"dato_privado": "no exponer"})
        with self.assertRaises(DatabaseResultError) as raised:
            self.movements.list_for_demo(12)
        self.assertNotIn("dato_privado", str(raised.exception))


class DemoMemoryDatabase:
    """Snapshots del catálogo para observar commits/rollbacks, nunca datos reales."""

    def __init__(self):
        self.vehicles = {
            vehicle_id: {
                "id_vehiculo": vehicle_id, "nombre": f"Vehículo {vehicle_id}", "modelo": None,
                "descripcion": None, "microcontrolador": None, "fecha_registro": None, "activo": 1,
            }
            for vehicle_id in (3, 4)
        }
        self.commands = {
            1: {"id_comando": 1, "id_vehiculo": 3, "nombre": "DETENER", "codigo": 0, "descripcion": None, "activo": 1},
            7: {"id_comando": 7, "id_vehiculo": 3, "nombre": "AVANZAR", "codigo": 1, "descripcion": None, "activo": 1},
            8: {"id_comando": 8, "id_vehiculo": 4, "nombre": "OTRO", "codigo": 1, "descripcion": None, "activo": 1},
            9: {"id_comando": 9, "id_vehiculo": 3, "nombre": "INACTIVO", "codigo": -1, "descripcion": None, "activo": 0},
        }
        self.demos = {
            10: {"id_demo": 10, "id_vehiculo": 3, "nombre": "Secuencia", "descripcion": "Anterior", "activo": 1},
            11: {"id_demo": 11, "id_vehiculo": 3, "nombre": "Inactiva", "descripcion": None, "activo": 0},
            20: {"id_demo": 20, "id_vehiculo": 4, "nombre": "Ajena", "descripcion": None, "activo": 1},
        }
        self.movements = {
            30: {"id_demo_movimiento": 30, "id_demo": 10, "id_comando": 7, "orden": 1, "duracion_ms": 100, "pausa_ms": 0},
            31: {"id_demo_movimiento": 31, "id_demo": 10, "id_comando": 1, "orden": 2, "duracion_ms": 0, "pausa_ms": 10},
            40: {"id_demo_movimiento": 40, "id_demo": 20, "id_comando": 8, "orden": 1, "duracion_ms": 100, "pausa_ms": 0},
        }
        self.next_demo_id = 100
        self.next_movement_id = 1000
        self.calls = []
        self.transactions = []
        self.read_only = None
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0
        self.failures = {}
        self.overrides = {}
        self.transaction_error = None
        self.fail_commit = False

    @contextmanager
    def transaction(self, *, read_only=False):
        if self.transaction_error is not None:
            raise self.transaction_error
        snapshot = deepcopy((self.demos, self.movements, self.next_demo_id, self.next_movement_id))
        self.transactions.append(read_only)
        self.read_only = read_only
        try:
            yield self
            if self.fail_commit:
                raise DatabaseTransactionError()
        except BaseException:
            self.demos, self.movements, self.next_demo_id, self.next_movement_id = snapshot
            self.rollbacks += 1
            raise
        else:
            if read_only:
                self.rollbacks += 1
            else:
                self.commits += 1
        finally:
            self.closed += 1
            self.read_only = None


class DemoMemoryExecutor:
    READ_PROCEDURES = {
        "sp_obtener_vehiculo", "sp_obtener_comandos_vehiculo", "sp_obtener_demos", "sp_obtener_movimientos_demo",
    }

    def __init__(self, connection):
        self.database = connection

    def execute(self, procedure, parameters=()):
        values = tuple(parameters)
        self.database.calls.append((procedure, values))
        occurrence = sum(name == procedure for name, _ in self.database.calls)
        key = (procedure, occurrence)
        if key in self.database.failures:
            raise self.database.failures[key]
        if self.database.read_only and procedure not in self.READ_PROCEDURES:
            raise AssertionError("Una transacción READ ONLY no debe escribir.")
        if key in self.database.overrides:
            rows = self.database.overrides[key]
        else:
            method = getattr(self, procedure, None)
            if method is None:
                raise AssertionError(f"SP no permitido en el CRUD DEMO: {procedure}")
            rows = method(*values)
        return ProcedureResult(()) if rows is None else result(*deepcopy(rows))

    def sp_obtener_vehiculo(self, vehicle_id):
        vehicle = self.database.vehicles.get(vehicle_id)
        return [vehicle] if vehicle else []

    def sp_obtener_comandos_vehiculo(self, vehicle_id):
        return sorted(
            (value for value in self.database.commands.values() if value["id_vehiculo"] == vehicle_id),
            key=lambda value: value["codigo"],
        )

    def sp_crear_demo(self, vehicle_id, name, description):
        demo_id = self.database.next_demo_id
        self.database.next_demo_id += 1
        self.database.demos[demo_id] = {
            "id_demo": demo_id, "id_vehiculo": vehicle_id, "nombre": name, "descripcion": description, "activo": 1,
        }
        return [{"id_demo": demo_id}]

    def sp_obtener_demos(self, vehicle_id):
        return [value for _, value in sorted(self.database.demos.items()) if value["id_vehiculo"] == vehicle_id]

    def sp_actualizar_demo(self, demo_id, name, description, active):
        self.database.demos[demo_id].update(nombre=name, descripcion=description, activo=int(active))

    def sp_eliminar_demo(self, demo_id):
        del self.database.demos[demo_id]
        self.database.movements = {
            key: value for key, value in self.database.movements.items() if value["id_demo"] != demo_id
        }

    def check_unique_order(self, demo_id, order, excluded=None):
        if any(
            value["id_demo"] == demo_id and value["orden"] == order and key != excluded
            for key, value in self.database.movements.items()
        ):
            raise DatabaseConflictError()

    def sp_agregar_movimiento_demo(self, demo_id, command_id, order, duration, pause):
        self.check_unique_order(demo_id, order)
        movement_id = self.database.next_movement_id
        self.database.next_movement_id += 1
        self.database.movements[movement_id] = {
            "id_demo_movimiento": movement_id, "id_demo": demo_id, "id_comando": command_id,
            "orden": order, "duracion_ms": duration, "pausa_ms": pause,
        }
        return None

    def sp_obtener_movimientos_demo(self, demo_id):
        values = []
        for movement in sorted(self.database.movements.values(), key=lambda value: value["orden"]):
            if movement["id_demo"] == demo_id:
                command = self.database.commands[movement["id_comando"]]
                values.append({
                    **{key: value for key, value in movement.items() if key != "id_demo"},
                    "comando": command["nombre"], "codigo": command["codigo"],
                })
        return values

    def sp_actualizar_movimiento_demo(self, movement_id, command_id, order, duration, pause):
        movement = self.database.movements[movement_id]
        self.check_unique_order(movement["id_demo"], order, excluded=movement_id)
        movement.update(id_comando=command_id, orden=order, duracion_ms=duration, pausa_ms=pause)

    def sp_eliminar_movimiento_demo(self, movement_id):
        del self.database.movements[movement_id]


class DemoFixture:
    def setUp(self):
        self.database = DemoMemoryDatabase()
        self.demo_service = DemoService(self.database)
        self.movement_service = DemoMovementService(self.database)
        self.executor_patch = patch("app.services.demos.StoredProcedureExecutor", DemoMemoryExecutor)
        self.executor_patch.start()
        self.addCleanup(self.executor_patch.stop)
        self.connection_patch = patch(
            "app.database.connection.pymysql.connect", side_effect=AssertionError("No conectar RDS en estas pruebas.")
        )
        self.connection_guard = self.connection_patch.start()
        self.addCleanup(self.connection_patch.stop)
        self.settings_patch = patch(
            "app.config.settings.Settings", side_effect=AssertionError("No cargar .env en estas pruebas.")
        )
        self.settings_guard = self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
        self.create_movement = DemoMovementCreate(id_comando=7, orden=3, duracion_ms=0)
        self.update_movement = DemoMovementUpdate(id_comando=7, orden=3, duracion_ms=0, pausa_ms=0)

    def tearDown(self):
        self.connection_guard.assert_not_called()
        self.settings_guard.assert_not_called()


class DemoServiceTests(DemoFixture, unittest.TestCase):
    def test_demo_four_crud_operations_keep_complete_response_and_delete_cascades(self):
        created = self.demo_service.create(3, DemoCreate(nombre="Nueva"))
        self.assertEqual(created.id_demo, 100)
        self.assertIsNone(created.descripcion)
        self.assertTrue(created.activo)
        self.assertEqual([value.id_demo for value in self.demo_service.list_for_vehicle(3)], [10, 11, 100])
        updated = self.demo_service.update(3, 10, DemoUpdate(nombre="Renombrada", activo=False))
        self.assertIsNone(updated.descripcion)
        self.assertFalse(updated.activo)
        self.demo_service.delete(3, 10)
        self.assertNotIn(10, self.database.demos)
        self.assertFalse(any(value["id_demo"] == 10 for value in self.database.movements.values()))
        self.assertEqual(self.database.transactions, [False, True, False, False])
        self.assertEqual((self.database.commits, self.database.rollbacks), (3, 1))

    def test_movement_four_crud_operations_discover_new_id_from_readback(self):
        created = self.movement_service.create(3, 10, self.create_movement)
        self.assertEqual(created.id_demo_movimiento, 1000)
        self.assertEqual(created.pausa_ms, 0)
        self.assertNotIn("id_demo", created.model_dump())
        self.assertEqual([value.orden for value in self.movement_service.list_for_demo(3, 10)], [1, 2, 3])
        updated = self.movement_service.update(3, 10, 1000, self.update_movement)
        self.assertEqual(updated.id_demo_movimiento, 1000)
        self.movement_service.delete(3, 10, 1000)
        self.assertNotIn(1000, self.database.movements)
        self.assertEqual(self.database.transactions, [False, True, False, False])
        self.assertEqual((self.database.commits, self.database.rollbacks), (3, 1))

    def test_movement_create_uses_one_transaction_and_exact_read_write_read_sequence(self):
        self.movement_service.create(3, 10, self.create_movement)
        self.assertEqual(self.database.calls, [
            ("sp_obtener_vehiculo", (3,)), ("sp_obtener_demos", (3,)),
            ("sp_obtener_comandos_vehiculo", (3,)), ("sp_obtener_movimientos_demo", (10,)),
            ("sp_agregar_movimiento_demo", (10, 7, 3, 0, 0)), ("sp_obtener_movimientos_demo", (10,)),
        ])
        self.assertEqual(self.database.closed, 1)
        self.assertEqual(self.database.commits, 1)

    def test_valid_empty_collections_are_empty_and_use_read_only_transactions(self):
        self.database.demos.clear()
        self.assertEqual(self.demo_service.list_for_vehicle(3), [])
        self.database.demos[10] = {"id_demo": 10, "id_vehiculo": 3, "nombre": "Vacía", "descripcion": None, "activo": 1}
        self.database.movements.clear()
        self.assertEqual(self.movement_service.list_for_demo(3, 10), [])
        self.assertEqual(self.database.transactions, [True, True])
        self.assertEqual(self.database.commits, 0)
        self.assertTrue(all(name in DemoMemoryExecutor.READ_PROCEDURES for name, _ in self.database.calls))

    def test_catalog_allows_inactive_parents_demos_and_duplicate_demo_names(self):
        self.database.vehicles[3]["activo"] = 0
        first = self.demo_service.create(3, DemoCreate(nombre="Secuencia"))
        second = self.demo_service.create(3, DemoCreate(nombre="Secuencia"))
        self.assertNotEqual(first.id_demo, second.id_demo)
        response = self.movement_service.create(3, 11, self.create_movement)
        self.assertEqual(response.id_comando, 7)
        self.assertFalse(self.demo_service.list_for_vehicle(3)[1].activo)

    def test_missing_parent_fails_all_eight_operations_before_any_other_procedure(self):
        operations = (
            lambda: self.demo_service.create(99, DemoCreate(nombre="Demo")),
            lambda: self.demo_service.list_for_vehicle(99),
            lambda: self.demo_service.update(99, 10, DemoUpdate(nombre="Demo", activo=True)),
            lambda: self.demo_service.delete(99, 10),
            lambda: self.movement_service.create(99, 10, self.create_movement),
            lambda: self.movement_service.list_for_demo(99, 10),
            lambda: self.movement_service.update(99, 10, 30, self.update_movement),
            lambda: self.movement_service.delete(99, 10, 30),
        )
        for operation in operations:
            with self.subTest(operation=operation):
                self.database.calls.clear()
                with self.assertRaises(ResourceNotFoundError):
                    operation()
                self.assertEqual(self.database.calls, [("sp_obtener_vehiculo", (99,))])
        self.assertEqual(self.database.commits, 0)

    def test_foreign_or_missing_demo_cannot_be_updated_deleted_or_used_for_movements(self):
        for demo_id in (20, 99):
            operations = (
                lambda: self.demo_service.update(3, demo_id, DemoUpdate(nombre="Demo", activo=True)),
                lambda: self.demo_service.delete(3, demo_id),
                lambda: self.movement_service.create(3, demo_id, self.create_movement),
                lambda: self.movement_service.list_for_demo(3, demo_id),
                lambda: self.movement_service.update(3, demo_id, 30, self.update_movement),
                lambda: self.movement_service.delete(3, demo_id, 30),
            )
            for operation in operations:
                with self.subTest(demo_id=demo_id, operation=operation), self.assertRaises(ResourceNotFoundError):
                    operation()
        self.assertEqual(self.database.commits, 0)

    def test_foreign_or_missing_movement_cannot_be_changed_or_deleted(self):
        for movement_id in (40, 99):
            with self.subTest(movement_id=movement_id):
                with self.assertRaises(ResourceNotFoundError):
                    self.movement_service.update(3, 10, movement_id, self.update_movement)
                with self.assertRaises(ResourceNotFoundError):
                    self.movement_service.delete(3, 10, movement_id)
        self.assertEqual(self.database.commits, 0)
        self.assertEqual(self.database.movements[40]["id_demo"], 20)

    def test_foreign_missing_and_inactive_commands_are_rejected_before_writing(self):
        for command_id, error_type in ((8, ResourceNotFoundError), (99, ResourceNotFoundError), (9, ResourceConflictError)):
            for update in (False, True):
                with self.subTest(command_id=command_id, update=update):
                    data = {"id_comando": command_id, "orden": 3, "duracion_ms": 0, "pausa_ms": 0}
                    with self.assertRaises(error_type):
                        if update:
                            self.movement_service.update(3, 10, 30, DemoMovementUpdate(**data))
                        else:
                            self.movement_service.create(3, 10, DemoMovementCreate(**data))
        self.assertEqual(self.database.commits, 0)
        self.assertNotIn("sp_agregar_movimiento_demo", [name for name, _ in self.database.calls])
        self.assertNotIn("sp_actualizar_movimiento_demo", [name for name, _ in self.database.calls])

    def test_unique_order_conflicts_come_from_procedure_and_roll_back(self):
        original = deepcopy(self.database.movements)
        with self.assertRaises(DatabaseConflictError):
            self.movement_service.create(3, 10, DemoMovementCreate(id_comando=7, orden=1, duracion_ms=0))
        with self.assertRaises(DatabaseConflictError):
            self.movement_service.update(3, 10, 30, DemoMovementUpdate(id_comando=7, orden=2, duracion_ms=0, pausa_ms=0))
        self.assertEqual(self.database.movements, original)
        self.assertEqual((self.database.commits, self.database.rollbacks), (0, 2))
        self.assertIn(("sp_agregar_movimiento_demo", (10, 7, 1, 0, 0)), self.database.calls)

    def test_identical_updates_are_successful_without_using_affected_rows(self):
        self.demo_service.update(3, 10, DemoUpdate(nombre="Secuencia", descripcion="Anterior", activo=True))
        self.movement_service.update(3, 10, 30, DemoMovementUpdate(id_comando=7, orden=1, duracion_ms=100, pausa_ms=0))
        self.assertEqual(self.database.commits, 2)

    def test_reads_preserve_existing_sql_unsigned_times_and_signed_order(self):
        self.database.movements[30].update(orden=-1, duracion_ms=UINT_MAX, pausa_ms=INT_MAX + 1)
        value = self.movement_service.list_for_demo(3, 10)[0]
        self.assertEqual(value.orden, -1)
        self.assertEqual(value.duracion_ms, UINT_MAX)

    def test_wrong_vehicle_result_and_wrong_owner_in_list_are_controlled_errors(self):
        self.database.overrides[("sp_obtener_vehiculo", 1)] = [self.database.vehicles[4]]
        with self.assertRaises(DatabaseResultError):
            self.demo_service.create(3, DemoCreate(nombre="Demo"))
        self.database.calls.clear()
        self.database.overrides.clear()
        self.database.overrides[("sp_obtener_demos", 1)] = [self.database.demos[20]]
        with self.assertRaises(DatabaseResultError):
            self.demo_service.list_for_vehicle(3)
        self.assertEqual(self.database.commits, 0)

    def test_demo_create_missing_readback_rolls_back_insert(self):
        original = deepcopy(self.database.demos)
        self.database.overrides[("sp_obtener_demos", 1)] = []
        with self.assertRaises(DatabaseResultError):
            self.demo_service.create(3, DemoCreate(nombre="Demo"))
        self.assertEqual(self.database.demos, original)
        self.assertEqual(self.database.commits, 0)

    def test_demo_update_wrong_readback_rolls_back_edit(self):
        original = deepcopy(self.database.demos)
        self.database.overrides[("sp_obtener_demos", 2)] = [deepcopy(self.database.demos[10])]
        with self.assertRaises(DatabaseResultError):
            self.demo_service.update(3, 10, DemoUpdate(nombre="Nuevo", activo=False))
        self.assertEqual(self.database.demos, original)

    def test_demo_delete_failed_absence_check_rolls_back_cascade(self):
        original = deepcopy((self.database.demos, self.database.movements))
        self.database.overrides[("sp_obtener_demos", 2)] = [deepcopy(self.database.demos[10])]
        with self.assertRaises(DatabaseResultError):
            self.demo_service.delete(3, 10)
        self.assertEqual((self.database.demos, self.database.movements), original)

    def test_movement_create_requires_a_new_id_and_matching_written_values(self):
        original = deepcopy(self.database.movements)
        old = DemoMemoryExecutor(self.database).sp_obtener_movimientos_demo(10)[0]
        self.database.overrides[("sp_obtener_movimientos_demo", 2)] = [{**old, "orden": 3}]
        with self.assertRaises(DatabaseResultError):
            self.movement_service.create(3, 10, self.create_movement)
        self.assertEqual(self.database.movements, original)

    def test_movement_create_rejects_ambiguous_new_rows_at_requested_order(self):
        value = {"id_demo_movimiento": 1000, "orden": 3, "id_comando": 7, "comando": "AVANZAR", "codigo": 1, "duracion_ms": 0, "pausa_ms": 0}
        self.database.overrides[("sp_obtener_movimientos_demo", 2)] = [value, {**value, "id_demo_movimiento": 1001}]
        with self.assertRaises(DatabaseResultError):
            self.movement_service.create(3, 10, self.create_movement)
        self.assertNotIn(1000, self.database.movements)

    def test_movement_update_and_delete_bad_readbacks_roll_back(self):
        original = deepcopy(self.database.movements)
        self.database.overrides[("sp_obtener_movimientos_demo", 2)] = []
        with self.assertRaises(DatabaseResultError):
            self.movement_service.update(3, 10, 30, self.update_movement)
        self.assertEqual(self.database.movements, original)
        self.database.calls.clear()
        existing = DemoMemoryExecutor(self.database).sp_obtener_movimientos_demo(10)
        self.database.overrides[("sp_obtener_movimientos_demo", 2)] = existing
        with self.assertRaises(DatabaseResultError):
            self.movement_service.delete(3, 10, 30)
        self.assertEqual(self.database.movements, original)

    def test_procedure_failure_after_insert_reverts_new_movement(self):
        original = deepcopy(self.database.movements)
        self.database.failures[("sp_obtener_movimientos_demo", 2)] = StoredProcedureExecutionError()
        with self.assertRaises(StoredProcedureExecutionError):
            self.movement_service.create(3, 10, self.create_movement)
        self.assertEqual(self.database.movements, original)
        self.assertEqual((self.database.commits, self.database.rollbacks, self.database.closed), (0, 1, 1))

    def test_commit_failure_cannot_return_a_created_resource(self):
        original = deepcopy(self.database.demos)
        self.database.fail_commit = True
        with self.assertRaises(DatabaseTransactionError):
            self.demo_service.create(3, DemoCreate(nombre="Demo"))
        self.assertEqual(self.database.demos, original)
        self.assertEqual((self.database.commits, self.database.rollbacks, self.database.closed), (0, 1, 1))


class DemoHttpTests(DemoFixture, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.application = FastAPI()
        self.application.include_router(router)
        register_exception_handlers(self.application)
        self.application.dependency_overrides[get_database] = lambda: self.database

    async def request(self, method, path, payload=None):
        body = b"" if payload is None else json.dumps(payload).encode("utf-8")
        messages = []
        received = False

        async def receive():
            nonlocal received
            if received:
                return {"type": "http.disconnect"}
            received = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            messages.append(message)

        scope = {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1", "method": method, "scheme": "http", "path": path,
            "raw_path": path.encode("ascii"), "query_string": b"", "root_path": "",
            "headers": [(b"content-type", b"application/json")],
            "client": ("test.invalid", 50000), "server": ("test.invalid", 80),
        }
        await self.application(scope, receive, send)
        start = next(message for message in messages if message["type"] == "http.response.start")
        content = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
        return start["status"], json.loads(content) if content else None

    async def test_http_demo_create_list_replace_delete(self):
        status, created = await self.request("POST", "/vehiculos/3/demos", {"nombre": "Nueva"})
        self.assertEqual(status, 201)
        self.assertEqual(created, {"id_demo": 100, "id_vehiculo": 3, "nombre": "Nueva", "descripcion": None, "activo": True})
        status, values = await self.request("GET", "/vehiculos/3/demos")
        self.assertEqual(status, 200)
        self.assertEqual([value["id_demo"] for value in values], [10, 11, 100])
        status, updated = await self.request("PUT", "/vehiculos/3/demos/100", {"nombre": "Cambio", "activo": False})
        self.assertEqual(status, 200)
        self.assertIsNone(updated["descripcion"])
        self.assertIs(updated["activo"], False)
        self.assertEqual(await self.request("DELETE", "/vehiculos/3/demos/100"), (204, None))

    async def test_http_movement_create_list_replace_delete(self):
        path = "/vehiculos/3/demos/10/movimientos"
        status, created = await self.request("POST", path, {"id_comando": 7, "orden": 3, "duracion_ms": 0})
        self.assertEqual(status, 201)
        self.assertEqual(created, {
            "id_demo_movimiento": 1000, "orden": 3, "id_comando": 7,
            "comando": "AVANZAR", "codigo": 1, "duracion_ms": 0, "pausa_ms": 0,
        })
        status, values = await self.request("GET", path)
        self.assertEqual(status, 200)
        self.assertEqual([value["orden"] for value in values], [1, 2, 3])
        status, updated = await self.request("PUT", f"{path}/1000", {"id_comando": 1, "orden": 4, "duracion_ms": 0, "pausa_ms": 0})
        self.assertEqual(status, 200)
        self.assertEqual((updated["comando"], updated["codigo"], updated["orden"]), ("DETENER", 0, 4))
        self.assertEqual(await self.request("DELETE", f"{path}/1000"), (204, None))

    async def test_empty_collections_are_http_200(self):
        self.database.demos.clear()
        self.assertEqual(await self.request("GET", "/vehiculos/3/demos"), (200, []))
        self.database.demos[10] = {"id_demo": 10, "id_vehiculo": 3, "nombre": "Demo", "descripcion": None, "activo": 0}
        self.database.movements.clear()
        self.assertEqual(await self.request("GET", "/vehiculos/3/demos/10/movimientos"), (200, []))

    async def test_missing_foreign_parents_commands_and_movements_are_http_404(self):
        cases = (
            ("GET", "/vehiculos/99/demos", None),
            ("PUT", "/vehiculos/3/demos/20", {"nombre": "Demo", "activo": True}),
            ("GET", "/vehiculos/3/demos/20/movimientos", None),
            ("POST", "/vehiculos/3/demos/10/movimientos", {"id_comando": 8, "orden": 3, "duracion_ms": 0}),
            ("DELETE", "/vehiculos/3/demos/10/movimientos/40", None),
        )
        for method, path, body in cases:
            with self.subTest(path=path):
                status, content = await self.request(method, path, body)
                self.assertEqual(status, 404)
                self.assertEqual(set(content), {"detail"})
        self.assertEqual(self.database.commits, 0)

    async def test_request_validation_422_happens_without_transactions(self):
        base = "/vehiculos/3/demos/10/movimientos"
        valid = {"id_comando": 7, "orden": 3, "duracion_ms": 0, "pausa_ms": 0}
        cases = (
            ("POST", "/vehiculos/0/demos", {"nombre": "Demo"}),
            ("DELETE", f"/vehiculos/3/demos/{INT_MAX + 1}", None),
            ("POST", "/vehiculos/3/demos", {"nombre": " "}),
            ("PUT", "/vehiculos/3/demos/10", {"nombre": "Demo", "activo": 1}),
            ("POST", base, {**valid, "orden": 0}),
            ("POST", base, {**valid, "id_comando": True}),
            ("POST", base, {**valid, "duracion_ms": INT_MAX + 1}),
            ("POST", base, {**valid, "pausa_ms": -1}),
            ("POST", base, {**valid, "codigo": 1}),
            ("PUT", f"{base}/30", {key: value for key, value in valid.items() if key != "pausa_ms"}),
        )
        for method, path, body in cases:
            with self.subTest(path=path, body=body):
                status, _ = await self.request(method, path, body)
                self.assertEqual(status, 422)
        self.assertEqual(self.database.transactions, [])

    async def test_sql_unique_order_and_inactive_command_are_http_409(self):
        path = "/vehiculos/3/demos/10/movimientos"
        for values in (
            {"id_comando": 7, "orden": 1, "duracion_ms": 0},
            {"id_comando": 9, "orden": 3, "duracion_ms": 0},
        ):
            with self.subTest(values=values):
                status, content = await self.request("POST", path, values)
                self.assertEqual(status, 409)
                self.assertNotIn("MySQL", content["detail"])
        self.assertEqual(self.database.commits, 0)

    async def test_database_failures_are_sanitized_http_500_and_503(self):
        error = StoredProcedureExecutionError()
        self.database.failures[("sp_obtener_demos", 1)] = error
        status, content = await self.request("GET", "/vehiculos/3/demos")
        self.assertEqual(status, 500)
        self.assertEqual(content, {"detail": str(error)})
        self.database.transaction_error = DatabaseUnavailableError()
        status, content = await self.request("GET", "/vehiculos/3/demos")
        self.assertEqual(status, 503)
        self.assertEqual(content, {"detail": str(self.database.transaction_error)})

    async def test_openapi_documents_eight_operations_with_exact_models_and_procedures(self):
        schema = self.application.openapi()
        mapping = {
            ("/vehiculos/{id_vehiculo}/demos", "post"): ("sp_crear_demo", "201"),
            ("/vehiculos/{id_vehiculo}/demos", "get"): ("sp_obtener_demos", "200"),
            ("/vehiculos/{id_vehiculo}/demos/{id_demo}", "put"): ("sp_actualizar_demo", "200"),
            ("/vehiculos/{id_vehiculo}/demos/{id_demo}", "delete"): ("sp_eliminar_demo", "204"),
            ("/vehiculos/{id_vehiculo}/demos/{id_demo}/movimientos", "post"): ("sp_agregar_movimiento_demo", "201"),
            ("/vehiculos/{id_vehiculo}/demos/{id_demo}/movimientos", "get"): ("sp_obtener_movimientos_demo", "200"),
            ("/vehiculos/{id_vehiculo}/demos/{id_demo}/movimientos/{id_demo_movimiento}", "put"): ("sp_actualizar_movimiento_demo", "200"),
            ("/vehiculos/{id_vehiculo}/demos/{id_demo}/movimientos/{id_demo_movimiento}", "delete"): ("sp_eliminar_movimiento_demo", "204"),
        }
        self.assertEqual(sum(len(methods) for methods in schema["paths"].values()), 8)
        for (path, method), (procedure, status) in mapping.items():
            with self.subTest(path=path, method=method):
                operation = schema["paths"][path][method]
                self.assertEqual(operation["tags"], ["DEMO"])
                self.assertIn(procedure, operation["description"])
                self.assertTrue({status, "404", "422", "500", "503"}.issubset(operation["responses"]))
                if method != "get":
                    self.assertIn("409", operation["responses"])
        fields = schema["components"]["schemas"]["DemoMovementResponse"]["properties"]
        self.assertEqual(set(fields), {"id_demo_movimiento", "orden", "id_comando", "comando", "codigo", "duracion_ms", "pausa_ms"})


if __name__ == "__main__":
    unittest.main()
