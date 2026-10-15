"""Vehículos: modelos, firmas SQL y transacciones sin archivos .env ni red."""

from contextlib import contextmanager
from datetime import datetime
import unittest
from unittest.mock import Mock, call, patch

from fastapi import FastAPI
from pydantic import TypeAdapter, ValidationError

from app.database.procedures import ProcedureResult, StoredProcedureExecutor
from app.errors.database import DatabaseResultError, StoredProcedureExecutionError
from app.errors.domain import ResourceNotFoundError
from app.models.common import EntityId, INT_MAX
from app.models.vehicles import VehicleCreate, VehicleResponse, VehicleUpdate
from app.repositories.vehicles import VehicleRepository
from app.routers import vehicles as routes
from app.services.vehicles import VehicleService


def vehicle_row(**changes):
    row = {
        "id_vehiculo": 7,
        "nombre": "Vehículo de pruebas",
        "modelo": "Modelo A",
        "descripcion": None,
        "microcontrolador": "ESP32",
        "fecha_registro": datetime(2026, 10, 14, 12, 0),
        "activo": 1,
    }
    row.update(changes)
    return row


def result_with_rows(*rows):
    return ProcedureResult((tuple(rows),))


class TransactionDatabase:
    """Registrar el límite transaccional sin simular reglas de los repositorios."""

    def __init__(self):
        self.connection = Mock()
        self.events = []
        self.read_only_calls = []

    @contextmanager
    def transaction(self, *, read_only=False):
        self.read_only_calls.append(read_only)
        self.events.append("begin_read" if read_only else "begin_write")
        try:
            yield self.connection
        except BaseException:
            self.events.append("rollback")
            raise
        else:
            self.events.append("rollback" if read_only else "commit")
        finally:
            self.events.append("close")


class VehicleModelTests(unittest.TestCase):
    def test_create_defaults_are_null_without_client_control_of_sql_defaults(self):
        data = VehicleCreate(nombre="Vehículo")
        self.assertEqual(
            data.model_dump(),
            {"nombre": "Vehículo", "modelo": None, "descripcion": None, "microcontrolador": None},
        )

    def test_requests_reject_unknown_and_database_managed_fields(self):
        for field in ("id_vehiculo", "fecha_registro", "activo", "extra"):
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    VehicleCreate(nombre="Vehículo", **{field: "valor"})
        with self.assertRaises(ValidationError):
            VehicleUpdate(nombre="Vehículo", activo=True, extra="valor")

    def test_nombre_rejects_empty_whitespace_and_non_strings(self):
        for value in ("", "  \t\n", None, 123, True):
            with self.subTest(nombre=value):
                with self.assertRaises(ValidationError):
                    VehicleCreate(nombre=value)
        self.assertEqual(VehicleCreate(nombre="  Vehículo  ").nombre, "  Vehículo  ")

    def test_sql_character_limits_accept_the_boundary_and_reject_overflow(self):
        lengths = {"nombre": 80, "modelo": 80, "descripcion": 255, "microcontrolador": 50}
        for model, required in ((VehicleCreate, {}), (VehicleUpdate, {"activo": True})):
            for field, limit in lengths.items():
                with self.subTest(model=model.__name__, field=field):
                    values = {"nombre": "Vehículo", **required, field: "á" * limit}
                    self.assertEqual(getattr(model(**values), field), "á" * limit)
                    values[field] += "á"
                    with self.assertRaises(ValidationError):
                        model(**values)

    def test_update_requires_nombre_and_a_strict_boolean(self):
        for data in ({"nombre": "Vehículo"}, {"activo": True}):
            with self.subTest(data=data):
                with self.assertRaises(ValidationError):
                    VehicleUpdate(**data)
        for value in (0, 1, "true", "false", "1", None):
            with self.subTest(activo=value):
                with self.assertRaises(ValidationError):
                    VehicleUpdate(nombre="Vehículo", activo=value)

    def test_update_replaces_omitted_optional_fields_with_null(self):
        data = VehicleUpdate(nombre="Nuevo nombre", activo=False)
        self.assertEqual(
            data.model_dump(),
            {
                "nombre": "Nuevo nombre",
                "modelo": None,
                "descripcion": None,
                "microcontrolador": None,
                "activo": False,
            },
        )

    def test_response_converts_only_database_boolean_values_and_allows_null_timestamp(self):
        for value in (False, True, 0, 1):
            with self.subTest(activo=value):
                response = VehicleResponse.model_validate(vehicle_row(activo=value, fecha_registro=None))
                self.assertIs(response.activo, bool(value))
                self.assertIsNone(response.fecha_registro)
        for value in (2, -1, "true", "0", None):
            with self.subTest(activo=value):
                with self.assertRaises(ValidationError):
                    VehicleResponse.model_validate(vehicle_row(activo=value))

    def test_response_requires_all_sql_columns(self):
        for field in vehicle_row():
            with self.subTest(missing=field):
                row = vehicle_row()
                del row[field]
                with self.assertRaises(ValidationError):
                    VehicleResponse.model_validate(row)

    def test_response_accepts_existing_empty_name_allowed_by_sql(self):
        self.assertEqual(VehicleResponse.model_validate(vehicle_row(nombre="")).nombre, "")

    def test_entity_ids_match_positive_signed_mysql_int(self):
        adapter = TypeAdapter(EntityId)
        self.assertEqual(adapter.validate_python(1), 1)
        self.assertEqual(adapter.validate_python(INT_MAX), INT_MAX)
        for value in (0, -1, INT_MAX + 1):
            with self.subTest(id=value):
                with self.assertRaises(ValidationError):
                    adapter.validate_python(value)


class VehicleRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.executor = Mock(spec=StoredProcedureExecutor)
        self.repository = VehicleRepository(self.executor)

    def test_create_uses_exact_sql_argument_order_and_returned_id(self):
        self.executor.execute.return_value = result_with_rows({"id_vehiculo": 34})
        data = VehicleCreate(nombre="Nombre", modelo="Modelo", descripcion="Descripción", microcontrolador="MCU")
        self.assertEqual(self.repository.create(data), 34)
        self.executor.execute.assert_called_once_with(
            "sp_crear_vehiculo", ("Nombre", "Modelo", "Descripción", "MCU")
        )

    def test_create_never_guesses_an_id_from_missing_or_invalid_results(self):
        for value in (None, 0, -1, True, "7", INT_MAX + 1):
            with self.subTest(id=value):
                self.executor.execute.return_value = result_with_rows({"id_vehiculo": value})
                with self.assertRaises(DatabaseResultError):
                    self.repository.create(VehicleCreate(nombre="Vehículo"))
        self.executor.execute.return_value = result_with_rows()
        with self.assertRaises(DatabaseResultError):
            self.repository.create(VehicleCreate(nombre="Vehículo"))

    def test_list_preserves_order_and_includes_inactive_vehicles(self):
        self.executor.execute.return_value = result_with_rows(
            vehicle_row(id_vehiculo=3, activo=0), vehicle_row(id_vehiculo=8)
        )
        result = self.repository.list()
        self.assertEqual([vehicle.id_vehiculo for vehicle in result], [3, 8])
        self.assertIs(result[0].activo, False)
        self.executor.execute.assert_called_once_with("sp_obtener_vehiculos")

    def test_get_uses_exact_sql_signature_and_distinguishes_missing_row(self):
        self.executor.execute.return_value = result_with_rows(vehicle_row())
        self.assertEqual(self.repository.get(7).id_vehiculo, 7)
        self.executor.execute.assert_called_once_with("sp_obtener_vehiculo", (7,))
        self.executor.execute.return_value = result_with_rows()
        self.assertIsNone(self.repository.get(7))

    def test_update_passes_nulls_and_false_in_sql_argument_order(self):
        data = VehicleUpdate(nombre="Nuevo nombre", activo=False)
        self.repository.update(7, data)
        self.executor.execute.assert_called_once_with(
            "sp_actualizar_vehiculo", (7, "Nuevo nombre", None, None, None, False)
        )

    def test_delete_uses_only_the_existing_delete_procedure(self):
        self.assertIsNone(self.repository.delete(7))
        self.executor.execute.assert_called_once_with("sp_eliminar_vehiculo", (7,))


