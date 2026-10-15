"""Contratos, SP y transacciones de comandos con resultados simulados, sin RDS."""

from contextlib import contextmanager
import unittest
from unittest.mock import Mock, call, patch

from pydantic import ValidationError

from app.database.procedures import ProcedureResult, StoredProcedureExecutor
from app.errors.database import DatabaseConflictError, DatabaseResultError
from app.errors.domain import ResourceNotFoundError
from app.models.commands import CommandCreate, CommandResponse, CommandUpdate
from app.models.common import INT_MAX, INT_MIN
from app.repositories.commands import CommandRepository
from app.services.commands import CommandService


def rows(*values: dict) -> ProcedureResult:
    return ProcedureResult((tuple(values),))


def vehicle_row(**overrides: object) -> dict:
    values = {
        "id_vehiculo": 3,
        "nombre": "Vehículo de prueba",
        "modelo": None,
        "descripcion": None,
        "microcontrolador": None,
        "fecha_registro": None,
        "activo": 1,
    }
    values.update(overrides)
    return values


def command_row(**overrides: object) -> dict:
    values = {
        "id_comando": 7,
        "id_vehiculo": 3,
        "nombre": "Reversa",
        "codigo": -5,
        "descripcion": None,
        "activo": 1,
    }
    values.update(overrides)
    return values


class CommandModelTests(unittest.TestCase):
    def test_create_only_requires_name_and_integer_code(self):
        data = CommandCreate(nombre="Reversa", codigo=0)
        self.assertIsNone(data.descripcion)
        self.assertEqual(data.model_dump(), {"nombre": "Reversa", "codigo": 0, "descripcion": None})

    def test_declared_varchar_lengths_and_signed_int_limits_are_accepted(self):
        for code in (INT_MIN, -1, 0, INT_MAX):
            with self.subTest(code=code):
                data = CommandCreate(nombre="n" * 60, codigo=code, descripcion="d" * 255)
                self.assertEqual(data.codigo, code)

    def test_names_must_be_present_nonempty_and_fit_varchar_60(self):
        for name in (None, "", " ", "\t\n", "n" * 61, 123):
            with self.subTest(name=name):
                with self.assertRaises(ValidationError):
                    CommandCreate(nombre=name, codigo=1)
        with self.assertRaises(ValidationError):
            CommandCreate(codigo=1)

    def test_name_is_validated_without_stripping_or_case_folding(self):
        self.assertEqual(CommandCreate(nombre="  Atrás  ", codigo=1).nombre, "  Atrás  ")

    def test_integer_code_does_not_accept_coercion_or_overflow(self):
        for code in (True, False, "1", 1.0, None, INT_MIN - 1, INT_MAX + 1):
            with self.subTest(code=code):
                with self.assertRaises(ValidationError):
                    CommandCreate(nombre="Mover", codigo=code)
        with self.assertRaises(ValidationError):
            CommandCreate(nombre="Mover")

    def test_description_is_nullable_and_limited_to_varchar_255(self):
        for description in (None, "", "d" * 255):
            with self.subTest(description=description):
                data = CommandCreate(nombre="Mover", codigo=1, descripcion=description)
                self.assertEqual(data.descripcion, description)
        with self.assertRaises(ValidationError):
            CommandCreate(nombre="Mover", codigo=1, descripcion="d" * 256)

    def test_create_rejects_owner_id_and_active_fields_outside_its_contract(self):
        for extra in ({"id_vehiculo": 3}, {"id_comando": 7}, {"activo": False}):
            with self.subTest(extra=extra):
                with self.assertRaises(ValidationError):
                    CommandCreate(nombre="Mover", codigo=1, **extra)

    def test_update_requires_all_non_nullable_editable_fields(self):
        valid = {"nombre": "Mover", "codigo": -1, "activo": False}
        for missing in valid:
            with self.subTest(missing=missing):
                with self.assertRaises(ValidationError):
                    CommandUpdate(**{key: value for key, value in valid.items() if key != missing})

    def test_update_active_is_a_strict_boolean(self):
        for active in (1, 0, "true", "false", None):
            with self.subTest(active=active):
                with self.assertRaises(ValidationError):
                    CommandUpdate(nombre="Mover", codigo=1, activo=active)
        self.assertIs(CommandUpdate(nombre="Mover", codigo=1, activo=False).activo, False)

    def test_update_clears_omitted_nullable_description(self):
        data = CommandUpdate(nombre="Mover", codigo=1, activo=True)
        self.assertIsNone(data.descripcion)
        self.assertIn("descripcion", data.model_dump())

    def test_response_converts_only_database_boolean_values(self):
        for active, expected in ((0, False), (1, True), (False, False), (True, True)):
            with self.subTest(active=active):
                self.assertIs(CommandResponse(**command_row(activo=active)).activo, expected)
        for active in (2, -1, "true", "0", None):
            with self.subTest(active=active):
                with self.assertRaises(ValidationError):
                    CommandResponse(**command_row(activo=active))

    def test_response_requires_positive_signed_int_identifiers(self):
        for field in ("id_vehiculo", "id_comando"):
            for value in (0, -1, INT_MAX + 1):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValidationError):
                        CommandResponse(**command_row(**{field: value}))


class CommandRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.executor = Mock(spec=StoredProcedureExecutor)
        self.repository = CommandRepository(self.executor)

    def test_create_passes_sql_parameter_order_and_reads_only_generated_id(self):
        data = CommandCreate(nombre="x'); DROP TABLE comandos; --", codigo=INT_MIN)
        self.executor.execute.return_value = rows({"id_comando": 7})
        self.assertEqual(self.repository.create(3, data), 7)
        self.executor.execute.assert_called_once_with(
            "sp_crear_comando", (3, data.nombre, INT_MIN, None)
        )

    def test_list_uses_existing_parent_procedure_and_preserves_its_order(self):
        self.executor.execute.return_value = rows(
            command_row(codigo=-5, activo=0), command_row(id_comando=8, codigo=0)
        )
        result = self.repository.list_for_vehicle(3)
        self.assertEqual([command.codigo for command in result], [-5, 0])
        self.assertIs(result[0].activo, False)
        self.executor.execute.assert_called_once_with("sp_obtener_comandos_vehiculo", (3,))

    def test_empty_result_is_an_empty_command_list(self):
        self.executor.execute.return_value = rows()
        self.assertEqual(self.repository.list_for_vehicle(3), [])

    def test_update_sends_all_editable_parameters_in_sql_order_including_null(self):
        data = CommandUpdate(nombre="Frenar", codigo=0, activo=False)
        self.assertIsNone(self.repository.update(7, data))
        self.executor.execute.assert_called_once_with(
            "sp_actualizar_comando", (7, "Frenar", 0, None, False)
        )

    def test_delete_uses_existing_procedure_with_only_command_id(self):
        self.assertIsNone(self.repository.delete(7))
        self.executor.execute.assert_called_once_with("sp_eliminar_comando", (7,))

    def test_invalid_generated_id_is_a_controlled_result_error(self):
        for result in (rows(), rows({}), rows({"id_comando": 0}), rows({"id_comando": True})):
            with self.subTest(result=result):
                self.executor.execute.return_value = result
                with self.assertRaises(DatabaseResultError):
                    self.repository.create(3, CommandCreate(nombre="Mover", codigo=1))

    def test_malformed_database_row_is_sanitized(self):
        self.executor.execute.return_value = rows(command_row(codigo="dato privado"))
        with self.assertRaises(DatabaseResultError) as raised:
            self.repository.list_for_vehicle(3)
        self.assertNotIn("dato privado", str(raised.exception))


class TransactionDatabase:
    """Contexto mínimo para observar el límite transaccional sin sockets ni .env."""

    def __init__(self):
        self.connection = object()
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


