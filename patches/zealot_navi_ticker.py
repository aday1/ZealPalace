#!/usr/bin/env python3
"""Read the Navi summary ticker pushed from CELES."""
from __future__ import annotations

import json
import re
from pathlib import Path


NAVI_JSON = Path.home() / ".cache" / "zealot" / "navi_ticker.json"
VEC_PREFIX = re.compile(r"^VEC\?\s*")


def read_navi_ticker_line(max_len: int = 140) -> str:
    try:
        data = json.loads(NAVI_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return ""
    line = (data.get("ticker") or "").strip()
    line = VEC_PREFIX.sub("", line)
    line = " ".join(line.split())
    if len(line) > max_len:
        line = line[: max_len - 3].rsplit(" ", 1)[0] + "..."
    return line