class VehicleServiceTests(unittest.TestCase):
    def setUp(self):
        self.database = TransactionDatabase()
        self.executor = Mock(spec=StoredProcedureExecutor)
        executor_patch = patch("app.services.vehicles.StoredProcedureExecutor", return_value=self.executor)
        self.executor_class = executor_patch.start()
        self.addCleanup(executor_patch.stop)
        self.service = VehicleService(self.database)

    def return_results(self, *results):
        pending = iter(results)

        def execute(procedure, parameters=()):
            self.database.events.append(procedure)
            result = next(pending)
            if isinstance(result, BaseException):
                raise result
            return result

        self.executor.execute.side_effect = execute

    def assert_one_connection(self, *, read_only):
        self.assertEqual(self.database.read_only_calls, [read_only])
        self.executor_class.assert_called_once_with(self.database.connection)
        self.database.connection.commit.assert_not_called()
        self.database.connection.rollback.assert_not_called()
        self.database.connection.close.assert_not_called()

    def test_create_and_validated_reread_share_one_transaction(self):
        self.return_results(result_with_rows({"id_vehiculo": 7}), result_with_rows(vehicle_row()))
        result = self.service.create(VehicleCreate(nombre="Vehículo"))
        self.assertEqual(result.id_vehiculo, 7)
        self.assert_one_connection(read_only=False)
        self.assertEqual(
            self.database.events,
            ["begin_write", "sp_crear_vehiculo", "sp_obtener_vehiculo", "commit", "close"],
        )

    def test_create_missing_or_invalid_reread_rolls_back_before_returning(self):
        for reread in (
            result_with_rows(),
            result_with_rows({"nombre": "dato-privado"}),
            result_with_rows(vehicle_row(id_vehiculo=8)),
        ):
            with self.subTest(reread=reread):
                self.database.events.clear()
                self.return_results(result_with_rows({"id_vehiculo": 7}), reread)
                with self.assertRaises(DatabaseResultError) as raised:
                    self.service.create(VehicleCreate(nombre="Vehículo"))
                self.assertNotIn("dato-privado", str(raised.exception))
                self.assertEqual(self.database.events[-2:], ["rollback", "close"])
                self.assertNotIn("commit", self.database.events)

    def test_list_uses_read_only_and_keeps_inactive_rows(self):
        self.return_results(result_with_rows(vehicle_row(activo=0)))
        self.assertIs(self.service.list()[0].activo, False)
        self.assert_one_connection(read_only=True)
        self.assertEqual(self.database.events, ["begin_read", "sp_obtener_vehiculos", "rollback", "close"])

    def test_get_uses_read_only_and_allows_inactive_vehicle(self):
        self.return_results(result_with_rows(vehicle_row(activo=0)))
        self.assertIs(self.service.get(7).activo, False)
        self.assert_one_connection(read_only=True)

    def test_get_missing_raises_inside_read_transaction(self):
        self.return_results(result_with_rows())
        with self.assertRaises(ResourceNotFoundError):
            self.service.get(7)
        self.assert_one_connection(read_only=True)
        self.assertEqual(self.database.events[-2:], ["rollback", "close"])

    def test_get_rejects_a_row_with_another_vehicle_id(self):
        self.return_results(result_with_rows(vehicle_row(id_vehiculo=8)))
        with self.assertRaises(DatabaseResultError):
            self.service.get(7)
        self.assert_one_connection(read_only=True)
        self.assertEqual(self.database.events[-2:], ["rollback", "close"])

    def test_wrong_id_in_precheck_cannot_update_or_delete_another_vehicle(self):
        for operation in (
            lambda: self.service.update(7, VehicleUpdate(nombre="Actualizado", activo=True)),
            lambda: self.service.delete(7),
        ):
            with self.subTest(operation=operation):
                self.executor.reset_mock()
                self.database.events.clear()
                self.return_results(result_with_rows(vehicle_row(id_vehiculo=8)))
                with self.assertRaises(DatabaseResultError):
                    operation()
                self.executor.execute.assert_called_once_with("sp_obtener_vehiculo", (7,))
                self.assertEqual(self.database.events[-2:], ["rollback", "close"])
                self.assertNotIn("commit", self.database.events)

    def test_update_checks_existence_and_rereads_before_single_commit(self):
        self.return_results(
            result_with_rows(vehicle_row(activo=0)),
            ProcedureResult(()),
            result_with_rows(vehicle_row(nombre="Actualizado", modelo=None, microcontrolador=None)),
        )
        data = VehicleUpdate(nombre="Actualizado", activo=True)
        result = self.service.update(7, data)
        self.assertEqual(result.nombre, "Actualizado")
        self.assertIsNone(result.modelo)
        self.assert_one_connection(read_only=False)
        self.assertEqual(
            self.database.events,
            ["begin_write", "sp_obtener_vehiculo", "sp_actualizar_vehiculo", "sp_obtener_vehiculo", "commit", "close"],
        )
        self.assertEqual(
            self.executor.execute.call_args_list,
            [
                call("sp_obtener_vehiculo", (7,)),
                call("sp_actualizar_vehiculo", (7, "Actualizado", None, None, None, True)),
                call("sp_obtener_vehiculo", (7,)),
            ],
        )

    def test_update_missing_does_not_execute_write_procedure(self):
        self.return_results(result_with_rows())
        with self.assertRaises(ResourceNotFoundError):
            self.service.update(7, VehicleUpdate(nombre="Actualizado", activo=True))
        self.executor.execute.assert_called_once_with("sp_obtener_vehiculo", (7,))
        self.assertEqual(self.database.events, ["begin_write", "sp_obtener_vehiculo", "rollback", "close"])

    def test_update_invalid_reread_rolls_back_the_successful_write(self):
        for reread in (
            result_with_rows(),
            result_with_rows(vehicle_row(activo=2)),
            result_with_rows(vehicle_row(id_vehiculo=8)),
        ):
            with self.subTest(reread=reread):
                self.database.events.clear()
                self.return_results(result_with_rows(vehicle_row()), ProcedureResult(()), reread)
                with self.assertRaises(DatabaseResultError):
                    self.service.update(7, VehicleUpdate(nombre="Actualizado", activo=False))
                self.assertNotIn("commit", self.database.events)
                self.assertEqual(self.database.events[-2:], ["rollback", "close"])

    def test_update_procedure_failure_rolls_back_without_reread(self):
        self.return_results(result_with_rows(vehicle_row()), StoredProcedureExecutionError())
        with self.assertRaises(StoredProcedureExecutionError):
            self.service.update(7, VehicleUpdate(nombre="Actualizado", activo=True))
        self.assertEqual(self.executor.execute.call_count, 2)
        self.assert_one_connection(read_only=False)
        self.assertEqual(self.database.events[-2:], ["rollback", "close"])
        self.assertNotIn("commit", self.database.events)

    def test_delete_checks_existence_and_allows_inactive_vehicle(self):
        self.return_results(result_with_rows(vehicle_row(activo=0)), ProcedureResult(()))
        self.assertIsNone(self.service.delete(7))
        self.assert_one_connection(read_only=False)
        self.assertEqual(
            self.database.events,
            ["begin_write", "sp_obtener_vehiculo", "sp_eliminar_vehiculo", "commit", "close"],
        )

    def test_delete_missing_does_not_execute_delete_procedure(self):
        self.return_results(result_with_rows())
        with self.assertRaises(ResourceNotFoundError):
            self.service.delete(7)
        self.executor.execute.assert_called_once_with("sp_obtener_vehiculo", (7,))
        self.assertEqual(self.database.events[-2:], ["rollback", "close"])


