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
    chunky_scroller,
    comet_line,
    demoscene_greetz,
    event_lines,
    fit,
    gpu_summary,
    header_title,
    marquee,
    mode_name,
    mode_art,
    motivational_line,
    pad,
    panel_lines,
    raster_bar,
    sparkle_line,
    ticker_text,
    tunnel_line,
    transition_text,
)

try:
    import pyfiglet
except Exception:  # pragma: no cover - optional on development hosts
    pyfiglet = None

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
PAIR_ART = 12
PAIR_GLINT = 13
PAIR_BANNER = 14
PAIR_RASTER = 15
PAIR_GREETZ = 16
PAIR_MOTIVE = 17


def heartbeat(now: float | None = None) -> None:
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        HEARTBEAT.write_text(str(now if now is not None else time.time()), encoding="utf-8")
    except OSError:
        pass


def figlet_lines(text: str, max_w: int = WIDTH, fonts=None) -> list[str]:
    clean = str(text or "").strip()[:16]
    if not clean:
        return []
    if pyfiglet is not None:
        for font in fonts or ("small", "digital", "mini"):
            try:
                rendered = pyfiglet.figlet_format(clean, font=font, width=max_w)
            except Exception:
                continue
            rows = [row.rstrip() for row in rendered.splitlines() if row.strip()]
            if rows and max(len(row) for row in rows) <= max_w:
                return [pad(row.center(max_w), max_w) for row in rows]
    return [pad(clean.center(max_w), max_w)]


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
        (PAIR_ART, curses.COLOR_BLUE, curses.COLOR_BLACK),
        (PAIR_GLINT, curses.COLOR_MAGENTA, curses.COLOR_BLACK),
        (PAIR_BANNER, curses.COLOR_RED, curses.COLOR_BLACK),
        (PAIR_RASTER, curses.COLOR_BLUE, curses.COLOR_BLACK),
        (PAIR_GREETZ, curses.COLOR_GREEN, curses.COLOR_BLACK),
        (PAIR_MOTIVE, curses.COLOR_YELLOW, curses.COLOR_BLACK),
    )
    for pair, fg, bg in pairs:
        try:
            curses.init_pair(pair, fg, bg)
        except curses.error:
            pass


def attr_for(style: str, bold: bool = False, now: float | None = None, row: int = 0) -> int:
    if style == "GLINT":
        cycle = (PAIR_HEADER, PAIR_TICKER, PAIR_ST, PAIR_NOC)
        pair = cycle[int((now or 0) * 5 + row) % len(cycle)]
    elif style == "ART":
        cycle = (PAIR_ART, PAIR_RPG, PAIR_ST, PAIR_NOC)
        pair = cycle[int((now or 0) * 2 + row) % len(cycle)]
    elif style == "BANNER":
        pair = PAIR_BANNER if int((now or 0) * 2) % 2 else PAIR_RPG
    elif style == "RASTER":
        cycle = (PAIR_RASTER, PAIR_NOC, PAIR_TICKER, PAIR_RPG)
        pair = cycle[int((now or 0) * 2 + row) % len(cycle)]
    elif style == "GREETZ":
        cycle = (PAIR_GREETZ, PAIR_ST, PAIR_TICKER, PAIR_NOC)
        pair = cycle[int((now or 0) * 2 + row) % len(cycle)]
    elif style == "MOTIVE":
        pair = PAIR_MOTIVE if int((now or 0) // 2) % 2 else PAIR_RPG
    else:
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
        "INPUT": PAIR_INPUT,
        }.get(style, PAIR_EVENT)
    attr = curses.color_pair(pair)
    if style == "SYS":
        attr |= curses.A_DIM
    if style in ("GLINT", "BANNER", "GREETZ", "MOTIVE"):
        attr |= curses.A_BOLD
    if style == "RASTER" and int((now or 0) * 2 + row) % 3 == 0:
        attr |= curses.A_REVERSE
    if style == "ART" and int((now or 0) * 3 + row) % 5 == 0:
        attr |= curses.A_BOLD
    if bold:
        attr |= curses.A_BOLD
    return attr


def add_line(
    stdscr,
    row: int,
    text: str,
    style: str = "SYS",
    bold: bool = False,
    raw: bool = False,
    now: float | None = None,
) -> None:
    if row < 0 or row >= HEIGHT:
        return
    value = pad(text, WIDTH) if raw else fit(text, WIDTH)
    try:
        stdscr.addnstr(row, 0, value, WIDTH, attr_for(style, bold, now, row))
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


def draw_raw(stdscr, row: int, text: str, pair: int, flags: int = 0) -> None:
    if row < 0 or row >= HEIGHT:
        return
    try:
        stdscr.addnstr(row, 0, pad(text, WIDTH), WIDTH, curses.color_pair(pair) | flags)
    except curses.error:
        pass


