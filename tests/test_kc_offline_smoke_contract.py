"""Contrato estático del smoke offline: CI NO dispone del archivo KC local."""
import ast
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prueba_kc_turnos_offline.py"


def test_smoke_importable_syntax_and_intercepted_dispatch():
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    simulator = next(n for n in classes if n.name == "MemoryOnlyKC")
    assert [ast.unparse(b) for b in simulator.bases] == ["kc.KCController"]
    dispatches = [n for n in simulator.body
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and n.name == "dispatch"]
    assert len(dispatches) == 1
    dispatch = dispatches[0]
    assert isinstance(dispatch, ast.AsyncFunctionDef)
    # No calling the inherited production-capable dispatcher.
    assert all(not isinstance(node, ast.Await) for node in ast.walk(dispatch))
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                   and node.func.attr == "dispatch" for node in ast.walk(dispatch))
    assert "self.sent.append((code, duration))" in ast.unparse(dispatch)


def test_smoke_cannot_open_network_and_requires_negative_cases():
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    top_imports = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            top_imports.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_imports.append(node.module.split(".")[0])
    assert not set(top_imports) & {"socket", "requests", "httpx", "uvicorn", "subprocess"}
    calls = [ast.unparse(node.func) for node in ast.walk(tree)
             if isinstance(node, ast.Call)]
    forbidden = {"kc.main", "kc.old.main", "uvicorn.run", "subprocess.run",
                 "asyncio.open_connection", "socket.socket"}
    assert not forbidden.intersection(calls)
    for marker in (
        'move_authorized("guest", 9, 250, BROWSER_SECRET)',
        'status=409',
        'status=403',
        '"revocado_o_caducado"',
        '"parada_fisica_verificada"',
        'SIN RED | SIN WSS | SIN MOTORES',
    ):
        assert marker in source
