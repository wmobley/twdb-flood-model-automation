"""SSH access to a DYNAMO Windows VM with TACC multi-factor login, plus PowerShell helpers."""

from __future__ import annotations

import getpass
import socket
import time
from pathlib import Path, PurePosixPath
from typing import Callable

import paramiko

from .scripts import check_arg as _check_arg
from .scripts import parse_json, read_script

REMOTE_DIR = "rubric-review"  # relative to the SSH user's home (C:\Users\<user>)
_TOKEN_HINTS = ("token", "code", "verification", "otp", "passcode")

PromptFn = Callable[[str], str]


def secret_prompt(prompt: str) -> str:
    return getpass.getpass(prompt)


class RemoteError(RuntimeError):
    pass


class VMSession:
    """One authenticated SSH connection. Credentials are prompted for, never stored or logged."""

    def __init__(self, host: str, username: str, port: int = 22, prompt: PromptFn = secret_prompt):
        self.host, self.username, self.port = host, username, port
        self._prompt = prompt
        self._transport: paramiko.Transport | None = None
        self._sftp: paramiko.SFTPClient | None = None
        self._password: str | None = None

    # -- connection -------------------------------------------------------------------------
    def connect(self, timeout: float = 30) -> "VMSession":
        sock = socket.create_connection((self.host, self.port), timeout=timeout)
        transport = paramiko.Transport(sock)
        transport.start_client(timeout=timeout)
        self._transport = transport
        self._authenticate(transport)
        if not transport.is_authenticated():
            raise RemoteError(f"Authentication to {self.host} did not complete")
        transport.set_keepalive(30)
        return self

    def _answer(self, _title: str, _instructions: str, prompts: list[tuple[str, bool]]) -> list[str]:
        answers = []
        for text, _echo in prompts:
            if any(hint in text.lower() for hint in _TOKEN_HINTS):
                answers.append(self._prompt(f"{self.host}: {text.strip()} "))
            else:
                if self._password is None:
                    self._password = self._prompt(f"{self.username}@{self.host} password: ")
                answers.append(self._password)
        return answers

    def _authenticate(self, transport: paramiko.Transport) -> None:
        """Password and TACC token may arrive as one keyboard-interactive round or as separate stages."""
        methods = ["keyboard-interactive", "password"]
        for _ in range(4):
            if transport.is_authenticated():
                return
            method = methods[0]
            try:
                if method == "keyboard-interactive":
                    remaining = transport.auth_interactive(self.username, self._answer)
                else:
                    if self._password is None:
                        self._password = self._prompt(f"{self.username}@{self.host} password: ")
                    remaining = transport.auth_password(self.username, self._password)
            except paramiko.BadAuthenticationType as exc:
                methods = [m for m in exc.allowed_types if m in ("keyboard-interactive", "password")]
                if not methods:
                    raise RemoteError(f"{self.host} offers no supported auth methods: {exc.allowed_types}") from exc
                continue
            if remaining:
                methods = [m for m in remaining if m in ("keyboard-interactive", "password")] or methods
        if not transport.is_authenticated():
            raise RemoteError(f"Could not authenticate to {self.host}")

    def close(self) -> None:
        for resource in (self._sftp, self._transport):
            if resource is not None:
                resource.close()
        self._sftp = self._transport = None
        self._password = None

    def __enter__(self) -> "VMSession":
        return self.connect()

    def __exit__(self, *_exc) -> None:
        self.close()

    # -- files ------------------------------------------------------------------------------
    @property
    def sftp(self) -> paramiko.SFTPClient:
        if self._transport is None:
            raise RemoteError("Not connected")
        if self._sftp is None:
            self._sftp = paramiko.SFTPClient.from_transport(self._transport)
            try:
                self._sftp.mkdir(REMOTE_DIR)
            except OSError:
                pass  # already exists
        return self._sftp

    def upload(self, local: str | Path, remote_name: str) -> str:
        """Upload into the rubric-review folder under the remote home; returns the home-relative Windows path."""
        self.sftp.put(str(local), str(PurePosixPath(REMOTE_DIR) / remote_name))
        return f"{REMOTE_DIR}\\{remote_name}"

    # -- commands ---------------------------------------------------------------------------
    def exec(self, command: str, timeout: float = 120) -> tuple[int, str, str]:
        if self._transport is None:
            raise RemoteError("Not connected")
        chan = self._transport.open_session()
        chan.settimeout(timeout)
        chan.exec_command(command)
        out, err = bytearray(), bytearray()
        deadline = time.monotonic() + timeout
        while not chan.exit_status_ready() or chan.recv_ready() or chan.recv_stderr_ready():
            if time.monotonic() > deadline:
                chan.close()
                raise RemoteError(f"Timed out after {timeout:.0f}s: {command[:120]}")
            if chan.recv_ready():
                out += chan.recv(65536)
            elif chan.recv_stderr_ready():
                err += chan.recv_stderr(65536)
            else:
                time.sleep(0.05)
        status = chan.recv_exit_status()
        chan.close()
        return status, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")

    def run_script(self, name: str, timeout: float = 120, **params: str | int) -> object:
        """Upload ``powershell/<name>`` and run it with ``-Param value`` arguments; parse its JSON output."""
        script = read_script(name)
        remote = self._upload_text(name, script)
        args = " ".join(f'-{key} "{_check_arg(value)}"' for key, value in params.items())
        command = f'powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{remote}" {args}'
        status, out, err = self.exec(command, timeout=timeout)
        if status != 0:
            raise RemoteError(f"{name} exited {status}: {(err or out).strip()[:600]}")
        try:
            return parse_json(name, out)
        except RuntimeError as exc:
            raise RemoteError(str(exc)) from exc

    def _upload_text(self, name: str, text: str) -> str:
        with self.sftp.open(str(PurePosixPath(REMOTE_DIR) / name), "w") as handle:
            handle.write(text)
        return f"{REMOTE_DIR}\\{name}"

