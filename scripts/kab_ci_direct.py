"""K-AB: shim SOLO para GitHub Actions, no instalar en EC2.

Task Scheduler ejecuta directamente ESTE proceso Python LocalService;
configuración y claves permanecen en el fixture con ACL privada.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--runner", required=True)
    p.add_argument("--state", required=True)
    p.add_argument("--mode", choices=("preflight", "serve"), required=True)
    a = p.parse_args()
    if os.name != "nt":
        return 2
    try:
        runner = Path(a.runner).resolve(strict=True)
        state = Path(a.state).resolve(strict=True)
        if (state.name != "kab-private"
                or state == runner
                or not state.is_relative_to(runner)
                or not (state / "KAB_CI_ONLY.marker").is_file()):
            return 2
        os.environ.update({
            "GITHUB_ACTIONS": "true",
            "KAB_WINDOWS_CI_ONLY": "isolated-loopback",
            "RUNNER_TEMP": str(runner),
        })
        from app.public_control.kab_windows_staging import main as launch
        return launch(["--mode", a.mode, "--state", str(state)])
    except Exception:
        return 2


if __name__ == "__main__":
    sys.exit(main())
