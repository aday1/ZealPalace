#!/usr/bin/env python3
"""NOC mesh status for ZealPalace LCD: green 1 / flashing X offline / yellow 0 recent; WAN-X flash."""
from __future__ import annotations

import json
import random
import time
from pathlib import Path

NOC_JSON = Path.home() / ".cache" / "zealot" / "noc_mesh.json"
RECENT_OFFLINE_SEC = 600

HOST_ROWS = (
    (("nidhogg", "NID"), ("midgard", "MID")),
    (("zeal", "ZEA"), ("asgard", "ASG"), ("vector", "VEC")),
    (("lain", "LAI"),),
)


class NocMeshStatus:
    def __init__(self):
        self.data: dict = {}
        self._mtime = 0.0
        self._recent_until: dict[str, float] = {}
        self._prev_up: dict[str, bool] = {}
        self._rf_next = 0.0
        self._rf_until = 0.0
        self._rf_start = 0.0

    def poll(self) -> None:
        try:
            st = NOC_JSON.stat()
        except OSError:
            self.data = {}
            return
        if st.st_mtime == self._mtime:
            return
        self._mtime = st.st_mtime
        try:
            self.data = json.loads(NOC_JSON.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            self.data = {}
            return
        now = time.time()
        inet = self.data.get("internet") or {}
        for key, up in (
            ("nidhogg", bool(inet.get("nidhogg_up"))),
            ("midgard", bool(inet.get("midgard_up"))),
        ):
            self._track_edge(key, up, now)
        for row in self.data.get("hosts") or []:
            hid = str(row.get("id") or "")
            if not hid:
                continue
            up = bool(row.get("up"))
            if not up and row.get("recent_offline"):
                self._recent_until[hid] = max(
                    self._recent_until.get(hid, 0), now + RECENT_OFFLINE_SEC
                )
            self._track_edge(hid, up, now)

    def _track_edge(self, hid: str, up: bool, now: float) -> None:
        was = self._prev_up.get(hid, True)
        if was and not up:
            self._recent_until[hid] = now + RECENT_OFFLINE_SEC
        if up:
            self._recent_until.pop(hid, None)
        self._prev_up[hid] = up

    def _host_up(self, hid: str) -> bool:
        if hid in ("nidhogg", "midgard"):
            inet = self.data.get("internet") or {}
            if hid == "nidhogg":
                return bool(inet.get("nidhogg_up"))
            return bool(inet.get("midgard_up"))
        for row in self.data.get("hosts") or []:
            if str(row.get("id")) == hid:
                return bool(row.get("up"))
        return False

    def _recent(self, hid: str) -> bool:
        return self._recent_until.get(hid, 0) > time.time()

    def wan_up(self) -> bool:
        inet = self.data.get("internet") or {}
        return bool(inet.get("up", True))

    def nidhogg_up(self) -> bool:
        if not self.data:
            return True
        inet = self.data.get("internet") or {}
        return bool(inet.get("nidhogg_up", True))

    def _paint_fullscreen(self, stdscr, height: int, width: int, curses, invert: bool) -> None:
        attr = curses.A_REVERSE if invert else curses.A_NORMAL
        line = " " * max(1, min(width, 512))
        last_row = max(0, height - 1)
        for y in range(last_row):
            try:
                stdscr.addnstr(y, 0, line, max(1, width - 1), attr)
            except Exception:
                pass

    def router_flashbang(self, stdscr) -> bool:
        """Full-screen black/white flashes while NIDHOGG (10.13.37.1) is unreachable."""
        curses = __import__("curses")
        self.poll()
        now = time.time()
        height, width = stdscr.getmaxyx()

        if self.nidhogg_up():
            self._rf_next = 0.0
            self._rf_until = 0.0
            self._rf_start = 0.0
            return False

        if now < self._rf_until:
            step = int((now - self._rf_start) / 0.18) % 2
            self._paint_fullscreen(stdscr, height, width, curses, invert=step == 1)
            return True

        if self._rf_next <= 0:
            self._rf_next = now + random.uniform(18.0, 32.0)
        if now >= self._rf_next:
            self._rf_start = now
            self._rf_until = now + random.uniform(0.35, 0.65)
            self._rf_next = now + random.uniform(28.0, 55.0)
            self._paint_fullscreen(stdscr, height, width, curses, invert=True)
            return True
        return False

    def header(self, width: int = 40) -> str:
        if not self.data:
            return "NOC MESH (no data)"[:40]
        hosts = self.data.get("hosts") or []
        up_n = sum(1 for h in hosts if h.get("up"))
        tot = len(hosts) or 1
        if not self.wan_up():
            return "NOC WAN DOWN !!!"[:40]
        return f"NOC {up_n}/{tot} hosts up"[:40]

    def _digit_for(self, hid: str) -> tuple[str, bool]:
        if self._host_up(hid):
            return "1", False
        if self._recent(hid):
            return "0", False
        return "X", True

    def _pair_attr(self, curses, hid: str, c_ok: int, c_warn: int, c_bad: int, flash: bool) -> int:
        if self._host_up(hid):
            return curses.color_pair(c_ok) | curses.A_BOLD
        if self._recent(hid):
            return curses.color_pair(c_warn) | curses.A_BOLD
        if flash and int(time.time()) % 4 == 1:
            return curses.color_pair(c_bad) | curses.A_DIM
        return curses.color_pair(c_bad) | curses.A_BOLD

    def _draw_pair(
        self,
        stdscr,
        row: int,
        col: int,
        label: str,
        hid: str,
        width: int,
        curses,
        c_ok: int,
        c_warn: int,
        c_bad: int,
    ) -> int:
        digit, flash = self._digit_for(hid)
        chunk = f"{label}:{digit} "
        attr = self._pair_attr(curses, hid, c_ok, c_warn, c_bad, flash)
        try:
            stdscr.addnstr(row, col, chunk[: max(0, width - col)], width - col, attr)
        except Exception:
            pass
        return col + len(chunk)

    def _draw_wan(self, stdscr, row: int, width: int, curses, c_ok: int, c_warn: int, c_bad: int) -> None:
        if self.wan_up():
            text = "WAN 1  INTERNET OK"
            attr = curses.color_pair(c_ok) | curses.A_BOLD
        else:
            flash = int(time.time()) % 4 == 0
            text = "WAN-X  NO INTERNET!!!"
            attr = curses.color_pair(c_warn) | (curses.A_BOLD if flash else curses.A_DIM)
        try:
            stdscr.addnstr(row, 0, text.center(width)[:width], width, attr)
        except Exception:
            pass

    def draw(self, stdscr, y0: int, width: int, c_ok: int, c_warn: int, c_bad: int) -> int:
        curses = __import__("curses")
        self.poll()
        row = y0
        if not self.data:
            try:
                stdscr.addnstr(
                    row,
                    0,
                    "NOC: waiting for CELES push".center(width)[:width],
                    width,
                    curses.color_pair(c_warn) | curses.A_DIM,
                )
            except Exception:
                pass
            return row + 3

        self._draw_wan(stdscr, row, width, curses, c_ok, c_warn, c_bad)
        row += 1
        for host_row in HOST_ROWS:
            col = 0
            for hid, label in host_row:
                col = self._draw_pair(
                    stdscr, row, col, label, hid, width, curses, c_ok, c_warn, c_bad
                )
            row += 1
        return row
