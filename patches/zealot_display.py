#!/usr/bin/env python3
"""ZealPalace LCD hybrid ticker.

This is the clean, first-class replacement for the older patched display file.
It renders a fixed 40x34 curses UI from typed feeds: IRC, Crystal Mesh bridge,
SillyTavern companion continuity, PBX, NOC, Navi, and local fallbacks.
"""
from __future__ import annotations

import curses
import os
import signal
import time
from pathlib import Path

from zealot_lcd_feeds import CACHE, IrcTap, collect_snapshot, now_iso
from zealot_lcd_render import (
    HEIGHT,
    WIDTH,
    banner_text,
    event_lines,
    fit,
    header_title,
    marquee,
    mode_name,
    panel_lines,
    ticker_text,
)

try:
    from zealot_noc_mesh import NocMeshStatus
except Exception:  # pragma: no cover - optional on development hosts
    NocMeshStatus = None

try:
    from zealot_sip_flash import SipCallFlash, poll_sip_call_flash
except Exception:  # pragma: no cover - optional on development hosts
    SipCallFlash = None
    poll_sip_call_flash = None


os.environ["TERM"] = os.environ.get("TERM") or "linux"
CHAT_FIFO = CACHE / "chat_in"
HEARTBEAT = CACHE / "lcd_heartbeat"
ERR_LOG = Path("/tmp/zealot_display_err.log")

PAIR_HEADER = 1
PAIR_TICKER = 2
PAIR_RPG = 3
PAIR_ST = 4
PAIR_PBX = 5
PAIR_NOC = 6
PAIR_WARN = 7
PAIR_BAD = 8
PAIR_DIM = 9
PAIR_INPUT = 10
PAIR_EVENT = 11


def heartbeat(now: float | None = None) -> None:
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        HEARTBEAT.write_text(str(now if now is not None else time.time()), encoding="utf-8")
    except OSError:
        pass


def figlet_lines(text: str, max_w: int = WIDTH, fonts=None) -> list[str]:
    del fonts
    clean = str(text or "")[:max_w]
    return [clean.center(max_w)]


def init_colors() -> None:
    curses.start_color()
    curses.use_default_colors()
    pairs = (
        (PAIR_HEADER, curses.COLOR_CYAN, curses.COLOR_BLACK),
        (PAIR_TICKER, curses.COLOR_YELLOW, curses.COLOR_BLACK),
        (PAIR_RPG, curses.COLOR_GREEN, curses.COLOR_BLACK),
        (PAIR_ST, curses.COLOR_MAGENTA, curses.COLOR_BLACK),
        (PAIR_PBX, curses.COLOR_YELLOW, curses.COLOR_BLACK),
        (PAIR_NOC, curses.COLOR_CYAN, curses.COLOR_BLACK),
        (PAIR_WARN, curses.COLOR_YELLOW, curses.COLOR_BLACK),
        (PAIR_BAD, curses.COLOR_RED, curses.COLOR_BLACK),
        (PAIR_DIM, curses.COLOR_WHITE, curses.COLOR_BLACK),
        (PAIR_INPUT, curses.COLOR_GREEN, curses.COLOR_BLACK),
        (PAIR_EVENT, curses.COLOR_WHITE, curses.COLOR_BLACK),
    )
    for pair, fg, bg in pairs:
        try:
            curses.init_pair(pair, fg, bg)
        except curses.error:
            pass


def attr_for(style: str, bold: bool = False) -> int:
    pair = {
        "RPG": PAIR_RPG,
        "ST": PAIR_ST,
        "GMQ": PAIR_ST,
        "PBX": PAIR_PBX,
        "PCORP": PAIR_PBX,
        "NOC": PAIR_NOC,
        "SYS": PAIR_DIM,
        "ZH": PAIR_EVENT,
        "ZP": PAIR_EVENT,
        "IRC": PAIR_EVENT,
    }.get(style, PAIR_EVENT)
    attr = curses.color_pair(pair)
    if style == "SYS":
        attr |= curses.A_DIM
    if bold:
        attr |= curses.A_BOLD
    return attr


def add_line(stdscr, row: int, text: str, style: str = "SYS", bold: bool = False) -> None:
    if row < 0 or row >= HEIGHT:
        return
    try:
        stdscr.addnstr(row, 0, fit(text, WIDTH), WIDTH, attr_for(style, bold))
    except curses.error:
        pass


