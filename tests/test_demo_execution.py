"""Ejecución DEMO, HTTP y eventos sobre servicios ficticios sin .env ni RDS."""

import asyncio
from datetime import datetime
import json
from threading import Event, get_ident
import unittest
from unittest.mock import patch

from fastapi import FastAPI

from app.errors.database import DatabaseUnavailableError, StoredProcedureExecutionError
from app.errors.domain import ResourceConflictError, ResourceNotFoundError
from app.errors.handlers import register_exception_handlers
from app.execution.dependencies import get_demo_execution_manager
from app.execution.manager import DemoExecutionManager
from app.models.demo_execution import DemoExecutionPlan
from app.models.demos import DemoMovementResponse, DemoResponse
from app.models.state import StateResponse
from app.routers.demo_execution import get_demo_execution_service, router
from app.services.demo_execution import DemoExecutionCancelled
from app.websocket.manager import WebSocketManager


DB_TIME = datetime(2026, 10, 14, 12, 30, 45)


def make_plan(vehicle_id=3, demo_id=5):
    return DemoExecutionPlan(
        demo=DemoResponse(
            id_demo=demo_id, id_vehiculo=vehicle_id, nombre="DEMO ficticia",
            descripcion=None, activo=True,
        ),
        movimientos=tuple(
            DemoMovementResponse(
                id_demo_movimiento=identifier, orden=order, id_comando=command_id,
                comando=name, codigo=code, duracion_ms=duration, pausa_ms=pause,
            )
            for identifier, order, command_id, name, code, duration, pause in (
                (71, 2, 7, "REVERSA", -5, 1250, 50),
                (84, 5, 4, "GIRO", 11, 0, 7),
                (99, 9, 9, "DETENER", 0, 9, 0),
            )
        ),
    )


class ControlledSleep:
    """Esperas observables; ninguna duración de la DEMO transcurre realmente."""

    def __init__(self):
        self.calls = []
        self.entered = asyncio.Queue()
        self.pending = set()
        self.automatic = False

    async def __call__(self, seconds):
        self.calls.append(seconds)
        if self.automatic:
            await asyncio.sleep(0)
            return
        gate = asyncio.Event()
        self.pending.add(gate)
        self.entered.put_nowait((seconds, gate))
        try:
            await gate.wait()
        finally:
            self.pending.discard(gate)

    async def next(self):
        return await asyncio.wait_for(self.entered.get(), timeout=2)


class DemoServiceFake:
    """DB síncrona controlada: prepare y cada paso ocurren en el worker real."""

    def __init__(self, plan):
        self.plan = plan
        self.loop = asyncio.get_running_loop()
        self.prepare_started = asyncio.Event()
        self.step_started = asyncio.Queue()
        self.prepare_gate = Event()
        self.prepare_gate.set()
        self.step_gate = Event()
        self.step_gate.set()
        self.prepare_error = None
        self.fail_step = None
        self.prepare_calls = []
        self.step_calls = []
        self.committed = []
        self.closed = []
        self.threads = []
        self.should_cancel = None

    def prepare(self, vehicle_id, demo_id):
        self.prepare_calls.append((vehicle_id, demo_id))
        self.threads.append(get_ident())
        self.loop.call_soon_threadsafe(self.prepare_started.set)
        if not self.prepare_gate.wait(timeout=2):
            raise AssertionError("La prueba no liberó su validación ficticia.")
        if self.prepare_error is not None:
            raise self.prepare_error
        if (vehicle_id, demo_id) != (self.plan.demo.id_vehiculo, self.plan.demo.id_demo):
            raise ResourceNotFoundError()
        return self.plan

    def apply_step(self, plan, movement, *, should_cancel=None):
        identifier = movement.id_demo_movimiento
        self.step_calls.append(identifier)
        self.threads.append(get_ident())
        self.should_cancel = should_cancel
        self.loop.call_soon_threadsafe(self.step_started.put_nowait, identifier)
        try:
            if not self.step_gate.wait(timeout=2):
                raise AssertionError("La prueba no liberó su transacción ficticia.")
            if should_cancel is not None and should_cancel():
                raise DemoExecutionCancelled()
            if self.fail_step == identifier:
                raise StoredProcedureExecutionError() from RuntimeError("DETALLE_INTERNO_FICTICIO")
            self.committed.append(identifier)
            return StateResponse(
                id_vehiculo=plan.demo.id_vehiculo, vehiculo="Vehículo ficticio",
                id_comando=movement.id_comando, comando=movement.comando,
                codigo=movement.codigo, conectado=False, fecha_actualizacion=DB_TIME,
            )
        finally:
            self.closed.append(identifier)


