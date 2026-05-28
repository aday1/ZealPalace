#!/usr/bin/env python3
"""Merged IRC + PBX tail for ZealPalace LCD with clear channel tags."""
from __future__ import annotations

import re
from collections import deque
from pathlib import Path

CACHE = Path.home() / ".cache" / "zealot"

SOURCES = (
    ("[PBX]", CACHE / "pbx.log"),
    ("[ZP]", CACHE / "irc.log"),
    ("[RPG]", CACHE / "rpg.log"),
    ("[ZH]", CACHE / "hangs.log"),
)


def _tail_lines(path: Path, max_lines: int) -> list[str]:
    if not path.is_file():
        return []
    try:
        data = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out = []
    for raw in data[-max_lines:]:
        line = raw.strip()
        if line:
            out.append(line)
    return out


def read_irc_tail(n: int) -> list[str]:
    """Return up to n recent lines, tagged by source (PBX / ZealPalace / RPG / hangs)."""
    want = max(8, int(n or 20))
    per = max(6, want // len(SOURCES) + 2)
    merged: list[str] = []
    for tag, path in SOURCES:
        for line in _tail_lines(path, per):
            if line.startswith("["):
                merged.append(line[:200])
            else:
                merged.append(f"{tag} {line}"[:200])
    if len(merged) <= want:
        return merged[-want:]
    return merged[-want:]


def irc_line_tag(line: str) -> str:
    m = re.match(r"^(\[[A-Z]+\])", line or "")
    return m.group(1) if m else ""
