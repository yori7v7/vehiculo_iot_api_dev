"""K-D: barrera de movimiento y DEMO heredados, sin BD ni WSS.

Este contrato NO conecta los comandos legacy al nuevo coordinador. Solo
garantiza que queden cerrados cuando una futura autoridad exclusiva esté activa.
"""
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.public_control.legacy_guard import require_legacy_dispatch


@pytest.fixture
def app():
    application = FastAPI()
    application.state.public_control_simulation = False
    application.state.exclusive_device_control_enabled = False
    called = []

    @application.post('/vehiculos/1/movimientos', dependencies=[Depends(require_legacy_dispatch)])
    def movement():
        called.append('movement')
        return {'ok': True}

    @application.post('/vehiculos/1/demos/2/ejecutar', dependencies=[Depends(require_legacy_dispatch)])
    def start_demo():
        called.append('demo')
        return {'ok': True}

    @application.post('/vehiculos/1/demos/2/cancelar', dependencies=[Depends(require_legacy_dispatch)])
    def cancel_demo():
        called.append('cancel')
        return {'ok': True}

    @application.get('/vehiculos/1/estado')
    def read_state():
        return {'estado': 'lectura'}

    return application, called


def test_legacy_works_with_coordinator_off(app):
    application, called = app
    with TestClient(application) as c:
        for path in ('/vehiculos/1/movimientos', '/vehiculos/1/demos/2/ejecutar', '/vehiculos/1/demos/2/cancelar'):
            assert c.post(path).status_code == 200
    assert called == ['movement', 'demo', 'cancel']


def test_exclusive_coordinator_blocks_every_legacy_write(app):
    application, called = app
    application.state.exclusive_device_control_enabled = True
    with TestClient(application) as c:
        for path in ('/vehiculos/1/movimientos', '/vehiculos/1/demos/2/ejecutar', '/vehiculos/1/demos/2/cancelar'):
            response = c.post(path)
            assert response.status_code == 503
            assert 'aislado' in response.json()['detail']
    assert not called


def test_public_simulation_still_blocks_legacy(app):
    application, called = app
    application.state.public_control_simulation = True
    with TestClient(application) as c:
        assert c.post('/vehiculos/1/movimientos').status_code == 503
    assert not called


def test_read_only_unaffected_when_exclusive(app):
    application, called = app
    application.state.exclusive_device_control_enabled = True
    with TestClient(application) as c:
        assert c.get('/vehiculos/1/estado').json() == {'estado': 'lectura'}
    assert not called


def test_missing_flag_defaults_to_legacy_mode(app):
    application, called = app
    delattr(application.state, 'exclusive_device_control_enabled')
    with TestClient(application) as c:
        assert c.post('/vehiculos/1/movimientos').status_code == 200
    assert called == ['movement']
