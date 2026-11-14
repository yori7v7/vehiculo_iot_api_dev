"""K-A: admission model for one public URL; no HTTP, AWS, WSS or motors.

An anonymous visitor may *request* access but cannot gain a guest turn until
an authorized supervisor approves that exact browser ticket. This module is
in-memory and disposable; it is not a production service or physical interlock.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest
from math import isfinite
import re
from secrets import token_urlsafe
from time import monotonic
from typing import Callable, Literal
from uuid import uuid4

from app.public_control.invitation_lab import GuestInvitationLab, InvitationDenied


class AdmissionDenied(Exception):
    pass


_CLIENT_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z", re.ASCII)


@dataclass
class BrowserTicket:
    request_id: str
    secret_hash: bytes
    display_code: str
    expires_at: float
    status: Literal["waiting", "approved", "rejected"] = "waiting"
    guest_token: str | None = None
    idempotency_hash: bytes | None = None
    client_identity_hash: bytes | None = None


class SingleLinkAdmissionLab:
    """Isolated admission queue. Never sends movement or authorizes legacy API."""

    def __init__(self, admin_session_token: str, *, clock: Callable[[], float] = monotonic,
                 pending_seconds: int = 120, max_pending: int = 5):
        if type(admin_session_token) is not str or len(admin_session_token) < 32:
            raise ValueError("Se requiere un token administrativo independiente.")
        if type(pending_seconds) is not int or not 10 <= pending_seconds <= 300:
            raise ValueError("Vigencia de espera inválida.")
        if type(max_pending) is not int or not 1 <= max_pending <= 20:
            raise ValueError("Capacidad de solicitudes inválida.")
        self._admin_hash = self._hash(admin_session_token)
        self._admission = GuestInvitationLab(admin_session_token, clock=clock)
        self._clock = clock
        self._pending_seconds = pending_seconds
        self._max_pending = max_pending
        self._requests: dict[str, BrowserTicket] = {}
        self._last_time: float | None = None

    @staticmethod
    def _hash(value: str) -> bytes:
        return sha256(value.encode("utf-8")).digest()

    def _time(self) -> float:
        now = self._clock()
        if type(now) not in (int, float) or not isfinite(now) or now < 0:
            self._revoke_all()
            raise AdmissionDenied("Reloj inválido.")
        if self._last_time is not None and now < self._last_time:
            self._revoke_all()
            raise AdmissionDenied("Reloj retrocedió.")
        self._last_time = float(now)
        return float(now)

    def _admin(self, proof: str):
        if type(proof) is not str or not compare_digest(self._hash(proof), self._admin_hash):
            raise AdmissionDenied("Permiso administrativo inválido.")

    def _revoke_all(self) -> None:
        self._admission.device_lost()
        for ticket in self._requests.values():
            if ticket.status != "rejected":
                ticket.status = "rejected"
                ticket.guest_token = None

    def _cleanup(self, now: float) -> None:
        for request_id, ticket in list(self._requests.items()):
            if ticket.status == "waiting" and now >= ticket.expires_at:
                ticket.status = "rejected"
            # Release only terminal tickets; do not delete approved sessions here.
            if ticket.status == "rejected" and now >= ticket.expires_at + 60:
                del self._requests[request_id]

    def arrive(self) -> dict:
        """Called automatically by opening the single official URL.

        Caller must rate-limit by origin/IP/device and protect against CSRF
        before exposing as HTTP. This isolated model has no network access.
        """
        now = self._time()
        self._cleanup(now)
        waiting = sum(t.status == "waiting" for t in self._requests.values())
        if waiting >= self._max_pending:
            raise AdmissionDenied("Demasiadas solicitudes pendientes.")
        request_id = str(uuid4())
        browser_secret = token_urlsafe(32)
        display_code = request_id.split("-")[0].upper()
        self._requests[request_id] = BrowserTicket(request_id, self._hash(browser_secret),
                                                   display_code, now + self._pending_seconds)
        return {"request_id": request_id, "browser_secret": browser_secret,
                "display_code": display_code, "estado": "esperando_autorizacion"}

    def arrive_idempotent(
        self, *, idempotency_key: str, browser_secret: str, client_identity: str,
    ) -> dict:
        """K-I/K-T LAB: browser-owned retry pair uses the SAME KC gate and lock.

        Not persistent across restart, not a public production API. Replays
        only recover the original browser secret; they never issue a drive
        token. A changed secret/identity, expired ticket or reused secret fails
        closed rather than creating a different authorization on retry.
        """
        if (type(idempotency_key) is not str or
                _CLIENT_TOKEN.fullmatch(idempotency_key) is None or
                type(browser_secret) is not str or
                _CLIENT_TOKEN.fullmatch(browser_secret) is None or
                idempotency_key == browser_secret or
                type(client_identity) is not str or not 1 <= len(client_identity) <= 256):
            raise AdmissionDenied("Par de reintento invalido.")
        now = self._time()
        self._cleanup(now)
        key_hash = self._hash(idempotency_key)
        secret_hash = self._hash(browser_secret)
        client_hash = self._hash(client_identity)
        for ticket in self._requests.values():
            if ticket.idempotency_hash is not None and compare_digest(
                    ticket.idempotency_hash, key_hash):
                if (ticket.client_identity_hash is None or
                        not compare_digest(ticket.client_identity_hash, client_hash) or
                        not compare_digest(ticket.secret_hash, secret_hash) or
                        ticket.status != "waiting" or now >= ticket.expires_at):
                    raise AdmissionDenied("Reintento no vigente o no autorizado.")
                return {
                    "request_id": ticket.request_id,
                    "browser_secret": browser_secret,
                    "display_code": ticket.display_code,
                    "estado": "esperando_autorizacion",
                    "idempotent_replay": True,
                }
            if compare_digest(ticket.secret_hash, secret_hash):
                raise AdmissionDenied("Sesion del navegador ya utilizada.")
        waiting = sum(t.status == "waiting" for t in self._requests.values())
        if waiting >= self._max_pending:
            raise AdmissionDenied("Demasiadas solicitudes pendientes.")
        request_id = str(uuid4())
        display_code = request_id.split("-")[0].upper()
        self._requests[request_id] = BrowserTicket(
            request_id, secret_hash, display_code, now + self._pending_seconds,
            idempotency_hash=key_hash, client_identity_hash=client_hash,
        )
        return {
            "request_id": request_id, "browser_secret": browser_secret,
            "display_code": display_code, "estado": "esperando_autorizacion",
            "idempotent_replay": False,
        }

    def _ticket(self, browser_secret: str) -> BrowserTicket:
        if type(browser_secret) is not str or not 32 <= len(browser_secret) <= 128:
            raise AdmissionDenied("Sesión de navegador inválida.")
        hash_value = self._hash(browser_secret)
        for ticket in self._requests.values():
            if compare_digest(ticket.secret_hash, hash_value):
                return ticket
        raise AdmissionDenied("Sesión de navegador desconocida.")

    def visitor_status(self, browser_secret: str) -> dict:
        now = self._time()
        self._cleanup(now)
        ticket = self._ticket(browser_secret)
        status = ticket.status
        guest_token = None
        if status == "approved":
            if ticket.guest_token is None or not self._admission.guest_allowed(ticket.guest_token):
                status = ticket.status = "rejected"
                ticket.guest_token = None
            else:
                guest_token = ticket.guest_token
        return {"estado": "autorizado" if status == "approved" else
                "esperando_autorizacion" if status == "waiting" else "revocado_o_caducado",
                "display_code": ticket.display_code,
                "guest_token": guest_token,
                "control_fisico": False}

    def supervisor_heartbeat(self, admin_proof: str) -> None:
        self._admin(admin_proof)
        self._time()
        self._admission.supervisor_heartbeat(admin_proof)

    def pending(self, admin_proof: str) -> list[dict]:
        self._admin(admin_proof)
        now = self._time()
        self._cleanup(now)
        return [{"request_id": t.request_id, "display_code": t.display_code,
                 "vence_en_seg": round(t.expires_at - now)} for t in self._requests.values()
                if t.status == "waiting"]

    def approve(self, admin_proof: str, request_id: str, *, mode: Literal["supervised", "timed"] = "supervised",
                turn_seconds: int | None = None) -> None:
        self._admin(admin_proof)
        now = self._time()
        self._cleanup(now)
        ticket = self._requests.get(request_id)
        if ticket is None or ticket.status != "waiting" or now >= ticket.expires_at:
            raise AdmissionDenied("La solicitud no existe o ya caducó.")
        try:
            invitation = self._admission.issue_invitation(admin_proof, mode=mode,
                                                          turn_seconds=turn_seconds, link_ttl_s=10)
            admitted = self._admission.redeem_invitation(invitation)
        except (InvitationDenied, ValueError) as exc:
            raise AdmissionDenied("No es posible aprobar sin supervisión o neutro válido.") from exc
        ticket.status = "approved"
        ticket.guest_token = admitted.session_token

    def reject(self, admin_proof: str, request_id: str) -> None:
        self._admin(admin_proof)
        self._time()
        ticket = self._requests.get(request_id)
        if ticket is None or ticket.status != "waiting":
            raise AdmissionDenied("Solicitud no pendiente.")
        ticket.status = "rejected"

    def revoke(self, admin_proof: str) -> None:
        self._admin(admin_proof)
        self._time()
        self._admission.revoke(admin_proof)
        for ticket in self._requests.values():
            if ticket.status == "approved":
                ticket.status = "rejected"
                ticket.guest_token = None

    def administrator_gone(self) -> None:
        self._revoke_all()

    def device_lost(self) -> None:
        self._revoke_all()

    def neutral_confirmed_by_transport_for_lab(self, admin_proof: str, signed_neutral_ack: bool) -> None:
        """Only the trusted transport can call this after HMAC ACK verification.

        Never offer as a public HTTP parameter, never equate with motor stop.
        """
        self._admin(admin_proof)
        self._time()
        self._admission.confirm_neutral_for_lab(admin_proof, signed_neutral_ack=signed_neutral_ack)

    def snapshot(self) -> dict:
        now = self._time()
        self._cleanup(now)
        return {"pendientes": sum(t.status == "waiting" for t in self._requests.values()),
                **self._admission.snapshot(), "control_fisico": False}
