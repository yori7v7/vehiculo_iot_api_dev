"""Preparación y pasos DEMO con transacciones reales de la fábrica, sin red."""

from copy import deepcopy
from datetime import datetime
import ssl
from threading import Event
import unittest
from unittest.mock import patch

import pymysql
from pydantic import ValidationError

from app.config.settings import Settings
from app.database.connection import MySQLDatabase
from app.errors.database import DatabaseResultError, DatabaseTransactionError, StoredProcedureExecutionError
from app.errors.domain import ResourceConflictError, ResourceNotFoundError
from app.models.demo_execution import DemoExecutionPlan, DemoExecutionResponse
from app.models.demos import DemoMovementResponse, DemoResponse, UINT_MAX
from app.services.demo_execution import DemoExecutionCancelled, DemoExecutionService


SQL_TIMESTAMP = datetime(2026, 10, 14, 12, 30, 45)


class DemoStore:
    def __init__(self):
        self.vehicle = {
            "id_vehiculo": 3, "nombre": "Vehículo", "modelo": None, "descripcion": None,
            "microcontrolador": None, "fecha_registro": None, "activo": 1,
        }
        self.demos = [{"id_demo": 5, "id_vehiculo": 3, "nombre": "Secuencia SQL", "descripcion": None, "activo": 1}]
        self.commands = [
            {"id_comando": 7, "id_vehiculo": 3, "nombre": "REVERSA", "codigo": -5, "descripcion": None, "activo": 1},
            {"id_comando": 8, "id_vehiculo": 3, "nombre": "AVANZAR", "codigo": 1, "descripcion": None, "activo": 1},
        ]
        self.movements = [
            {"id_demo_movimiento": 11, "orden": 2, "id_comando": 7, "comando": "REVERSA", "codigo": -5, "duracion_ms": 125, "pausa_ms": 30},
            {"id_demo_movimiento": 14, "orden": 8, "id_comando": 8, "comando": "AVANZAR", "codigo": 1, "duracion_ms": 240, "pausa_ms": 70},
        ]
        self.state = {"id_vehiculo": 3, "id_comando": 7, "conectado": 0, "fecha_actualizacion": None}
        self.failures = {}
        self.overrides = {}
        self.state_overrides = {}
        self.on_update = None
        self.commit_error = None
        self.timestamp = SQL_TIMESTAMP


class DemoCursor:
    def __init__(self, connection):
        self.connection = connection
        self.result_sets = [None]
        self.index = 0
        self.procedure = None
        self.occurrence = 0
        self.drained = False
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True

    def execute(self, statement):
        if statement != "START TRANSACTION READ ONLY":
            raise AssertionError("Sólo se permite iniciar la lectura; los datos requieren SP")
        self.connection.read_only = True
        self.connection.working_state = deepcopy(self.connection.store.state)
        self.drained = True

    def callproc(self, procedure, parameters):
        self.procedure = procedure
        self.connection.calls.append((procedure, tuple(parameters)))
        self.occurrence = sum(name == procedure for name, _ in self.connection.calls)
        error = self.connection.store.failures.get((procedure, self.occurrence, "call"))
        if error is not None:
            raise error
        result = self.connection.run_procedure(procedure, tuple(parameters))
        self.result_sets = [result, None] if result is not None else [None]

    @property
    def description(self):
        return (("column",),) if self.result_sets[self.index] is not None else None

    def fetchall(self):
        return deepcopy(self.result_sets[self.index])

    def nextset(self):
        error = self.connection.store.failures.get((self.procedure, self.occurrence, "drain"))
        if error is not None:
            raise error
        if self.index + 1 < len(self.result_sets):
            self.index += 1
            return True
        self.drained = True
        return None


