#!/usr/bin/env python3
"""ZealPalace LCD — polished hybrid terrarium dashboard.

Full 40x34 curses UI on the 320x480 TFT: calm demoscene header, rotating mode
panels (BOOT AGE, NOC disk bars, agents, RPG), calendar footer, SIP/WOPR overlays.
"""
from __future__ import annotations

import curses
import os
import signal
import time
from pathlib import Path

from zealot_lcd_feeds import CACHE, IrcTap, collect_snapshot, event_is_recurring_noise, now_iso
from zealot_lcd_feeds import FEED_NOISE_RE
from zealot_lcd_render import (
    HEIGHT,
    WIDTH,
    LCD_PANEL_MAX_ROWS,
    LCD_EVENT_MAX_BODY_LINES,
    SCROLLER_SPEED,
    TICKER_SCROLLER_SPEED,
    lcd_frame_cols,
    lcd_frame_zones,
    anim_now,
    calendar_segments,
    top_status_segments,
    wopr_header_segments,
    ticker_scroll_body,
    weekend_monday_countdown_segments,
    chunky_scroller,
    comet_line,
    demoscene_fx_row,
    dashboard_footer_segments,
    event_segments,
    event_display_rows,
    event_lines,
    fit,
    lcd_status_line,
    agents_art_live,
    mode_art_compact,
    mode_name,
    pad,
    panel_lines,
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

try:
    from zealot_wopr_lcd import draw_wopr_overlay, poll_joshua_wopr
except Exception:  # pragma: no cover - optional on development hosts
    poll_joshua_wopr = None
    draw_wopr_overlay = None

try:
    from lcd_tmux_bar import set_tmux_bar
except Exception:  # pragma: no cover - optional on development hosts
    def set_tmux_bar(
        *,
        snapshot: dict | None = None,
        mode: str | None = None,
        wopr_caller: str | None = None,
        force: bool = False,
    ) -> None:
        pass


os.environ["TERM"] = os.environ.get("TERM") or "linux"
CHAT_FIFO = CACHE / "chat_in"
HEARTBEAT = CACHE / "lcd_heartbeat"
ERR_LOG = Path("/tmp/zealot_display_err.log")

# CGA palette — foreground on black for TFT readability
PAIR_BORDER = 1      # dim cyan — rules only
PAIR_TITLE = 2       # bright cyan — header
PAIR_TREE = 3        # white — idle tab
PAIR_TREE_SEL = 4    # yellow — active tab (no reverse)
PAIR_PANEL = 5       # white — panel labels
PAIR_CYAN = 6        # cyan on black — NOC / headers
PAIR_MAG = 7         # magenta on black — ST / bridge
PAIR_GREEN = 8       # green on black — RPG / OK
PAIR_YELLOW = 9      # yellow on black — PBX / warn
PAIR_RED = 10        # red on black — alerts
PAIR_DIM = 11        # white dim — SYS
PAIR_INPUT = 12      # green on black — command line
PAIR_LOG = 13        # white on black — IRC log
PAIR_TICK = 14       # magenta on black — tick bar
PAIR_ART = 15        # cyan on black — ASCII art
PAIR_TAB_ON = 16     # yellow bold — active mode tab
PAIR_ZP = 17
PAIR_ZH = 18
PAIR_RPG = 19
PAIR_ST = 20
PAIR_PBX = 21
PAIR_PBX_CALL = 25
PAIR_NOC = 22
PAIR_RGB = 23
PAIR_GMQ = 24
PAIR_MOTD = 26       # bright yellow — MOTD body
PAIR_MOTD_FX = 27    # dim cyan — scroller edge glyphs only
PAIR_IRC_CHAN = 28   # cyan — channel tag
PAIR_IRC_MSG = 29    # white — message body

_FRAME_W = WIDTH
_FRAME_H = HEIGHT


def begin_frame(stdscr) -> tuple[int, int]:
    """Match render width/height to the live TFT curses geometry."""
    global _FRAME_W, _FRAME_H
    screen_h, screen_w = stdscr.getmaxyx()
    fallback_w = lcd_frame_cols(WIDTH)
    _FRAME_W = max(32, screen_w) if screen_w > 0 else fallback_w
    _FRAME_H = max(8, min(HEIGHT, screen_h)) if screen_h > 0 else HEIGHT
    return _FRAME_W, _FRAME_H


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
        (PAIR_BORDER, curses.COLOR_CYAN, curses.COLOR_BLACK),
        (PAIR_TITLE, curses.COLOR_CYAN, curses.COLOR_BLACK),
        (PAIR_TREE, curses.COLOR_WHITE, curses.COLOR_BLACK),
        (PAIR_TREE_SEL, curses.COLOR_YELLOW, curses.COLOR_BLACK),
        (PAIR_PANEL, curses.COLOR_WHITE, curses.COLOR_BLACK),
        (PAIR_CYAN, curses.COLOR_CYAN, curses.COLOR_BLACK),
        (PAIR_MAG, curses.COLOR_MAGENTA, curses.COLOR_BLACK),
        (PAIR_GREEN, curses.COLOR_GREEN, curses.COLOR_BLACK),
        (PAIR_YELLOW, curses.COLOR_YELLOW, curses.COLOR_BLACK),
        (PAIR_RED, curses.COLOR_RED, curses.COLOR_BLACK),
        (PAIR_DIM, curses.COLOR_WHITE, curses.COLOR_BLACK),
        (PAIR_INPUT, curses.COLOR_GREEN, curses.COLOR_BLACK),
        (PAIR_LOG, curses.COLOR_WHITE, curses.COLOR_BLACK),
        (PAIR_TICK, curses.COLOR_MAGENTA, curses.COLOR_BLACK),
        (PAIR_ART, curses.COLOR_CYAN, curses.COLOR_BLACK),
        (PAIR_TAB_ON, curses.COLOR_YELLOW, curses.COLOR_BLACK),
        (PAIR_ZP, curses.COLOR_CYAN, curses.COLOR_BLACK),
        (PAIR_ZH, curses.COLOR_GREEN, curses.COLOR_BLACK),
        (PAIR_RPG, curses.COLOR_GREEN, curses.COLOR_BLACK),
        (PAIR_ST, curses.COLOR_MAGENTA, curses.COLOR_BLACK),
        (PAIR_PBX, curses.COLOR_YELLOW, curses.COLOR_BLACK),
        (PAIR_PBX_CALL, curses.COLOR_YELLOW, curses.COLOR_BLACK),
        (PAIR_NOC, curses.COLOR_CYAN, curses.COLOR_BLACK),
        (PAIR_RGB, curses.COLOR_MAGENTA, curses.COLOR_BLACK),
        (PAIR_GMQ, curses.COLOR_MAGENTA, curses.COLOR_BLACK),
        (PAIR_MOTD, curses.COLOR_YELLOW, curses.COLOR_BLACK),
        (PAIR_MOTD_FX, curses.COLOR_CYAN, curses.COLOR_BLACK),
        (PAIR_IRC_CHAN, curses.COLOR_CYAN, curses.COLOR_BLACK),
        (PAIR_IRC_MSG, curses.COLOR_WHITE, curses.COLOR_BLACK),
    )
    for pair, fg, bg in pairs:
        try:
            curses.init_pair(pair, fg, bg)
        except curses.error:
            pass


