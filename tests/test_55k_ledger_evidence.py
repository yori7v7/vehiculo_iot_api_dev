"""55-K: autoridad de roles probada con SQLite K-R real."""
import tempfile
import unittest
from pathlib import Path

from app.public_control.kq_restart_fence import KQRestartFence
from app.public_control.kr_ticket_ledger import KRTicketLedger
from app.public_control.control_evidence_55k import (
    can_dispatch_virtual_55k,
)
from app.public_control.control_permissions_55k import (
    ADMIN, GUEST, OBSERVER, CONTROL_CODES, SOFTWARE_ACTIONS,
)

PROOF = "TEST-ADMIN-55K-" + "A" * 48


class TestEvidence55K(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        path = Path(self.temp.name) / "kv_55k.sqlite3"
        self.now = 1000.0
        self.fence = KQRestartFence(path)
        epoch = self.fence.start()
        self.ledger = KRTicketLedger(
            self.fence, epoch, PROOF,
            clock=lambda: self.now
        )
        self.ledger.prepare()

    def tearDown(self):
        self.ledger.close()
        self.fence.close()
        self.temp.cleanup()

    def allowed(self, role, credential, action,
                device=True):
        return can_dispatch_virtual_55k(
            self.ledger,
            server_role=role,
            credential=credential,
            action=action,
            authenticated_device=device,
        )

    def approve_guest(self):
        ticket = self.ledger.request("203.0.113.25")
        self.ledger.supervise(PROOF)
        self.ledger.approve_virtual(
            PROOF, ticket["request_id"],
            seconds=120, mode="timed"
        )
        return ticket["browser_secret"]

    def test_no_supervision_no_controller(self):
        self.assertFalse(self.allowed(ADMIN, PROOF, 1))

    def test_admin_controls_only_when_unoccupied(self):
        self.ledger.supervise(PROOF)
        for action in CONTROL_CODES | SOFTWARE_ACTIONS:
            self.assertTrue(
                self.allowed(ADMIN, PROOF, action), action
            )

    def test_guest_gets_same_controls(self):
        secret = self.approve_guest()
        for action in CONTROL_CODES | SOFTWARE_ACTIONS:
            self.assertTrue(
                self.allowed(GUEST, secret, action), action
            )

    def test_guest_occupies_exclusive_turn(self):
        secret = self.approve_guest()
        self.assertTrue(self.allowed(GUEST, secret, 9))
        self.assertFalse(self.allowed(ADMIN, PROOF, 9))

    def test_wrong_credentials_and_observer_rejected(self):
        secret = self.approve_guest()
        self.assertFalse(
            self.allowed(GUEST, "invalid", 128)
        )
        self.assertFalse(
            self.allowed(ADMIN, "invalid", 128)
        )
        self.assertFalse(
            self.allowed(OBSERVER, secret, 0)
        )
        self.assertFalse(
            self.allowed(GUEST, secret, 1, device=False)
        )

    def test_revocation_disables_guest(self):
        secret = self.approve_guest()
        self.assertTrue(self.allowed(GUEST, secret, 1))
        self.ledger.revoke(PROOF)
        self.assertFalse(self.allowed(GUEST, secret, 1))
        self.assertFalse(self.allowed(ADMIN, PROOF, 1))

    def test_supervision_timeout_disables_control(self):
        secret = self.approve_guest()
        self.now += 16
        self.assertFalse(self.allowed(GUEST, secret, 1))
        self.assertFalse(self.allowed(ADMIN, PROOF, 1))

    def test_guest_expiry_not_resurrected(self):
        secret = self.approve_guest()
        self.now += 121
        self.ledger.supervise(PROOF)
        self.assertFalse(self.allowed(GUEST, secret, 1))

    def test_invalid_actions_and_device_state(self):
        self.ledger.supervise(PROOF)
        for action in (3, 255, True, "aprobar", "revocar"):
            self.assertFalse(self.allowed(ADMIN, PROOF, action))
        self.assertFalse(self.allowed(ADMIN, PROOF, 1, device=False))
        self.assertFalse(can_dispatch_virtual_55k(
            self.ledger, server_role=ADMIN, credential=PROOF,
            action=1, authenticated_device=1,
        ))


if __name__ == "__main__":
    unittest.main()
