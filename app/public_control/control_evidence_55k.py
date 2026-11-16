"""Evidencia de control 55-K obtenida del servidor K-R.

Solo virtual. No aceptar role ni device_authenticated de JSON HTTP.
El futuro despacho debe revalidar bajo el mismo coordinador que revoca.
"""
from app.public_control.control_permissions_55k import (
    ADMIN, GUEST, ServerEvidence55K, can_control,
)
from app.public_control.kr_ticket_ledger import (
    KRTicketDenied, KRTicketLedger,
)
from app.public_control.kq_restart_fence import FenceRejected
from app.public_control.repository import StoreUnavailable


def can_dispatch_virtual_55k(
    ledger: KRTicketLedger,
    *,
    server_role: str,
    credential: str,
    action: object,
    authenticated_device: bool,
) -> bool:
    """Comprobar datos K-R reales, sin conceder control fisico."""
    if (type(ledger) is not KRTicketLedger
            or type(server_role) is not str
            or type(credential) is not str
            or type(authenticated_device) is not bool
            or not authenticated_device):
        return False

    try:
        if server_role == GUEST:
            verified = ledger.verify_virtual_action(credential)
        elif server_role == ADMIN:
            verified = ledger.verify_admin_virtual_action(credential)
        else:
            return False
    except (KRTicketDenied, FenceRejected, StoreUnavailable):
        return False

    if verified is not True:
        return False

    evidence = ServerEvidence55K(
        role=server_role,
        exclusive_holder=server_role,
        identity_verified=True,
        lease_valid=True,
        supervision_valid=True,
        device_authenticated=authenticated_device,
    )

    return can_control(evidence, action)