class DemoConnection:
    def __init__(self, store):
        self.store = store
        self.working_state = None
        self.calls = []
        self.cursors = []
        self.read_only = False
        self.begins = self.commits = self.commit_attempts = self.rollbacks = self.closed = 0
        self.state_reads = 0

    def begin(self):
        self.begins += 1
        self.working_state = deepcopy(self.store.state)

    def commit(self):
        self.commit_attempts += 1
        if self.store.commit_error is not None:
            raise self.store.commit_error
        self.store.state = deepcopy(self.working_state)
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1
        self.working_state = deepcopy(self.store.state)

    def close(self):
        self.closed += 1

    def cursor(self):
        if self.cursors and not self.cursors[-1].drained:
            raise AssertionError("El SP previo debe drenar todos los resultados")
        cursor = DemoCursor(self)
        self.cursors.append(cursor)
        return cursor

    def state_rows(self):
        if self.working_state is None:
            return []
        row = deepcopy(self.working_state)
        command = next((value for value in self.store.commands if value["id_comando"] == row["id_comando"]), None)
        row.update(
            vehiculo=self.store.vehicle["nombre"],
            comando=command["nombre"] if command else None,
            codigo=command["codigo"] if command else None,
        )
        return [row]

    def run_procedure(self, name, parameters):
        if "historial" in name:
            raise AssertionError("Una ejecución DEMO nunca debe leer ni escribir historial")
        if name in self.store.overrides:
            return deepcopy(self.store.overrides[name])
        if name == "sp_obtener_vehiculo":
            (vehicle_id,) = parameters
            return [deepcopy(self.store.vehicle)] if self.store.vehicle and self.store.vehicle["id_vehiculo"] == vehicle_id else []
        if name == "sp_obtener_demos":
            (vehicle_id,) = parameters
            return deepcopy([value for value in self.store.demos if value["id_vehiculo"] == vehicle_id])
        if name == "sp_obtener_movimientos_demo":
            (demo_id,) = parameters
            return deepcopy(self.store.movements) if demo_id == 5 else []
        if name == "sp_obtener_comandos_vehiculo":
            (vehicle_id,) = parameters
            return deepcopy([value for value in self.store.commands if value["id_vehiculo"] == vehicle_id])
        if name == "sp_obtener_estado":
            (vehicle_id,) = parameters
            self.state_reads += 1
            if self.state_reads in self.store.state_overrides:
                return deepcopy(self.store.state_overrides[self.state_reads])
            return self.state_rows()
        if name == "sp_actualizar_estado":
            if self.read_only:
                raise AssertionError("Una lectura no debe actualizar estado")
            vehicle_id, command_id, connected = parameters
            self.working_state = {
                "id_vehiculo": vehicle_id, "id_comando": command_id,
                "conectado": int(connected), "fecha_actualizacion": self.store.timestamp,
            }
            if self.store.on_update is not None:
                self.store.on_update(self)
            return None
        raise AssertionError(f"SP inesperado en la ejecución: {name}")


class DemoExecutionModelTests(unittest.TestCase):
    def test_plan_is_independent_and_nested_models_are_frozen(self):
        store = DemoStore()
        demo = DemoResponse.model_validate(store.demos[0])
        movement = DemoMovementResponse.model_validate(store.movements[0])
        plan = DemoExecutionPlan(demo=demo, movimientos=(movement,))
        demo.nombre = "Modificado afuera"
        movement.duracion_ms = 999
        self.assertEqual(plan.demo.nombre, "Secuencia SQL")
        self.assertEqual(plan.movimientos[0].duracion_ms, 125)
        with self.assertRaises(ValidationError):
            plan.demo = demo
        with self.assertRaises(ValidationError):
            plan.demo.nombre = "No permitido"
        with self.assertRaises(ValidationError):
            plan.movimientos[0].duracion_ms = 999
        self.assertIsInstance(plan.movimientos, tuple)

    def test_control_response_has_only_ids_and_declared_status(self):
        for status in ("iniciada", "cancelada"):
            self.assertEqual(
                DemoExecutionResponse(id_vehiculo=3, id_demo=5, estado=status).model_dump(),
                {"id_vehiculo": 3, "id_demo": 5, "estado": status},
            )
        with self.assertRaises(ValidationError):
            DemoExecutionResponse(id_vehiculo=3, id_demo=5, estado="ok")