def attr_for(style: str, bold: bool = False, now: float | None = None, row: int = 0) -> int:
    phase = anim_now(now)
    pair = {
        "BORDER": PAIR_BORDER,
        "TITLE": PAIR_TITLE,
        "TREE": PAIR_TREE,
        "TREE_SEL": PAIR_TREE_SEL,
        "TAB": PAIR_TREE,
        "TAB_ON": PAIR_TAB_ON,
        "PANEL": PAIR_PANEL,
        "CYAN": PAIR_CYAN,
        "MAG": PAIR_MAG,
        "GREEN": PAIR_GREEN,
        "YELLOW": PAIR_YELLOW,
        "RED": PAIR_RED,
        "SYS": PAIR_DIM,
        "INPUT": PAIR_INPUT,
        "LOG": PAIR_LOG,
        "TICK": PAIR_TICK,
        "ART": PAIR_ART,

        "RPG": PAIR_RPG,
        "ST": PAIR_ST,
        "GMQ": PAIR_GMQ,
        "PBX": PAIR_PBX,
        "PBX_CALL": PAIR_PBX_CALL,
        "PCORP": PAIR_PBX,
        "NOC": PAIR_NOC,
        "RGB": PAIR_RGB,
        "ZH": PAIR_ZH,
        "ZP": PAIR_ZP,
        "IRC": PAIR_LOG,
        "EVENT": PAIR_LOG,
        "GLINT": PAIR_CYAN,
        "GREETZ": PAIR_MOTD,
        "MOTIVE": PAIR_MOTD,
        "MOTD": PAIR_MOTD,
        "MOTD_FX": PAIR_MOTD_FX,
        "IRC_CHAN": PAIR_IRC_CHAN,
        "IRC_TIME": PAIR_DIM,
        "IRC_MSG": PAIR_IRC_MSG,
        "IRC_ACT": PAIR_MAG,
        "IRC_NICK": PAIR_YELLOW,
        "SCROLLER": PAIR_MOTD,
        "BANNER": PAIR_MAG,
        "RASTER": PAIR_BORDER,
    }.get(style, PAIR_LOG)
    attr = curses.color_pair(pair)
    if style in ("SYS", "IRC_TIME"):
        attr |= curses.A_DIM
    if style in ("TITLE", "TAB_ON", "CYAN"):
        attr |= curses.A_BOLD
    if style in ("MOTD", "GREETZ", "MOTIVE", "IRC_MSG"):
        attr |= curses.A_BOLD
    if style in ("IRC_CHAN", "IRC_NICK", "ZP", "ZH", "RPG", "ST", "PBX", "NOC", "CYAN", "MAG", "RGB", "GREEN", "YELLOW", "RED", "TICK", "ART", "LOG", "GMQ"):
        attr |= curses.A_BOLD
    if style == "MOTD_FX":
        attr |= curses.A_DIM
    if style == "PBX_CALL":
        attr |= curses.A_BOLD | curses.A_REVERSE
        if int((now or time.time())) % 2 == 0:
            pair = PAIR_RED
            attr = curses.color_pair(pair) | curses.A_BOLD | curses.A_REVERSE
    if style == "BORDER":
        attr |= curses.A_DIM
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
    if row < 0 or row >= _FRAME_H:
        return
    value = pad(text, _FRAME_W) if raw else fit(text, _FRAME_W)
    try:
        stdscr.addnstr(row, 0, value, _FRAME_W, attr_for(style, bold, now, row))
    except curses.error:
        pass


