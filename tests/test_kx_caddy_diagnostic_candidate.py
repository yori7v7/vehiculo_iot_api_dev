"""K-X: politica propuesta de Caddy, NO instala servicios ni abre sockets.

Estos son controles de contrato estatico, NO una prueba de Caddy activo.
Falta validar con el binario Caddy real antes de desplegar.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROPOSED = ROOT / "deploy/staging/kw/Caddyfile.kx_diagnostic_NOT_DEPLOY"
LEGACY = ROOT / "deploy/windows/Caddyfile"

KX_BASE = "/publico/vehiculos/1/solicitudes"
ADMIN_BASE = "/admin/vehiculos/1/control-publico/solicitudes"
WSS_PATH = "/ws/kx-diagnostico/1"


def directives(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def match_path(path: str, rule: str) -> bool:
    return path.startswith(rule[:-1]) if rule.endswith("*") else path == rule


def modeled_policy(method: str, path: str, *, upgrade: bool = False) -> str:
    """Modelo de prioridades para detectar regresiones de rutas Caddy."""
    if any(match_path(path, x) for x in (
        WSS_PATH, KX_BASE, KX_BASE + "/*", ADMIN_BASE, ADMIN_BASE + "/*"
    )):
        return "kx-9444"
    if match_path(path, "/ws") or match_path(path, "/ws/*"):
        return "deny-ws"
    if upgrade:
        return "deny-upgrade"
    if method in {"POST", "PUT", "PATCH", "DELETE"}:
        return "deny-write"
    if method in {"GET", "HEAD", "OPTIONS"}:
        return "legacy-read-8000"
    return "deny-other"


def test_original_caddyfile_unchanged_and_isolated_candidate_exists():
    assert LEGACY.read_text(encoding="utf-8").strip() == (
        "100-30-4-62.nip.io {\n    reverse_proxy 127.0.0.1:8000\n}"
    )
    assert "NOT_DEPLOY" in PROPOSED.name
    text = PROPOSED.read_text(encoding="utf-8")
    assert "NO INSTALAR" in text
    assert "127.0.0.1:9444" in text
    assert "127.0.0.1:8000" in text
    assert "0.0.0.0:9444" not in text


def test_caddy_first_kx_then_deny_ws_then_deny_writes_then_legacy_read():
    data = directives(PROPOSED.read_text(encoding="utf-8"))
    assert data[0] == "100-30-4-62.nip.io {"
    assert "route {" in data
    order = [
        data.index("handle @kx_contract {"),
        data.index("handle @legacy_websockets {"),
        data.index("handle @legacy_upgrade {"),
        data.index("handle @legacy_write {"),
        data.index("handle @legacy_read {"),
        data.index("handle {"),
    ]
    assert order == sorted(order)
    assert data.count("reverse_proxy 127.0.0.1:9444 {") == 1
    assert data.count("reverse_proxy 127.0.0.1:8000") == 1
    assert "respond \"WebSocket legacy cerrado durante K-X\" 403" in data
    assert "respond \"Escrituras legacy cerradas durante K-X\" 503" in data
    assert "respond \"Metodo no autorizado\" 405" in data


def test_caddy_route_matchers_and_scheme_do_not_trust_client_forwarding():
    data = directives(PROPOSED.read_text(encoding="utf-8"))
    for entry in (
        "path /ws/kx-diagnostico/1 " + KX_BASE + " " + KX_BASE + "/* "
        + ADMIN_BASE + " " + ADMIN_BASE + "/*",
        "path /ws /ws/*",
        "method POST PUT PATCH DELETE",
        "method GET HEAD OPTIONS",
        "header_up Host 100-30-4-62.nip.io",
        "header_up X-Forwarded-For {remote_host}",
        "header_up X-Forwarded-Proto https",
        "header_up -Forwarded",
        "header_up -X-Forwarded-Host",
    ):
        assert entry in data
    assert "header_up X-Forwarded-For 8.8.8.8" not in data


def test_legacy_writes_and_websockets_cannot_match_candidate_route():
    for path in (
        "/vehiculos", "/vehiculos/1/movimientos",
        "/vehiculos/1/demos/1/ejecutar",
        "/comandos/1", "/estado/1",
        "/admin/vehiculos/1/control-publico",
        "/publico/vehiculos/1/sesion/acciones",
    ):
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            assert modeled_policy(method, path) == "deny-write"
    for path in ("/ws/vehiculos/1", "/ws/dispositivos-lab/1/contrato",
                 "/ws", "/ws/vehiculos/1?x=1"):
        assert modeled_policy("GET", path.split("?")[0]) == "deny-ws"


def test_kx_guest_admin_and_signed_wss_pass_only_to_9444():
    for path in (
        KX_BASE, KX_BASE + "/estado",
        KX_BASE + "/verificar-accion",
        ADMIN_BASE, ADMIN_BASE + "/supervision",
        ADMIN_BASE + "/7e6685d4-769b-4e80-8096-e7a8343cf83c/aprobar",
        ADMIN_BASE + "/revocar", WSS_PATH,
    ):
        assert modeled_policy("GET", path) == "kx-9444"
        assert modeled_policy("POST", path) == "kx-9444"
    assert modeled_policy("GET", "/docs") == "legacy-read-8000"
    assert modeled_policy("HEAD", "/docs") == "legacy-read-8000"
    assert modeled_policy("OPTIONS", "/estado/1") == "legacy-read-8000"
    assert modeled_policy("TRACE", "/docs") == "deny-other"


def test_encoded_or_rewritten_legacy_upgrade_is_denied_before_readonly():
    data = directives(PROPOSED.read_text(encoding="utf-8"))
    assert "header Upgrade *" in data
    assert "handle @legacy_upgrade {" in data
    assert "respond \"Upgrade legacy cerrado durante K-X\" 403" in data
    assert modeled_policy("GET", "/vehiculos/1", upgrade=True) == "deny-upgrade"
    assert modeled_policy("GET", "/ws%2Fvehiculos%2F1", upgrade=True) == "deny-upgrade"
    assert modeled_policy("GET", WSS_PATH, upgrade=True) == "kx-9444"
