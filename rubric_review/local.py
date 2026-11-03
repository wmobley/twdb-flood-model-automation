"""Run the bundled PowerShell scripts on this machine (use when the notebook runs on the Windows VM itself)."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .scripts import check_arg, parse_json, read_script


class LocalSession:
    """Same ``run_script`` interface as ``VMSession`` but executes locally; no credentials involved."""

    def __init__(self) -> None:
        self._shell = shutil.which("powershell") or shutil.which("pwsh")
        if sys.platform != "win32" or not self._shell:
            raise RuntimeError("LocalSession must run on the Windows VM (PowerShell not found)")
        self._tmp = Path(tempfile.mkdtemp(prefix="rubric-review-"))

    def run_script(self, name: str, timeout: float = 120, **params: str | int) -> object:
        script = self._tmp / name
        script.write_text(read_script(name), encoding="utf-8")
        cmd = [self._shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)]
        for key, value in params.items():
            cmd += [f"-{key}", check_arg(value)]
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if done.returncode != 0:
            raise RuntimeError(f"{name} exited {done.returncode}: {(done.stderr or done.stdout).strip()[:600]}")
        return parse_json(name, done.stdout)

    def close(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)