def add_segment_line(
    stdscr,
    row: int,
    segments: list[tuple[str, str]],
    now: float | None = None,
) -> None:
    if row < 0 or row >= _FRAME_H:
        return
    col = 0
    for text, style in segments:
        if col >= _FRAME_W:
            break
        chunk = text[: _FRAME_W - col]
        if not chunk:
            continue
        try:
            stdscr.addnstr(row, col, chunk, len(chunk), attr_for(style, now=now, row=row))
        except curses.error:
            pass
        col += len(chunk)


def drain_startup_keys(stdscr, seconds: float = 0.35) -> None:
    """Drop tmux send-keys / shell echo that lands in the curses input queue."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        if stdscr.getch() == -1:
            time.sleep(0.03)


def send_to_zealot(message: str) -> None:
    text = message.strip()
    if not text or FEED_NOISE_RE.search(text):
        return
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        CHAT_FIFO.write_text(text, encoding="utf-8")
    except OSError:
        pass


def draw_raw(stdscr, row: int, text: str, pair: int, flags: int = 0) -> None:
    if row < 0 or row >= _FRAME_H:
        return
    try:
        stdscr.addnstr(row, 0, pad(text, _FRAME_W), _FRAME_W, curses.color_pair(pair) | flags)
    except curses.error:
        pass


def _sip_overlay_allowed(sip_flash) -> bool:
    """Joshua ext 124 keeps the normal NOC mesh unless WarGames are live (WOPR path)."""
    if sip_flash is None:
        return False
    to_ext = str(getattr(sip_flash, "to_ext", "") or "").strip()
    if to_ext == "124":
        return False
    return True


def _sip_transcript_pair(style: str) -> int:
    return {
        "user": PAIR_GREEN,
        "agent": PAIR_MAG,
        "dim": PAIR_DIM,
    }.get(style, PAIR_LOG)


def draw_sip_overlay(stdscr, sip_flash, now: float, input_row: int) -> None:
    flash_on = int(anim_now(now, 2.0) // 2) % 2 == 0
    headline = str(getattr(sip_flash, "headline", "") or "PBX CALL")[:_FRAME_W]
    state = str(getattr(sip_flash, "active_state", "") or "active").upper()
    subline = str(getattr(sip_flash, "subline", "") or "")[:_FRAME_W]
    detail = str(getattr(sip_flash, "detail", "") or "")[:_FRAME_W]
    try:
        active_lines = max(1, int(getattr(sip_flash, "active_lines", 1) or 1))
    except (TypeError, ValueError):
        active_lines = 1

    header_rows = 4
    transcript_rows = max(1, input_row - header_rows)
    transcript_fn = getattr(sip_flash, "transcript_lines", None)
    if callable(transcript_fn):
        lines = transcript_fn(_FRAME_W, transcript_rows, now)
    else:
        lines = [("AWAITING TRANSCRIPT...", "dim")]

    for row in range(input_row):
        draw_raw(stdscr, row, " " * _FRAME_W, PAIR_BORDER, curses.A_DIM)

    title = f"CALL {headline} | {active_lines}LN {state}"[:_FRAME_W]
    draw_raw(stdscr, 0, title, PAIR_YELLOW if flash_on else PAIR_TITLE, curses.A_BOLD | curses.A_REVERSE)
    draw_raw(stdscr, 1, fit(subline, _FRAME_W), PAIR_CYAN, curses.A_BOLD)
    draw_raw(stdscr, 2, fit(detail, _FRAME_W), PAIR_MAG, curses.A_BOLD)
    draw_raw(stdscr, 3, section_bar("TRANSCRIPT", _FRAME_W), PAIR_BORDER, curses.A_DIM)

    row = header_rows
    for text, style in lines:
        if row >= input_row:
            break
        pair = _sip_transcript_pair(style)
        flags = curses.A_BOLD if style in ("user", "agent") else curses.A_DIM
        draw_raw(stdscr, row, fit(text, _FRAME_W), pair, flags)
        row += 1

    draw_raw(stdscr, input_row, "F1Help > live call transcript", PAIR_INPUT, curses.A_BOLD)


def draw(stdscr, snapshot: dict, input_buf: str, now: float, tick: int, sip_flash=None) -> None:
    mode = mode_name(now)
    frame_w, frame_h = begin_frame(stdscr)
    input_row = frame_h - 1
    footer_row = input_row - 1
    stdscr.erase()
    # Full-screen WOPR only during live WarGames (active game + call turns).
    # Otherwise stay on the normal mesh dashboard; DEFCON shows in ticker/ops panel.
    wopr_session = poll_joshua_wopr() if poll_joshua_wopr else None
    if wopr_session and draw_wopr_overlay is not None:
        set_tmux_bar(
            snapshot=snapshot,
            mode=mode,
            wopr_caller=str(wopr_session.get("caller_ext") or "?"),
        )
        draw_wopr_overlay(
            stdscr,
            wopr_session,
            now,
            input_row,
            frame_w,
            pair_title=PAIR_TITLE,
            pair_green=PAIR_GREEN,
            pair_yellow=PAIR_YELLOW,
            pair_red=PAIR_RED,
            pair_dim=PAIR_DIM,
            pair_input=PAIR_INPUT,
            pair_cyan=PAIR_CYAN,
            pair_magenta=PAIR_MAG,
            draw_fn=draw_raw,
        )
        return
    sip_active = (
        sip_flash is not None
        and getattr(sip_flash, "active", lambda: False)()
        and _sip_overlay_allowed(sip_flash)
    )
    set_tmux_bar(snapshot=snapshot, mode=mode)
    # Live PBX call: full-screen transcript takeover (mesh dashboard resumes after hangup).
    if sip_active and sip_flash is not None:
        draw_sip_overlay(stdscr, sip_flash, now, input_row)
        stdscr.refresh()
        return
    call_exts = set(getattr(sip_flash, "active_exts", set()) or ()) if sip_flash is not None else set()
    panel_mode = mode
    zones = lcd_frame_zones(frame_h)

    # --- Header (3 rows): ZEAL clock, WOPR/DEFCON, rotating mesh ticker ---
    add_segment_line(stdscr, zones["header_start"], top_status_segments(now, frame_w), now=now)
    add_segment_line(
        stdscr,
        zones["header_start"] + 1,
        wopr_header_segments(panel_mode, now, frame_w),
        now=now,
    )
    add_line(
        stdscr,
        zones["header_start"] + 2,
        chunky_scroller(
            ticker_scroll_body(snapshot, now),
            anim_now(now),
            frame_w,
            speed=TICKER_SCROLLER_SPEED,
        ),
        "NOC",
        bold=True,
        raw=True,
        now=now,
    )

    # --- WORK / TO-MON phase row with ANSI progress bar ---
    add_segment_line(stdscr, zones["mode_bar"], weekend_monday_countdown_segments(now, frame_w), now=now)

    # --- Centered ANSI mode art (3 rows) ---
    if panel_mode == "agents":
        art_rows = agents_art_live(snapshot, frame_w, now=now)
    else:
        art_rows = mode_art_compact(panel_mode, now, frame_w)
    for offset, art_row in enumerate(art_rows):
        add_line(stdscr, zones["art_start"] + offset, art_row, "ART", raw=True, now=now)

    # --- Panel zone (fixed 7 rows): NOC HOST TABLE / agents / RPG / lounge / etc. ---
    panel_row = zones["panel_start"]
    for idx, (text, style) in enumerate(
        panel_lines(
            snapshot,
            panel_mode,
            frame_w,
            now,
            call_exts,
            sip_flash=None,
            max_rows=LCD_PANEL_MAX_ROWS,
        )
    ):
        if panel_row >= zones["calendar_row"]:
            break
        if isinstance(text, list):
            add_segment_line(stdscr, panel_row, text, now=now)
        else:
            add_line(stdscr, panel_row, text, style, bold=(idx == 0), raw=True, now=now)
        panel_row += 1

    # --- Mid footer: calendar week countdown + host/motd scroller ---
    add_segment_line(stdscr, zones["calendar_row"], calendar_segments(now, frame_w), now=now)
    add_segment_line(stdscr, zones["status_row"], dashboard_footer_segments(snapshot, now, tick, frame_w), now=now)

    # --- Demoscene FX strip: rotating greetz / tunnel bus / sparkle / raster ---
    add_line(stdscr, zones["fx_row"], demoscene_fx_row(snapshot, now, frame_w), "GREETZ", raw=True, now=now)

    # --- Events zone (reserved rows, tail-pinned, colored segments) ---
    add_line(stdscr, zones["events_hdr"], comet_line("EVENTS", now + 2.0, frame_w), "GLINT", raw=True, now=now + 2.0)
    event_slot_rows: list[list[tuple[str, str]]] = []
    for event in snapshot.get("events") or []:
        if event_is_recurring_noise(event):
            continue
        event_slot_rows.extend(
            event_display_rows(event, frame_w, now=now, max_body_lines=LCD_EVENT_MAX_BODY_LINES)
        )
    event_slots = max(1, zones["events_end"] - zones["events_start"])
    event_slot_rows = event_slot_rows[-event_slots:]
    # Bottom-pin chatter like a chat log: freshest line sits just above the input row.
    start_row = zones["events_end"] - len(event_slot_rows)
    for idx, segments in enumerate(event_slot_rows):
        row = start_row + idx
        if row < zones["events_start"] or row >= zones["events_end"]:
            continue
        add_segment_line(stdscr, row, segments, now=now)

    if input_buf:
        input_text = fit("> " + input_buf[-(frame_w - 3) :], frame_w)
    else:
        input_text = lcd_status_line(snapshot, mode, now, frame_w)
    add_line(stdscr, zones["input_row"], input_text, "INPUT", bold=True, now=now)
    stdscr.refresh()


def main(stdscr) -> None:
    curses.curs_set(0)
    init_colors()
    stdscr.nodelay(True)
    stdscr.timeout(350)
    drain_startup_keys(stdscr)
    try:
        stdscr.bkgd(" ", curses.color_pair(PAIR_DIM))
    except curses.error:
        pass

    CACHE.mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGUSR1, lambda _sig, _frame: heartbeat())

    irc_tap = IrcTap()
    irc_tap.start()
    noc_mesh = NocMeshStatus() if NocMeshStatus else None
    sip_flash = SipCallFlash(figlet_lines) if SipCallFlash else None

    snapshot = collect_snapshot(irc_tap)
    last_snapshot = 0.0
    input_buf = ""
    session_tick = 0

    while True:
        now = time.time()
        session_tick += 1
        heartbeat(now)
        try:
            if noc_mesh is not None:
                try:
                    noc_mesh.poll()
                    if noc_mesh.router_flashbang(stdscr):
                        heartbeat(now)
                        stdscr.refresh()
                        time.sleep(0.15)
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

            draw(stdscr, snapshot, input_buf, now, session_tick, sip_flash)

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