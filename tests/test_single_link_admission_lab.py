import pytest

from app.public_control.single_link_admission_lab import SingleLinkAdmissionLab, AdmissionDenied

ADMIN = "Admin-sesion-ficticia-solo-tests-1234567890"


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def step(self, seconds):
        self.t += seconds


@pytest.fixture
def gate():
    clock = Clock()
    return SingleLinkAdmissionLab(ADMIN, clock=clock), clock


def test_one_url_visitor_waits_until_approved(gate):
    g, c = gate
    visitor = g.arrive()
    assert visitor['estado'] == 'esperando_autorizacion'
    assert g.visitor_status(visitor['browser_secret'])['guest_token'] is None
    with pytest.raises(AdmissionDenied):
        g.approve(ADMIN, visitor['request_id'])
    g.supervisor_heartbeat(ADMIN)
    g.approve(ADMIN, visitor['request_id'])
    result = g.visitor_status(visitor['browser_secret'])
    assert result['estado'] == 'autorizado' and result['guest_token'] and not result['control_fisico']


def test_no_admin_or_other_browser_can_control(gate):
    g, c = gate
    v = g.arrive()
    with pytest.raises(AdmissionDenied):
        g.pending('incorrecto')
    with pytest.raises(AdmissionDenied):
        g.visitor_status('incorrecto')
    with pytest.raises(AdmissionDenied):
        g.approve('incorrecto', v['request_id'])
    assert 'browser_secret' not in str(g.pending(ADMIN))


def test_guest_supervision_heartbeat_and_timeout(gate):
    g, c = gate
    v = g.arrive()
    g.supervisor_heartbeat(ADMIN)
    g.approve(ADMIN, v['request_id'])
    for _ in range(3):
        c.step(10)
        g.supervisor_heartbeat(ADMIN)
        assert g.visitor_status(v['browser_secret'])['estado'] == 'autorizado'
    c.step(15)
    assert g.visitor_status(v['browser_secret'])['estado'] == 'revocado_o_caducado'
    assert g.snapshot()['stop_required']


def test_approval_is_exclusive_and_requires_neutral_before_next(gate):
    g, c = gate
    g.supervisor_heartbeat(ADMIN)
    a, b = g.arrive(), g.arrive()
    g.approve(ADMIN, a['request_id'])
    with pytest.raises(AdmissionDenied):
        g.approve(ADMIN, b['request_id'])
    g.revoke(ADMIN)
    assert g.visitor_status(a['browser_secret'])['estado'] == 'revocado_o_caducado'
    with pytest.raises(AdmissionDenied):
        g.approve(ADMIN, b['request_id'])
    with pytest.raises(Exception):
        g.neutral_confirmed_by_transport_for_lab(ADMIN, False)
    g.neutral_confirmed_by_transport_for_lab(ADMIN, True)
    g.supervisor_heartbeat(ADMIN)
    g.approve(ADMIN, b['request_id'])
    assert g.visitor_status(b['browser_secret'])['estado'] == 'autorizado'


def test_pending_expiry_reject_and_limit(gate):
    g, c = gate
    v = g.arrive()
    g.reject(ADMIN, v['request_id'])
    assert g.visitor_status(v['browser_secret'])['estado'] == 'revocado_o_caducado'
    v2 = g.arrive()
    c.step(120)
    assert g.visitor_status(v2['browser_secret'])['estado'] == 'revocado_o_caducado'
    with pytest.raises(AdmissionDenied):
        g.approve(ADMIN, v2['request_id'])
    for i in range(5):
        g.arrive()
    with pytest.raises(AdmissionDenied):
        g.arrive()


def test_device_lost_closes_approved_session(gate):
    g, c = gate
    v = g.arrive()
    g.supervisor_heartbeat(ADMIN)
    g.approve(ADMIN, v['request_id'])
    g.device_lost()
    assert g.visitor_status(v['browser_secret'])['estado'] == 'revocado_o_caducado'
    assert g.snapshot()['stop_required']


def test_timed_mode_expires_without_javascript_poll(gate):
    g, c = gate
    v = g.arrive()
    g.supervisor_heartbeat(ADMIN)
    g.approve(ADMIN, v['request_id'], mode='timed', turn_seconds=5)
    c.step(5)
    assert g.visitor_status(v['browser_secret'])['estado'] == 'revocado_o_caducado'


def test_admin_departure_fail_closed(gate):
    g, c = gate
    v = g.arrive()
    g.supervisor_heartbeat(ADMIN)
    g.approve(ADMIN, v['request_id'])
    g.administrator_gone()
    assert g.visitor_status(v['browser_secret'])['estado'] == 'revocado_o_caducado'
    with pytest.raises(AdmissionDenied):
        g.approve(ADMIN, g.arrive()['request_id'])


def test_clock_rollback_fails_closed(gate):
    g, c = gate
    v = g.arrive()
    g.supervisor_heartbeat(ADMIN)
    g.approve(ADMIN, v['request_id'])
    c.step(-1)
    with pytest.raises(AdmissionDenied):
        g.visitor_status(v['browser_secret'])
    c.step(2)
    assert g.visitor_status(v['browser_secret'])['estado'] == 'revocado_o_caducado'
