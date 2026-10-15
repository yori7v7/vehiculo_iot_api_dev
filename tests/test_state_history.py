"""Estado e historial mediante modelos y resultados simulados, sin RDS ni .env."""

from contextlib import contextmanager
from datetime import datetime
import unittest
from unittest.mock import Mock, call, patch

from fastapi import FastAPI
from pydantic import ValidationError

from app.database.procedures import ProcedureResult, StoredProcedureExecutor
from app.errors.database import DatabaseResultError
from app.errors.domain import ResourceNotFoundError
from app.models.common import INT_MAX, INT_MIN
from app.models.history import HistoryResponse
from app.models.state import StateResponse
from app.repositories.history import HistoryRepository
from app.repositories.state import StateRepository
from app.routers import history as history_routes
from app.routers import state as state_routes
from app.services.history import HistoryService
from app.services.state import StateService


def rows(*values):
    return ProcedureResult((tuple(values),))


def vehicle_row(**overrides):
    row = {
        "id_vehiculo": 3,
        "nombre": "Vehículo de prueba",
        "modelo": None,
        "descripcion": None,
        "microcontrolador": None,
        "fecha_registro": None,
        "activo": 1,
    }
    row.update(overrides)
    return row


def state_row(**overrides):
    row = {
        "id_vehiculo": 3,
        "vehiculo": "Vehículo de prueba",
        "id_comando": 7,
        "comando": "Reversa",
        "codigo": -5,
        "conectado": 1,
        "fecha_actualizacion": datetime(2026, 10, 14, 12, 0),
    }
    row.update(overrides)
    return row


def history_row(**overrides):
    row = {
        "id_historial": 9,
        "id_vehiculo": 3,
        "comando": "Reversa",
        "codigo": -5,
        "fecha_hora": datetime(2026, 10, 14, 12, 0),
        "origen": "MANUAL",
    }
    row.update(overrides)
    return row


class ReadTransactionDatabase:
    def __init__(self):
        self.connection = Mock()
        self.modes = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0

    @contextmanager
    def transaction(self, *, read_only=False):
        self.modes.append(read_only)
        try:
            yield self.connection
        except BaseException:
            self.rollbacks += 1
            raise
        else:
            if read_only:
                self.rollbacks += 1
            else:
                self.commits += 1
        finally:
            self.closed += 1