def draw_sip_overlay(stdscr, sip_flash, now: float, input_row: int) -> None:
    flash_on = int(now * 4) % 2 == 0
    bg_pair = PAIR_BAD if flash_on else PAIR_PBX
    bg_flags = curses.A_REVERSE | curses.A_BOLD if flash_on else curses.A_BOLD
    for row in range(input_row):
        draw_raw(stdscr, row, " " * WIDTH, bg_pair, bg_flags)

    headline = str(getattr(sip_flash, "headline", "") or "PBX CALL")[:18]
    state = str(getattr(sip_flash, "active_state", "") or "active").upper()
    subline = str(getattr(sip_flash, "subline", "") or "")[:WIDTH]
    detail = str(getattr(sip_flash, "detail", "") or "")[:WIDTH]
    try:
        active_lines = max(1, int(getattr(sip_flash, "active_lines", 1) or 1))
    except (TypeError, ValueError):
        active_lines = 1

    draw_raw(stdscr, 0, comet_line(f"PBX {active_lines} LINE{'S' if active_lines != 1 else ''} ACTIVE", now), bg_pair, bg_flags)
    draw_raw(stdscr, 1, sparkle_line(now), PAIR_WARN, curses.A_BOLD)
    row = 3
    for line in figlet_lines(headline, WIDTH, fonts=("smslant", "small", "digital", "mini"))[:6]:
        draw_raw(stdscr, row, line, PAIR_WARN if flash_on else PAIR_PBX, curses.A_BOLD)
        row += 1
    for text, pair in (
        (state.center(WIDTH), PAIR_BAD if flash_on else PAIR_WARN),
        (subline.center(WIDTH), PAIR_PBX),
        (detail.center(WIDTH), PAIR_PBX),
        ("SIP event from CELES PBX monitor".center(WIDTH), PAIR_DIM),
    ):
        draw_raw(stdscr, row, text, pair, curses.A_BOLD if pair != PAIR_DIM else curses.A_DIM)
        row += 1
    draw_raw(stdscr, input_row, "> call overlay active", PAIR_INPUT, curses.A_BOLD)


def draw(stdscr, snapshot: dict, input_buf: str, now: float, sip_flash=None) -> None:
    mode = mode_name(now)
    screen_h, _screen_w = stdscr.getmaxyx()
    usable_h = max(8, min(HEIGHT, screen_h))
    input_row = usable_h - 1
    stdscr.erase()
    if sip_flash is not None and getattr(sip_flash, "active", lambda: False)():
        draw_sip_overlay(stdscr, sip_flash, now, input_row)
        stdscr.refresh()
        return

    add_line(stdscr, 0, comet_line(header_title(snapshot, mode).strip(), now), "GLINT", raw=True, now=now)
    add_line(stdscr, 1, raster_bar(now), "RASTER", raw=True, now=now)
    add_line(stdscr, 2, demoscene_greetz(snapshot, now, WIDTH), "GREETZ", raw=True, now=now)
    add_line(
        stdscr,
        3,
        chunky_scroller(ticker_text(snapshot) + " // " + gpu_summary(snapshot), now, WIDTH, speed=3.0),
        "NOC",
        bold=True,
        raw=True,
        now=now,
    )

    row = 4
    for art_row in mode_art(mode, now, WIDTH):
        add_line(stdscr, row, art_row, "ART", raw=True, now=now)
        row += 1

    for idx, (text, style) in enumerate(panel_lines(snapshot, mode, WIDTH)):
        add_line(stdscr, row, transition_text(text, now, idx, WIDTH), style, bold=(idx == 0), raw=True, now=now)
        row += 1

    add_line(stdscr, row, motivational_line(snapshot, now, WIDTH), "MOTIVE", raw=True, now=now)
    row += 1
    add_line(stdscr, row, marquee(banner_text(snapshot), WIDTH, 10, now), "BANNER", bold=True, now=now)
    row += 1
    add_line(stdscr, row, tunnel_line(now, WIDTH), "RASTER", raw=True, now=now)
    row += 1
    add_line(stdscr, row, comet_line("EVENTS", now + 2.0), "GLINT", raw=True, now=now + 2.0)
    row += 1

    rows = []
    for event in snapshot.get("events") or []:
        rows.extend(event_lines(event, WIDTH))
    event_slots = max(1, input_row - row)
    rows = rows[-event_slots:]
    start = row + max(0, event_slots - len(rows))
    for idx, (text, style) in enumerate(rows):
        add_line(stdscr, start + idx, transition_text(text, now, idx + 20, WIDTH), style, raw=True, now=now)

    add_line(stdscr, input_row, "> " + input_buf[-(WIDTH - 3) :], "INPUT", bold=True, now=now)
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