class DemoSocket:
    def __init__(self, service):
        self.service = service
        self.messages = []
        self.received = asyncio.Queue()
        self.observations = []
        self.fail_movements = False
        self.close_codes = []

    async def accept(self):
        pass

    async def send_json(self, event):
        if event["tipo_evento"] == "demo_movimiento":
            if self.fail_movements:
                raise OSError("Fallo ficticio de cliente")
            identifier = event["id_demo_movimiento"]
            self.observations.append((
                identifier, identifier in self.service.committed,
                identifier in self.service.closed, get_ident(),
            ))
        value = json.loads(json.dumps(event))
        self.messages.append(value)
        self.received.put_nowait(value)

    async def close(self, code=1000):
        self.close_codes.append(code)

    async def wait_event(self, kind):
        async def find():
            while True:
                event = await self.received.get()
                if event["tipo_evento"] == kind:
                    return event
        return await asyncio.wait_for(find(), timeout=2)


class DemoExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.websocket = WebSocketManager(send_timeout=0.03, close_timeout=0.03)
        self.sleep = ControlledSleep()
        self.manager = DemoExecutionManager(self.websocket, sleep=self.sleep)
        self.services = []
        self.service = self.new_service()
        self.application = FastAPI()
        self.application.include_router(router)
        register_exception_handlers(self.application)
        self.application.dependency_overrides[get_demo_execution_service] = lambda: self.service
        self.application.dependency_overrides[get_demo_execution_manager] = lambda: self.manager
        for target in ("app.config.settings.Settings", "app.database.connection.pymysql.connect"):
            guard = patch(target, side_effect=AssertionError("Prueba sin .env ni red."))
            mock = guard.start()
            self.addCleanup(guard.stop)
            self.addCleanup(mock.assert_not_called)
        self.addAsyncCleanup(self.cleanup)

    def new_service(self, vehicle_id=3, demo_id=5):
        service = DemoServiceFake(make_plan(vehicle_id, demo_id))
        self.services.append(service)
        return service

    async def cleanup(self):
        for service in self.services:
            service.prepare_gate.set()
            service.step_gate.set()
        await self.manager.close_all()
        await self.websocket.close_all()

    async def subscribe(self, vehicle_id=3, service=None):
        socket = DemoSocket(service or self.service)
        async def initial():
            return {"tipo_evento": "estado_actual", "id_vehiculo": vehicle_id}
        await self.websocket.connect(vehicle_id, socket, initial)
        socket.messages.clear()
        return socket

    async def wait_for(self, predicate):
        async def poll():
            while not predicate():
                await asyncio.sleep(0.001)
        await asyncio.wait_for(poll(), timeout=2)

    async def request(self, action, *, vehicle_id=3, demo_id=5, expected=202):
        messages = []
        received = False
        async def receive():
            nonlocal received
            if received:
                return {"type": "http.disconnect"}
            received = True
            return {"type": "http.request", "body": b"", "more_body": False}
        async def send(message):
            messages.append(message)
        path = f"/vehiculos/{vehicle_id}/demos/{demo_id}/{action}"
        scope = {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1", "method": "POST", "scheme": "http", "path": path,
            "raw_path": path.encode("ascii"), "query_string": b"", "root_path": "",
            "headers": [], "client": ("test.invalid", 50000), "server": ("test.invalid", 80),
        }
        await self.application(scope, receive, send)
        response = next(item for item in messages if item["type"] == "http.response.start")
        body = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
        value = json.loads(body)
        self.assertEqual(response["status"], expected, value)
        return value

    async def test_202_dynamic_steps_postcommit_events_and_all_duration_pause_waits(self):
        socket = await self.subscribe()
        other = await self.subscribe(4)
        response = await asyncio.wait_for(self.request("ejecutar"), timeout=2)
        self.assertEqual(response, {"id_vehiculo": 3, "id_demo": 5, "estado": "iniciada"})
        self.assertEqual(self.manager.active_count, 1)
        for index, seconds in enumerate((1.25, 0.05, 0, 0.007, 0.009, 0)):
            actual, gate = await self.sleep.next()
            self.assertEqual(actual, seconds)
            self.assertNotIn("demo_fin", [event["tipo_evento"] for event in socket.messages])
            self.assertEqual(len(self.service.committed), index // 2 + 1)
            gate.set()
        await socket.wait_event("demo_fin")
        await self.wait_for(lambda: self.manager.active_count == 0)
        self.assertEqual(self.sleep.calls, [1.25, 0.05, 0, 0.007, 0.009, 0])
        self.assertEqual([event["tipo_evento"] for event in socket.messages], [
            "demo_inicio", "demo_movimiento", "demo_movimiento", "demo_movimiento", "demo_fin",
        ])
        movements = [event for event in socket.messages if event["tipo_evento"] == "demo_movimiento"]
        self.assertEqual([event["orden"] for event in movements], [2, 5, 9])
        self.assertEqual([event["id_demo_movimiento"] for event in movements], [71, 84, 99])
        for event, step in zip(movements, self.service.plan.movimientos):
            self.assertEqual((event["id_comando"], event["comando"], event["codigo"]),
                             (step.id_comando, step.comando, step.codigo))
            self.assertEqual((event["duracion_ms"], event["pausa_ms"]), (step.duracion_ms, step.pausa_ms))
            self.assertEqual(event["timestamp"], DB_TIME.isoformat())
            self.assertIs(event["conectado"], False)
        for event in socket.messages:
            self.assertTrue({"tipo_evento", "id_vehiculo", "id_demo", "nombre_demo", "comando", "codigo", "timestamp"} <= event.keys())
            self.assertEqual((event["id_vehiculo"], event["id_demo"]), (3, 5))
        self.assertTrue(all(committed and closed and thread == get_ident()
                            for _, committed, closed, thread in socket.observations))
        self.assertTrue(all(thread != get_ident() for thread in self.service.threads))
        self.assertEqual(other.messages, [])
        self.assertEqual(self.sleep.pending, set())

    async def test_reservation_blocks_same_vehicle_during_prepare_but_other_vehicle_runs(self):
        self.service.prepare_gate.clear()
        starting = asyncio.create_task(self.manager.start(3, 5, self.service))
        try:
            await asyncio.wait_for(self.service.prepare_started.wait(), timeout=2)
            with self.assertRaises(ResourceConflictError):
                await self.manager.start(3, 5, self.service)
            second = self.new_service(4, 6)
            response = await asyncio.wait_for(self.manager.start(4, 6, second), timeout=2)
            self.assertEqual(response.estado, "iniciada")
            self.assertEqual(self.manager.active_count, 2)
            await self.manager.cancel(4, 6)
            self.assertEqual(self.manager.active_count, 1)
        finally:
            self.service.prepare_gate.set()
            await starting
        await self.manager.cancel(3, 5)
        self.assertEqual(self.manager.active_count, 0)

    async def test_startup_errors_release_reservation_without_events_and_http_ids_validate(self):
        socket = await self.subscribe()
        for error, expected in (
            (ResourceNotFoundError(), 404), (ResourceConflictError(), 409),
            (DatabaseUnavailableError(), 503),
        ):
            with self.subTest(error=type(error).__name__):
                self.service.prepare_error = error
                response = await self.request("ejecutar", expected=expected)
                self.assertEqual(response, {"detail": str(error)})
                self.assertEqual(self.manager.active_count, 0)
                self.assertEqual(socket.messages, [])
        self.service.prepare_error = None
        calls = len(self.service.prepare_calls)
        for vehicle_id, demo_id in ((0, 5), (3, 0), (2**31, 5), (3, "1.5")):
            await self.request("ejecutar", vehicle_id=vehicle_id, demo_id=demo_id, expected=422)
        self.assertEqual(len(self.service.prepare_calls), calls)
        await self.request("ejecutar")
        await self.request("cancelar", expected=200)
        self.assertEqual(self.manager.active_count, 0)

    async def test_cancel_interrupts_wait_emits_once_and_allows_immediate_restart(self):
        socket = await self.subscribe()
        await self.request("ejecutar")
        await self.sleep.next()
        await self.request("cancelar", demo_id=99, expected=404)
        self.assertEqual(self.manager.active_count, 1)
        response = await asyncio.wait_for(self.request("cancelar", expected=200), timeout=2)
        self.assertEqual(response["estado"], "cancelada")
        self.assertEqual(self.manager.active_count, 0)
        self.assertEqual(self.sleep.pending, set())
        self.assertEqual(self.service.committed, [71])
        self.assertEqual([event["tipo_evento"] for event in socket.messages], [
            "demo_inicio", "demo_movimiento", "demo_cancelada",
        ])
        await self.request("cancelar", expected=404)
        previous = len(socket.messages)
        await self.request("ejecutar")
        await self.sleep.next()
        await self.request("cancelar", expected=200)
        self.assertEqual([event["tipo_evento"] for event in socket.messages[previous:]], [
            "demo_inicio", "demo_movimiento", "demo_cancelada",
        ])
        self.assertEqual(self.manager.active_count, 0)
        self.assertEqual(self.sleep.pending, set())

    async def test_cancel_inflight_database_waits_for_close_without_step_or_success_event(self):
        socket = await self.subscribe()
        self.service.step_gate.clear()
        await self.request("ejecutar")
        await asyncio.wait_for(self.service.step_started.get(), timeout=2)
        cancelling = asyncio.create_task(self.request("cancelar", expected=200))
        try:
            await self.wait_for(lambda: self.service.should_cancel is not None and self.service.should_cancel())
            self.assertFalse(cancelling.done())
            self.assertEqual(self.manager.active_count, 1)
            self.assertEqual(self.service.closed, [])
        finally:
            self.service.step_gate.set()
        response = await asyncio.wait_for(cancelling, timeout=2)
        self.assertEqual(response["estado"], "cancelada")
        self.assertEqual(self.service.closed, [71])
        self.assertEqual(self.service.committed, [])
        self.assertEqual(self.manager.active_count, 0)
        self.assertEqual([event["tipo_evento"] for event in socket.messages], ["demo_inicio", "demo_cancelada"])
        self.assertEqual(self.sleep.calls, [])

    async def test_cancelled_preparation_that_later_fails_still_emits_one_cancellation(self):
        socket = await self.subscribe()
        self.service.prepare_gate.clear()
        self.service.prepare_error = DatabaseUnavailableError()
        starting = asyncio.create_task(self.request("ejecutar", expected=503))
        await asyncio.wait_for(self.service.prepare_started.wait(), timeout=2)
        cancelling = asyncio.create_task(self.manager.cancel(3, 5))
        try:
            await asyncio.sleep(0)
            self.assertFalse(cancelling.done())
            self.assertEqual(self.manager.active_count, 1)
        finally:
            self.service.prepare_gate.set()
        await asyncio.wait_for(starting, timeout=2)
        response = await asyncio.wait_for(cancelling, timeout=2)
        self.assertEqual(response.estado, "cancelada")
        self.assertEqual(self.manager.active_count, 0)
        self.assertEqual(self.service.step_calls, [])
        self.assertEqual([event["tipo_evento"] for event in socket.messages], ["demo_cancelada"])

    async def test_cancel_suppresses_movement_already_queued_before_transport(self):
        socket = await self.subscribe()
        entered, release = asyncio.Event(), asyncio.Event()
        observed_stop = []
        original_broadcast = self.websocket.broadcast

        async def delayed_broadcast(vehicle_id, event, **kwargs):
            if event["tipo_evento"] == "demo_movimiento":
                entered.set()
                await release.wait()
                observed_stop.append(self.service.should_cancel())
            await original_broadcast(vehicle_id, event, **kwargs)

        with patch.object(self.websocket, "broadcast", new=delayed_broadcast):
            await self.request("ejecutar")
            await asyncio.wait_for(entered.wait(), timeout=2)
            cancelling = asyncio.create_task(self.manager.cancel(3, 5))
            # Cancelar y liberar en el mismo turno reproduce la carrera entre
            # la espera stop y las tareas de envío listas para ejecutarse.
            release.set()
            response = await asyncio.wait_for(cancelling, timeout=2)
        self.assertEqual(response.estado, "cancelada")
        self.assertEqual(observed_stop, [True])
        self.assertEqual(self.service.committed, [71])
        self.assertEqual([event["tipo_evento"] for event in socket.messages], ["demo_inicio", "demo_cancelada"])
        self.assertEqual(self.manager.active_count, 0)

    async def test_step_error_emits_one_safe_error_without_finish_and_releases_vehicle(self):
        self.sleep.automatic = True
        self.service.fail_step = 84
        socket = await self.subscribe()
        await self.request("ejecutar")
        event = await socket.wait_event("demo_error")
        await self.wait_for(lambda: self.manager.active_count == 0)
        self.assertNotIn("DETALLE_INTERNO_FICTICIO", json.dumps(event))
        self.assertEqual([event["tipo_evento"] for event in socket.messages], [
            "demo_inicio", "demo_movimiento", "demo_error",
        ])
        self.assertEqual(self.service.committed, [71])
        self.assertEqual(self.service.closed, [71, 84])
        self.assertEqual(self.sleep.calls, [1.25, 0.05])

    async def test_cancellation_during_final_broadcast_cannot_emit_a_second_terminal(self):
        self.websocket = WebSocketManager(send_timeout=1, close_timeout=0.03)
        self.manager = DemoExecutionManager(self.websocket, sleep=self.sleep)
        self.sleep.automatic = True
        healthy = await self.subscribe()
        final_started, release_final = asyncio.Event(), asyncio.Event()

        class SlowFinalSocket(DemoSocket):
            async def send_json(self, event):
                if event["tipo_evento"] == "demo_fin":
                    final_started.set()
                    await release_final.wait()
                await super().send_json(event)

        slow = SlowFinalSocket(self.service)
        async def initial():
            return {"tipo_evento": "estado_actual", "id_vehiculo": 3}
        await self.websocket.connect(3, slow, initial)
        slow.messages.clear()
        try:
            await self.request("ejecutar")
            await asyncio.wait_for(final_started.wait(), timeout=2)
            await healthy.wait_event("demo_fin")
            self.assertEqual(self.manager.active_count, 1)
            await self.request("cancelar", expected=404)
            self.assertNotIn("demo_cancelada", [event["tipo_evento"] for event in healthy.messages])
        finally:
            release_final.set()
        await slow.wait_event("demo_fin")
        await self.wait_for(lambda: self.manager.active_count == 0)
        for socket in (healthy, slow):
            terminals = [event["tipo_evento"] for event in socket.messages
                         if event["tipo_evento"] in {"demo_fin", "demo_cancelada", "demo_error"}]
            self.assertEqual(terminals, ["demo_fin"])

    async def test_no_clients_and_failed_client_do_not_abort_execution_or_cross_vehicle(self):
        self.sleep.automatic = True
        await self.request("ejecutar")
        await self.wait_for(lambda: self.manager.active_count == 0)
        self.assertEqual(self.service.committed, [71, 84, 99])
        self.assertEqual(self.websocket.vehicle_count, 0)
        self.service.committed.clear()
        self.service.closed.clear()
        healthy = await self.subscribe()
        broken = await self.subscribe()
        other = await self.subscribe(4)
        broken.fail_movements = True
        await self.request("ejecutar")
        await healthy.wait_event("demo_fin")
        await self.wait_for(lambda: self.manager.active_count == 0)
        self.assertEqual(self.service.committed, [71, 84, 99])
        self.assertEqual(self.websocket.connection_count(3), 1)
        self.assertEqual(broken.close_codes, [1011])
        self.assertEqual(other.messages, [])
        self.assertEqual([event["tipo_evento"] for event in healthy.messages], [
            "demo_inicio", "demo_movimiento", "demo_movimiento", "demo_movimiento", "demo_fin",
        ])

    async def test_close_all_collects_active_tasks_and_openapi_documents_control_routes(self):
        first = await self.subscribe()
        second_service = self.new_service(4, 6)
        second = await self.subscribe(4, second_service)
        await self.manager.start(3, 5, self.service)
        await self.manager.start(4, 6, second_service)
        await self.sleep.next()
        await self.sleep.next()
        await asyncio.wait_for(self.manager.close_all(), timeout=2)
        self.assertEqual(self.manager.active_count, 0)
        self.assertEqual(self.sleep.pending, set())
        for socket in (first, second):
            kinds = [event["tipo_evento"] for event in socket.messages]
            self.assertEqual(kinds.count("demo_cancelada"), 1)
            self.assertNotIn("demo_fin", kinds)
        schema = self.application.openapi()
        for action, success in (("ejecutar", "202"), ("cancelar", "200")):
            operation = schema["paths"][f"/vehiculos/{{id_vehiculo}}/demos/{{id_demo}}/{action}"]["post"]
            self.assertEqual(operation["tags"], ["DEMO"])
            self.assertNotIn("requestBody", operation)
            self.assertIn(success, operation["responses"])
        description = schema["paths"]["/vehiculos/{id_vehiculo}/demos/{id_demo}/ejecutar"]["post"]["description"]
        for name in ("sp_obtener_movimientos_demo", "sp_actualizar_estado", "duracion_ms", "pausa_ms"):
            self.assertIn(name, description)


if __name__ == "__main__":
    unittest.main()
