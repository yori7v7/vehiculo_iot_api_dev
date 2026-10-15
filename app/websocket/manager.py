"""Grupos WebSocket en memoria, sin dependencias de base de datos o Settings."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol


class WebSocketConnection(Protocol):
    async def accept(self) -> None: ...
    async def send_json(self, data: dict[str, Any]) -> None: ...
    async def close(self, code: int = 1000) -> None: ...


@dataclass(slots=True)
class _VehicleGroup:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    clients: dict[int, WebSocketConnection] = field(default_factory=dict)
    users: int = 0


class WebSocketManager:
    """Serializar la instantánea y las publicaciones por vehículo en este proceso."""

    def __init__(self, *, send_timeout: float = 5.0, close_timeout: float = 5.0) -> None:
        if send_timeout <= 0 or close_timeout <= 0:
            raise ValueError("Los tiempos de espera deben ser positivos.")
        self._send_timeout = send_timeout
        self._close_timeout = close_timeout
        self._groups: dict[int, _VehicleGroup] = {}
        self._close_all_lock = asyncio.Lock()
        self._closing = False
        self._epoch = 0

    @property
    def vehicle_count(self) -> int:
        """Grupos con clientes o con operaciones que todavía usan su lock."""
        return len(self._groups)

    def connection_count(self, vehicle_id: int) -> int:
        group = self._groups.get(vehicle_id)
        return len(group.clients) if group is not None else 0

    @asynccontextmanager
    async def _group(
        self, vehicle_id: int, *, create: bool
    ) -> AsyncIterator[_VehicleGroup | None]:
        group = self._groups.get(vehicle_id)
        if group is None:
            if not create:
                yield None
                return
            group = _VehicleGroup()
            self._groups[vehicle_id] = group
        # Contar también a quien espera evita sustituir un lock aún en uso.
        group.users += 1
        try:
            async with group.lock:
                yield group
        finally:
            group.users -= 1
            if not group.users and not group.clients and self._groups.get(vehicle_id) is group:
                del self._groups[vehicle_id]

    def _ensure_connect_allowed(self, epoch: int) -> None:
        if self._closing or epoch != self._epoch:
            raise RuntimeError("El administrador de conexiones se está cerrando.")

    async def connect(
        self,
        vehicle_id: int,
        websocket: WebSocketConnection,
        initial_event_factory: Callable[[], Awaitable[dict[str, Any]]],
    ) -> None:
        epoch = self._epoch
        self._ensure_connect_allowed(epoch)
        async with self._group(vehicle_id, create=True) as group:
            assert group is not None
            self._ensure_connect_allowed(epoch)
            if group.clients.get(id(websocket)) is websocket:
                return
            # Los errores de la lectura se propagan sin cerrar: la ruta elige
            # el código de rechazo (por ejemplo 1008 si el vehículo no existe).
            initial_event = await initial_event_factory()
            self._ensure_connect_allowed(epoch)
            try:
                await asyncio.wait_for(websocket.accept(), timeout=self._send_timeout)
                await asyncio.wait_for(
                    websocket.send_json(initial_event), timeout=self._send_timeout
                )
                self._ensure_connect_allowed(epoch)
            except BaseException:
                await self._close_socket(websocket, code=1011)
                raise
            group.clients[id(websocket)] = websocket

    async def disconnect(self, vehicle_id: int, websocket: WebSocketConnection) -> None:
        async with self._group(vehicle_id, create=False) as group:
            if group is None or group.clients.get(id(websocket)) is not websocket:
                return
            try:
                await self._close_socket(websocket, code=1000)
            finally:
                group.clients.pop(id(websocket), None)

    async def _send_one(self, websocket: WebSocketConnection, event: dict[str, Any]) -> bool:
        try:
            await asyncio.wait_for(websocket.send_json(event), timeout=self._send_timeout)
        except Exception:
            return False
        return True

    @staticmethod
    async def _finish_cleanup(operation: Awaitable[Any]) -> None:
        """Terminar el cierre acotado antes de propagar cancelaciones del caller."""
        cleanup = asyncio.ensure_future(operation)
        cancelled = False
        while True:
            try:
                await asyncio.shield(cleanup)
                break
            except asyncio.CancelledError:
                if cleanup.cancelled():
                    raise
                cancelled = True
        if cancelled:
            raise asyncio.CancelledError()

    async def _bounded_close(self, websocket: WebSocketConnection, *, code: int) -> None:
        try:
            await asyncio.wait_for(websocket.close(code=code), timeout=self._close_timeout)
        except Exception:
            pass

    async def _close_socket(self, websocket: WebSocketConnection, *, code: int) -> None:
        await self._finish_cleanup(self._bounded_close(websocket, code=code))

    async def _close_clients(self, clients: tuple[WebSocketConnection, ...], *, code: int) -> None:
        await self._finish_cleanup(
            asyncio.gather(*(self._bounded_close(client, code=code) for client in clients))
        )

    async def broadcast(self, vehicle_id: int, event: dict[str, Any]) -> None:
        async with self._group(vehicle_id, create=False) as group:
            if group is None or not group.clients:
                return
            clients = tuple(group.clients.values())
            delivered = await asyncio.gather(*(self._send_one(client, event) for client in clients))
            failed = [client for client, success in zip(clients, delivered) if not success]
            try:
                await self._close_clients(tuple(failed), code=1011)
            finally:
                for client in failed:
                    group.clients.pop(id(client), None)

    async def _close_vehicle(self, vehicle_id: int) -> None:
        async with self._group(vehicle_id, create=False) as group:
            if group is None:
                return
            clients = tuple(group.clients.values())
            try:
                await self._close_clients(clients, code=1001)
            finally:
                for client in clients:
                    group.clients.pop(id(client), None)

    async def close_all(self) -> None:
        """Cerrar grupos concurrentemente e invalidar altas que estaban pendientes."""
        async with self._close_all_lock:
            self._closing = True
            self._epoch += 1
            try:
                await self._finish_cleanup(
                    asyncio.gather(*(self._close_vehicle(vehicle_id) for vehicle_id in tuple(self._groups)))
                )
            finally:
                self._closing = False