def send_to_zealot(message: str) -> None:
    text = message.strip()
    if not text:
        return
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        CHAT_FIFO.write_text(text, encoding="utf-8")
    except OSError:
        pass
    try:
        with (CACHE / "irc.log").open("a", encoding="utf-8") as handle:
            handle.write(time.strftime("%I:%M%p").lstrip("0").lower() + f" <aday> {text}\n")
    except OSError:
        pass


def draw(stdscr, snapshot: dict, input_buf: str, now: float, sip_flash=None) -> None:
    mode = mode_name(now)
    stdscr.erase()
    add_line(stdscr, 0, header_title(snapshot, mode), "SYS", bold=True)
    add_line(stdscr, 1, marquee(ticker_text(snapshot), WIDTH, 18, now), "NOC", bold=True)

    if sip_flash is not None and getattr(sip_flash, "active", lambda: False)():
        title = getattr(sip_flash, "header_title", lambda width: "")(WIDTH)
        if title:
            add_line(stdscr, 0, title, "PBX", bold=True)
        try:
            sip_flash.draw(stdscr, 2, WIDTH, PAIR_PBX, PAIR_WARN)
        except Exception:
            pass
    else:
        for idx, (text, style) in enumerate(panel_lines(snapshot, mode, WIDTH), start=2):
            add_line(stdscr, idx, text, style, bold=(idx == 2))

    add_line(stdscr, 10, marquee(banner_text(snapshot), WIDTH, 10, now), "RPG", bold=True)
    add_line(stdscr, 11, "-" * 12 + " EVENTS " + "-" * 20, "SYS")

    rows = []
    for event in snapshot.get("events") or []:
        rows.extend(event_lines(event, WIDTH))
    rows = rows[-20:]
    start = 12 + max(0, 20 - len(rows))
    for idx, (text, style) in enumerate(rows):
        add_line(stdscr, start + idx, text, style)

    add_line(stdscr, HEIGHT - 1, "> " + input_buf[-(WIDTH - 3) :], "SYS", bold=True)
    stdscr.refresh()


def main(stdscr) -> None:
    curses.curs_set(0)
    init_colors()
    stdscr.nodelay(True)
    stdscr.timeout(120)

    CACHE.mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGUSR1, lambda _sig, _frame: heartbeat())

    irc_tap = IrcTap()
    irc_tap.start()
    noc_mesh = NocMeshStatus() if NocMeshStatus else None
    sip_flash = SipCallFlash(figlet_lines) if SipCallFlash else None

    snapshot = collect_snapshot(irc_tap)
    last_snapshot = 0.0
    input_buf = ""

    while True:
        now = time.time()
        heartbeat(now)
        try:
            if noc_mesh is not None:
                try:
                    noc_mesh.poll()
                    if noc_mesh.router_flashbang(stdscr):
                        heartbeat(now)
                        stdscr.refresh()
                        time.sleep(0.08)
                        continue
                except Exception:
                    pass

            if sip_flash is not None and poll_sip_call_flash is not None:
                try:
                    poll_sip_call_flash(sip_flash)
                except Exception:
                    pass

            if now - last_snapshot > 1.0:
                snapshot = collect_snapshot(irc_tap)
                last_snapshot = now

            draw(stdscr, snapshot, input_buf, now, sip_flash)

            ch = stdscr.getch()
            if ch == -1:
                continue
            if ch in (10, 13):
                send_to_zealot(input_buf)
                input_buf = ""
            elif ch == 27:
                input_buf = ""
            elif ch in (curses.KEY_BACKSPACE, 127, 8):
                input_buf = input_buf[:-1]
            elif 32 <= ch < 127 and len(input_buf) < 240:
                input_buf += chr(ch)
        except KeyboardInterrupt:
            irc_tap.stop()
            break
        except Exception as exc:
            try:
                with ERR_LOG.open("a", encoding="utf-8") as handle:
                    handle.write(f"{now_iso()} {type(exc).__name__}: {exc}\n")
            except OSError:
                pass
            time.sleep(0.5)


if __name__ == "__main__":
    curses.wrapper(main)
