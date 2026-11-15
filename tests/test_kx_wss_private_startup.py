"""K-X: activación WSS sólo con archivo privado válido y opt-in explícito.

Sin AWS, ESP, RDS ni motores; pruebas ASGI in-process y archivo temporal.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import secrets

import pytest
from fastapi.testclient import TestClient

from app.config.settings import PROJECT_ROOT, get_settings
from app.main import create_app
from app.public_control.kx_device_identity import (
    KXDeviceIdentityError, load_private_key,
)
from app.public_control.kx_signed_wss import KXDiagnosticWSSHub, PATH

HOST = "https://100-30-4-62.nip.io"
KEY = "KX-ADMIN-TEST-" + "X" * 50


@pytest.fixture
def setup(tmp_path, monkeypatch):
    secret = secrets.token_bytes(32)
    path = tmp_path / "kx-device-1-key.bin"
    path.write_bytes(secret)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("API_KEY", KEY)
    monkeypatch.setenv("PUBLIC_VIRTUAL_ADMISSION_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_VIRTUAL_ADMISSION_SQLITE_PATH", str(tmp_path / "kx.sqlite3"))
    monkeypatch.setenv("CONTROL_PUBLICO_ENABLED", "false")
    monkeypatch.setenv("CONTROL_PUBLICO_SIMULATION", "false")
    monkeypatch.setenv("DEVICE_LAB_ENABLED", "false")
    monkeypatch.setenv("KX_DIAGNOSTIC_WSS_ENABLED", "true")
    monkeypatch.setenv("KX_DIAGNOSTIC_WSS_KEY_PATH", str(path))
    get_settings.cache_clear()
    yield path, secret
    get_settings.cache_clear()


def test_startup_loads_private_binary_key_without_public_disclosure(setup):
    path, secret = setup
    key, fingerprint = load_private_key(path)
    assert key == secret
    assert fingerprint == sha256(secret).hexdigest().upper()
    app = create_app()
    assert app.state.kx_diag_hub is None
    with TestClient(app, base_url=HOST) as client:
        hub = app.state.kx_diag_hub
        assert isinstance(hub, KXDiagnosticWSSHub)
        assert hub.ready is False
        assert client.get("/docs").status_code == 200
        assert "kx-device-1-key.bin" not in client.get("/openapi.json").text
        assert secret.hex() not in client.get("/openapi.json").text
        # El canal sin autenticación completa no puede despachar una orden.
        with client.websocket_connect("wss://100-30-4-62.nip.io" + PATH) as ws:
            first = ws.receive_json()
            assert first["tipo"] == "desafio_dispositivo_lab"
            assert first["simulado"] is True
            assert hub.ready is False
    assert app.state.kx_diag_hub is None
    assert path.read_bytes() == secret


def test_missing_key_prevents_service_startup(setup):
    path, secret = setup
    path.unlink()
    app = create_app()
    with pytest.raises(KXDeviceIdentityError):
        with TestClient(app, base_url=HOST):
            pass


@pytest.mark.parametrize("bad", [b"", b"bad", b"x" * 31, b"x" * 33])
def test_wrong_key_size_fails_closed(setup, bad):
    path, _secret = setup
    path.write_bytes(bad)
    app = create_app()
    with pytest.raises(KXDeviceIdentityError):
        with TestClient(app, base_url=HOST):
            pass


def test_explicit_opt_in_required_even_if_key_file_exists(setup, monkeypatch):
    path, secret = setup
    monkeypatch.setenv("KX_DIAGNOSTIC_WSS_ENABLED", "false")
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app, base_url=HOST) as client:
        assert app.state.kx_diag_hub is None
        with pytest.raises(Exception):
            with client.websocket_connect("wss://100-30-4-62.nip.io" + PATH):
                pass
    assert path.read_bytes() == secret


def test_without_kx_admission_cannot_enable_wss(setup, monkeypatch):
    monkeypatch.setenv("PUBLIC_VIRTUAL_ADMISSION_ENABLED", "false")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="WSS K-X exige admision"):
        create_app()


def test_reject_key_location_inside_repository(setup, monkeypatch):
    monkeypatch.setenv("KX_DIAGNOSTIC_WSS_KEY_PATH", str(PROJECT_ROOT / "fake-key.bin"))
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="fuera del repositorio"):
        create_app()
