#!/usr/bin/env python3
"""Pull CELES phones.json into ZealPalace LCD cache (fallback when CELES push SSH fails)."""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

CACHE = Path.home() / ".cache" / "zealot"
PHONES_JSON = CACHE / "pbx_phones.json"
CELES_SRC = "aday@10.13.37.37:/var/www/pseudocorp/pbx/phones.json"
MIN_INTERVAL_SEC = 25.0
_LAST_PULL = 0.0


def _presence_state(row: dict) -> str:
    ext = str(row.get("ext") or "").strip()
    conn = str(row.get("connection") or "")
    kind = str(row.get("kind") or "")
    if ext in {"100", "101", "102", "110"}:
        detail = str(row.get("detail") or "").lower()
        if conn == "CONNECTED":
            return "online"
        if row.get("registered") and ("unavailable" in detail or "dnd" in detail):
            return "dnd"
        return str(conn or "idle").lower()
    if kind == "service":
        return "service" if conn == "CONNECTED" else str(conn or "idle").lower()
    return str(conn or "idle").lower()


def _roster_row(row: dict) -> dict:
    ext = str(row.get("ext") or "").strip()
    conn = str(row.get("connection") or "")
    return {
        "ext": ext,
        "name": row.get("name") or ext,
        "state": _presence_state(row),
        "connection": conn,
        "registered": bool(row.get("registered")),
        "last_seen": row.get("last_seen") or "",
        "last_call": row.get("last_call") or "",
        "last_call_summary": row.get("last_call_summary") or "",
        "last_call_peer": row.get("last_call_peer") or "",
    }


def pull_pbx_phones(*, force: bool = False) -> bool:
    """SCP phones.json from CELES; return True if cache updated."""
    global _LAST_PULL
    now = time.time()
    if not force and now - _LAST_PULL < MIN_INTERVAL_SEC:
        return False
    _LAST_PULL = now
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = PHONES_JSON.with_suffix(".json.tmp")
    proc = subprocess.run(
        [
            "scp",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=8",
            CELES_SRC,
            str(tmp),
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if proc.returncode != 0:
        return False
    try:
        data = json.loads(tmp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    rows = [_roster_row(row) for row in data.get("phones") or [] if isinstance(row, dict)]
    payload = {"updated": data.get("updated") or "", "phones": rows}
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(PHONES_JSON)
    return True


def ensure_pbx_phones_fresh(*, force: bool = False) -> None:
    pull_pbx_phones(force=force)