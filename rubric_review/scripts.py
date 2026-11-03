"""Shared helpers for running the bundled PowerShell scripts."""

from __future__ import annotations

import json
from importlib import resources


def read_script(name: str) -> str:
    return resources.files("rubric_review").joinpath("powershell", name).read_text(encoding="utf-8")


def check_arg(value: str | int) -> str:
    text = str(value)
    if '"' in text or "\n" in text or "`" in text or "$" in text:
        raise ValueError(f"Unsafe character in remote argument: {text!r}")
    return text


def parse_json(name: str, out: str) -> object:
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} returned non-JSON output: {out.strip()[:300]}") from exc
