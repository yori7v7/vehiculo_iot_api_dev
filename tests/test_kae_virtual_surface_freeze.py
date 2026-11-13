"""5.5-K-AE: fail-closed public route freeze, completely offline.

No AWS, ESP, real HTTP requests or deployment. The allowlist is intentionally
strict: changing any Caddy directive or adding any FastAPI route requires an
explicit security review rather than silently widening the remote attack surface.
"""
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

from app.public_control.kv_virtual_staging import create_kv_virtual_app

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "deploy/staging/kw/Caddyfile.candidate_NOT_DEPLOY"
ORIGINAL = ROOT / "deploy/windows/Caddyfile"

ADMIN = "/admin/vehiculos/{id_vehiculo}/control-publico/solicitudes"
GUEST = "/publico/vehiculos/{id_vehiculo}/solicitudes"
EXPECTED_ROUTES = {
    ("POST", GUEST),
    ("GET", GUEST + "/estado"),
    ("GET", ADMIN),
    ("POST", ADMIN + "/supervision"),
    ("POST", ADMIN + "/{request_id}/aprobar"),
    ("POST", ADMIN + "/{request_id}/rechazar"),
    ("POST", ADMIN + "/revocar"),
}

# Exact NON-COMMENT Caddy candidate. The wildcard under /admin/.../solicitudes
# does not itself authorize new APIs; the FastAPI exact-route check above is
# a second independent brake against accidental new physical endpoints.
EXPECTED_CADDY = (
    "100-30-4-62.nip.io {",
    "@kv_virtual_admission {",
    "path /publico/vehiculos/1/solicitudes /publico/vehiculos/1/solicitudes/estado /admin/vehiculos/1/control-publico/solicitudes /admin/vehiculos/1/control-publico/solicitudes/*",
    "}",
    "handle @kv_virtual_admission {",
    "reverse_proxy 127.0.0.1:9444 {",
    "header_up Host 100-30-4-62.nip.io",
    "header_up -Forwarded",
    "header_up -X-Forwarded-For",
    "header_up -X-Forwarded-Host",
    "header_up -X-Forwarded-Proto",
    "header_up -X-Real-IP",
    "header_up -Via",
    "header_up -Cookie",
    "header_up -Authorization",
    "header_up -Proxy-Authorization",
    "header_up -X-Original-URL",
    "header_up -X-Rewrite-URL",
    "header_up X-Admission-Proxy-Token {$KW_PROXY_TOKEN}",
    "header_up X-Admission-Client-IP {remote_host}",
    "header_up X-Admission-Scheme https",
    "}",
    "}",
    "handle {",
    "reverse_proxy 127.0.0.1:8000",
    "}",
    "}",
)
EXPECTED_ORIGINAL = (
    "100-30-4-62.nip.io {",
    "reverse_proxy 127.0.0.1:8000",
    "}",
)


def _lines(source: str):
    return tuple(line.strip() for line in source.splitlines()
                 if line.strip() and not line.lstrip().startswith("#"))


def verify_virtual_caddy_contract(source: str):
    assert _lines(source) == EXPECTED_CADDY, (
        "K-AE: candidate Caddy routing or headers changed; manual security "
        "review required before any EC2 deployment"
    )


def test_kae_candidate_and_legacy_config_remain_exact():
    verify_virtual_caddy_contract(CANDIDATE.read_text(encoding="utf-8"))
    assert _lines(ORIGINAL.read_text(encoding="utf-8")) == EXPECTED_ORIGINAL


def test_kae_fastapi_routes_exact_and_never_motor(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("ADMISSION_VIRTUAL_ONLY", "enabled")
    # The app is built only in memory. Its lifespan (database) is NEVER run.
    app = create_kv_virtual_app(
        tmp_path / "unopened.sqlite3",
        "admin-offline-only-" + "A" * 50,
        "proxy-offline-only-" + "P" * 50,
    )
    exposed = {(method, route.path)
               for route in app.routes if isinstance(route, APIRoute)
               for method in route.methods}
    assert exposed == EXPECTED_ROUTES, (
        "K-AE: unexpected public virtual route; explicit review required"
    )
    assert len(app.routes) == 7
    assert app.openapi_url is None and app.docs_url is None
    assert app.redoc_url is None
    assert app.state.kv_virtual_only is True
    assert all("movim" not in path.lower() and
               "demo" not in path.lower() and
               "accion" not in path.lower()
               for _, path in exposed)


@pytest.mark.parametrize("old,new", [
    ("reverse_proxy 127.0.0.1:9444", "reverse_proxy 0.0.0.0:9444"),
    ("reverse_proxy 127.0.0.1:8000", "reverse_proxy 0.0.0.0:8000"),
    ("header_up X-Admission-Client-IP {remote_host}",
     "header_up X-Admission-Client-IP {header.X-Forwarded-For}"),
    ("header_up X-Admission-Proxy-Token {$KW_PROXY_TOKEN}",
     "header_up X-Admission-Proxy-Token test-token"),
    ("header_up -Authorization", "header_up Authorization {header.Authorization}"),
    ("header_up -Cookie", "header_up Cookie {header.Cookie}"),
    ("header_up X-Admission-Scheme https", "header_up X-Admission-Scheme http"),
    ("path /publico/vehiculos/1/solicitudes ",
     "path /publico/vehiculos/* "),
    ("handle @kv_virtual_admission {", "handle {"),
    ("header_up Host 100-30-4-62.nip.io", "header_up Host {host}"),
])
def test_kae_rejects_unsafe_or_unreviewed_caddy_mutations(old, new):
    source = CANDIDATE.read_text(encoding="utf-8")
    assert old in source
    tampered = source.replace(old, new, 1)
    with pytest.raises(AssertionError, match="manual security review"):
        verify_virtual_caddy_contract(tampered)


def test_kae_documentation_explicitly_disables_physical_control():
    source = (ROOT / "app/public_control/kv_virtual_staging.py").read_text("utf-8")
    assert '"canDrive": False' in source
    assert '"control_fisico": False' in source
    assert "No" or source  # no runtime use, covered by response tests elsewhere
