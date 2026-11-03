"""PowerShell remoting (WinRM) to a DYNAMO Windows VM. Same ``run_script`` interface as ``LocalSession``/``VMSession``."""

from __future__ import annotations

import getpass
import re
from pathlib import Path, PureWindowsPath

from .scripts import check_arg, parse_json, read_script

REMOTE_DIR = "rubric-review"  # relative to the remote user's home


def load_env(path: str | Path) -> dict[str, str]:
    """Minimal ``KEY=value`` reader (keys lower-cased); never logs values."""
    values: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if match and not line.lstrip().startswith("#"):
            values[match.group(1).lower()] = match.group(2).strip("'\"")
    return values


def _ps_quote(value: str | int) -> str:
    return "'" + check_arg(value).replace("'", "''") + "'"


class WinRMSession:
    """One WinRM connection (NTLM). Makes a single login attempt on ``connect``; it never retries.

    The account must be an Administrator or in "Remote Management Users" on the VM.
    """

    def __init__(self, host: str, username: str, password: str | None = None, port: int = 5985,
                 ssl: bool = False, auth: str = "ntlm"):
        self.host, self.username, self.port, self.ssl, self.auth = host, username, port, ssl, auth
        self._password = password
        self._client = None

    def connect(self) -> "WinRMSession":
        from pypsrp.client import Client  # imported late: only needed for this mode

        if self._password is None:
            self._password = getpass.getpass(f"{self.username}@{self.host} password: ")
        self._client = Client(self.host, username=self.username, password=self._password, ssl=self.ssl,
                              port=self.port, auth=self.auth, cert_validation=False,
                              connection_timeout=30, operation_timeout=60, read_timeout=120)
        self._client.execute_ps("$env:COMPUTERNAME")  # fails here, once, if the login is refused
        return self

    def _ps(self, script: str) -> str:
        if self._client is None:
            raise RuntimeError("Not connected")
        output, streams, had_errors = self._client.execute_ps(script)
        if had_errors:
            detail = "; ".join(str(e) for e in streams.error)[:600]
            raise RuntimeError(f"Remote PowerShell error: {detail}")
        return output

    def run_script(self, name: str, timeout: float = 120, **params: str | int) -> object:
        """Run ``powershell/<name>`` remotely with ``-Param value`` arguments and parse its JSON output.

        ``timeout`` is accepted for interface parity; long computes are bounded by each script's own ``TimeoutMin``.
        """
        args = " ".join(f"-{key} {_ps_quote(value)}" for key, value in params.items())
        out = self._ps("& {\n" + read_script(name) + "\n} " + args)
        return parse_json(name, out)

    def upload(self, local: str | Path, remote_name: str) -> str:
        """Copy a file into the remote ``rubric-review`` folder; returns the home-relative Windows path."""
        home = self._ps("$HOME").strip()
        self._ps(f"New-Item -ItemType Directory -Force -Path (Join-Path $HOME '{REMOTE_DIR}') | Out-Null")
        self._client.copy(str(local), str(PureWindowsPath(home) / REMOTE_DIR / remote_name))
        return f"{REMOTE_DIR}\\{remote_name}"

    def close(self) -> None:
        self._client = None
        self._password = None
