"""Contrato de invitaciones efímeras *sin despacho*, aislado del control real.

NO registrar este módulo como ruta HTTP ni integrarlo con motores. Quien lo
integre deberá autenticar a un administrador, observar presencia real y
solicitar STOP en el coordinador tras toda revocación / desconexión.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest
from math import isfinite
from secrets import token_urlsafe
from threading import RLock
from time import monotonic
from typing import Callable, Literal

Mode = Literal["supervised", "timed"]
SUPERVISOR_TIMEOUT = 15.0
MAX_INVITATION_TTL = 300


class InvitationDenied(Exception):
    """Acceso no autorizado, inválido o caducado."""


@dataclass(frozen=True)
class GuestAdmission:
    session_token: str
    mode: Mode
    expires_in_s: float | None


class GuestInvitationLab:
    """Un solo invitado, link un solo uso y presencia administrativa activa.

    El token administrador es una credencial *de sesión* independiente de la
    API key histórica. No es mecanismo HTTP; este contrato NO transmite nada.
    """

    def __init__(self, admin_session_token: str, *, clock: Callable[[], float] = monotonic):
        if type(admin_session_token) is not str or len(admin_session_token) < 32:
            raise ValueError("Se requiere una sesión administrativa independiente.")
        self._admin_hash = self._digest(admin_session_token)
        self._clock = clock
        self._lock = RLock()
        self._previous_now: float | None = None
        self._supervisor_until = 0.0
        self._invitation: tuple[bytes, float, Mode, int | None] | None = None
        self._guest_hash: bytes | None = None
        self._guest_mode: Mode | None = None
        self._guest_until: float | None = None
        self._generation = 0
        self._needs_stop = False

    @staticmethod
    def _digest(value: str) -> bytes:
        return sha256(value.encode("utf-8")).digest()

    def _time(self) -> float:
        now = self._clock()
        if type(now) not in (int, float) or not isfinite(now) or now < 0:
            self._invalidate()
            raise InvitationDenied("Reloj inválido; permisos cerrados.")
        if self._previous_now is not None and now < self._previous_now:
            self._invalidate()
            raise InvitationDenied("El reloj retrocedió; permisos cerrados.")
        self._previous_now = float(now)
        return float(now)

    def _admin(self, proof: str) -> None:
        if type(proof) is not str or not compare_digest(self._admin_hash, self._digest(proof)):
            raise InvitationDenied("Administrador no autorizado.")

    def _invalidate(self) -> None:
        if self._guest_hash is not None:
            self._needs_stop = True
        self._guest_hash = None
        self._guest_mode = None
        self._guest_until = None
        self._invitation = None
        self._generation += 1
        self._supervisor_until = 0

    def _expire(self, now: float) -> None:
        if self._invitation is not None and now >= self._invitation[1]:
            self._invitation = None
        if self._guest_hash is not None and (now >= self._supervisor_until or
                (self._guest_until is not None and now >= self._guest_until)):
            self._invalidate()

    def supervisor_heartbeat(self, admin_proof: str) -> None:
        with self._lock:
            self._admin(admin_proof)
            now = self._time()
            self._expire(now)
            self._supervisor_until = now + SUPERVISOR_TIMEOUT

    def issue_invitation(self, admin_proof: str, *, mode: Mode = "supervised",
                         link_ttl_s: int = 120, turn_seconds: int | None = None) -> str:
        """Invitación URL-fragment; servidor almacena solo su digest.

        Se exige supervisión *vigente* al emitir y canjear, no basta el link.
        """
        with self._lock:
            self._admin(admin_proof)
            now = self._time()
            self._expire(now)
            if not now < self._supervisor_until:
                raise InvitationDenied("Se requiere supervisión vigente.")
            if mode not in ("supervised", "timed") or type(link_ttl_s) is not int or not 1 <= link_ttl_s <= MAX_INVITATION_TTL:
                raise ValueError("Modo o caducidad de invitación inválidos.")
            if mode == "timed":
                if type(turn_seconds) is not int or not 1 <= turn_seconds <= 300:
                    raise ValueError("Duración temporal inválida.")
            elif turn_seconds is not None:
                raise ValueError("El turno supervisado no admite duración fija.")
            if self._needs_stop:
                raise InvitationDenied("Se requiere confirmar neutro firmado antes de otro turno.")
            if self._guest_hash is not None:
                raise InvitationDenied("Ya existe un invitado activo.")
            link_token = token_urlsafe(32)
            self._invitation = (self._digest(link_token), now + link_ttl_s, mode, turn_seconds)
            return link_token

    def redeem_invitation(self, link_token: str) -> GuestAdmission:
        with self._lock:
            now = self._time()
            self._expire(now)
            if type(link_token) is not str or not 32 <= len(link_token) <= 128:
                raise InvitationDenied("Invitación inválida.")
            entry = self._invitation
            if entry is None or self._needs_stop or self._guest_hash is not None or now >= self._supervisor_until or not compare_digest(entry[0], self._digest(link_token)):
                raise InvitationDenied("Invitación expirada o revocada.")
            self._invitation = None  # Canje único y atómico
            session_token = token_urlsafe(32)
            self._guest_hash = self._digest(session_token)
            self._guest_mode = entry[2]
            self._guest_until = now + entry[3] if entry[3] is not None else None
            self._generation += 1
            return GuestAdmission(session_token, entry[2], entry[3])

    def guest_allowed(self, guest_session_token: str) -> bool:
        """Solo admisión lógica. No concede movimiento físico."""
        with self._lock:
            now = self._time()
            self._expire(now)
            return (type(guest_session_token) is str and self._guest_hash is not None
                    and now < self._supervisor_until
                    and compare_digest(self._guest_hash, self._digest(guest_session_token)))

    def revoke(self, admin_proof: str) -> None:
        with self._lock:
            self._admin(admin_proof)
            self._time()
            self._invalidate()

    def disconnect_admin(self) -> None:
        with self._lock:
            self._invalidate()

    def device_lost(self) -> None:
        with self._lock:
            self._invalidate()

    def snapshot(self) -> dict:
        with self._lock:
            now = self._time()
            self._expire(now)
            return {
                "guest_active": self._guest_hash is not None,
                "mode": self._guest_mode,
                "supervisor_active": now < self._supervisor_until,
                "supervisor_remaining_s": max(0, self._supervisor_until - now),
                "generation": self._generation,
                "stop_required": self._needs_stop,
                "simulated_only": True,
            }

    def confirm_neutral_for_lab(self, admin_proof: str, *, signed_neutral_ack: bool) -> None:
        """La *capa de transporte* debe verificar un ACK HMAC antes de llamar.

        Esto desbloquea un nuevo turno LOGICO únicamente en laboratorio,
        nunca afirma que se detuvieron mecánicamente los motores.
        """
        with self._lock:
            self._admin(admin_proof)
            self._time()
            if signed_neutral_ack is not True:
                raise InvitationDenied("No existe confirmación de neutro firmado.")
            self._needs_stop = False
