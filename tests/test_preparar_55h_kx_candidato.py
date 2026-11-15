"""Pruebas offline del preparado K-X: sin credenciales, ESP ni AWS."""
from __future__ import annotations

from hashlib import sha256

import pytest

from scripts import preparar_55h_kx_candidato as stage


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_prepare_isolated_candidate_preserves_original_and_private_header(
    tmp_path, monkeypatch, newline,
):
    source_dir = tmp_path / stage.ORIGINAL_SKETCH
    source_dir.mkdir()
    source = source_dir / (stage.ORIGINAL_SKETCH + ".ino")
    code = newline.join((
        '#include "config_55h_local.h"',
        '#define ETAPA54_DIAGNOSTICO_SEGURO 1',
        '#if ETAPA54_DIAGNOSTICO_SEGURO != 1',
        '#error "Safety"',
        '#endif',
        'ws.beginSslWithCA(LAB55H_HOST, LAB55H_PORT,',
        '"/ws/dispositivos-lab/1/contrato", LAB55H_CA_CERT);',
        '',
    )).encode("utf-8")
    source.write_bytes(code)
    header = source_dir / stage.HEADER_NAME
    header.write_bytes(b"PRIVATE TEST HEADER - NEVER PRINT")
    monkeypatch.setattr(stage, "SOURCE_SHA256", sha256(code).hexdigest())

    target = tmp_path / stage.NEW_SKETCH
    original, candidate = stage.prepare(source, target)
    generated = (target / (stage.NEW_SKETCH + ".ino")).read_bytes()
    assert original == sha256(code).hexdigest().upper()
    assert candidate == sha256(generated).hexdigest().upper()
    assert source.read_bytes() == code
    assert header.read_bytes() == (target / stage.HEADER_NAME).read_bytes()
    assert b"KX_AWS_TLS_CONFIG_OK" in generated
    assert b"#error \"KX AWS:" in generated
    assert stage.OLD_ROUTE.encode() not in generated
    assert stage.NEW_ROUTE.encode() in generated
    assert newline.encode() in generated
    if newline == "\r\n":
        assert b"\r\n#ifndef KX_AWS_TLS_CONFIG_OK\r\n" in generated
    with pytest.raises(FileExistsError):
        stage.prepare(source, target)


def test_digest_mismatch_refuses_to_copy(tmp_path):
    source_dir = tmp_path / stage.ORIGINAL_SKETCH
    source_dir.mkdir()
    source = source_dir / (stage.ORIGINAL_SKETCH + ".ino")
    source.write_bytes(b"not our validated firmware")
    (source_dir / stage.HEADER_NAME).write_bytes(b"PRIVATE")
    target = tmp_path / stage.NEW_SKETCH
    with pytest.raises(ValueError, match="SHA256"):
        stage.prepare(source, target)
    assert not target.exists()


def test_never_copy_private_header_into_git_tree(tmp_path):
    source_dir = tmp_path / stage.ORIGINAL_SKETCH
    source_dir.mkdir()
    source = source_dir / (stage.ORIGINAL_SKETCH + ".ino")
    source.write_bytes(b"not yet copied")
    (source_dir / stage.HEADER_NAME).write_bytes(b"PRIVATE")
    git_root = tmp_path / "repo"
    (git_root / ".git").mkdir(parents=True)
    with pytest.raises(ValueError, match="repositorio Git"):
        stage.prepare(source, git_root / stage.NEW_SKETCH)
    assert not (git_root / stage.NEW_SKETCH).exists()
