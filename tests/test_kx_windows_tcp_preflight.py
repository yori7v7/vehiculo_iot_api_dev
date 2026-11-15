"""Regression: close subprocess before Windows deletes SQLite lock file."""
import ast
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import kx_windows_tcp_preflight as smoke


class FakeChild:
    def __init__(self):
        self.running = True
        self.calls = []

    def poll(self):
        return None if self.running else 0

    def terminate(self):
        self.calls.append("terminate")
        self.running = False

    def wait(self, timeout):
        self.calls.append("wait")
        return 0


def test_process_closed_before_removing_sqlite_lock(tmp_path, monkeypatch):
    child = FakeChild()
    state = tmp_path / "kx.sqlite"
    state.mkdir()
    (state / "tickets.sqlite3.lock").write_text("fixture")
    events = []
    original = smoke.shutil.rmtree

    def guarded_rmtree(path):
        assert not child.running, "Windows would raise WinError 32"
        events.append("delete")
        original(path)

    monkeypatch.setattr(smoke.shutil, "rmtree", guarded_rmtree)
    monkeypatch.setattr(smoke, "assert_port_free", lambda: None)
    smoke.terminate_own_child(child)
    smoke.cleanup_temporary_state(state)
    assert child.calls == ["terminate", "wait"]
    assert events == ["delete"]
    assert not state.exists()


def test_temp_cleanup_retries_locked_file(tmp_path, monkeypatch):
    target = tmp_path / "db"
    target.mkdir()
    (target / "tickets.sqlite3.lock").write_text("fixture")
    original = smoke.shutil.rmtree
    calls = []

    def flaky(path):
        calls.append(1)
        if len(calls) == 1:
            raise PermissionError("WinError 32 fake")
        return original(path)

    monkeypatch.setattr(smoke.shutil, "rmtree", flaky)
    monkeypatch.setattr(smoke.time, "sleep", lambda _n: None)
    smoke.cleanup_temporary_state(target)
    assert len(calls) == 2
    assert not target.exists()


def test_refuses_manual_execution_on_non_windows(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(smoke.sys, "platform", "linux")
    result = smoke.main([
        "--repo", str(repo),
        "--key-path", str(tmp_path / "fake.bin"),
        "--active-caddy", str(tmp_path / "Caddyfile"),
    ])
    out = capsys.readouterr().out
    assert result == 2
    assert "NO-GO" in out


def test_only_test_pid_is_terminated(monkeypatch):
    calls = []
    monkeypatch.setattr(smoke, "assert_port_free", lambda: calls.append("port_free"))
    child = FakeChild()
    smoke.terminate_own_child(child)
    assert child.calls == ["terminate", "wait"]
    assert calls == ["port_free"]


def test_script_syntax_and_loopback_only():
    src = Path(smoke.__file__).read_text(encoding="utf-8")
    ast.parse(src)
    assert 'HOST = "127.0.0.1"' in src
    assert "PORT = 9444" in src
    assert "--no-proxy-headers" in src
    assert "--no-access-log" in src
    assert "challenge_only()" in src
    assert "terminate_own_child(process)" in src
    assert "cleanup_temporary_state(temporary)" in src
    assert src.index("terminate_own_child(process)") < src.index(
        "cleanup_temporary_state(temporary)"
    )
