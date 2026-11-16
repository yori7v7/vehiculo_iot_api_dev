"""Pruebas de permisos 55-K, sin red ni hardware."""
import unittest

from app.public_control.control_permissions_55k import (
    ADMIN, GUEST, OBSERVER,
    CONTROL_CODES, SOFTWARE_ACTIONS,
    ServerEvidence55K,
    can_control, can_manage_requests, can_monitor,
)


def evidence(role, *, holder=None, identity=True,
             lease=True, supervision=True, device=True):
    return ServerEvidence55K(
        role=role,
        exclusive_holder=holder,
        identity_verified=identity,
        lease_valid=lease,
        supervision_valid=supervision,
        device_authenticated=device,
    )


class TestControlPermissions55K(unittest.TestCase):

    def test_guest_has_all_vehicle_functions(self):
        guest = evidence(GUEST, holder=GUEST)
        for action in CONTROL_CODES | SOFTWARE_ACTIONS:
            self.assertTrue(can_control(guest, action), action)

    def test_admin_has_same_vehicle_functions(self):
        admin = evidence(ADMIN, holder=ADMIN)
        for action in CONTROL_CODES | SOFTWARE_ACTIONS:
            self.assertTrue(can_control(admin, action), action)

    def test_guest_cannot_manage_requests(self):
        self.assertFalse(
            can_manage_requests(evidence(GUEST, holder=GUEST))
        )

    def test_admin_can_manage_without_taking_guest_turn(self):
        admin = evidence(ADMIN, holder=GUEST)
        self.assertTrue(can_manage_requests(admin))
        self.assertFalse(can_control(admin, 1))

    def test_observer_monitors_but_never_controls(self):
        viewer = evidence(OBSERVER, holder=OBSERVER)
        self.assertTrue(can_monitor(OBSERVER))
        self.assertFalse(can_control(viewer, 0))
        self.assertFalse(can_control(viewer, 128))
        self.assertFalse(can_manage_requests(viewer))

    def test_guest_and_admin_do_not_compete(self):
        active_guest = evidence(GUEST, holder=GUEST)
        admin = evidence(ADMIN, holder=GUEST)
        self.assertTrue(can_control(active_guest, 9))
        self.assertFalse(can_control(admin, 9))

    def test_revoked_expired_or_unsupervised_denied(self):
        for condition in (
            {"lease": False},
            {"supervision": False},
            {"device": False},
            {"identity": False},
        ):
            actor = evidence(GUEST, holder=GUEST, **condition)
            self.assertFalse(can_control(actor, 1))
            self.assertFalse(can_control(actor, 128))
            self.assertFalse(can_control(actor, "demo_programada"))

    def test_no_holder_means_no_control(self):
        self.assertFalse(can_control(evidence(ADMIN), 1))
        self.assertFalse(can_control(evidence(GUEST), 1))

    def test_unknown_actions_rejected(self):
        actor = evidence(GUEST, holder=GUEST)
        for action in (3, 255, True, None, "aprobar", "revocar"):
            self.assertFalse(can_control(actor, action))

    def test_all_roles_can_monitor(self):
        for role in (ADMIN, GUEST, OBSERVER):
            self.assertTrue(can_monitor(role))
        self.assertFalse(can_monitor("desconocido"))


if __name__ == "__main__":
    unittest.main()