class VehicleRouterTests(unittest.TestCase):
    def test_routes_forward_to_service_and_delete_returns_an_empty_204(self):
        service = Mock(spec=VehicleService)
        response = VehicleResponse.model_validate(vehicle_row())
        service.list.return_value = [response]
        service.get.return_value = response
        service.create.return_value = response
        service.update.return_value = response
        create = VehicleCreate(nombre="Vehículo")
        update = VehicleUpdate(nombre="Vehículo", activo=True)
        self.assertEqual(routes.list_vehicles(service), [response])
        self.assertIs(routes.get_vehicle(7, service), response)
        self.assertIs(routes.create_vehicle(create, service), response)
        self.assertIs(routes.update_vehicle(7, update, service), response)
        deleted = routes.delete_vehicle(7, service)
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(deleted.body, b"")
        service.get.assert_called_once_with(7)
        service.create.assert_called_once_with(create)
        service.update.assert_called_once_with(7, update)
        service.delete.assert_called_once_with(7)

    def test_openapi_documents_methods_limits_and_responses_without_starting_app(self):
        app = FastAPI()
        app.include_router(routes.router)
        schema = app.openapi()
        collection = schema["paths"]["/vehiculos"]
        item = schema["paths"]["/vehiculos/{id_vehiculo}"]
        self.assertEqual(set(collection), {"get", "post"})
        self.assertEqual(set(item), {"get", "put", "delete"})
        self.assertIn("201", collection["post"]["responses"])
        self.assertIn("200", item["put"]["responses"])
        self.assertNotIn("content", item["delete"]["responses"]["204"])
        for operation in item.values():
            self.assertIn("404", operation["responses"])
            parameter = operation["parameters"][0]["schema"]
            self.assertEqual(parameter["exclusiveMinimum"], 0)
            self.assertEqual(parameter["maximum"], INT_MAX)
        self.assertIn("409", item["delete"]["responses"])
        self.assertNotIn("409", collection["post"]["responses"])
        self.assertNotIn("409", item["put"]["responses"])
        update_schema = schema["components"]["schemas"]["VehicleUpdate"]
        self.assertEqual(set(update_schema["required"]), {"nombre", "activo"})
        self.assertIs(update_schema["additionalProperties"], False)


if __name__ == "__main__":
    unittest.main()