class StateHistoryModelTests(unittest.TestCase):
    def test_state_contains_exact_columns_of_select_without_id_estado(self):
        response = StateResponse.model_validate(state_row())
        self.assertEqual(set(response.model_dump()), set(state_row()))
        self.assertNotIn("id_estado", response.model_dump())
        self.assertIs(response.conectado, True)

    def test_state_accepts_null_command_join_and_timestamp(self):
        response = StateResponse.model_validate(
            state_row(id_comando=None, comando=None, codigo=None, fecha_actualizacion=None)
        )
        for field in ("id_comando", "comando", "codigo", "fecha_actualizacion"):
            self.assertIsNone(getattr(response, field))

    def test_connected_only_accepts_database_boolean_values(self):
        for value in (0, 1, False, True):
            with self.subTest(value=value):
                self.assertIs(StateResponse.model_validate(state_row(conectado=value)).conectado, bool(value))
        for value in (2, -1, "true", "0", None):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    StateResponse.model_validate(state_row(conectado=value))

    def test_response_names_obey_varchar_limits_and_allow_existing_empty_names(self):
        for model, fixture, field, limit in (
            (StateResponse, state_row, "vehiculo", 80),
            (StateResponse, state_row, "comando", 60),
            (HistoryResponse, history_row, "comando", 60),
            (HistoryResponse, history_row, "origen", 30),
        ):
            with self.subTest(model=model.__name__, field=field):
                self.assertEqual(getattr(model.model_validate(fixture(**{field: ""})), field), "")
                self.assertEqual(getattr(model.model_validate(fixture(**{field: "á" * limit})), field), "á" * limit)
                with self.assertRaises(ValidationError):
                    model.model_validate(fixture(**{field: "á" * (limit + 1)}))

    def test_history_id_uses_full_positive_signed_bigint_range(self):
        for value in (1, INT_MAX + 1, 2**63 - 1):
            with self.subTest(value=value):
                self.assertEqual(HistoryResponse.model_validate(history_row(id_historial=value)).id_historial, value)
        for value in (0, -1, 2**63, True, "9"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    HistoryResponse.model_validate(history_row(id_historial=value))

    def test_history_contains_exact_select_columns_and_allows_nullable_join(self):
        response = HistoryResponse.model_validate(history_row(comando=None, codigo=None, fecha_hora=None))
        self.assertEqual(set(response.model_dump()), set(history_row()))
        self.assertNotIn("id_comando", response.model_dump())
        self.assertIsNone(response.comando)
        self.assertIsNone(response.codigo)
        self.assertIsNone(response.fecha_hora)

    def test_origin_is_varchar_without_a_database_enum(self):
        self.assertEqual(HistoryResponse.model_validate(history_row(origen="ORIGEN_DESCONOCIDO")).origen, "ORIGEN_DESCONOCIDO")
        self.assertIs(HistoryResponse.model_fields["origen"].annotation, str)

    def test_both_responses_preserve_signed_command_codes_and_reject_coercion(self):
        for model, fixture in ((StateResponse, state_row), (HistoryResponse, history_row)):
            for code in (INT_MIN, 0, INT_MAX, None):
                with self.subTest(model=model.__name__, code=code):
                    self.assertEqual(model.model_validate(fixture(codigo=code)).codigo, code)
            for code in (INT_MIN - 1, INT_MAX + 1, True, "1", 1.0):
                with self.subTest(model=model.__name__, code=code):
                    with self.assertRaises(ValidationError):
                        model.model_validate(fixture(codigo=code))

    def test_nullable_columns_are_required_and_non_nullable_vehicle_ids_are_validated(self):
        for model, fixture in ((StateResponse, state_row), (HistoryResponse, history_row)):
            for field in fixture():
                with self.subTest(model=model.__name__, missing=field):
                    row = fixture()
                    del row[field]
                    with self.assertRaises(ValidationError):
                        model.model_validate(row)
            for value in (None, 0, -1, INT_MAX + 1):
                with self.subTest(model=model.__name__, id=value):
                    with self.assertRaises(ValidationError):
                        model.model_validate(fixture(id_vehiculo=value))


class StateHistoryRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.executor = Mock(spec=StoredProcedureExecutor)

    def test_state_get_uses_exact_read_procedure_and_can_return_none(self):
        repository = StateRepository(self.executor)
        self.executor.execute.return_value = rows(state_row())
        self.assertEqual(repository.get(3).id_comando, 7)
        self.executor.execute.assert_called_once_with("sp_obtener_estado", (3,))
        self.executor.execute.return_value = rows()
        self.assertIsNone(repository.get(3))

    def test_state_update_uses_exact_three_parameter_signature(self):
        repository = StateRepository(self.executor)
        self.assertIsNone(repository.update(3, 7, True))
        self.executor.execute.assert_called_once_with("sp_actualizar_estado", (3, 7, True))
        self.executor.reset_mock()
        repository.update(3, None, False)
        self.executor.execute.assert_called_once_with("sp_actualizar_estado", (3, None, False))

    def test_history_repository_returns_all_rows_and_origins_in_received_order(self):
        data = [history_row(id_historial=value, origen="DEMO" if value % 2 else "OTRO") for value in range(20, 0, -1)]
        self.executor.execute.return_value = rows(*data)
        response = HistoryRepository(self.executor).list_for_vehicle(3)
        self.assertEqual(len(response), 20)
        self.assertEqual([item.id_historial for item in response], list(range(20, 0, -1)))
        self.assertEqual([item.origen for item in response], [item["origen"] for item in data])
        self.executor.execute.assert_called_once_with("sp_obtener_historial", (3,))

    def test_history_register_uses_exact_three_parameter_signature(self):
        self.assertIsNone(HistoryRepository(self.executor).register(3, 7, "API"))
        self.executor.execute.assert_called_once_with("sp_registrar_historial", (3, 7, "API"))

    def test_history_empty_result_is_an_empty_list(self):
        self.executor.execute.return_value = rows()
        self.assertEqual(HistoryRepository(self.executor).list_for_vehicle(3), [])

    def test_malformed_sql_rows_are_sanitized(self):
        for repository, result in (
            (StateRepository(self.executor), rows(state_row(conectado="dato privado"))),
            (HistoryRepository(self.executor), rows(history_row(codigo="dato privado"))),
        ):
            with self.subTest(repository=type(repository).__name__):
                self.executor.execute.return_value = result
                with self.assertRaises(DatabaseResultError) as raised:
                    if isinstance(repository, StateRepository):
                        repository.get(3)
                    else:
                        repository.list_for_vehicle(3)
                self.assertNotIn("dato privado", str(raised.exception))


class StateHistoryServiceTests(unittest.TestCase):
    def setUp(self):
        self.database = ReadTransactionDatabase()
        self.executor = Mock(spec=StoredProcedureExecutor)
        self.factories = []
        for path in ("app.services.state.StoredProcedureExecutor", "app.services.history.StoredProcedureExecutor"):
            executor_patch = patch(path, return_value=self.executor)
            self.factories.append(executor_patch.start())
            self.addCleanup(executor_patch.stop)
        self.state = StateService(self.database)
        self.history = HistoryService(self.database)

    def assert_read_only_operation(self, factory_index):
        self.assertEqual(self.database.modes, [True])
        self.assertEqual((self.database.commits, self.database.rollbacks, self.database.closed), (0, 1, 1))
        self.factories[factory_index].assert_called_once_with(self.database.connection)
        self.database.connection.commit.assert_not_called()
        self.database.connection.rollback.assert_not_called()
        self.database.connection.close.assert_not_called()

    def test_state_get_shares_parent_check_and_read_on_one_connection_without_writes(self):
        self.executor.execute.side_effect = [rows(vehicle_row()), rows(state_row())]
        self.assertEqual(self.state.get(3).id_comando, 7)
        self.assertEqual(self.executor.execute.call_args_list, [
            call("sp_obtener_vehiculo", (3,)), call("sp_obtener_estado", (3,))
        ])
        self.assert_read_only_operation(0)

    def test_existing_inactive_vehicle_without_state_returns_none(self):
        self.executor.execute.side_effect = [rows(vehicle_row(activo=0)), rows()]
        self.assertIsNone(self.state.get(3))
        self.assert_read_only_operation(0)

    def test_history_existing_inactive_vehicle_without_rows_returns_empty_list(self):
        self.executor.execute.side_effect = [rows(vehicle_row(activo=0)), rows()]
        self.assertEqual(self.history.list_for_vehicle(3), [])
        self.assertEqual(self.executor.execute.call_args_list, [
            call("sp_obtener_vehiculo", (3,)), call("sp_obtener_historial", (3,))
        ])
        self.assert_read_only_operation(1)

    def test_missing_parent_is_404_before_reading_state_or_history(self):
        for operation in (self.state.get, self.history.list_for_vehicle):
            with self.subTest(operation=operation):
                self.executor.reset_mock()
                self.executor.execute.side_effect = [rows()]
                with self.assertRaises(ResourceNotFoundError):
                    operation(3)
                self.executor.execute.assert_called_once_with("sp_obtener_vehiculo", (3,))
        self.assertEqual(self.database.modes, [True, True])
        self.assertEqual((self.database.commits, self.database.rollbacks), (0, 2))

    def test_wrong_parent_id_is_a_result_error_before_reading_state_or_history(self):
        for operation in (self.state.get, self.history.list_for_vehicle):
            with self.subTest(operation=operation):
                self.executor.reset_mock()
                self.executor.execute.side_effect = [rows(vehicle_row(id_vehiculo=4))]
                with self.assertRaises(DatabaseResultError):
                    operation(3)
                self.executor.execute.assert_called_once_with("sp_obtener_vehiculo", (3,))
        self.assertEqual(self.database.commits, 0)

    def test_state_of_another_vehicle_cannot_be_returned(self):
        self.executor.execute.side_effect = [rows(vehicle_row()), rows(state_row(id_vehiculo=4))]
        with self.assertRaises(DatabaseResultError):
            self.state.get(3)
        self.assert_read_only_operation(0)

    def test_history_limits_to_ten_and_preserves_received_tie_order_for_every_origin(self):
        received_ids = [80, 79, 77, 76, 74, 72, 71, 68, 66, 65, 63, 61]
        origins = ("WORKBENCH", "API", "MANUAL", "DEMO", "ORIGEN_DESCONOCIDO")
        received = [
            history_row(id_historial=value, origen=origins[index % len(origins)])
            for index, value in enumerate(received_ids)
        ]
        # Todos comparten fecha: se conserva el desempate que ya entrega el SP.
        self.executor.execute.side_effect = [rows(vehicle_row()), rows(*received)]
        response = self.history.list_for_vehicle(3)
        self.assertEqual([item.id_historial for item in response], received_ids[:10])
        self.assertEqual([item.origen for item in response], [row["origen"] for row in received[:10]])
        self.assert_read_only_operation(1)

    def test_history_does_not_sort_again_after_the_procedure(self):
        received_ids = [5, 9, 3]
        self.executor.execute.side_effect = [
            rows(vehicle_row()), rows(*(history_row(id_historial=value) for value in received_ids))
        ]
        self.assertEqual([item.id_historial for item in self.history.list_for_vehicle(3)], received_ids)

    def test_history_preserves_workbench_and_unknown_origins_without_a_whitelist(self):
        self.executor.execute.side_effect = [
            rows(vehicle_row()), rows(history_row(origen="WORKBENCH"), history_row(origen="ORIGEN_DESCONOCIDO"))
        ]
        self.assertEqual(
            [item.origen for item in self.history.list_for_vehicle(3)],
            ["WORKBENCH", "ORIGEN_DESCONOCIDO"],
        )
        self.assert_read_only_operation(1)

    def test_history_validates_ownership_without_classifying_origin(self):
        self.executor.execute.side_effect = [
            rows(vehicle_row()), rows(history_row(id_vehiculo=4, origen="ORIGEN_DESCONOCIDO"))
        ]
        with self.assertRaises(DatabaseResultError):
            self.history.list_for_vehicle(3)
        self.assert_read_only_operation(1)


class StateHistoryRouterTests(unittest.TestCase):
    def test_no_state_returns_none_directly_and_history_forwards_without_writing(self):
        state_service = Mock(spec=StateService)
        state_service.get.return_value = None
        self.assertIsNone(state_routes.get_state(3, state_service))
        state_service.get.assert_called_once_with(3)
        history_service = Mock(spec=HistoryService)
        history_service.list_for_vehicle.return_value = []
        self.assertEqual(history_routes.list_history(3, history_service), [])
        history_service.list_for_vehicle.assert_called_once_with(3)

    def test_get_only_openapi_defines_null_state_and_read_error_responses(self):
        app = FastAPI()
        app.include_router(state_routes.router)
        app.include_router(history_routes.router)
        schema = app.openapi()
        paths = schema["paths"]
        for suffix in ("estado", "historial"):
            path = paths[f"/vehiculos/{{id_vehiculo}}/{suffix}"]
            self.assertEqual(set(path), {"get"})
            operation = path["get"]
            self.assertEqual(set(operation["responses"]), {"200", "404", "422", "500", "503"})
            parameter = operation["parameters"][0]["schema"]
            self.assertEqual(parameter["exclusiveMinimum"], 0)
            self.assertEqual(parameter["maximum"], INT_MAX)
        state_schema = paths["/vehiculos/{id_vehiculo}/estado"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        self.assertIn({"type": "null"}, state_schema["anyOf"])
        self.assertNotIn("id_estado", schema["components"]["schemas"]["StateResponse"]["properties"])
        self.assertNotIn("id_comando", schema["components"]["schemas"]["HistoryResponse"]["properties"])
        description = paths["/vehiculos/{id_vehiculo}/historial"]["get"]["description"]
        self.assertIn("WORKBENCH", description)
        self.assertIn("No filtra por origen", description)


if __name__ == "__main__":
    unittest.main()
