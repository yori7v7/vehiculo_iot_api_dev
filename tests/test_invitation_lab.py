import pytest

from app.public_control.invitation_lab import GuestInvitationLab, InvitationDenied

ADMIN = "Admin-sesion-de-prueba-no-producion-1234567890"


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def step(self, n):
        self.t += n


@pytest.fixture
def demo():
    clock = Clock()
    control = GuestInvitationLab(ADMIN, clock=clock)
    return control, clock


def test_requires_supervisor_and_admin(demo):
    a, clock = demo
    with pytest.raises(InvitationDenied):
        a.issue_invitation(ADMIN)
    with pytest.raises(InvitationDenied):
        a.supervisor_heartbeat("1234")
    a.supervisor_heartbeat(ADMIN)
    with pytest.raises(InvitationDenied):
        a.issue_invitation("impostor")
    assert a.snapshot()["supervisor_active"]


def test_one_use_link_and_session(demo):
    a, clock = demo
    a.supervisor_heartbeat(ADMIN)
    link = a.issue_invitation(ADMIN)
    entry = a.redeem_invitation(link)
    assert entry.mode == "supervised" and entry.expires_in_s is None
    assert a.guest_allowed(entry.session_token)
    with pytest.raises(InvitationDenied):
        a.redeem_invitation(link)
    assert not a.guest_allowed("incorrecto")
    with pytest.raises(InvitationDenied):
        a.issue_invitation(ADMIN)


def test_indefinite_only_while_supervised(demo):
    a, c = demo
    a.supervisor_heartbeat(ADMIN)
    guest = a.redeem_invitation(a.issue_invitation(ADMIN)).session_token
    for _ in range(5):
        c.step(10)
        a.supervisor_heartbeat(ADMIN)
        assert a.guest_allowed(guest)
    c.step(15)
    assert not a.guest_allowed(guest)
    assert a.snapshot()["stop_required"]


def test_supervisor_timeout_fails_closed(demo):
    a, c = demo
    a.supervisor_heartbeat(ADMIN)
    guest = a.redeem_invitation(a.issue_invitation(ADMIN)).session_token
    c.step(15)
    assert not a.guest_allowed(guest)
    assert not a.snapshot()["guest_active"]


def test_manual_revoke_and_device_lost(demo):
    a, c = demo
    a.supervisor_heartbeat(ADMIN)
    guest = a.redeem_invitation(a.issue_invitation(ADMIN)).session_token
    a.revoke(ADMIN)
    assert not a.guest_allowed(guest)
    assert a.snapshot()["stop_required"]
    with pytest.raises(InvitationDenied):
        a.confirm_neutral_for_lab(ADMIN, signed_neutral_ack=False)
    with pytest.raises(InvitationDenied):
        a.issue_invitation(ADMIN)
    a.confirm_neutral_for_lab(ADMIN, signed_neutral_ack=True)
    a.supervisor_heartbeat(ADMIN)
    guest2 = a.redeem_invitation(a.issue_invitation(ADMIN)).session_token
    a.device_lost()
    assert not a.guest_allowed(guest2)
    with pytest.raises(InvitationDenied):
        a.issue_invitation(ADMIN)


def test_timed_turn_and_link_expiration(demo):
    a, c = demo
    a.supervisor_heartbeat(ADMIN)
    link = a.issue_invitation(ADMIN, mode="timed", turn_seconds=5, link_ttl_s=10)
    guest = a.redeem_invitation(link)
    c.step(5)
    assert not a.guest_allowed(guest.session_token)
    a.supervisor_heartbeat(ADMIN)
    a.confirm_neutral_for_lab(ADMIN, signed_neutral_ack=True)
    link = a.issue_invitation(ADMIN, link_ttl_s=3)
    c.step(3)
    with pytest.raises(InvitationDenied):
        a.redeem_invitation(link)


def test_replaced_link_invalidates_previous(demo):
    a, c = demo
    a.supervisor_heartbeat(ADMIN)
    old = a.issue_invitation(ADMIN)
    new = a.issue_invitation(ADMIN)
    with pytest.raises(InvitationDenied):
        a.redeem_invitation(old)
    assert a.guest_allowed(a.redeem_invitation(new).session_token)


def test_clock_rollback_fails_closed(demo):
    a, c = demo
    a.supervisor_heartbeat(ADMIN)
    guest = a.redeem_invitation(a.issue_invitation(ADMIN)).session_token
    c.step(-1)
    with pytest.raises(InvitationDenied):
        a.guest_allowed(guest)
    c.step(2)
    assert not a.guest_allowed(guest)


def test_bad_invite_options(demo):
    a, c = demo
    a.supervisor_heartbeat(ADMIN)
    with pytest.raises(ValueError):
        a.issue_invitation(ADMIN, mode="timed")
    with pytest.raises(ValueError):
        a.issue_invitation(ADMIN, mode="supervised", turn_seconds=10)
    with pytest.raises(ValueError):
        a.issue_invitation(ADMIN, link_ttl_s=600)


def test_no_new_guest_until_neutral_ack(demo):
    a, c = demo
    a.supervisor_heartbeat(ADMIN)
    first = a.redeem_invitation(a.issue_invitation(ADMIN)).session_token
    a.disconnect_admin()
    a.supervisor_heartbeat(ADMIN)
    with pytest.raises(InvitationDenied):
        a.issue_invitation(ADMIN)
    with pytest.raises(InvitationDenied):
        a.confirm_neutral_for_lab("intruso", signed_neutral_ack=True)
    a.confirm_neutral_for_lab(ADMIN, signed_neutral_ack=True)
    second = a.redeem_invitation(a.issue_invitation(ADMIN)).session_token
    assert not a.guest_allowed(first)
    assert a.guest_allowed(second)
