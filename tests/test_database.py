"""Pruebas de la capa de datos con conexiones y resultados simulados."""

import os
from pathlib import Path
import ssl
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, Mock, patch

import pymysql
from fastapi import HTTPException

from app.config.settings import PROJECT_ROOT, Settings
from app.database.connection import MySQLDatabase
from app.database.procedures import ProcedureResult, StoredProcedureExecutor
from app.errors.database import (
    DatabaseConfigurationError,
    DatabaseTransactionError,
    DatabaseUnavailableError,
    StoredProcedureExecutionError,
)
from app.models.health import DatabaseHealthResponse
from app.routers.health import database_health
from app.services.database_health import DatabaseHealthService


def settings_for_test(**overrides: object) -> Settings:
    """Valores ficticios explícitos: no se consulta el archivo .env."""
    values = {
        "db_host": "mysql.example.invalid",
        "db_port": 3306,
        "db_name": "vehiculo_iot_test",
        "db_user": "usuario_test",
        "db_password": "password-ficticio-no-utilizable",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


class ProcedureCursor:
    """Cursor controlado que distingue resultados tabulares y sets de estado."""

    def __init__(self, result_sets):
        self.result_sets = result_sets
        self.index = 0
        self.callproc = Mock()
        self.fetchall = Mock(side_effect=self._fetchall)
        self.nextset = Mock(side_effect=self._nextset)
        self.close = Mock()

    @property
    def description(self):
        if self.result_sets[self.index] is None:
            return None
        return (("value",),)

    def _fetchall(self):
        rows = self.result_sets[self.index]
        if rows is None:
            raise AssertionError("No se deben leer filas de un set sin columnas")
        return rows

    def _nextset(self):
        if self.index + 1 >= len(self.result_sets):
            return None
        self.index += 1
        return True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class MySQLDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.connection = MagicMock()
        self.cert_directory = TemporaryDirectory()
        self.addCleanup(self.cert_directory.cleanup)
        self.ca_path = Path(self.cert_directory.name) / "test-ca.pem"
        self.ca_path.write_text("CA pública ficticia para pruebas con mocks", encoding="utf-8")
        self.tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.tls_patch = patch(
            "app.database.connection.ssl.create_default_context",
            return_value=self.tls_context,
        )
        self.create_tls_context = self.tls_patch.start()
        self.addCleanup(self.tls_patch.stop)
        self.connect_patch = patch(
            "app.database.connection.pymysql.connect",
            return_value=self.connection,
        )
        self.connect = self.connect_patch.start()
        self.addCleanup(self.connect_patch.stop)
        self.database = MySQLDatabase(settings_for_test(db_ssl_ca=self.ca_path))

    def test_incomplete_configuration_does_not_open_a_connection(self):
        for field in ("db_host", "db_user", "db_password"):
            with self.subTest(field=field):
                with self.assertRaises(DatabaseConfigurationError):
                    database = MySQLDatabase(settings_for_test(**{field: ""}))
                    with database.transaction():
                        self.fail("No debe iniciarse una transacción incompleta")
        self.connect.assert_not_called()

    def test_success_commits_once_and_closes(self):
        with self.database.transaction() as connection:
            self.assertIs(connection, self.connection)
            connection.begin.assert_called_once_with()
            connection.commit.assert_not_called()
        self.connection.commit.assert_called_once_with()
        self.connection.rollback.assert_not_called()
        self.connection.close.assert_called_once_with()

    def test_driver_configuration_disables_autocommit_and_uses_dict_cursor(self):
        with self.database.transaction():
            pass
        arguments = self.connect.call_args.kwargs
        self.assertEqual(arguments["host"], "mysql.example.invalid")
        self.assertEqual(arguments["port"], 3306)
        self.assertEqual(arguments["database"], "vehiculo_iot_test")
        self.assertEqual(arguments["user"], "usuario_test")
        self.assertEqual(arguments["password"], "password-ficticio-no-utilizable")
        self.assertIs(arguments["autocommit"], False)
        self.assertIs(arguments["cursorclass"], pymysql.cursors.DictCursor)

    def test_tls_requires_trusted_certificate_and_server_identity(self):
        with self.database.transaction():
            pass
        self.create_tls_context.assert_called_once_with(cafile=str(self.ca_path))
        self.assertEqual(self.tls_context.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertEqual(self.tls_context.verify_mode, ssl.CERT_REQUIRED)
        self.assertIs(self.tls_context.check_hostname, True)
        arguments = self.connect.call_args.kwargs
        self.assertIs(arguments["ssl"], self.tls_context)

    def test_real_driver_preserves_required_tls_context_without_network(self):
        # Ejercitar el constructor real detecta opciones que PyMySQL podría
        # combinar o sustituir antes de establecer una conexión de red.
        self.connect.side_effect = lambda **arguments: pymysql.connections.Connection(
            defer_connect=True, **arguments
        )
        with patch(
            "pymysql.connections.socket.create_connection",
            side_effect=AssertionError("Esta prueba no debe acceder a la red"),
        ) as create_socket:
            connection = self.database._connect()
        self.addCleanup(connection.close)
        create_socket.assert_not_called()
        self.create_tls_context.assert_called_once_with(cafile=str(self.ca_path))
        self.assertIs(connection.ctx, self.tls_context)
        self.assertEqual(connection.ctx.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertEqual(connection.ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertIs(connection.ctx.check_hostname, True)
        self.assertIs(connection._ssl_required, True)

    def test_relative_ca_is_resolved_against_project_root(self):
        relative_ca = Path("tests") / "test-ca.pem"
        database = MySQLDatabase(settings_for_test(db_ssl_ca=relative_ca))
        with database.transaction():
            pass
        self.create_tls_context.assert_called_once_with(
            cafile=str(PROJECT_ROOT / relative_ca)
        )

    def test_ca_path_can_be_configured_from_environment(self):
        with patch.dict(os.environ, {"DB_SSL_CA": "tests/environment-ca.pem"}):
            settings = settings_for_test()
        self.assertEqual(settings.db_ssl_ca, Path("tests/environment-ca.pem"))
        with MySQLDatabase(settings).transaction():
            pass
        self.create_tls_context.assert_called_once_with(
            cafile=str(PROJECT_ROOT / "tests" / "environment-ca.pem")
        )

    def test_missing_ca_is_a_configuration_error_before_connecting(self):
        self.tls_patch.stop()
        missing_ca = Path(self.cert_directory.name) / "does-not-exist.pem"
        database = MySQLDatabase(settings_for_test(db_ssl_ca=missing_ca))
        with self.assertRaises(DatabaseConfigurationError) as raised:
            with database.transaction():
                self.fail("No debe conectarse sin un certificado CA disponible")
        self.assertNotIn(str(missing_ca), str(raised.exception))
        self.connect.assert_not_called()

    def test_invalid_ca_is_a_configuration_error_before_connecting(self):
        self.tls_patch.stop()
        with self.assertRaises(DatabaseConfigurationError) as raised:
            with self.database.transaction():
                self.fail("No debe conectarse con un certificado CA inválido")
        self.assertNotIn(str(self.ca_path), str(raised.exception))
        self.connect.assert_not_called()

    def test_each_transaction_opens_its_own_connection(self):
        second_connection = MagicMock()
        self.connect.side_effect = [self.connection, second_connection]
        with self.database.transaction() as first:
            self.assertIs(first, self.connection)
        with self.database.transaction() as second:
            self.assertIs(second, second_connection)
        self.assertEqual(self.connect.call_count, 2)
        self.connection.close.assert_called_once_with()
        second_connection.close.assert_called_once_with()

    def test_application_error_rolls_back_and_preserves_the_error(self):
        original_error = ValueError("validación ficticia")
        with self.assertRaises(ValueError) as raised:
            with self.database.transaction():
                raise original_error
        self.assertIs(raised.exception, original_error)
        self.connection.rollback.assert_called_once_with()
        self.connection.commit.assert_not_called()
        self.connection.close.assert_called_once_with()

    def test_base_exception_also_rolls_back_and_closes(self):
        with self.assertRaises(KeyboardInterrupt):
            with self.database.transaction():
                raise KeyboardInterrupt()
        self.connection.rollback.assert_called_once_with()
        self.connection.commit.assert_not_called()
        self.connection.close.assert_called_once_with()

    def test_read_only_transaction_uses_server_enforcement_and_never_commits(self):
        cursor = self.connection.cursor.return_value
        cursor.__enter__.return_value = cursor
        with self.database.transaction(read_only=True) as connection:
            self.assertIs(connection, self.connection)
            cursor.execute.assert_called_once_with("START TRANSACTION READ ONLY")
        self.connection.commit.assert_not_called()
        self.connection.rollback.assert_called_once_with()
        self.connection.close.assert_called_once_with()

    def test_read_only_failure_rolls_back_and_closes(self):
        with self.assertRaises(ValueError):
            with self.database.transaction(read_only=True):
                raise ValueError("fallo ficticio")
        self.connection.commit.assert_not_called()
        self.connection.rollback.assert_called_once_with()
        self.connection.close.assert_called_once_with()

    def test_connect_error_is_sanitized(self):
        driver_message = "mysql.example.invalid usuario_test password-ficticio-no-utilizable"
        self.connect.side_effect = pymysql.err.OperationalError(2003, driver_message)
        with self.assertRaises(DatabaseUnavailableError) as raised:
            with self.database.transaction():
                self.fail("No debe devolverse una conexión que no pudo abrirse")
        self.assertNotIn(driver_message, str(raised.exception))
        self.assertNotIn("password-ficticio-no-utilizable", str(raised.exception))

    def test_begin_error_is_sanitized_and_connection_closes(self):
        self.connection.begin.side_effect = pymysql.err.OperationalError(
            2013, "detalle privado del servidor"
        )
        with self.assertRaises(DatabaseTransactionError) as raised:
            with self.database.transaction():
                self.fail("No debe entregarse una transacción que no inició")
        self.assertNotIn("detalle privado", str(raised.exception))
        self.connection.commit.assert_not_called()
        self.connection.close.assert_called_once_with()

    def test_commit_failure_rolls_back_and_closes(self):
        self.connection.commit.side_effect = pymysql.err.OperationalError(
            2013, "detalle privado del commit"
        )
        with self.assertRaises(DatabaseTransactionError) as raised:
            with self.database.transaction():
                pass
        self.assertNotIn("detalle privado", str(raised.exception))
        self.connection.rollback.assert_called_once_with()
        self.connection.close.assert_called_once_with()

    def test_read_only_rollback_error_is_sanitized_and_connection_closes(self):
        self.connection.rollback.side_effect = pymysql.err.OperationalError(
            2013, "detalle privado del rollback"
        )
        with self.assertRaises(DatabaseTransactionError) as raised:
            with self.database.transaction(read_only=True):
                pass
        self.assertNotIn("detalle privado", str(raised.exception))
        self.connection.commit.assert_not_called()
        self.connection.close.assert_called_once_with()

    def test_second_procedure_failure_rolls_back_both_calls_on_same_connection(self):
        first_cursor = ProcedureCursor([[{"id": 1}], None])
        second_cursor = ProcedureCursor([None])
        second_cursor.callproc.side_effect = pymysql.err.OperationalError(
            1644, "fallo simulado del segundo procedimiento"
        )
        self.connection.cursor.side_effect = [first_cursor, second_cursor]
        with self.assertRaises(StoredProcedureExecutionError):
            with self.database.transaction() as connection:
                executor = StoredProcedureExecutor(connection)
                executor.execute("sp_primero", [1])
                executor.execute("sp_segundo", [2])
        self.connect.assert_called_once()
        first_cursor.callproc.assert_called_once_with("sp_primero", (1,))
        second_cursor.callproc.assert_called_once_with("sp_segundo", (2,))
        self.connection.commit.assert_not_called()
        self.connection.rollback.assert_called_once_with()
        self.connection.close.assert_called_once_with()
        first_cursor.close.assert_called_once_with()
        second_cursor.close.assert_called_once_with()


class StoredProcedureExecutorTests(unittest.TestCase):
    def executor_with_results(self, result_sets):
        connection = MagicMock()
        cursor = ProcedureCursor(result_sets)
        connection.cursor.return_value = cursor
        return StoredProcedureExecutor(connection), connection, cursor

    def test_parameters_are_passed_separately_from_the_procedure_name(self):
        executor, connection, cursor = self.executor_with_results([[{"id": 7}], None])
        parameters = ["x'); DROP TABLE vehiculos; --", 7, None]
        result = executor.execute("sp_consultar", parameters)
        cursor.callproc.assert_called_once_with("sp_consultar", tuple(parameters))
        self.assertEqual(result.result_sets, (({"id": 7},),))
        connection.commit.assert_not_called()
        connection.rollback.assert_not_called()
        connection.close.assert_not_called()
        cursor.close.assert_called_once_with()

    def test_all_tabular_sets_are_retained_and_status_sets_are_drained(self):
        executor, _, cursor = self.executor_with_results(
            [None, [], [{"id": 1}, {"id": 2}], None, [{"total": 2}], None]
        )
        result = executor.execute("sp_varios_resultados")
        self.assertEqual(result.result_sets, ((), ({"id": 1}, {"id": 2}), ({"total": 2},)))
        self.assertEqual(cursor.fetchall.call_count, 3)
        self.assertEqual(cursor.nextset.call_count, 6)
        self.assertEqual(result.fetch_all(), [])
        self.assertIsNone(result.fetch_one())

    def test_no_tabular_sets_produce_an_empty_result(self):
        executor, _, cursor = self.executor_with_results([None])
        result = executor.execute("sp_sin_resultados")
        self.assertEqual(result.result_sets, ())
        self.assertIsNone(result.fetch_one())
        self.assertEqual(result.fetch_all(), [])
        cursor.fetchall.assert_not_called()
        cursor.nextset.assert_called_once_with()

    def test_helpers_use_only_the_first_result_set(self):
        result = ProcedureResult((({"id": 1}, {"id": 2}), ({"id": 3},)))
        self.assertEqual(result.fetch_one(), {"id": 1})
        self.assertEqual(result.fetch_all(), [{"id": 1}, {"id": 2}])

    def test_invalid_names_are_rejected_before_creating_a_cursor(self):
        executor, connection, _ = self.executor_with_results([None])
        for name in ("", "sp_", "SP_valido", "sp_ñ", "sp_x; DROP TABLE x", "sp_x\n"):
            with self.subTest(procedure=name):
                with self.assertRaises(ValueError):
                    executor.execute(name)
        connection.cursor.assert_not_called()

    def test_callproc_error_is_sanitized_and_cursor_closes(self):
        executor, connection, cursor = self.executor_with_results([None])
        cursor.callproc.side_effect = pymysql.err.OperationalError(
            1644, "password-ficticio-no-utilizable consulta privada"
        )
        with self.assertRaises(StoredProcedureExecutionError) as raised:
            executor.execute("sp_consultar", ["parametro-privado"])
        self.assertNotIn("password-ficticio", str(raised.exception))
        self.assertNotIn("consulta privada", str(raised.exception))
        self.assertNotIn("parametro-privado", str(raised.exception))
        cursor.close.assert_called_once_with()
        connection.commit.assert_not_called()
        connection.rollback.assert_not_called()
        connection.close.assert_not_called()

    def test_error_in_later_result_set_is_not_silently_ignored(self):
        executor, _, cursor = self.executor_with_results([[{"id": 1}], None])
        cursor.nextset.side_effect = pymysql.err.OperationalError(
            2013, "detalle privado del segundo resultado"
        )
        with self.assertRaises(StoredProcedureExecutionError) as raised:
            executor.execute("sp_consultar")
        self.assertNotIn("detalle privado", str(raised.exception))
        cursor.close.assert_called_once_with()


class DatabaseHealthServiceTests(unittest.TestCase):
    @patch("app.services.database_health.StoredProcedureExecutor")
    def test_check_uses_read_only_procedure_and_discards_rows(self, executor_class):
        database = MagicMock()
        connection = database.transaction.return_value.__enter__.return_value
        executor_class.return_value.execute.return_value = ProcedureResult(
            (({"dato": "contenido que no debe devolverse"},),)
        )
        result = DatabaseHealthService(database).check()
        self.assertIsNone(result)
        database.transaction.assert_called_once_with(read_only=True)
        executor_class.assert_called_once_with(connection)
        executor_class.return_value.execute.assert_called_once_with("sp_obtener_vehiculos")

    @patch("app.services.database_health.StoredProcedureExecutor")
    def test_check_propagates_database_error(self, executor_class):
        database = MagicMock()
        error = StoredProcedureExecutionError()
        executor_class.return_value.execute.side_effect = error
        with self.assertRaises(StoredProcedureExecutionError) as raised:
            DatabaseHealthService(database).check()
        self.assertIs(raised.exception, error)
        database.transaction.assert_called_once_with(read_only=True)


class DatabaseHealthRouteTests(unittest.TestCase):
    def test_success_returns_only_availability_status(self):
        service = Mock(spec=DatabaseHealthService)
        service.check.return_value = None
        response = database_health(service=service)
        self.assertIsInstance(response, DatabaseHealthResponse)
        self.assertEqual(response.model_dump(), {"status": "ok", "database": "available"})
        service.check.assert_called_once_with()

    def test_database_errors_become_503_with_the_same_public_detail(self):
        public_detail = (
            "No fue posible completar la comprobación de lectura de la base de datos."
        )
        for error_type in (
            DatabaseConfigurationError,
            DatabaseUnavailableError,
            DatabaseTransactionError,
            StoredProcedureExecutionError,
        ):
            with self.subTest(error_type=error_type.__name__):
                service = Mock(spec=DatabaseHealthService)
                error = error_type()
                error.args = ("detalle-interno-privado password-ficticio",)
                service.check.side_effect = error
                with self.assertRaises(HTTPException) as raised:
                    database_health(service=service)
                self.assertEqual(raised.exception.status_code, 503)
                self.assertEqual(raised.exception.detail, public_detail)
                self.assertNotIn("detalle-interno-privado", str(raised.exception))
                self.assertNotIn("password-ficticio", str(raised.exception))
                self.assertTrue(raised.exception.__suppress_context__)
                service.check.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
