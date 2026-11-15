"""Canal de autenticación de dispositivo: laboratorio AISLADO, sin actuadores.

Este contrato NO es el protocolo de operación física final. No incorpora el
coordinador público ni permite despachar movimientos. Las claves se inyectan.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import base64
import hmac
import json
import secrets
import struct
from typing import Any


PROTOCOL = 1
UINT32_MAX = 2**32 - 1
NONCE_LEN = 32
BOOT_LEN = 16
SESSION_LEN = 16
AUTH_CONTEXT = b"vehiculo-iot|lab-device-auth|v1|"
SERVER_CONTEXT = b"vehiculo-iot|lab-device-server|v1|"
RX_CONTEXT = b"vehiculo-iot|lab-device-rx|v1|"
TX_CONTEXT = b"vehiculo-iot|lab-device-tx|v1|"
TELEMETRY_CONTEXT = b"vehiculo-iot|lab-device-telemetry|v1|"
ACK_CONTEXT = b"vehiculo-iot|lab-device-telemetry-ack|v1|"


class LabDeviceProtocolError(ValueError):
    """Credencial o contenido inválido. No incluir secretos en el mensaje."""


def encoded(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def decoded(value: Any, count: int) -> bytes:
    if not isinstance(value, str) or len(value) != (count * 8 + 5) // 6:
        raise LabDeviceProtocolError("Identificador de sesión inválido.")
    try:
        out = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, base64.binascii.Error):
        raise LabDeviceProtocolError("Identificador de sesión inválido.") from None
    if len(out) != count or encoded(out) != value:
        raise LabDeviceProtocolError("Identificador de sesión inválido.")
    return out


def check_key(secret: bytes) -> bytes:
    if type(secret) is not bytes or len(secret) != 32:
        raise LabDeviceProtocolError("La clave del dispositivo debe ser privada y tener 32 bytes.")
    return secret


def _mac(key: bytes, domain: bytes, payload: bytes) -> str:
    return hmac.new(key, domain + payload, sha256).hexdigest()


def _validate_mac(mac: Any, expected: str) -> None:
    if (type(mac) is not str or len(mac) != 64
            or any(c not in "0123456789abcdef" for c in mac)
            or not hmac.compare_digest(mac, expected)):
        raise LabDeviceProtocolError("Firma de dispositivo inválida.")


def canonical(value: dict) -> bytes:
    """JSON canónico, exacto y sin serialización dependiente de espacios."""
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("ascii")


@dataclass(frozen=True, repr=False)
class DeviceSession:
    vehicle_id: int
    session_id: str
    boot_id: str
    device_nonce: str
    command_key: bytes
    telemetry_key: bytes
    session_binding: bytes
    last_counter: int = 0


class DeviceLabHandshake:
    """Desafío de uso único: credencial de dispositivo nunca viaja por WSS."""

    def __init__(self, vehicle_id: int, secret: bytes, *, nonce: bytes | None = None):
        if type(vehicle_id) is not int or not 0 < vehicle_id <= UINT32_MAX:
            raise ValueError("Identificador de vehículo inválido.")
        self.vehicle_id = vehicle_id
        self._secret = check_key(secret)
        self._nonce = nonce if nonce is not None else secrets.token_bytes(NONCE_LEN)
        if type(self._nonce) is not bytes or len(self._nonce) != NONCE_LEN:
            raise ValueError("Desafío inválido.")
        self._consumed = False

    @property
    def challenge(self) -> dict:
        return {"tipo": "desafio_dispositivo_lab", "version": PROTOCOL,
                "vehiculo": self.vehicle_id, "desafio": encoded(self._nonce),
                "simulado": True}

    def _binding(self, boot: bytes, nonce_device: bytes) -> bytes:
        return struct.pack(">I", self.vehicle_id) + self._nonce + boot + nonce_device

    def verify(self, reply: dict) -> tuple[DeviceSession, dict]:
        if self._consumed:
            raise LabDeviceProtocolError("El desafío ya se usó.")
        self._consumed = True
        if (type(reply) is not dict or set(reply) !=
            {"tipo", "version", "vehiculo", "arranque", "nonce_dispositivo", "prueba", "simulado"}
            or reply["tipo"] != "autenticar_dispositivo_lab"
            or type(reply["version"]) is not int or reply["version"] != PROTOCOL
            or type(reply["vehiculo"]) is not int or reply["vehiculo"] != self.vehicle_id
            or reply["simulado"] is not True):
            raise LabDeviceProtocolError("Respuesta de autenticación inválida.")
        boot = decoded(reply["arranque"], BOOT_LEN)
        device_nonce = decoded(reply["nonce_dispositivo"], BOOT_LEN)
        binding = self._binding(boot, device_nonce)
        _validate_mac(reply["prueba"], _mac(self._secret, AUTH_CONTEXT, binding))
        session_raw = secrets.token_bytes(SESSION_LEN)
        session = encoded(session_raw)
        base = binding + session_raw
        tx_key = hmac.new(self._secret, TX_CONTEXT + base, sha256).digest()
        rx_key = hmac.new(self._secret, RX_CONTEXT + base, sha256).digest()
        server_mac = _mac(self._secret, SERVER_CONTEXT, base)
        device_session = DeviceSession(self.vehicle_id, session, encoded(boot),
                                       encoded(device_nonce), tx_key, rx_key, base)
        return device_session, {"tipo": "dispositivo_autenticado_lab", "version": PROTOCOL,
                                "vehiculo": self.vehicle_id, "sesion": session,
                                "prueba_servidor": server_mac, "simulado": True}


def device_auth_reply(secret: bytes, challenge: dict, *, boot: bytes,
                      nonce_device: bytes) -> dict:
    """Ayudante de pruebas para cliente virtual; no incorpora transporte."""
    secret = check_key(secret)
    if (type(challenge) is not dict or challenge.get("tipo") != "desafio_dispositivo_lab"
            or challenge.get("version") != PROTOCOL or challenge.get("simulado") is not True
            or type(challenge.get("vehiculo")) is not int):
        raise LabDeviceProtocolError("Desafío incorrecto.")
    vehicle = challenge["vehiculo"]
    server_nonce = decoded(challenge.get("desafio"), NONCE_LEN)
    if (type(boot) is not bytes or len(boot) != BOOT_LEN
            or type(nonce_device) is not bytes or len(nonce_device) != BOOT_LEN):
        raise LabDeviceProtocolError("Identidad del arranque inválida.")
    context = struct.pack(">I", vehicle) + server_nonce + boot + nonce_device
    return {"tipo": "autenticar_dispositivo_lab", "version": PROTOCOL,
            "vehiculo": vehicle, "arranque": encoded(boot),
            "nonce_dispositivo": encoded(nonce_device),
            "prueba": _mac(secret, AUTH_CONTEXT, context), "simulado": True}


def verify_server_auth(secret: bytes, challenge: dict, reply: dict,
                       confirmation: dict) -> bytes:
    """El dispositivo también debe autenticar al servidor, no solo el TLS."""
    secret = check_key(secret)
    if (type(confirmation) is not dict or set(confirmation) !=
        {"tipo", "version", "vehiculo", "sesion", "prueba_servidor", "simulado"}
        or confirmation.get("tipo") != "dispositivo_autenticado_lab"
        or confirmation.get("version") != PROTOCOL or confirmation.get("simulado") is not True
        or confirmation.get("vehiculo") != challenge.get("vehiculo")):
        raise LabDeviceProtocolError("Confirmación del servidor inválida.")
    session = decoded(confirmation["sesion"], SESSION_LEN)
    context = (struct.pack(">I", challenge["vehiculo"]) + decoded(challenge["desafio"], NONCE_LEN)
               + decoded(reply["arranque"], BOOT_LEN) + decoded(reply["nonce_dispositivo"], BOOT_LEN) + session)
    _validate_mac(confirmation["prueba_servidor"], _mac(secret, SERVER_CONTEXT, context))
    return hmac.new(secret, RX_CONTEXT + context, sha256).digest()


class DeviceTelemetryVerifier:
    """Verifica telemetría *simulada*. Jamás devuelve confirmación física."""

    def __init__(self, session: DeviceSession):
        self._session = session
        self._last_counter = 0

    @property
    def safe_for_physical_control(self) -> bool:
        return False

    def verify(self, message: dict) -> int:
        if (type(message) is not dict or set(message) !=
            {"tipo", "sesion", "contador", "codigo_salida", "parada", "simulado", "firma"}
            or message["tipo"] != "telemetria_dispositivo_lab"
            or message["sesion"] != self._session.session_id
            or type(message["contador"]) is not int
            or message["contador"] != self._last_counter + 1
            or message["contador"] > UINT32_MAX
            or type(message["codigo_salida"]) is not int or message["codigo_salida"] != 0
            or message["parada"] != "neutral_virtual" or message["simulado"] is not True):
            raise LabDeviceProtocolError("Telemetría de laboratorio inválida.")
        body = {k: value for k, value in message.items() if k != "firma"}
        _validate_mac(message["firma"], _mac(self._session.telemetry_key,
                                               TELEMETRY_CONTEXT, canonical(body)))
        self._last_counter = message["contador"]
        return self._last_counter

    def confirmation(self, count: int) -> dict:
        body = {"tipo": "telemetria_recibida_lab", "sesion": self._session.session_id,
                "contador": count, "simulado": True}
        return {**body, "firma": _mac(self._session.command_key,
                                     ACK_CONTEXT, canonical(body))}


def make_virtual_telemetry(key: bytes, session_id: str, count: int) -> dict:
    body = {"tipo": "telemetria_dispositivo_lab", "sesion": session_id,
            "contador": count, "codigo_salida": 0, "parada": "neutral_virtual",
            "simulado": True}
    return {**body, "firma": _mac(key, TELEMETRY_CONTEXT, canonical(body))}