class DemoExecutionDataTests(unittest.TestCase):
    def setUp(self):
        self.store = DemoStore()
        self.connections = []
        settings = Settings(
            _env_file=None, db_host="database.example.invalid", db_name="demo_test",
            db_user="test_user", db_password="test-only-nonfunctional", db_ssl_ca="tests/fake-ca.pem",
        )
        tls_patch = patch(
            "app.database.connection.ssl.create_default_context",
            return_value=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
        )
        tls_patch.start()
        self.addCleanup(tls_patch.stop)

        def connect(**_):
            connection = DemoConnection(self.store)
            self.connections.append(connection)
            return connection

        connect_patch = patch("app.database.connection.pymysql.connect", side_effect=connect)
        self.connect = connect_patch.start()
        self.addCleanup(connect_patch.stop)
        self.service = DemoExecutionService(MySQLDatabase(settings))

    def prepare(self):
        return self.service.prepare(3, 5)

    def assert_rolled_back(self, expected_state):
        connection = self.connections[-1]
        self.assertEqual((connection.commits, connection.rollbacks, connection.closed), (0, 1, 1))
        self.assertEqual(self.store.state, expected_state)

    def test_prepare_reads_exact_sp_and_preserves_dynamic_sequence_and_times(self):
        plan = self.prepare()
        self.assertEqual([step.orden for step in plan.movimientos], [2, 8])
        self.assertEqual([(step.duracion_ms, step.pausa_ms) for step in plan.movimientos], [(125, 30), (240, 70)])
        connection = self.connections[0]
        self.assertTrue(connection.read_only)
        self.assertEqual(connection.calls, [
            ("sp_obtener_vehiculo", (3,)), ("sp_obtener_demos", (3,)),
            ("sp_obtener_movimientos_demo", (5,)), ("sp_obtener_comandos_vehiculo", (3,)),
        ])
        self.assertEqual((connection.commits, connection.rollbacks, connection.closed), (0, 1, 1))

    def test_prepare_accepts_zero_and_full_existing_unsigned_times(self):
        self.store.movements[0].update(duracion_ms=0, pausa_ms=0)
        self.store.movements[1].update(duracion_ms=UINT_MAX, pausa_ms=UINT_MAX)
        plan = self.prepare()
        self.assertEqual([(step.duracion_ms, step.pausa_ms) for step in plan.movimientos], [(0, 0), (UINT_MAX, UINT_MAX)])

    def test_prepare_missing_and_inactive_vehicle_fail_before_demo_read(self):
        for vehicle, error_type in ((None, ResourceNotFoundError), ({**self.store.vehicle, "activo": 0}, ResourceConflictError)):
            with self.subTest(error_type=error_type):
                self.store.vehicle = vehicle
                with self.assertRaises(error_type):
                    self.prepare()
                self.assertEqual(self.connections[-1].calls, [("sp_obtener_vehiculo", (3,))])

    def test_prepare_missing_foreign_or_inactive_demo_is_rejected(self):
        original = deepcopy(self.store.demos[0])
        for demos, error_type in (
            ([], ResourceNotFoundError),
            ([{**original, "id_vehiculo": 4}], ResourceNotFoundError),
            ([{**original, "activo": 0}], ResourceConflictError),
        ):
            with self.subTest(demos=demos):
                self.store.demos = demos
                with self.assertRaises(error_type):
                    self.prepare()
                self.assertEqual(len(self.connections[-1].calls), 2)

    def test_prepare_empty_demo_is_conflict_without_state_writes(self):
        self.store.movements = []
        with self.assertRaises(ResourceConflictError):
            self.prepare()
        self.assertNotIn("sp_actualizar_estado", [name for name, _ in self.connections[-1].calls])

    def test_prepare_rejects_nonpositive_duplicate_or_descending_order_without_sorting(self):
        original = deepcopy(self.store.movements)
        invalid = [
            [{**original[0], "orden": 0}], [{**original[0], "orden": -1}],
            [original[0], {**original[1], "orden": 2}], list(reversed(original)),
            [original[0], {**original[1], "id_demo_movimiento": 11}],
        ]
        for movements in invalid:
            with self.subTest(movements=movements):
                self.store.movements = movements
                with self.assertRaises(ResourceConflictError):
                    self.prepare()
                self.assertEqual(self.connections[-1].commits, 0)

    def test_prepare_rejects_missing_inactive_foreign_or_changed_command_metadata(self):
        original = deepcopy(self.store.commands)
        for commands in (
            original[1:], [{**original[0], "activo": 0}, original[1]],
            [{**original[0], "id_vehiculo": 4}, original[1]],
            [{**original[0], "nombre": "dato privado cambiado"}, original[1]],
            [{**original[0], "codigo": 99}, original[1]],
        ):
            with self.subTest(commands=commands):
                self.store.commands = commands
                with self.assertRaises(ResourceConflictError) as raised:
                    self.prepare()
                self.assertNotIn("dato privado", str(raised.exception))

    def test_malformed_prepare_result_is_sanitized(self):
        self.store.overrides["sp_obtener_movimientos_demo"] = [{"dato_privado": "no devolver"}]
        with self.assertRaises(DatabaseResultError) as raised:
            self.prepare()
        self.assertNotIn("dato_privado", str(raised.exception))
        self.assertEqual(self.connections[-1].closed, 1)

    def test_each_step_uses_new_connection_one_commit_and_current_connectivity(self):
        plan = self.prepare()
        self.store.state["conectado"] = 1
        first = self.service.apply_step(plan, plan.movimientos[0])
        self.assertIs(first.conectado, True)
        self.assertEqual(first.fecha_actualizacion, SQL_TIMESTAMP)
        self.store.state["conectado"] = 0
        second = self.service.apply_step(plan, plan.movimientos[1])
        self.assertIs(second.conectado, False)
        self.assertEqual(second.id_comando, 8)
        self.assertEqual(len(self.connections), 3)
        for connection in self.connections[1:]:
            self.assertEqual((connection.begins, connection.commits, connection.closed), (1, 1, 1))
            self.assertEqual(connection.calls, [
                ("sp_obtener_vehiculo", (3,)), ("sp_obtener_demos", (3,)),
                ("sp_obtener_comandos_vehiculo", (3,)), ("sp_obtener_estado", (3,)),
                ("sp_actualizar_estado", (3, connection.working_state["id_comando"], bool(connection.working_state["conectado"]))),
                ("sp_obtener_estado", (3,)),
            ])
            self.assertTrue(all(cursor.closed and cursor.drained for cursor in connection.cursors))

    def test_missing_state_uses_false_and_timestamp_is_not_fabricated(self):
        plan = self.prepare()
        self.store.state = None
        self.store.timestamp = None
        response = self.service.apply_step(plan, plan.movimientos[0])
        self.assertIs(response.conectado, False)
        self.assertIsNone(response.fecha_actualizacion)

    def test_step_keeps_prepared_sequence_when_database_configuration_is_edited(self):
        plan = self.prepare()
        self.store.movements[0].update(id_comando=8, comando="AVANZAR", codigo=1, duracion_ms=999)
        response = self.service.apply_step(plan, plan.movimientos[0])
        self.assertEqual(response.id_comando, 7)
        self.assertEqual(plan.movimientos[0].duracion_ms, 125)
        self.assertNotIn("sp_obtener_movimientos_demo", [name for name, _ in self.connections[-1].calls])

    def test_foreign_step_is_rejected_without_opening_a_connection(self):
        plan = self.prepare()
        foreign = DemoMovementResponse.model_validate({**self.store.movements[0], "id_demo_movimiento": 99})
        with self.assertRaises(ResourceConflictError):
            self.service.apply_step(plan, foreign)
        self.assertEqual(len(self.connections), 1)

    def test_step_revalidates_vehicle_and_demo_before_writing(self):
        plan = self.prepare()
        original_vehicle, original_demos = deepcopy(self.store.vehicle), deepcopy(self.store.demos)
        cases = [
            (None, original_demos, ResourceNotFoundError),
            ({**original_vehicle, "activo": 0}, original_demos, ResourceConflictError),
            (original_vehicle, [], ResourceNotFoundError),
            (original_vehicle, [{**original_demos[0], "id_vehiculo": 4}], ResourceNotFoundError),
            (original_vehicle, [{**original_demos[0], "activo": 0}], ResourceConflictError),
        ]
        for vehicle, demos, error_type in cases:
            with self.subTest(error_type=error_type, demos=demos):
                self.store.vehicle, self.store.demos = vehicle, demos
                before = deepcopy(self.store.state)
                with self.assertRaises(error_type):
                    self.service.apply_step(plan, plan.movimientos[0])
                self.assert_rolled_back(before)
                self.assertNotIn("sp_actualizar_estado", [name for name, _ in self.connections[-1].calls])

    def test_step_revalidates_command_activity_ownership_name_and_code(self):
        plan = self.prepare()
        original = deepcopy(self.store.commands)
        for commands in (
            original[1:], [{**original[0], "activo": 0}, original[1]],
            [{**original[0], "id_vehiculo": 4}, original[1]],
            [{**original[0], "nombre": "dato privado"}, original[1]],
            [{**original[0], "codigo": 100}, original[1]],
        ):
            with self.subTest(commands=commands):
                self.store.commands = commands
                before = deepcopy(self.store.state)
                with self.assertRaises(ResourceConflictError) as raised:
                    self.service.apply_step(plan, plan.movimientos[0])
                self.assertNotIn("dato privado", str(raised.exception))
                self.assert_rolled_back(before)

    def test_update_driver_failure_rolls_back_and_closes(self):
        plan = self.prepare()
        before = deepcopy(self.store.state)
        self.store.failures[("sp_actualizar_estado", 1, "call")] = pymysql.OperationalError(1644, "detalle privado")
        with self.assertRaises(StoredProcedureExecutionError) as raised:
            self.service.apply_step(plan, plan.movimientos[0])
        self.assertNotIn("detalle privado", str(raised.exception))
        self.assert_rolled_back(before)

    def test_final_read_failure_reverts_the_successful_update(self):
        plan = self.prepare()
        before = deepcopy(self.store.state)
        self.store.failures[("sp_obtener_estado", 2, "drain")] = pymysql.OperationalError(1644, "fallo tardío privado")
        with self.assertRaises(StoredProcedureExecutionError):
            self.service.apply_step(plan, plan.movimientos[1])
        self.assert_rolled_back(before)

    def test_missing_malformed_or_incoherent_final_state_never_commits(self):
        plan = self.prepare()
        valid = {
            "id_vehiculo": 3, "vehiculo": "Vehículo", "id_comando": 7,
            "comando": "REVERSA", "codigo": -5, "conectado": 0, "fecha_actualizacion": SQL_TIMESTAMP,
        }
        invalid_rows = [
            [], [{"dato_privado": "no exponer"}], [{**valid, "id_vehiculo": 4}],
            [{**valid, "id_comando": 8}], [{**valid, "comando": "OTRO"}],
            [{**valid, "codigo": 77}], [{**valid, "conectado": 1}],
        ]
        for result in invalid_rows:
            with self.subTest(result=result):
                before = deepcopy(self.store.state)
                self.store.state_overrides[2] = result
                with self.assertRaises(DatabaseResultError) as raised:
                    self.service.apply_step(plan, plan.movimientos[0])
                self.assertNotIn("dato_privado", str(raised.exception))
                self.assert_rolled_back(before)

    def test_commit_failure_does_not_return_success_or_change_persisted_state(self):
        plan = self.prepare()
        before = deepcopy(self.store.state)
        self.store.commit_error = pymysql.OperationalError(2013, "detalle privado de commit")
        with self.assertRaises(DatabaseTransactionError) as raised:
            self.service.apply_step(plan, plan.movimientos[1])
        self.assertNotIn("detalle privado", str(raised.exception))
        self.assertEqual(self.connections[-1].commit_attempts, 1)
        self.assert_rolled_back(before)

    def test_cancel_before_update_rolls_back_without_any_write(self):
        plan = self.prepare()
        before = deepcopy(self.store.state)
        cancel = Event()
        cancel.set()
        with self.assertRaises(DemoExecutionCancelled):
            self.service.apply_step(plan, plan.movimientos[0], should_cancel=cancel.is_set)
        self.assertNotIn("sp_actualizar_estado", [name for name, _ in self.connections[-1].calls])
        self.assert_rolled_back(before)

    def test_cancel_after_update_rolls_back_before_commit(self):
        plan = self.prepare()
        before = deepcopy(self.store.state)
        cancel = Event()
        self.store.on_update = lambda _: cancel.set()
        with self.assertRaises(DemoExecutionCancelled):
            self.service.apply_step(plan, plan.movimientos[1], should_cancel=cancel.is_set)
        self.assertIn(("sp_actualizar_estado", (3, 8, False)), self.connections[-1].calls)
        self.assertEqual(self.connections[-1].state_reads, 2)
        self.assertEqual(self.connections[-1].commit_attempts, 0)
        self.assert_rolled_back(before)


if __name__ == "__main__":
    unittest.main()
