"""55-K: politica aislada de roles, sin despacho ni GPIO.

La evidencia debe provenir del servidor, NO del cuerpo HTTP ni del navegador.
Esta politica no autentica usuarios, no concede turnos y no activa motores.
"""
from dataclasses import dataclass

ADMIN = "administrador"
GUEST = "invitado"
OBSERVER = "observador"

DIRECTIONS = frozenset((1, 2, 4, 5, 6, 8, 9, 10))
AUXILIARIES = frozenset((16, 32, 128))
ORIGINAL_DEMO = 64

CONTROL_CODES = DIRECTIONS | AUXILIARIES | {0, ORIGINAL_DEMO}
SOFTWARE_ACTIONS = frozenset(("demo_programada", "cancelar_demo"))


@dataclass(frozen=True)
class ServerEvidence55K:
    role: str
    exclusive_holder: str | None
    identity_verified: bool
    lease_valid: bool
    supervision_valid: bool
    device_authenticated: bool


def can_monitor(role: str) -> bool:
    return role in (ADMIN, GUEST, OBSERVER)


def can_manage_requests(evidence: ServerEvidence55K) -> bool:
    return (
        evidence.role == ADMIN
        and evidence.identity_verified is True
    )


def can_control(evidence: ServerEvidence55K, action: object) -> bool:
    # El sistema de parada de emergencia es independiente de
    # los permisos para emitir ordenes de usuario.
    valid_action = (
        (type(action) is int and action in CONTROL_CODES)
        or (type(action) is str and action in SOFTWARE_ACTIONS)
    )

    return (
        valid_action
        and evidence.role in (ADMIN, GUEST)
        and evidence.exclusive_holder == evidence.role
        and evidence.identity_verified is True
        and evidence.lease_valid is True
        and evidence.supervision_valid is True
        and evidence.device_authenticated is True
    )
