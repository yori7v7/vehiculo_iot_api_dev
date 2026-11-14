"""K-G must fail closed when the local KC file imports a duplicate gate.

No external Downloads source, config, WSS or physical hardware is imported.
"""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "servidor_55kg.py"


def _guard_code():
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert any(
        isinstance(node, ast.ImportFrom)
        and node.module == "app.public_control.single_link_admission_lab"
        and any(alias.asname == "CanonicalAdmissionGate" for alias in node.names)
        for node in tree.body
    )
    checks = [
        node for node in tree.body
        if isinstance(node, ast.If)
        and "CanonicalAdmissionGate" in ast.unparse(node.test)
        and "getattr(kc, 'SingleLinkAdmissionLab', None)" in ast.unparse(node.test)
    ]
    assert len(checks) == 1
    return compile(
        ast.fix_missing_locations(ast.Module(body=[checks[0]], type_ignores=[])),
        "<KG gate guard>", "exec",
    )


def test_kc_gate_identity_must_be_exact_class_object():
    code = _guard_code()
    canonical = object()
    exec(code, {"kc": SimpleNamespace(SingleLinkAdmissionLab=canonical),
                "CanonicalAdmissionGate": canonical})


@pytest.mark.parametrize("kc", [
    SimpleNamespace(),
    SimpleNamespace(SingleLinkAdmissionLab=object()),
    SimpleNamespace(SingleLinkAdmissionLab=None),
])
def test_duplicate_or_missing_kc_gate_prevents_startup(kc):
    with pytest.raises(SystemExit, match="NO-GO"):
        exec(_guard_code(), {"kc": kc, "CanonicalAdmissionGate": object()})
