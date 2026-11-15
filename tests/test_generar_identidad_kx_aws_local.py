"""Provision K-X solo local: idempotencia, fail-closed y sin secretos en Git."""
from __future__ import annotations

from hashlib import sha256
import json

import pytest

from scripts import generar_identidad_kx_aws_local as unit


@pytest.fixture
def sample(tmp_path, monkeypatch):
    code = (
        b'#define ETAPA54_DIAGNOSTICO_SEGURO 1\n'
        b'#if ETAPA54_DIAGNOSTICO_SEGURO != 1\n'
        b'#error "Safety"\n#endif\n'
        b'#ifndef KX_AWS_TLS_CONFIG_OK\n#error "Blocked"\n#endif\n'
        b'"/ws/kx-diagnostico/1"\n'
    )
    sketch = tmp_path / "demo.ino"
    sketch.write_bytes(code)
    header = tmp_path / "config_55h_local.h"
    header.write_bytes(b"PRIVATE TEST CREDENTIALS")
    ca = tmp_path / "root.pem"
    ca.write_text("FAKE PUBLIC ROOT", encoding="ascii")
    monkeypatch.setattr(unit, "CANDIDATE_SHA256", sha256(code).hexdigest())
    monkeypatch.setattr(unit.ssl, "PEM_cert_to_DER_cert", lambda unused: b"public root der")
    monkeypatch.setattr(unit, "ROOT_CA_SHA256", sha256(b"public root der").hexdigest())
    return tmp_path / "private-key-dir", ca, sketch, header


def test_private_identity_is_generated_once_and_reused(sample):
    directory, ca, sketch, header = sample
    created, fingerprint = unit.provision(directory, ca, sketch, header)
    assert created is True
    key_path = directory / unit.KEY_NAME
    first = key_path.read_bytes()
    assert len(first) == 32
    assert fingerprint == sha256(first).hexdigest().upper()
    created_again, fingerprint_again = unit.provision(directory, ca, sketch, header)
    assert created_again is False
    assert fingerprint_again == fingerprint
    assert key_path.read_bytes() == first
    assert (directory / unit.MANIFEST_NAME).is_file()
    metadata = json.loads((directory / unit.MANIFEST_NAME).read_text())
    assert metadata["compile_unlocked"] is False
    assert metadata["aws_configured"] is False
    assert metadata["esp_configured"] is False
    assert not any(first in file.read_bytes() for file in (sketch, header))


def test_refuses_mismatch_without_creating_any_secret(sample, monkeypatch):
    directory, ca, sketch, header = sample
    monkeypatch.setattr(unit, "ROOT_CA_SHA256", "0" * 64)
    with pytest.raises(ValueError, match="ISRG Root X1"):
        unit.provision(directory, ca, sketch, header)
    assert not directory.exists()


def test_refuses_existing_invalid_key_without_overwrite(sample):
    directory, ca, sketch, header = sample
    directory.mkdir()
    path = directory / unit.KEY_NAME
    path.write_bytes(b"invalid")
    with pytest.raises(ValueError, match="NO reemplazar"):
        unit.provision(directory, ca, sketch, header)
    assert path.read_bytes() == b"invalid"
    assert not (directory / unit.MANIFEST_NAME).exists()


def test_refuses_private_key_inside_git_repo(sample):
    directory, ca, sketch, header = sample
    (directory.parent / ".git").mkdir()
    with pytest.raises(ValueError, match="Git"):
        unit.provision(directory, ca, sketch, header)
    assert not directory.exists()


def test_refuses_compilation_unlocked_candidate(sample):
    directory, ca, sketch, header = sample
    header.write_bytes(b"#define KX_AWS_TLS_CONFIG_OK 1")
    with pytest.raises(ValueError, match="habilita compilacion"):
        unit.provision(directory, ca, sketch, header)
    assert not directory.exists()
