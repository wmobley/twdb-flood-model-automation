"""Single-attempt WinRM login test for a DYNAMO Windows VM.

Reads ``username`` and ``password`` from ``.env`` (the username is used exactly as written, e.g.
``wmobley@production.tacc.utexas.edu``), makes ONE login attempt and reports the result. It never retries:
repeated failures can lock the account.

    python scripts/remote/winrm_smoke_test.py dynamo03.tacc.utexas.edu --dry-run   # show what would be sent
    python scripts/remote/winrm_smoke_test.py dynamo03.tacc.utexas.edu             # real attempt

Requires ``pip install pypsrp``. The password is never printed.
"""

from __future__ import annotations

import argparse
import re
import socket
import sys
from pathlib import Path

PS_PROBE = (
    r"[pscustomobject]@{computer=$env:COMPUTERNAME; user=$env:USERNAME; "
    r"powershell=$PSVersionTable.PSVersion.ToString()} | ConvertTo-Json -Compress"
)


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if match and not line.lstrip().startswith("#"):
            values[match.group(1).lower()] = match.group(2).strip("'\"")
    return values


def port_open(host: str, port: int, timeout: float = 5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("host", help="e.g. dynamo03.tacc.utexas.edu")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--username", help="override the .env username")
    parser.add_argument("--auth", default="ntlm", choices=["ntlm", "negotiate", "credssp"])
    parser.add_argument("--port", type=int, default=5985)
    parser.add_argument("--ssl", action="store_true", help="use HTTPS (default port becomes 5986)")
    parser.add_argument("--dry-run", action="store_true", help="show the settings and test the port only; no login")
    args = parser.parse_args()
    port = 5986 if args.ssl and args.port == 5985 else args.port

    env = load_env(args.env_file)
    username = args.username or env.get("username", "")
    password = env.get("password", "")
    if not username or not password:
        print(f"{args.env_file} must define non-empty 'username' and 'password'", file=sys.stderr)
        return 2

    print(f"host={args.host} port={port} auth={args.auth} ssl={args.ssl}")
    print(f"username={username!r} password={'set' if password else 'MISSING'} ({len(password)} chars)")
    reachable = port_open(args.host, port)
    print(f"port {port}: {'open' if reachable else 'NOT reachable (firewall/VPN?)'}")
    if args.dry_run or not reachable:
        print("dry run: no login attempted" if args.dry_run else "not attempting a login")
        return 0 if args.dry_run else 1

    from pypsrp.client import Client  # imported late so --dry-run works without pypsrp

    try:
        client = Client(args.host, username=username, password=password, ssl=args.ssl, port=port, auth=args.auth,
                        cert_validation=False, connection_timeout=15, operation_timeout=20)
        out, _streams, had_errors = client.execute_ps(PS_PROBE)
    except Exception as exc:  # noqa: BLE001 - report any failure once and stop
        print(f"LOGIN FAILED: {type(exc).__name__}: {str(exc).replace(password, '***')[:300]}")
        print("Not retrying. Check lockout state and the username/password before running again.")
        return 1
    print(f"LOGIN OK: {out.strip()} (PowerShell errors: {had_errors})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
