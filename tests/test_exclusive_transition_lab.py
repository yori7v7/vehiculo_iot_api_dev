"""K-E: conectar gestor DEMO a barrera, sin motos ni hardware."""
import pytest
from fastapi import FastAPI

from app.public_control.exclusive_transition_lab import prepare_exclusive_for_lab
from app.public_control.legacy_handover import HandoverRefused, LegacyHandoverGate


@pytest.mark.asyncio
async def test_integration_calls_manager_before_signed_stop():
    app = FastAPI()
    app.state.legacy_handover = LegacyHandoverGate()
    actions = []

    class Demos:
        async def close_all(self):
            actions.append("demo-closed")

    app.state.demo_execution_manager = Demos()

    async def stop():
        actions.append("signed-stop")
        return True

    await prepare_exclusive_for_lab(app, signed_stop_ack=stop)
    assert actions == ["demo-closed", "signed-stop"]
    assert app.state.legacy_handover.phase == "exclusive"


@pytest.mark.asyncio
async def test_reject_missing_demo_manager():
    app = FastAPI()
    app.state.legacy_handover = LegacyHandoverGate()

    async def stop():
        return True

    with pytest.raises(HandoverRefused):
        await prepare_exclusive_for_lab(app, signed_stop_ack=stop)
    assert app.state.legacy_handover.phase == "legacy"


@pytest.mark.asyncio
async def test_demo_error_holds_fence():
    app = FastAPI()
    app.state.legacy_handover = LegacyHandoverGate()

    class Demos:
        async def close_all(self):
            raise RuntimeError("demo pending")

    app.state.demo_execution_manager = Demos()

    async def stop():
        return True

    with pytest.raises(RuntimeError):
        await prepare_exclusive_for_lab(app, signed_stop_ack=stop)
    assert app.state.legacy_handover.phase == "blocked"
