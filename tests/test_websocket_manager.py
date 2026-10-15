"""Eventos y coordinación WebSocket con sockets simulados, sin red ni RDS."""

import asyncio
from copy import deepcopy
from datetime import datetime
import json
import unittest

from app.models.movement import MovementResponse
from app.models.state import StateResponse
from app.websocket.events import InitialStateEvent, MovementEvent
from app.websocket.manager import WebSocketManager


DB_TIMESTAMP = datetime(2026, 10, 14, 12, 34, 56)


def initial_event(vehicle_id=3):
    return {"tipo_evento": "estado_actual", "id_vehiculo": vehicle_id}


def movement_event(vehicle_id=3):
    return {"tipo_evento": "movimiento", "id_vehiculo": vehicle_id, "codigo": -5}


class FakeSocket:
    def __init__(self):
        self.accepted = 0
        self.messages = []
        self.close_codes = []
        self.closed = False
        self.accept_error = None
        self.send_error = None
        self.close_error = None
        self.send_gate = None
        self.close_gate = None
        self.send_started = asyncio.Event()
        self.close_started = asyncio.Event()

    async def accept(self):
        if self.accept_error is not None:
            raise self.accept_error
        self.accepted += 1

    async def send_json(self, data):
        self.send_started.set()
        if self.send_gate is not None:
            await self.send_gate.wait()
        if self.send_error is not None:
            raise self.send_error
        self.messages.append(deepcopy(data))

    async def close(self, code=1000):
        self.close_codes.append(code)
        self.close_started.set()
        if self.close_gate is not None:
            await self.close_gate.wait()
        if self.close_error is not None:
            raise self.close_error
        self.closed = True


class WebSocketEventTests(unittest.TestCase):
    def test_initial_state_uses_exact_persisted_values_and_serializes_timestamp(self):
        state = StateResponse(
            id_vehiculo=3, vehiculo="Vehículo", id_comando=7, comando="REVERSA",
            codigo=-5, conectado=0, fecha_actualizacion=DB_TIMESTAMP,
        )
        event = InitialStateEvent.from_state(3, state)
        self.assertEqual(event.model_dump(mode="json"), {
            "tipo_evento": "estado_actual", "id_vehiculo": 3, "comando": "REVERSA",
            "codigo": -5, "timestamp": "2026-10-14T12:34:56",
            "estado": {
                "id_vehiculo": 3, "vehiculo": "Vehículo", "id_comando": 7,
                "comando": "REVERSA", "codigo": -5, "conectado": False,
                "fecha_actualizacion": "2026-10-14T12:34:56",
            },
        })
        json.dumps(event.model_dump(mode="json"))

    def test_initial_without_state_preserves_nulls_and_does_not_invent_time(self):
        self.assertEqual(InitialStateEvent.from_state(3, None).model_dump(mode="json"), {
            "tipo_evento": "estado_actual", "id_vehiculo": 3, "comando": None,
            "codigo": None, "timestamp": None, "estado": None,
        })

    def test_initial_rejects_state_owned_by_another_vehicle(self):
        state = StateResponse(
            id_vehiculo=4, vehiculo="Otro", id_comando=None, comando=None,
            codigo=None, conectado=False, fecha_actualizacion=None,
        )
        with self.assertRaises(ValueError):
            InitialStateEvent.from_state(3, state)

    def test_movement_event_uses_confirmed_response_and_database_timestamp(self):
        response = MovementResponse(
            resultado="ok", id_vehiculo=3, id_comando=7, comando="REVERSA",
            codigo=-5, conectado=False, fecha_actualizacion=DB_TIMESTAMP, origen="API",
        )
        event = MovementEvent.from_movement(response)
        self.assertEqual(event.model_dump(mode="json"), {
            "tipo_evento": "movimiento", "id_vehiculo": 3, "id_comando": 7,
            "comando": "REVERSA", "codigo": -5, "timestamp": "2026-10-14T12:34:56",
            "conectado": False, "origen": "API",
        })
        response.fecha_actualizacion = None
        self.assertIsNone(MovementEvent.from_movement(response).timestamp)


class WebSocketManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager = WebSocketManager(send_timeout=0.2, close_timeout=0.2)

    async def asyncTearDown(self):
        await self.manager.close_all()

    async def connect(self, socket, vehicle_id=3):
        async def factory():
            return initial_event(vehicle_id)
        await self.manager.connect(vehicle_id, socket, factory)

    async def test_groups_broadcast_to_same_vehicle_and_isolate_another(self):
        first, second, other = FakeSocket(), FakeSocket(), FakeSocket()
        await self.connect(first)
        await self.connect(second)
        await self.connect(other, 4)
        await self.manager.broadcast(3, movement_event())
        self.assertEqual(first.messages, [initial_event(), movement_event()])
        self.assertEqual(second.messages, first.messages)
        self.assertEqual(other.messages, [initial_event(4)])
        self.assertEqual(self.manager.connection_count(3), 2)
        self.assertEqual(self.manager.connection_count(4), 1)
        self.assertEqual(self.manager.vehicle_count, 2)

    async def test_empty_broadcast_and_unknown_disconnect_do_not_create_groups(self):
        for vehicle_id in range(50):
            await self.manager.broadcast(vehicle_id, movement_event(vehicle_id))
            await self.manager.disconnect(vehicle_id, FakeSocket())
        self.assertEqual(self.manager.vehicle_count, 0)

    async def test_factory_failure_propagates_without_accept_close_or_group_leak(self):
        socket = FakeSocket()
        error = ValueError("fallo controlado de lectura")

        async def factory():
            raise error

        with self.assertRaises(ValueError) as raised:
            await self.manager.connect(3, socket, factory)
        self.assertIs(raised.exception, error)
        self.assertEqual(socket.accepted, 0)
        self.assertEqual(socket.close_codes, [])
        self.assertEqual(self.manager.vehicle_count, 0)

    async def test_accept_failure_propagates_and_closes_failed_socket(self):
        socket = FakeSocket()
        socket.accept_error = RuntimeError("socket cerrado")
        with self.assertRaises(RuntimeError):
            await self.connect(socket)
        self.assertEqual(socket.close_codes, [1011])
        self.assertEqual(self.manager.vehicle_count, 0)

    async def test_initial_send_failure_propagates_without_registering_socket(self):
        socket = FakeSocket()
        socket.send_error = OSError("socket perdido")
        with self.assertRaises(OSError):
            await self.connect(socket)
        self.assertEqual(socket.accepted, 1)
        self.assertEqual(socket.close_codes, [1011])
        self.assertEqual(self.manager.connection_count(3), 0)
        self.assertEqual(self.manager.vehicle_count, 0)

    async def test_initial_send_timeout_is_bounded_and_cleans_group(self):
        self.manager = WebSocketManager(send_timeout=0.01, close_timeout=0.01)
        socket = FakeSocket()
        socket.send_gate = asyncio.Event()
        with self.assertRaises(TimeoutError):
            await asyncio.wait_for(self.connect(socket), timeout=0.3)
        self.assertEqual(socket.close_codes, [1011])
        self.assertEqual(self.manager.vehicle_count, 0)

    async def test_initial_snapshot_is_sent_before_waiting_broadcast(self):
        socket = FakeSocket()
        factory_started, release_factory = asyncio.Event(), asyncio.Event()

        async def factory():
            factory_started.set()
            await release_factory.wait()
            return initial_event()

        connect = asyncio.create_task(self.manager.connect(3, socket, factory))
        await factory_started.wait()
        broadcast = asyncio.create_task(self.manager.broadcast(3, movement_event()))
        await asyncio.sleep(0)
        self.assertFalse(broadcast.done())
        self.assertEqual(socket.messages, [])
        release_factory.set()
        await asyncio.gather(connect, broadcast)
        self.assertEqual(socket.messages, [initial_event(), movement_event()])

    async def test_broadcast_waits_until_initial_send_finishes_and_client_registers(self):
        socket = FakeSocket()
        socket.send_gate = asyncio.Event()
        connect = asyncio.create_task(self.connect(socket))
        await socket.send_started.wait()
        broadcast = asyncio.create_task(self.manager.broadcast(3, movement_event()))
        await asyncio.sleep(0)
        self.assertEqual(self.manager.connection_count(3), 0)
        self.assertFalse(broadcast.done())
        socket.send_gate.set()
        await asyncio.gather(connect, broadcast)
        self.assertEqual(socket.messages, [initial_event(), movement_event()])

    async def test_slow_factory_does_not_block_another_vehicle(self):
        first, second = FakeSocket(), FakeSocket()
        started, release = asyncio.Event(), asyncio.Event()
        await self.connect(second, 4)

        async def factory():
            started.set()
            await release.wait()
            return initial_event()

        connect = asyncio.create_task(self.manager.connect(3, first, factory))
        await started.wait()
        await asyncio.wait_for(self.manager.broadcast(4, movement_event(4)), timeout=0.3)
        self.assertEqual(second.messages[-1], movement_event(4))
        release.set()
        await connect

    async def test_broadcast_sends_to_clients_concurrently(self):
        slow, fast = FakeSocket(), FakeSocket()
        await self.connect(slow)
        await self.connect(fast)
        slow.send_gate = asyncio.Event()
        fast.send_started.clear()
        broadcast = asyncio.create_task(self.manager.broadcast(3, movement_event()))
        await fast.send_started.wait()
        self.assertEqual(fast.messages[-1], movement_event())
        self.assertEqual(slow.messages, [initial_event()])
        slow.send_gate.set()
        await broadcast

    async def test_one_failed_client_is_removed_closed_and_others_still_receive(self):
        failed, healthy = FakeSocket(), FakeSocket()
        await self.connect(failed)
        await self.connect(healthy)
        failed.send_error = RuntimeError("socket cerrado")
        failed.close_error = OSError("cierre ya completado")
        await self.manager.broadcast(3, movement_event())
        self.assertEqual(healthy.messages[-1], movement_event())
        self.assertEqual(failed.close_codes, [1011])
        self.assertEqual(self.manager.connection_count(3), 1)

    async def test_send_and_close_timeouts_remove_last_client_without_hanging(self):
        self.manager = WebSocketManager(send_timeout=0.01, close_timeout=0.01)
        socket = FakeSocket()
        await self.connect(socket)
        socket.send_gate, socket.close_gate = asyncio.Event(), asyncio.Event()
        await asyncio.wait_for(self.manager.broadcast(3, movement_event()), timeout=0.3)
        self.assertEqual(socket.close_codes, [1011])
        self.assertEqual(self.manager.connection_count(3), 0)
        self.assertEqual(self.manager.vehicle_count, 0)

    async def test_disconnect_is_idempotent_and_last_client_cleans_group(self):
        socket = FakeSocket()
        await self.connect(socket)
        await self.manager.disconnect(4, socket)
        self.assertEqual(self.manager.connection_count(3), 1)
        await self.manager.disconnect(3, socket)
        await self.manager.disconnect(3, socket)
        self.assertEqual(socket.close_codes, [1000])
        self.assertEqual(self.manager.vehicle_count, 0)

    async def test_reconnection_after_failure_uses_a_clean_group(self):
        failed, reconnected = FakeSocket(), FakeSocket()
        await self.connect(failed)
        failed.send_error = OSError("desconexión")
        await self.manager.broadcast(3, movement_event())
        self.assertEqual(self.manager.vehicle_count, 0)
        await self.connect(reconnected)
        await self.manager.broadcast(3, movement_event())
        self.assertEqual(reconnected.messages, [initial_event(), movement_event()])
        self.assertEqual(self.manager.connection_count(3), 1)

    async def test_factory_failure_keeps_same_lock_for_waiting_broadcast_and_reconnect(self):
        first, second = FakeSocket(), FakeSocket()
        started, release = asyncio.Event(), asyncio.Event()

        async def failing_factory():
            started.set()
            await release.wait()
            raise ValueError("lectura fallida")

        first_connect = asyncio.create_task(self.manager.connect(3, first, failing_factory))
        await started.wait()
        original_group = self.manager._groups[3]
        broadcast = asyncio.create_task(self.manager.broadcast(3, movement_event()))

        async def second_factory():
            self.assertIs(self.manager._groups[3], original_group)
            return initial_event()

        second_connect = asyncio.create_task(self.manager.connect(3, second, second_factory))
        await asyncio.sleep(0)
        release.set()
        with self.assertRaises(ValueError):
            await first_connect
        await asyncio.gather(broadcast, second_connect)
        self.assertEqual(second.messages, [initial_event()])
        await self.manager.disconnect(3, second)
        self.assertEqual(self.manager.vehicle_count, 0)

    async def test_cancelled_lock_waiter_does_not_leak_group_or_replace_lock(self):
        started, release = asyncio.Event(), asyncio.Event()

        async def factory():
            started.set()
            await release.wait()
            raise ValueError("lectura fallida")

        owner = asyncio.create_task(self.manager.connect(3, FakeSocket(), factory))
        await started.wait()
        original_group = self.manager._groups[3]
        waiter = asyncio.create_task(self.connect(FakeSocket()))
        await asyncio.sleep(0)
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiter
        self.assertIs(self.manager._groups[3], original_group)
        self.assertEqual(original_group.users, 1)
        release.set()
        with self.assertRaises(ValueError):
            await owner
        self.assertEqual(self.manager.vehicle_count, 0)

    async def test_close_all_closes_groups_concurrently_and_rejects_new_connections(self):
        first, second = FakeSocket(), FakeSocket()
        await self.connect(first)
        await self.connect(second, 4)
        first.close_gate, second.close_gate = asyncio.Event(), asyncio.Event()
        close_all = asyncio.create_task(self.manager.close_all())
        await asyncio.gather(first.close_started.wait(), second.close_started.wait())
        with self.assertRaises(RuntimeError):
            await self.connect(FakeSocket(), 5)
        first.close_gate.set()
        second.close_gate.set()
        await close_all
        self.assertEqual(first.close_codes, [1001])
        self.assertEqual(second.close_codes, [1001])
        self.assertEqual(self.manager.vehicle_count, 0)

    async def test_close_all_invalidates_factory_in_progress_before_accept(self):
        socket = FakeSocket()
        started, release = asyncio.Event(), asyncio.Event()

        async def factory():
            started.set()
            await release.wait()
            return initial_event()

        connect = asyncio.create_task(self.manager.connect(3, socket, factory))
        await started.wait()
        close_all = asyncio.create_task(self.manager.close_all())
        await asyncio.sleep(0)
        release.set()
        with self.assertRaises(RuntimeError):
            await connect
        await close_all
        self.assertEqual(socket.accepted, 0)
        self.assertEqual(self.manager.vehicle_count, 0)

    async def test_close_all_timeout_still_cleans_all_groups_and_allows_reuse(self):
        self.manager = WebSocketManager(send_timeout=0.01, close_timeout=0.01)
        socket = FakeSocket()
        await self.connect(socket)
        socket.close_gate = asyncio.Event()
        await asyncio.wait_for(self.manager.close_all(), timeout=0.3)
        self.assertEqual(self.manager.vehicle_count, 0)
        await self.connect(FakeSocket())
        self.assertEqual(self.manager.connection_count(3), 1)

    async def test_cancelled_close_all_finishes_closing_sockets_before_removing_groups(self):
        first, second = FakeSocket(), FakeSocket()
        await self.connect(first)
        await self.connect(second, 4)
        first.close_gate, second.close_gate = asyncio.Event(), asyncio.Event()
        close_all = asyncio.create_task(self.manager.close_all())
        await asyncio.gather(first.close_started.wait(), second.close_started.wait())
        close_all.cancel()
        await asyncio.sleep(0)
        self.assertFalse(close_all.done())
        self.assertFalse(first.closed)
        self.assertFalse(second.closed)
        self.assertEqual(self.manager.connection_count(3), 1)
        self.assertEqual(self.manager.connection_count(4), 1)
        first.close_gate.set()
        second.close_gate.set()
        with self.assertRaises(asyncio.CancelledError):
            await close_all
        self.assertTrue(first.closed)
        self.assertTrue(second.closed)
        self.assertEqual(self.manager.vehicle_count, 0)
        await self.manager.close_all()
        self.assertEqual(first.close_codes, [1001])
        self.assertEqual(second.close_codes, [1001])

    async def test_repeated_cancellation_of_disconnect_preserves_bounded_cleanup(self):
        socket = FakeSocket()
        await self.connect(socket)
        socket.close_gate = asyncio.Event()
        disconnect = asyncio.create_task(self.manager.disconnect(3, socket))
        await socket.close_started.wait()
        disconnect.cancel()
        await asyncio.sleep(0)
        disconnect.cancel()
        await asyncio.sleep(0)
        self.assertFalse(disconnect.done())
        self.assertFalse(socket.closed)
        self.assertEqual(self.manager.connection_count(3), 1)
        socket.close_gate.set()
        with self.assertRaises(asyncio.CancelledError):
            await disconnect
        self.assertTrue(socket.closed)
        self.assertEqual(socket.close_codes, [1000])
        self.assertEqual(self.manager.vehicle_count, 0)

    async def test_cancelled_broadcast_finishes_failed_socket_close_and_keeps_healthy_client(self):
        failed, healthy = FakeSocket(), FakeSocket()
        await self.connect(failed)
        await self.connect(healthy)
        failed.send_error = OSError("socket perdido")
        failed.close_gate = asyncio.Event()
        broadcast = asyncio.create_task(self.manager.broadcast(3, movement_event()))
        await failed.close_started.wait()
        broadcast.cancel()
        await asyncio.sleep(0)
        self.assertFalse(broadcast.done())
        self.assertEqual(self.manager.connection_count(3), 2)
        failed.close_gate.set()
        with self.assertRaises(asyncio.CancelledError):
            await broadcast
        self.assertTrue(failed.closed)
        self.assertFalse(healthy.closed)
        self.assertEqual(healthy.messages[-1], movement_event())
        self.assertEqual(self.manager.connection_count(3), 1)
        await self.manager.disconnect(3, healthy)
        self.assertTrue(healthy.closed)
        self.assertEqual(self.manager.vehicle_count, 0)

    async def test_nonpositive_timeouts_are_rejected(self):
        for options in ({"send_timeout": 0}, {"send_timeout": -1}, {"close_timeout": 0}):
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    WebSocketManager(**options)


if __name__ == "__main__":
    unittest.main()
