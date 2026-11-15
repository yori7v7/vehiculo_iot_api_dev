"""K-AA CI-only: ejecutar K-Y DENTRO del proceso Python que posee Task Scheduler.

Evita procesos Python hijos que puedan quedar huerfanos si se detiene la
tarea PowerShell. No es un lanzador instalable de EC2 ni contiene secretos.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--fixture", required=True)
    args = parser.parse_args()
    if os.name != "nt":
        return 2
    try:
        workspace = Path(args.workspace).resolve(strict=True)
        fixture = Path(args.fixture).resolve(strict=True)
        config = fixture / "private.json"
        marker = fixture / "KAA_CI_ONLY.marker"
        if (not marker.is_file() or not config.is_file()
                or not (workspace / "app" / "public_control" / "ky_windows_sidecar.py").is_file()
                or not fixture.name.startswith("kaa-ci-")
                or len(fixture.name) > 80):
            return 2
        # Lab-only flags. K-Y still validates ALL data/host/port/DB.
        os.environ.update({
            "GITHUB_ACTIONS": "true",
            "KY_WINDOWS_CI_ONLY": "isolated-sidecar",
            "APP_ENV": "staging",
            "ADMISSION_VIRTUAL_ONLY": "enabled",
            "RUNNER_TEMP": str(fixture),
        })
        status = fixture / "kaa-state.txt"
        status.write_text("direct-python-started\n", encoding="utf-8")
        os.environ["KAA_CI_DIAG_TYPE_ONLY"] = "true"
        sys.argv = ["ky_windows_sidecar", "--config", str(config)]
        from app.public_control.ky_windows_sidecar import main as start_sidecar
        status.write_text("sidecar-imported\n", encoding="utf-8")
        result = start_sidecar()
        status.write_text("ky-main-return-" + str(result) + "\n", encoding="utf-8")
        return result
    except Exception as error:
        # CI-only exception class, NEVER exception message or path.
        try:
            label = type(error).__name__
            if not label.isidentifier() or len(label) > 70:
                label = "Unknown"
            (fixture / "kaa-state.txt").write_text(
                "direct-exception-" + label + "\n", encoding="utf-8"
            )
        except Exception:
            pass
        return 3


if __name__ == "__main__":
    sys.exit(main())