class CommandServiceTests(unittest.TestCase):
    def setUp(self):
        self.database = TransactionDatabase()
        self.executor = Mock(spec=StoredProcedureExecutor)
        self.executor_patch = patch(
            "app.services.commands.StoredProcedureExecutor", return_value=self.executor
        )
        self.executor_factory = self.executor_patch.start()
        self.addCleanup(self.executor_patch.stop)
        self.service = CommandService(self.database)
        self.create_data = CommandCreate(nombre="Reversa", codigo=-5)
        self.update_data = CommandUpdate(nombre="Reversa", codigo=-5, activo=False)

    def test_create_checks_parent_creates_and_rereads_with_one_connection(self):
        self.executor.execute.side_effect = [
            rows(vehicle_row()), rows({"id_comando": 7}), rows(command_row())
        ]
        response = self.service.create(3, self.create_data)
        self.assertEqual(response.id_comando, 7)
        self.assertEqual(response.id_vehiculo, 3)
        self.assertEqual(self.executor.execute.call_args_list, [
            call("sp_obtener_vehiculo", (3,)),
            call("sp_crear_comando", (3, "Reversa", -5, None)),
            call("sp_obtener_comandos_vehiculo", (3,)),
        ])
        self.executor_factory.assert_called_once_with(self.database.connection)
        self.assertEqual(self.database.modes, [False])
        self.assertEqual((self.database.commits, self.database.rollbacks, self.database.closed), (1, 0, 1))

    def test_all_operations_check_missing_parent_before_any_command_procedure(self):
        operations = (
            lambda: self.service.create(3, self.create_data),
            lambda: self.service.list_for_vehicle(3),
            lambda: self.service.update(3, 7, self.update_data),
            lambda: self.service.delete(3, 7),
        )
        for operation in operations:
            with self.subTest(operation=operation):
                self.executor.reset_mock()
                self.executor.execute.side_effect = [rows()]
                with self.assertRaises(ResourceNotFoundError):
                    operation()
                self.executor.execute.assert_called_once_with("sp_obtener_vehiculo", (3,))
        self.assertEqual(self.database.commits, 0)
        self.assertEqual(self.database.rollbacks, 4)

    def test_list_for_existing_parent_without_commands_returns_empty_collection(self):
        self.executor.execute.side_effect = [rows(vehicle_row()), rows()]
        self.assertEqual(self.service.list_for_vehicle(3), [])
        self.assertEqual(self.database.modes, [True])
        self.assertEqual((self.database.commits, self.database.rollbacks), (0, 1))

    def test_inactive_parent_and_command_are_not_hidden_or_blocked(self):
        self.executor.execute.side_effect = [rows(vehicle_row(activo=0)), rows(command_row(activo=0))]
        response = self.service.list_for_vehicle(3)
        self.assertEqual(len(response), 1)
        self.assertIs(response[0].activo, False)

    def test_inactive_parent_accepts_new_command_without_an_invented_business_rule(self):
        self.executor.execute.side_effect = [
            rows(vehicle_row(activo=0)), rows({"id_comando": 7}), rows(command_row())
        ]
        self.assertEqual(self.service.create(3, self.create_data).id_comando, 7)
        self.assertEqual(self.database.commits, 1)

    def test_update_checks_membership_then_replaces_and_rereads_before_commit(self):
        self.executor.execute.side_effect = [
            rows(vehicle_row()), rows(command_row(descripcion="Anterior")),
            rows(), rows(command_row(activo=0)),
        ]
        response = self.service.update(3, 7, self.update_data)
        self.assertIsNone(response.descripcion)
        self.assertIs(response.activo, False)
        self.assertEqual(self.executor.execute.call_args_list, [
            call("sp_obtener_vehiculo", (3,)),
            call("sp_obtener_comandos_vehiculo", (3,)),
            call("sp_actualizar_comando", (7, "Reversa", -5, None, False)),
            call("sp_obtener_comandos_vehiculo", (3,)),
        ])
        self.assertEqual(self.database.modes, [False])
        self.assertEqual(self.database.commits, 1)
        self.executor_factory.assert_called_once_with(self.database.connection)

    def test_identical_update_is_successful_without_affected_row_inference(self):
        same_row = command_row(activo=0)
        self.executor.execute.side_effect = [rows(vehicle_row()), rows(same_row), rows(), rows(same_row)]
        response = self.service.update(3, 7, self.update_data)
        self.assertEqual(response.model_dump(), CommandResponse(**same_row).model_dump())
        self.assertEqual(self.database.commits, 1)

    def test_update_of_missing_command_does_not_write(self):
        self.executor.execute.side_effect = [rows(vehicle_row()), rows(command_row(id_comando=8))]
        with self.assertRaises(ResourceNotFoundError):
            self.service.update(3, 7, self.update_data)
        self.assertEqual(self.executor.execute.call_count, 2)
        self.assertEqual((self.database.commits, self.database.rollbacks), (0, 1))

    def test_command_of_another_vehicle_is_404_for_update_and_delete(self):
        for operation in (
            lambda: self.service.update(3, 7, self.update_data),
            lambda: self.service.delete(3, 7),
        ):
            with self.subTest(operation=operation):
                self.executor.reset_mock()
                self.executor.execute.side_effect = [rows(vehicle_row()), rows(command_row(id_vehiculo=4))]
                with self.assertRaises(ResourceNotFoundError):
                    operation()
                self.assertEqual(self.executor.execute.call_count, 2)
        self.assertEqual(self.database.commits, 0)

    def test_delete_checks_parent_and_membership_before_existing_delete_procedure(self):
        self.executor.execute.side_effect = [rows(vehicle_row()), rows(command_row(activo=0)), rows()]
        self.assertIsNone(self.service.delete(3, 7))
        self.assertEqual(self.executor.execute.call_args_list, [
            call("sp_obtener_vehiculo", (3,)),
            call("sp_obtener_comandos_vehiculo", (3,)),
            call("sp_eliminar_comando", (7,)),
        ])
        self.assertEqual(self.database.modes, [False])
        self.assertEqual(self.database.commits, 1)

    def test_delete_of_missing_command_does_not_call_delete_procedure(self):
        self.executor.execute.side_effect = [rows(vehicle_row()), rows()]
        with self.assertRaises(ResourceNotFoundError):
            self.service.delete(3, 7)
        self.assertEqual(self.executor.execute.call_count, 2)
        self.assertEqual(self.database.commits, 0)

    def test_database_uniqueness_conflict_reverts_create(self):
        error = DatabaseConflictError()
        self.executor.execute.side_effect = [rows(vehicle_row()), error]
        with self.assertRaises(DatabaseConflictError) as raised:
            self.service.create(3, self.create_data)
        self.assertIs(raised.exception, error)
        self.assertEqual(self.executor.execute.call_count, 2)
        self.assertEqual((self.database.commits, self.database.rollbacks), (0, 1))

    def test_database_uniqueness_conflict_reverts_update(self):
        self.executor.execute.side_effect = [rows(vehicle_row()), rows(command_row()), DatabaseConflictError()]
        with self.assertRaises(DatabaseConflictError):
            self.service.update(3, 7, self.update_data)
        self.assertEqual((self.database.commits, self.database.rollbacks), (0, 1))

    def test_foreign_key_restriction_reverts_delete(self):
        self.executor.execute.side_effect = [rows(vehicle_row()), rows(command_row()), DatabaseConflictError()]
        with self.assertRaises(DatabaseConflictError):
            self.service.delete(3, 7)
        self.assertEqual((self.database.commits, self.database.rollbacks), (0, 1))

    def test_create_missing_readback_rolls_back_instead_of_returning_only_id(self):
        self.executor.execute.side_effect = [rows(vehicle_row()), rows({"id_comando": 7}), rows()]
        with self.assertRaises(DatabaseResultError):
            self.service.create(3, self.create_data)
        self.assertEqual((self.database.commits, self.database.rollbacks), (0, 1))

    def test_create_wrong_owner_or_id_in_readback_cannot_commit(self):
        for returned in (command_row(id_vehiculo=4), command_row(id_comando=8)):
            with self.subTest(returned=returned):
                self.executor.execute.side_effect = [rows(vehicle_row()), rows({"id_comando": 7}), rows(returned)]
                with self.assertRaises(DatabaseResultError):
                    self.service.create(3, self.create_data)
        self.assertEqual(self.database.commits, 0)

    def test_update_missing_or_malformed_readback_rolls_back(self):
        for result in (rows(), rows(command_row(activo="dato privado"))):
            with self.subTest(result=result):
                self.executor.execute.side_effect = [rows(vehicle_row()), rows(command_row()), rows(), result]
                with self.assertRaises(DatabaseResultError):
                    self.service.update(3, 7, self.update_data)
        self.assertEqual((self.database.commits, self.database.rollbacks), (0, 2))

    def test_wrong_parent_result_cannot_be_used_for_create(self):
        self.executor.execute.side_effect = [rows(vehicle_row(id_vehiculo=4))]
        with self.assertRaises(DatabaseResultError):
            self.service.create(3, self.create_data)
        self.assertEqual(self.executor.execute.call_count, 1)
        self.assertEqual(self.database.commits, 0)

    def test_list_rejects_result_containing_another_vehicle_data(self):
        self.executor.execute.side_effect = [rows(vehicle_row()), rows(command_row(id_vehiculo=4))]
        with self.assertRaises(DatabaseResultError):
            self.service.list_for_vehicle(3)
        self.assertEqual(self.database.commits, 0)


if __name__ == "__main__":
    unittest.main()
