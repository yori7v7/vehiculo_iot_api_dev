"""K-E: transicion y barrera REST en ASGI, sin RDS, WSS ni motores."""
import asyncio

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.public_control.legacy_guard import require_legacy_dispatch
from app.public_control.legacy_handover import HandoverRefused, LegacyHandoverGate


@pytest.fixture
def app():
    api = FastAPI()
    api.state.public_control_simulation = False
    api.state.exclusive_device_control_enabled = False
    api.state.legacy_handover = LegacyHandoverGate()
    calls = []

    @api.post("/vehiculos/1/movimientos", dependencies=[Depends(require_legacy_dispatch)])
    async def move():
        calls.append("move")
        return {"ok": True}

    @api.post("/vehiculos/1/demos/2/ejecutar", dependencies=[Depends(require_legacy_dispatch)])
    async def demo():
        calls.append("demo")
        return {"ok": True}

    @api.post("/vehiculos/1/demos/2/cancelar", dependencies=[Depends(require_legacy_dispatch)])
    async def cancel():
        calls.append("cancel")
        return {"ok": True}

    @api.get("/vehiculos/1/estado")
    async def read_only():
        return {"only": "read"}

    return api, calls


@pytest.mark.asyncio
async def test_transfer_excludes_legacy_and_allows_read_only(app):
    api, calls = app
    gate = api.state.legacy_handover
    phases = []

    async def close_demos():
        phases.append(("demos", gate.phase))

    async def signed_stop_ack():
        phases.append(("stop", gate.phase))
        return True

    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        assert (await client.post("/vehiculos/1/movimientos")).status_code == 200
        await gate.prepare_exclusive(close_demos=close_demos, signed_stop_ack=signed_stop_ack)
        assert gate.phase == "exclusive"
        for path in ["/vehiculos/1/movimientos", "/vehiculos/1/demos/2/ejecutar", "/vehiculos/1/demos/2/cancelar"]:
            assert (await client.post(path)).status_code == 503
        assert (await client.get("/vehiculos/1/estado")).json() == {"only": "read"}
    assert phases == [("demos", "draining"), ("stop", "draining")]
    assert calls == ["move"]


@pytest.mark.asyncio
async def test_inflight_request_drains_before_demo_close(app):
    api, calls = app
    gate = api.state.legacy_handover
    entered, release = asyncio.Event(), asyncio.Event()

    @api.post("/vehiculos/1/larga", dependencies=[Depends(require_legacy_dispatch)])
    async def long_work():
        entered.set()
        await release.wait()
        return {"ok": True}

    async def close_demos():
        assert gate.in_flight == 0

    async def stop_ack():
        return True

    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        old = asyncio.create_task(client.post("/vehiculos/1/larga"))
        await entered.wait()
        switch = asyncio.create_task(gate.prepare_exclusive(close_demos=close_demos, signed_stop_ack=stop_ack))
        await asyncio.sleep(0.01)
        assert gate.phase == "draining" and not switch.done()
        assert (await client.post("/vehiculos/1/movimientos")).status_code == 503
        release.set()
        assert (await old).status_code == 200
        await switch
        assert gate.phase == "exclusive"


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_at", ["demos", "stop", "false"])
async def test_failure_fences_reentry(app, fail_at):
    api, calls = app
    gate = api.state.legacy_handover

    async def close_demos():
        if fail_at == "demos":
            raise RuntimeError("No se pudo detener DEMO")

    async def stop_ack():
        if fail_at == "stop":
            raise OSError("No hay ESP")
        return fail_at != "false"

    with pytest.raises((RuntimeError, OSError, HandoverRefused)):
        await gate.prepare_exclusive(close_demos=close_demos, signed_stop_ack=stop_ack)
    assert gate.phase == "blocked"
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        assert (await client.post("/vehiculos/1/movimientos")).status_code == 503
    with pytest.raises(HandoverRefused):
        await gate.prepare_exclusive(close_demos=close_demos, signed_stop_ack=stop_ack)


@pytest.mark.asyncio
async def test_timeout_is_fail_closed(app):
    api, _ = app
    gate = api.state.legacy_handover

    async def never():
        await asyncio.sleep(10)

    async def stop_ack():
        return True

    with pytest.raises(TimeoutError):
        await gate.prepare_exclusive(close_demos=never, signed_stop_ack=stop_ack, timeout_s=0.02)
    assert gate.phase == "blocked"


@pytest.mark.asyncio
async def test_cancellation_is_fail_closed(app):
    api, _ = app
    gate = api.state.legacy_handover
    entered = asyncio.Event()

    async def never():
        entered.set()
        await asyncio.sleep(100)

    async def stop_ack():
        return True

    task = asyncio.create_task(gate.prepare_exclusive(close_demos=never, signed_stop_ack=stop_ack))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert gate.phase == "blocked"


def test_old_flag_and_simulation_compatible(app):
    api, calls = app
    with TestClient(api) as client:
        assert client.post("/vehiculos/1/movimientos").status_code == 200
        api.state.exclusive_device_control_enabled = True
        assert client.post("/vehiculos/1/movimientos").status_code == 503
        api.state.exclusive_device_control_enabled = False
        api.state.public_control_simulation = True
        assert client.post("/vehiculos/1/movimientos").status_code == 503
    assert calls == ["move"]
