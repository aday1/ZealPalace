#!/usr/bin/env python3
"""PSEUDOCORP human SIP lines for ZealPalace LCD (yellow, online-only, DND)."""
from __future__ import annotations

import json
import time
from pathlib import Path

PHONES_JSON = Path.home() / ".cache" / "zealot" / "pbx_phones.json"
HUMAN_LABELS = {
    "100": "aday",
    "110": "aday mob",
    "101": "BMO",
    "102": "BMO mob",
}


class PbxPhoneStatus:
    def __init__(self):
        self.lines: list[dict] = []
        self.updated = 0.0
        self._mtime = 0.0

    def poll(self) -> None:
        try:
            st = PHONES_JSON.stat()
        except OSError:
            self.lines = []
            return
        if st.st_mtime == self._mtime:
            return
        self._mtime = st.st_mtime
        try:
            data = json.loads(PHONES_JSON.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            self.lines = []
            return
        self.updated = time.time()
        out: list[dict] = []
        for row in data.get("phones") or []:
            ext = str(row.get("ext") or "")
            if ext not in HUMAN_LABELS:
                continue
            conn = str(row.get("connection") or "")
            reg = bool(row.get("registered"))
            detail = str(row.get("detail") or "").lower()
            if conn == "CONNECTED":
                state = "online"
            elif reg and ("unavailable" in detail or "dnd" in detail):
                state = "dnd"
            else:
                continue
            out.append(
                {
                    "ext": ext,
                    "label": HUMAN_LABELS[ext],
                    "state": state,
                }
            )
        order = ("100", "110", "101", "102")
        out.sort(key=lambda r: order.index(r["ext"]) if r["ext"] in order else 99)
        self.lines = out

    def has_online(self) -> bool:
        return bool(self.lines)

    def format_row(self, row: dict, width: int = 40) -> str:
        ext = row["ext"]
        label = row["label"]
        if row["state"] == "dnd":
            tag = "DND"
        else:
            tag = "ON"
        text = f"{ext} {label} {tag}"
        return text[:width]

    def draw(self, stdscr, y0: int, width: int, c_pair: int) -> int:
        """Draw phone rows in yellow; returns next row."""
        curses = __import__("curses")
        row = y0
        if not self.lines:
            try:
                stdscr.addnstr(
                    row,
                    0,
                    "PBX: no human lines online".center(width)[:width],
                    width,
                    curses.color_pair(c_pair) | curses.A_DIM,
                )
            except Exception:
                pass
            return row + 1
        for item in self.lines[:4]:
            line = self.format_row(item, width)
            try:
                stdscr.addnstr(
                    row,
                    0,
                    line.center(width)[:width],
                    width,
                    curses.color_pair(c_pair) | curses.A_BOLD,
                )
            except Exception:
                pass
            row += 1
        return row

    def header(self, width: int = 40) -> str:
        n = len(self.lines)
        if n == 0:
            return "PBX SIP (none online)"[:width]
        dnd = sum(1 for r in self.lines if r["state"] == "dnd")
        if dnd:
            return f"PBX SIP {n} online ({dnd} DND)"[:width]
        return f"PBX SIP {n} online"[:width]
