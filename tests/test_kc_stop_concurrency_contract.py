"""Static fail-closed check of the offline STOP non-preemption witness."""
from pathlib import Path
import ast

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prueba_kc_stop_concurrencia_offline.py"


def test_offline_dispatch_uses_no_transport_or_real_kc_dispatch():
    src = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(src)
    klass = next(n for n in tree.body
                 if isinstance(n, ast.ClassDef) and n.name == "DelayedMemoryKC")
    assert [ast.unparse(x) for x in klass.bases] == ["kc.KCController"]
    dispatch = next(n for n in klass.body
                    if isinstance(n, ast.AsyncFunctionDef) and n.name == "dispatch")
    text = ast.unparse(dispatch)
    assert "self.commands.append" in text
    assert "self.release.wait()" in text
    assert "super()" not in text
    assert not any(isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute)
                   and x.func.attr == "dispatch" for x in ast.walk(dispatch))
    imports = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            imports += [a.name.split(".")[0] for a in node.names]
        if isinstance(node, ast.ImportFrom) and node.module:
            imports += [node.module.split(".")[0]]
    assert not set(imports).intersection(
        {"socket", "requests", "httpx", "uvicorn", "subprocess", "websockets"}
    )


def test_negative_witness_labels_stop_as_not_physically_preemptive():
    source = SCRIPT.read_text(encoding="utf-8")
    for phrase in (
        'assert not revoke.done()',
        '"MOVIMIENTO_ENTRO"',
        '"MOVIMIENTO_SALIO"',
        '["STOP_VIRTUAL", "MOVIMIENTO_ENTRO"]',
        'stopped["parada_fisica_verificada"] is False',
        "NO-GO CONTROL FISICO",
    ):
        assert phrase in source
