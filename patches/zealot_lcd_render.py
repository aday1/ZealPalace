#!/usr/bin/env python3
"""Pure text rendering helpers for the ZealPalace LCD."""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import textwrap
import time
import zlib
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from zealot_lcd_feeds import LcdEvent, SPAWN_BODY_RE, clip_sentence, parse_iso_ts, short_text

try:
    from zealot_sip_flash import (
        read_active_call_exts_highlight,
        read_ext_last_call_ts,
        transcript_panel_segment_rows,
    )
except Exception:  # pragma: no cover - optional on development hosts
    def read_active_call_exts_highlight(path=None) -> set[str]:
        return set()

    def read_ext_last_call_ts(path=None) -> dict[str, float]:
        return {}

    def transcript_panel_segment_rows(
        turns: list,
        width: int,
        max_rows: int,
        now: float | None = None,
    ) -> list[tuple[list[tuple[str, str]], str]]:
        return []

try:
    from zealot_wopr_lcd import joshua_defcon_ticker
except Exception:  # pragma: no cover - optional on development hosts
    def joshua_defcon_ticker(path=None) -> str:
        return "J124 DEFCON 5 STANDBY"


WIDTH = 40
HEIGHT = 34

# Fixed TFT frame budget (40x34 TerminusBold14). Prevents header/panel/footer overlap.
LCD_HEADER_ROWS = 3
LCD_MODE_BAR_ROWS = 1
LCD_ART_ROWS = 3
LCD_PANEL_MAX_ROWS = 5
LCD_MID_FOOTER_ROWS = 2
LCD_FX_ROWS = 1
LCD_EVENTS_HEADER_ROWS = 1
LCD_EVENTS_MIN_ROWS = 14
LCD_EVENTS_ON_SCREEN = 24
LCD_EVENT_MAX_BODY_LINES = 14
LCD_EVENT_OLD_CHATTER_LINES = 6
LCD_EVENT_OLD_MAX_LINES = 6
LCD_EVENT_OLD_NARRATIVE_LINES = 3
NARRATIVE_EVENT_KINDS = frozenset(
    {
        "lore",
        "bridge",
        "gm_queue",
        "gm",
        "battle",
        "realm_event",
        "travel",
        "weather",
        "notice",
        "world",
        "pulse",
        "spawn",
        "birth",
        "rebirth",
        "rpg",
    }
)
LCD_EVENT_DANGLING_WORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "against",
        "to",
        "of",
        "in",
        "on",
        "at",
        "for",
        "and",
        "or",
        "but",
        "with",
        "from",
        "into",
        "onto",
        "upon",
        "over",
        "under",
        "about",
        "as",
        "by",
    }
)

# Per-IRC-nick CGA color (Crystal Mesh party + terrarium NPCs).
IRC_NICK_STYLES: dict[str, str] = {
    "yomiko": "MAG",
    "rei": "CYAN",
    "nyx": "RGB",
    "mira": "GREEN",
    "misato": "YELLOW",
    "celes": "ST",
    "holybell": "ZH",
    "vexara": "PBX",
    "aeris": "NOC",
    "zealot": "ZP",
    "chmod": "RED",
    "n0va": "TICK",
    "nova": "TICK",
    "glitchgrl": "GMQ",
    "pixel": "RPG",
    "lyric": "ART",
    "riff": "GREEN",
    "vendor": "YELLOW",
    "cleric": "ST",
    "sybil": "MAG",
    "vex": "RGB",
    "index": "CYAN",
    "botmcbotface": "LOG",
    "joshua": "RED",
    "grepzilla": "GREEN",
    "kernelix": "CYAN",
    "spectralbyte": "MAG",
    "dark": "RED",
    "sage": "YELLOW",
    "glitch": "GMQ",
    "dm": "PBX",
    "rift": "CYAN",
    "hex": "RGB",
}


def lcd_frame_cols(fallback: int = WIDTH) -> int:
    """Physical TFT column count — env LCD_COLS or default 40 (320px / TerminusBold14)."""
    raw = os.environ.get("LCD_COLS", "").strip()
    if raw.isdigit():
        return max(32, min(80, int(raw)))
    return fallback
MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# Calm LCD timing — step visuals instead of every refresh tick.
MODE_PERIOD_SEC = 18.0
METRIC_CYCLE_SEC = 12.0
# pct_hdr (4), metric_id, bar_label (10) — bar_label is the readable column title.
METRIC_CYCLE: tuple[tuple[str, str, str], ...] = (
    ("CPU%", "cpu", "CPU USAGE"),
    ("MEM%", "mem", "MEMORY USE"),
    ("DIS%", "disk", "DISK SPACE"),
    ("GPU%", "gpu", "GPU UTIL  "),
    ("LOD%", "load1", "LOAD 1MIN "),
    ("TMP%", "temp", "CPU TEMP  "),
    ("NET%", "net", "NET TRAFF "),
)
ANIM_STEP_SEC = 5.0
MARQUEE_SPEED = 1.8
SCROLLER_SPEED = 1.2
TICKER_SCROLLER_SPEED = 0.58
FOOTER_SCROLLER_SPEED = 0.35
FOOTER_FRAME_PERIOD_SEC = 15.0
LCD_TICKER_VERSION = "tkr0624q"
TICKER_FRAME_PERIOD_SEC = 8.0
FLOURISH_BURST_PERIOD_SEC = 12.0
FLOURISH_BURST_WINDOW_SEC = 2.5
FLOURISH_TICK_SEC = 0.35
FLOURISH_BRACKET_PAIRS: tuple[tuple[str, str], ...] = (
    ("<", ">"),
    ("[", "]"),
    ("{", "}"),
    ("(", ")"),
)
WORK_OPEN_HOUR = 10
WORK_CLOSE_HOUR = 17
AGENT_CALL_FRESH_SEC = 2 * 3600
AGENT_TICKER_SHOW_SEC = 25 * 60
AGENT_TICKER_IDLE_RE = re.compile(
    r"(?i)(quiet|no tickets|ticket desk idle|intake folder|standing by|"
    r"no prior calls|file open|awaiting further|tap navi|parody counsel)"
)
# Header ticker row: PBX agents whose call summaries rotate on row 3.
AGENT_TICKER_ROSTER: tuple[tuple[str, str], ...] = (
    ("111", "HERMES"),
    ("117", "HOLLY"),
    ("122", "NAVI"),
    ("123", "BOFH"),
    ("130", "LAWYER"),
)
_AGENT_TICKER_SEEN: dict[str, tuple[str, float]] = {}
RASTER_SPEED = 0.35
TUNNEL_SPEED = 0.2
COMET_SPEED = 1.5
SPARKLE_SPEED = 0.8
GREETZ_PERIOD_SEC = 28
MOTIVE_PERIOD_SEC = 45
RGB_FRAME_SEC = 10.0

XTREE_MODES: tuple[str, ...] = (
    "terrarium",
    "uptime",
    "ops",
    "rpg",
    "rgb",
    "agents",
    "bridge",
    "lounge",
)
MODE_TITLES: dict[str, str] = {
    "terrarium": "TERRARIUM",
    "uptime": "UPTIME",
    "ops": "NOC OPS",
    "rpg": "CRYSTAL RPG",
    "rgb": "RGB BATTLE",
    "agents": "PBX AGENTS",
    "bridge": "ST BRIDGE",
    "lounge": "IRC LOUNGE",
}
# Legacy aliases used by older render helpers.
XTREE_LABELS = MODE_TITLES
XTREE_TREE_W = 5
XTREE_BODY_W = WIDTH - XTREE_TREE_W
TAB_W = 5
MODE_TAB_SHORT: dict[str, str] = {
    "terrarium": "TERR",
    "uptime": "UPTM",
    "ops": "NOC",
    "rpg": "CRPG",
    "rgb": "RGB",
    "agents": "AGNT",
    "bridge": "BRDG",
    "lounge": "LOUN",
}
PANEL_SECTION_LABELS: dict[str, str] = {
    "terrarium": "LAN VITALS",
    "uptime": "BOOT AGE",
    "ops": "NOC DETAIL",
    "rpg": "CRYSTAL RPG",
    "rgb": "RGB BATTLE",
    "agents": "PBX ROSTER",
    "bridge": "COMPANIONS",
    "lounge": "LIVE CHATTER",
}
TAB_SHORT = dict(MODE_TAB_SHORT)

MESH_COL_ASCII = "ASCII BAR"
MESH_COL_BLOCK = "BLOCK BAR"
DETAIL_KEY_W = 12
OPS_DETAIL_KEY_W = 10
TERRARIUM_DETAIL_KEY_W = 10
VITALS_BAR_W = 12
# ~10 chars/s: long detail lines finish well inside the 18s mode window.
DETAIL_SCROLL_SPEED = 10.0
IRC_SCROLL_SPEED = 9.0
PBX_AGENT_VISIBLE = 4
PBX_AGENT_VISIBLE_CALL = 2
PBX_TRANSCRIPT_ROWS = 3
HUMAN_EXTS = frozenset({"100", "101", "102", "110"})
AGENT_EXT_W = 4
AGENT_LAST_W = 12
AGENT_NAME_W = WIDTH - AGENT_EXT_W - 1 - AGENT_LAST_W - 1
PBX_AGENT_ROSTER: tuple[tuple[str, str], ...] = (
    ("111", "Hermes"),
    ("117", "Mr Holand"),
    ("122", "Navi"),
    ("124", "Joshua WOPR"),
    ("128", "Imagine"),
    ("129", "Imagine Live"),
    ("112", "Grok Unhinged"),
    ("113", "Grok Therapist"),
    ("114", "Grok Conspiracy"),
    ("115", "Grok Default"),
    ("116", "Grok Storytel"),
    ("118", "Grok Adventure"),
    ("119", "Grok Motivator"),
    ("120", "Grok Custom"),
    ("123", "IT BoFH"),
    ("690", "Yomiko Readline"),
    ("691", "Rei Patchbay"),
    ("692", "Nyx Breakpoint"),
    ("693", "Mira Yggdrasil"),
    ("694", "Misato NeonOps"),
    ("695", "Celes Runecompiler"),
    ("696", "Holybell Firewall"),
    ("697", "Bellona Skyforge"),
    ("698", "Aeris Gardenbyte"),
)

# Per-host CGA colors for NOC disk detail and mesh table rows.
HOST_LABEL_STYLES: dict[str, str] = {
    "ZEA": "NOC",
    "ZTW": "ST",
    "VEC": "RPG",
    "NIF": "MAG",
    "ASG": "YELLOW",
    "LAI": "ZP",
}
DISK_USAGE_WARN_PCT = 75.0
DISK_USAGE_CRIT_PCT = 90.0

# Per-companion CGA colors for the COMPANIONS scroller (Crystal Mesh 690-698).
COMPANION_LINE_COLORS: tuple[str, ...] = (
    "MAG",
    "CYAN",
    "RGB",
    "GREEN",
    "YELLOW",
    "ST",
    "ZH",
    "PBX",
    "NOC",
    "ZP",
    "RED",
    "RPG",
    "GMQ",
    "TICK",
    "ART",
)


def fit(text: Any, width: int = WIDTH) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(value) > width:
        value = value[: max(0, width - 1)] + "~"
    return pad(value, width)


def pad(text: Any, width: int = WIDTH) -> str:
    value = str(text or "")
    if len(value) > width:
        value = value[:width]
    return value.ljust(width)


def center(text: Any, width: int = WIDTH) -> str:
    value = str(text or "").strip()
    if len(value) >= width:
        return value[:width]
    pad_total = width - len(value)
    left = pad_total // 2
    return " " * left + value + " " * (pad_total - left)


def scroll_speed_for_text(text: str, period: float, width: int = WIDTH) -> float:
    """Pick a marquee speed that traverses the full line within one display period."""
    core = normalize_line(text)
    travel = max(0, len(core) + 3 - width)
    if travel <= 0:
        return TICKER_SCROLLER_SPEED
    return min(4.0, max(0.6, travel / max(1.0, period)))


def fmt_duration_short(seconds: Any) -> str:
    try:
        value = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        return "?"
    days, rem = divmod(value, 86400)
    hours = rem // 3600
    minutes = (rem % 3600) // 60
    if days:
        return f"{days}d{hours:02d}h"
    if hours:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m"


WIPE_TIMESTAMPS_FILE = Path.home() / ".cache" / "zealot" / "wipe_timestamps.json"


def meteor_strike_age_label(now: float | None = None) -> str:
    """Compact age since last meteor wipe for the physical tmux row."""
    ts = time.time() if now is None else now
    try:
        data = json.loads(WIPE_TIMESTAMPS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return "MET ?"
    raw = str(data.get("last_meteor") or data.get("last_genesis") or "").strip()
    if not raw:
        return "MET ?"
    strike = parse_iso_ts(raw)
    if strike <= 0:
        return "MET ?"
    return f"MET+{fmt_duration_short(int(ts - strike))}"


def calendar_line(now: float | None = None, width: int = WIDTH) -> str:
    ts = time.time() if now is None else now
    return "".join(text for text, _style in calendar_segments(ts, width))


def normalize_line(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def calendar_segments(now: float | None = None, width: int = WIDTH) -> list[tuple[str, str]]:
    """Calendar row — full weekday + date + ISO week, centered (week bars live in header)."""
    ts = time.time() if now is None else now
    dt = datetime.fromtimestamp(ts)
    month = MONTH_NAMES[max(0, min(11, dt.month - 1))]
    iso_week = max(1, min(52, int(dt.isocalendar().week)))
    core = f"{dt:%A} {dt.day:02d} {month} - Week {iso_week}/52"
    return flourished_title_segments(core, ts, width, salt="calendar", title_style="CYAN", pad_to=width)


def _weekly_milestones(dt: datetime) -> tuple[datetime, datetime, datetime]:
    """Work Mon 10:00, work Fri 17:00, and the Mon 10:00 that ends the weekend phase."""
    mon0 = (dt - timedelta(days=dt.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    this_mon_10 = mon0.replace(hour=WORK_OPEN_HOUR, minute=0, second=0, microsecond=0)
    this_fri_17 = mon0 + timedelta(days=4, hours=WORK_CLOSE_HOUR)
    next_mon_10 = mon0 + timedelta(days=7, hours=WORK_OPEN_HOUR)
    if dt.weekday() == 0 and dt < this_mon_10:
        prev_mon0 = mon0 - timedelta(days=7)
        return (
            prev_mon0.replace(hour=WORK_OPEN_HOUR, minute=0, second=0, microsecond=0),
            prev_mon0 + timedelta(days=4, hours=WORK_CLOSE_HOUR),
            this_mon_10,
        )
    return this_mon_10, this_fri_17, next_mon_10


def work_week_phase(dt: datetime) -> str:
    mon_10, fri_17, next_mon_10 = _weekly_milestones(dt)
    if mon_10 <= dt < fri_17:
        return "work"
    return "weekend"


def _span_pct(start: datetime, end: datetime, dt: datetime) -> float:
    total = (end - start).total_seconds()
    if total <= 0:
        return 0.0
    elapsed = (dt - start).total_seconds()
    return max(0.0, min(100.0, (elapsed / total) * 100.0))


def work_week_countdown_line(now: float | None = None, width: int = WIDTH) -> str:
    ts = time.time() if now is None else now
    return "".join(text for text, _style in work_week_compact_segments(ts, width))


def weekend_monday_countdown_line(now: float | None = None, width: int = WIDTH) -> str:
    ts = time.time() if now is None else now
    return "".join(text for text, _style in weekend_monday_countdown_segments(ts, width))


def work_week_progress(dt: datetime) -> tuple[float, int, str, str, str]:
    """Return pct_val, pct_int, countdown, phase tag, bar color for the active week phase."""
    mon_10, fri_17, next_mon_10 = _weekly_milestones(dt)
    if work_week_phase(dt) == "work":
        pct_val = _span_pct(mon_10, fri_17, dt)
        left = max(0, int((fri_17 - dt).total_seconds()))
        return pct_val, int(round(pct_val)), fmt_duration_short(left), "WORK", "GREEN"
    pct_val = _span_pct(fri_17, next_mon_10, dt)
    left = max(0, int((next_mon_10 - dt).total_seconds()))
    return pct_val, int(round(pct_val)), fmt_duration_short(left), "TO-MON", "MAG"


def _fri_progress(dt: datetime) -> tuple[float, int]:
    """Progress + seconds toward this work-week's Friday 17:00 (100% once closed)."""
    mon_10, fri_17, _next_mon_10 = _weekly_milestones(dt)
    if dt >= fri_17:
        return 100.0, 0
    return _span_pct(mon_10, fri_17, dt), max(0, int((fri_17 - dt).total_seconds()))


def _mon_progress(dt: datetime) -> tuple[float, int]:
    """Progress + seconds toward Monday 10:00 across the whole week (always advancing)."""
    mon_10, _fri_17, next_mon_10 = _weekly_milestones(dt)
    secs = max(0, int((next_mon_10 - dt).total_seconds()))
    return _span_pct(mon_10, next_mon_10, dt), secs


def labeled_week_rail(
    now: float,
    width: int,
    label: str,
    pct_val: float,
    dur_secs: int,
    bar_style: str,
) -> list[tuple[str, str]]:
    """Normalized weekly counter: <LABEL> [*###---*] pct countdown, padded to width."""
    if width < 10:
        return [(fit(label, width), bar_style)]
    pct = int(round(pct_val))
    dur = fmt_duration_short(dur_secs)
    plb, prb, pstyle = flourish_bar_brackets(now, label)
    prefix: list[tuple[str, str]] = [(plb, pstyle), (label, "CYAN"), (prb, pstyle), (" ", "SYS")]
    prefix_len = sum(len(text) for text, _style in prefix)
    blb, brb, bbst = flourish_bar_brackets(now, label + "-bar")
    fixed = prefix_len + len(blb) + len(brb)
    for tail in (f" {pct}% {dur}", f" {pct}%", f" {dur}", ""):
        bar_w = width - fixed - len(tail)
        if bar_w >= 6:
            segments: list[tuple[str, str]] = [
                *prefix,
                (blb, bbst),
                *progress_bar_segments(pct_val, bar_w, bar_style),
                (brb, bbst),
            ]
            if tail:
                segments.extend(countdown_tail_segments(pct, dur, now, "GREEN"))
            return pad_colored_segments(segments, width)
    bar_w = max(3, width - fixed)
    return pad_colored_segments(
        [*prefix, (blb, bbst), *progress_bar_segments(pct_val, bar_w, bar_style), (brb, bbst)],
        width,
    )


def progress_bar_segments(
    pct: float,
    width: int,
    fill_style: str,
    empty_style: str = "SYS",
) -> list[tuple[str, str]]:
    w = max(6, width)
    inner = max(4, w - 2)
    clamped = max(0.0, min(100.0, float(pct)))
    filled = int(round((clamped / 100.0) * inner))
    if clamped > 0.0 and filled == 0:
        filled = 1
    empty = max(0, inner - filled)
    return [
        ("*", fill_style),
        ("#" * filled, fill_style),
        ("-" * empty, empty_style),
        ("*", fill_style),
    ]


def flourish_pulse(now: float, period: float = FLOURISH_BURST_PERIOD_SEC) -> float:
    t = float(now) % period
    start = period - FLOURISH_BURST_WINDOW_SEC
    if t < start:
        return 0.0
    x = (t - start) / FLOURISH_BURST_WINDOW_SEC
    return x * x * (3.0 - 2.0 * x)


def flourish_tick(now: float) -> int:
    return int(float(now) / FLOURISH_TICK_SEC)


def flourish_bracket_pair(now: float, salt: str = "") -> tuple[str, str]:
    idx = (flourish_tick(now) + (zlib.crc32(salt.encode()) & 0xFF)) % len(FLOURISH_BRACKET_PAIRS)
    return FLOURISH_BRACKET_PAIRS[idx]


def flourish_spark(now: float, offset: int = 0) -> str:
    tick = flourish_tick(now) + offset
    return SCROLLER_FX_GLINT[tick % len(SCROLLER_FX_GLINT)]


def flourish_bar_brackets(now: float, salt: str) -> tuple[str, str, str]:
    pulse = flourish_pulse(now)
    lb, rb = flourish_bracket_pair(now, salt)
    style = "YELLOW" if pulse > 0.4 else "MOTD_FX"
    return lb, rb, style


def countdown_tail_segments(
    pct: int,
    dur: str,
    now: float,
    base_style: str = "CYAN",
) -> list[tuple[str, str]]:
    pulse = flourish_pulse(now)
    pct_txt = f" {pct}%"
    dur_txt = f" {dur}"
    dur_style = "YELLOW" if pulse > 0.45 else base_style
    if pulse > 0.7:
        dur_style = "GREEN"
    segments: list[tuple[str, str]] = [(pct_txt, base_style)]
    if pulse > 0.8:
        segments.append((flourish_spark(now, 1), "MAG"))
    segments.append((dur_txt, dur_style))
    return segments


def justify_colored_segments(
    segments: list[tuple[str, str]],
    width: int,
    align: str = "left",
    pad_style: str = "MOTD_FX",
    pad_chars: str | None = None,
) -> list[tuple[str, str]]:
    chars = pad_chars or SCROLLER_FX_EDGE
    total = sum(len(text) for text, _style in segments)
    if total >= width:
        return pad_colored_segments(segments, width)
    room = width - total
    if align == "center":
        left_n = room // 2
        right_n = room - left_n
    elif align == "right":
        left_n = room
        right_n = 0
    else:
        left_n = 0
        right_n = room

    def fx_run(count: int) -> list[tuple[str, str]]:
        if count <= 0:
            return []
        text = "".join(chars[i % len(chars)] for i in range(count))
        return [(text, pad_style)]

    return pad_colored_segments([*fx_run(left_n), *segments, *fx_run(right_n)], width)


def center_colored_segments(segments: list[tuple[str, str]], width: int) -> list[tuple[str, str]]:
    return justify_colored_segments(segments, width, align="center")


def flourished_title_segments(
    label: str,
    now: float,
    width: int,
    salt: str = "hdr",
    title_style: str = "CYAN",
    pad_to: int | None = None,
) -> list[tuple[str, str]]:
    pulse = flourish_pulse(now)
    lb, rb = flourish_bracket_pair(now, salt)
    bracket_style = "YELLOW" if pulse > 0.55 else "MOTD_FX"
    spark_style = "MAG" if pulse > 0.75 else "MOTD_FX"
    frame_w = width if pad_to is None else pad_to
    title_room = max(1, frame_w - 8)
    core = normalize_line(label)
    if len(core) > title_room:
        core = core[:title_room]

    segments: list[tuple[str, str]] = [(lb, bracket_style)]
    if pulse > 0.35:
        segments.append((flourish_spark(now), spark_style))
    segments.append((" ", "SYS"))

    if pulse > 0.2 and core:
        hi = min(len(core) - 1, int(pulse * len(core) * 1.4))
        for i, ch in enumerate(core):
            segments.append((ch, "GLINT" if i == hi else title_style))
    else:
        segments.append((core, title_style))

    segments.append((" ", "SYS"))
    if pulse > 0.35:
        segments.append((flourish_spark(now, 2), spark_style))
    segments.append((rb, bracket_style))
    if pad_to is None:
        return segments
    return justify_colored_segments(segments, pad_to, align="center")


def work_week_rail_segments(
    now: float,
    width: int,
    *,
    compact: bool = False,
    pad_to_width: bool = True,
) -> list[tuple[str, str]]:
    if width < 10:
        return [(fit("?", width), "YELLOW")]
    dt = datetime.fromtimestamp(now)
    pct_val, pct, dur, _phase, bar_style = work_week_progress(dt)
    tail_opts = (f" {pct}% {dur}", f" {pct}%", f" {dur}", "")
    for tail in tail_opts:
        prefix_segs: list[tuple[str, str]] = []
        close_segs: list[tuple[str, str]] = []
        prefix_len = 0
        close_len = 0
        if not compact:
            open_b, close_b, bstyle = flourish_bar_brackets(now, "work-week")
            prefix_segs = [(open_b, bstyle)]
            close_segs = [(close_b, bstyle)]
            prefix_len = len(open_b)
            close_len = len(close_b)
        overhead = prefix_len + close_len + len(tail)
        bar_w = max(6, width - overhead)
        if bar_w >= 6 or not tail:
            segments: list[tuple[str, str]] = [
                *prefix_segs,
                *progress_bar_segments(pct_val, bar_w, bar_style),
                *close_segs,
            ]
            if tail:
                segments.extend(countdown_tail_segments(pct, dur, now, "CYAN"))
            if pad_to_width:
                return pad_colored_segments(segments, width)
            return segments
    return [(fit("?", width), "YELLOW")]


def work_week_compact_segments(now: float, width: int) -> list[tuple[str, str]]:
    """Friday counter — progress through the work week toward Fri 17:00."""
    dt = datetime.fromtimestamp(now)
    pct_val, secs = _fri_progress(dt)
    return labeled_week_rail(now, width, "FRI", pct_val, secs, "GREEN")


def weekend_monday_countdown_segments(
    now: float | None = None,
    width: int = WIDTH,
) -> list[tuple[str, str]]:
    """Monday counter — progress through the weekend toward Mon 10:00."""
    ts = time.time() if now is None else now
    dt = datetime.fromtimestamp(ts)
    pct_val, secs = _mon_progress(dt)
    return labeled_week_rail(ts, width, "MON", pct_val, secs, "MAG")


def zeal_clock_segments(now: float, max_width: int) -> list[tuple[str, str]]:
    dt = datetime.fromtimestamp(now)
    iso_week = max(1, min(52, int(dt.isocalendar().week)))
    epoch_txt = f"[{int(now)}]"
    prefixes = (
        f"ZEAL {dt:%H:%M:%S} W{iso_week:02d} ",
        f"ZEAL {dt:%H:%M} W{iso_week:02d} ",
        f"ZEAL {dt:%H:%M:%S} ",
        f"ZEAL {dt:%H:%M} ",
        f"{dt:%H:%M:%S} ",
        "",
    )
    for prefix in prefixes:
        if len(prefix) + len(epoch_txt) <= max_width:
            segs: list[tuple[str, str]] = []
            if prefix:
                segs.append((prefix, "CYAN"))
            segs.append((epoch_txt, "YELLOW"))
            return segs
    if len(epoch_txt) <= max_width:
        return [(epoch_txt, "YELLOW")]
    return [(epoch_txt[-max_width:], "YELLOW")]


def zeal_clock_bit(now: float, max_len: int | None = None) -> str:
    if max_len is None:
        dt = datetime.fromtimestamp(now)
        iso_week = max(1, min(52, int(dt.isocalendar().week)))
        return f"ZEAL {dt:%H:%M:%S} W{iso_week:02d} [{int(now)}]"
    return "".join(text for text, _style in zeal_clock_segments(now, max_len))


def top_status_segments(now: float | None = None, width: int = WIDTH) -> list[tuple[str, str]]:
    """Top row: ZEAL clock on the left, Friday counter filling the rest.

    The ISO week lives once on the calendar row -- not duplicated here.
    """
    ts = time.time() if now is None else now
    dt = datetime.fromtimestamp(ts)
    clock = f"ZEAL {dt:%H:%M:%S}"
    clock_segs: list[tuple[str, str]] = [(clock, "CYAN")]
    room = width - len(clock) - 1
    if room >= 12:
        pct_val, secs = _fri_progress(dt)
        rail = labeled_week_rail(ts, room, "FRI", pct_val, secs, "GREEN")
        return pad_colored_segments([*clock_segs, (" ", "SYS"), *rail], width)
    return pad_colored_segments(clock_segs, width)


def top_status_line(now: float | None = None, width: int = WIDTH) -> str:
    ts = time.time() if now is None else now
    return "".join(text for text, _style in top_status_segments(ts, width))


def _defcon_level_style(defcon_text: str) -> str:
    match = re.search(r"DEFCON\s+(\d+)", defcon_text, re.IGNORECASE)
    if not match:
        return "YELLOW"
    level = int(match.group(1))
    if level <= 2:
        return "RED"
    if level <= 4:
        return "YELLOW"
    return "GREEN"


def _defcon_colored_parts(defcon_text: str) -> list[tuple[str, str]]:
    level_style = _defcon_level_style(defcon_text)
    parts: list[tuple[str, str]] = []
    for token in re.sub(r"\s+", " ", defcon_text).strip().split():
        upper = token.upper()
        if upper.startswith("J") and any(ch.isdigit() for ch in token):
            style = "CYAN"
        elif upper == "DEFCON":
            style = "MAG"
        elif token.isdigit():
            style = level_style
        elif upper in ("STANDBY", "NORMAL", "READY", "HOLD"):
            style = "GREEN"
        elif upper in ("MAX", "ALERT", "CRITICAL", "COCKED"):
            style = "RED"
        else:
            style = "YELLOW"
        if parts:
            parts.append((" ", "SYS"))
        parts.append((token, style))
    return parts or [(defcon_text, "YELLOW")]


def wopr_header_segments(mode: str, now: float, width: int = WIDTH) -> list[tuple[str, str]]:
    defcon = joshua_defcon_ticker().strip() or "J124 DEFCON 5 STANDBY"
    rot = compact_mode_rotator(mode, now)
    tick = int(now * 0.75)
    glint = SCROLLER_FX_GLINT[tick % len(SCROLLER_FX_GLINT)]
    lfx = SCROLLER_FX_EDGE[tick % len(SCROLLER_FX_EDGE)]
    rfx = SCROLLER_FX_EDGE[(tick + 2) % len(SCROLLER_FX_EDGE)]
    ansi_mid = ("=", "-", "#", "*", "+")[tick % 5]

    segments: list[tuple[str, str]] = [
        (glint, "YELLOW"),
        (lfx, "MOTD_FX"),
        (ansi_mid, "CYAN"),
        (" ", "SYS"),
        *_defcon_colored_parts(defcon),
        (" ", "SYS"),
        (rot, "NOC"),
        (" ", "SYS"),
        (ansi_mid, "MAG"),
        (rfx, "MOTD_FX"),
        (glint, "YELLOW"),
    ]

    total = sum(len(text) for text, _style in segments)
    if total > width:
        segments = [
            (lfx, "MOTD_FX"),
            (" ", "SYS"),
            *_defcon_colored_parts(defcon),
            (" ", "SYS"),
            (rfx, "MOTD_FX"),
        ]
    total = sum(len(text) for text, _style in segments)
    if total > width:
        segments = _defcon_colored_parts(defcon)
    return center_colored_segments(segments, width)


def wopr_header_line(mode: str, now: float, width: int = WIDTH) -> str:
    return "".join(text for text, _style in wopr_header_segments(mode, now, width))


_TICKER_SCROLL_CACHE: dict[str, Any] = {}


def ticker_scroll_frames(snapshot: dict[str, Any], now: float | None = None) -> list[str]:
    status = as_dict(snapshot.get("status"))
    bridge = as_dict(snapshot.get("bridge"))
    ts = time.time() if now is None else now
    frames: list[str] = []
    if not status.get("vector_ok"):
        frames.append("ALERT VEC DN")
    if not status.get("pbx_api_ok"):
        frames.append("ALERT PBX DN")
    vm = as_dict(as_dict(status.get("pbx_phones")).get("voicemail"))
    vm_new = int(vm.get("new") or 0)
    if vm_new > 0:
        frames.append(f"VOICEMAIL {vm_new} NEW")
    zone = normalize_line(bridge.get("hot_zone"))
    if zone:
        frames.append(f"ZONE {zone[:20]}")
    npc = int(bridge.get("npc_count") or 0)
    players = int(bridge.get("players_total") or 0)
    if npc or players:
        frames.append(f"PARTY NPC {npc} PLAYERS {players}")
    for bit in agent_ticker_bits(status, now=ts):
        frames.append(normalize_line(bit))
    gpu = gpu_summary(snapshot)
    if gpu and gpu != "GPU telemetry warming up":
        frames.append(gpu)
    # Denoise: drop blanks, collapse case-insensitive duplicates, keep order.
    seen: set[str] = set()
    out: list[str] = []
    for frame in frames:
        clean = normalize_line(frame)
        if clean and clean.lower() not in seen:
            seen.add(clean.lower())
            out.append(clean)
    if not out:
        out.append(f"CRYSTAL MESH OK · tkr {LCD_TICKER_VERSION}")
    return out


def ticker_scroll_body(snapshot: dict[str, Any], now: float | None = None) -> str:
    ts = time.time() if now is None else now
    status = as_dict(snapshot.get("status"))
    frames = ticker_scroll_frames(snapshot, ts)
    frame_idx = int(ts // TICKER_FRAME_PERIOD_SEC) % len(frames)
    key = (
        frame_idx,
        bool(status.get("vector_ok")),
        bool(status.get("pbx_api_ok")),
        LCD_TICKER_VERSION,
        int(ts // TICKER_FRAME_PERIOD_SEC),
        len(frames),
    )
    if _TICKER_SCROLL_CACHE.get("key") == key and _TICKER_SCROLL_CACHE.get("body"):
        return str(_TICKER_SCROLL_CACHE["body"])
    body = frames[frame_idx]
    _TICKER_SCROLL_CACHE["key"] = key
    _TICKER_SCROLL_CACHE["body"] = body
    return body


def header_ticker_line(
    text: str,
    now: float,
    width: int = WIDTH,
    speed: float = TICKER_SCROLLER_SPEED,
) -> str:
    """Header row 3: center short frames; marquee-scroll long agent/NOC lines in full."""
    core = re.sub(r"\s+", " ", str(text or "")).strip()
    if not core:
        core = f"CRYSTAL MESH OK tkr {LCD_TICKER_VERSION}"
    if len(core) <= width:
        return center(core, width)
    body = core + "   "
    offset = int(now * speed) % len(body)
    loop = body + body
    return pad(loop[offset : offset + width], width)


def header_ticker_segments(
    text: str,
    now: float,
    width: int = WIDTH,
    speed: float = TICKER_SCROLLER_SPEED,
) -> list[tuple[str, str]]:
    """Header row 3 segments — center short frames; scroll long lines in full."""
    core = re.sub(r"\s+", " ", str(text or "")).strip()
    if not core:
        core = f"CRYSTAL MESH OK tkr {LCD_TICKER_VERSION}"
    if len(core) <= width:
        return [(center(core, width), "NOC")]
    return [(header_ticker_line(text, now, width, speed=speed), "NOC")]


def compact_mode_rotator(mode: str, now: float, width: int = 8) -> str:
    tag = mode_tab_short(mode)[:4]
    return fit(f"|{tag}{mode_seconds_left(now):02d}s", width)


def tick_counter(now: float | None = None) -> int:
    ts = time.time() if now is None else now
    return int(ts) % 100000


def xtree_hline(width: int = WIDTH, ch: str = "-") -> str:
    return pad("+" + (ch * max(0, width - 2)) + "+", width)


def xtree_title_bar(mode: str, now: float, tick: int, width: int = WIDTH) -> str:
    dt = datetime.fromtimestamp(now)
    label = XTREE_LABELS.get(mode, mode[:4].upper())
    cga_blink = "*" if int(anim_now(now, 2.0) // 2) % 2 else " "
    text = (
        f"ZEALTREE GOLD{cga_blink}{label} "
        f"T{dt:%H:%M:%S} WB{int((datetime.fromtimestamp(now).isocalendar().week))} "
        f"#{tick:05d}"
    )
    return fit(text, width)


def xtree_menu_bar(width: int = WIDTH) -> str:
    return fit("F1Help F2Mesh F5NOC F7RPG F10Log EscQuit", width)


def xtree_tree_cell(mode: str, active: str, width: int = XTREE_TREE_W) -> str:
    label = XTREE_LABELS.get(mode, mode[:4].upper())[:4]
    marker = ">" if mode == active else " "
    return pad(marker + label, width)


def xtree_split_row(tree: str, body: str, width: int = WIDTH) -> str:
    return pad(tree[:XTREE_TREE_W] + "|" + fit(body, XTREE_BODY_W - 1), width)


def xtree_tree_sidebar(active: str, now: float, width: int = XTREE_TREE_W) -> list[str]:
    blink = int(anim_now(now, 3.0) // 3) % 2
    rows = []
    for mode in XTREE_MODES:
        cell = xtree_tree_cell(mode, active, width)
        if mode == active and blink:
            cell = pad(">" + XTREE_LABELS.get(mode, mode[:4].upper())[:4], width)
        rows.append(cell)
    return rows


def xtree_status_tick(now: float, tick: int, width: int = WIDTH) -> str:
    dt = datetime.fromtimestamp(now)
    month = MONTH_NAMES[max(0, min(11, dt.month - 1))]
    iso_week = max(1, min(52, int(dt.isocalendar().week)))
    pulse = ":" if int(now) % 2 == 0 else "."
    text = f"TICK{pulse}{dt:%H%M%S} {dt.day:02d}{month} W{iso_week:02d} #{tick:05d}"
    return fit(text, width)


def xtree_panel_top(mode: str, width: int = XTREE_BODY_W) -> str:
    titles = {
        "terrarium": "LAN VITALS",
        "uptime": "BOOT AGE GRID",
        "ops": "NOC MESH OPS",
        "rpg": "CRYSTAL MESH RPG",
        "rgb": "RGB BATTLE",
        "agents": "PBX AGENTS",
        "bridge": "ST BRIDGE",
        "lounge": "LIVE CHATTER",
    }
    return fit(titles.get(mode, mode.upper()), width)


def xtree_panel_lines(snapshot: dict[str, Any], mode: str) -> list[tuple[str, str]]:
    content = panel_lines(snapshot, mode, XTREE_BODY_W - 1)
    if not content:
        return [(fit("waiting for feed", XTREE_BODY_W - 1), "SYS")]
    return content


def section_bar(label: str, width: int = WIDTH) -> str:
    tag = f" {label} "
    if len(tag) >= width:
        return fit(tag, width)
    fill = width - len(tag)
    left = fill // 2
    return pad("-" * left + tag + "-" * (fill - left), width)


def mode_seconds_left(now: float | None = None) -> int:
    ts = time.time() if now is None else now
    return max(0, int(MODE_PERIOD_SEC - (ts % MODE_PERIOD_SEC)))


def host_long_name(short: str, host: dict[str, Any] | None = None) -> str:
    if host:
        reported = str(host.get("host") or host.get("name") or "").strip()
        if reported:
            return reported[:14]
    return HOST_LONG_NAMES.get(short, short.lower())


def mode_tab_short(mode: str) -> str:
    return MODE_TAB_SHORT.get(mode, mode[:4].upper())


def mode_tab_display_name(mode: str, *, full: bool = True) -> str:
    if full:
        return MODE_TITLES.get(mode, mode.upper())
    return mode_tab_short(mode)


def panel_section_label(mode: str) -> str:
    return PANEL_SECTION_LABELS.get(mode, MODE_TITLES.get(mode, mode.upper()))


def mode_section_bar(active: str, width: int = WIDTH, now: float | None = None) -> str:
    """Mode rotator — full tab titles when they fit, else short codes."""
    ts = time.time() if now is None else now
    secs = mode_seconds_left(ts)
    try:
        idx = XTREE_MODES.index(active)
    except ValueError:
        idx = 0
    next_mode = XTREE_MODES[(idx + 1) % len(XTREE_MODES)]
    tag = ""
    for use_full in (True, False):
        cur = mode_tab_display_name(active, full=use_full)
        nxt = mode_tab_display_name(next_mode, full=use_full)
        candidate = f">>{cur} {secs:02d}s>>{nxt}"
        if len(candidate) <= width:
            tag = candidate
            break
    if not tag:
        cur = mode_tab_short(active)[:3]
        nxt = mode_tab_short(next_mode)[:3]
        tag = f">{cur}{secs:02d}s>{nxt}"[:width]
    fill = max(0, width - len(tag))
    left = fill // 2
    return pad("-" * left + tag + "-" * (fill - left), width)


def mesh_section_label(now: float | None = None) -> str:
    _pct_hdr, bar_label, _metric_id = mesh_metric_headers(now)
    return f"HOST TABLE: {bar_label.strip()}"


def kv_value_room(width: int = WIDTH, key_w: int = DETAIL_KEY_W) -> int:
    return max(1, width - key_w - 1)


def scroll_line(
    text: Any,
    width: int = WIDTH,
    now: float | None = None,
    speed: float = DETAIL_SCROLL_SPEED,
) -> str:
    body = re.sub(r"\s+", " ", str(text or "")).strip()
    if now is not None and len(body) > width:
        return marquee(body, width, speed=speed, now=now)
    return pad(body, width)


def detail_kv_header(width: int = WIDTH, key_w: int = DETAIL_KEY_W) -> str:
    return pad(f"{'LABEL':<{key_w}} {'DETAIL'}", width)


def detail_kv_rule(width: int = WIDTH, key_w: int = DETAIL_KEY_W) -> str:
    return pad("-" * key_w + " " + "-" * max(1, width - key_w - 1), width)


def detail_kv_fill(body: str, room: int) -> str:
    clean = re.sub(r"\s+", " ", str(body or "")).strip()
    if len(clean) >= room:
        return clean[:room]
    return clean + (" " * (room - len(clean)))


def usage_pct_style(pct: Any, warn: float = DISK_USAGE_WARN_PCT, crit: float = DISK_USAGE_CRIT_PCT) -> str:
    try:
        value = float(pct)
    except (TypeError, ValueError):
        return "SYS"
    if value >= crit:
        return "RED"
    if value >= warn:
        return "YELLOW"
    return "GREEN"


def host_label_style(label: str) -> str:
    return HOST_LABEL_STYLES.get(str(label or "").strip().upper(), "NOC")


def pad_colored_segments(segments: list[tuple[str, str]], width: int) -> list[tuple[str, str]]:
    total = sum(len(text) for text, _style in segments)
    if total < width:
        segments = [*segments, (" " * (width - total), "SYS")]
    elif total > width:
        trim = total - width
        last_text, last_style = segments[-1]
        segments = [*segments[:-1], (last_text[: max(0, len(last_text) - trim)], last_style)]
    return segments


def ops_disk_detail_line(pct: Any, room: int) -> str:
    pct_txt = fmt_pct(pct)
    lead = f"{pct_txt} "
    spare = room - len(lead)
    if spare < 6:
        return detail_kv_fill(lead.strip(), room)
    ascii_w = max(8, min(18, spare - 8))
    block_w = max(6, spare - ascii_w - 1)
    return detail_kv_fill(f"{lead}{ascii_bar(pct, ascii_w)} {bar(pct, block_w)}", room)


def ops_disk_detail_segments(
    label: str,
    pct: Any,
    width: int = WIDTH,
    key_w: int = OPS_DETAIL_KEY_W,
) -> list[tuple[str, str]]:
    host_style = host_label_style(label)
    usage_style = usage_pct_style(pct)
    key = pad(f"DISK {label}", key_w)[:key_w]
    room = kv_value_room(width, key_w)
    pct_txt = fmt_pct(pct)
    spare = room - len(pct_txt) - 1
    if spare < 6:
        body_segments: list[tuple[str, str]] = [(pct_txt, usage_style)]
    else:
        ascii_w = max(8, min(18, spare - 8))
        block_w = max(6, spare - ascii_w - 1)
        body_segments = [
            (pct_txt, usage_style),
            (" ", "SYS"),
            (ascii_bar(pct, ascii_w), usage_style),
            (" ", "SYS"),
            (bar(pct, block_w), usage_style),
        ]
    body = "".join(text for text, _style in body_segments)
    if len(body) < room:
        body_segments.append((" " * (room - len(body)), "SYS"))
    return pad_colored_segments([(f"{key} ", host_style), *body_segments], width)


def companion_display_name(comp: dict[str, Any]) -> str:
    name = re.sub(r"\s+", " ", str(comp.get("name") or comp.get("st_name") or "")).strip()
    return name or "?"


def sorted_companions(companions: list[Any]) -> list[dict[str, Any]]:
    comps = [comp for comp in companions if isinstance(comp, dict)]
    return sorted(
        comps,
        key=lambda comp: (-int(comp.get("bond") or 0), companion_display_name(comp)),
    )


def companion_value_segments(
    companions: list[dict[str, Any]],
    colors: tuple[str, ...] = COMPANION_LINE_COLORS,
) -> list[tuple[str, str]]:
    segments: list[tuple[str, str]] = []
    for idx, comp in enumerate(companions):
        name = companion_display_name(comp)
        if not name or name == "?":
            continue
        if segments:
            segments.append((" ", "SYS"))
        color = colors[idx % len(colors)]
        segments.append((f"[{name}]", color))
    return segments


def merge_adjacent_segments(segments: list[tuple[str, str]]) -> list[tuple[str, str]]:
    merged: list[tuple[str, str]] = []
    for text, style in segments:
        if merged and merged[-1][1] == style:
            merged[-1] = (merged[-1][0] + text, style)
        else:
            merged.append((text, style))
    return merged


def fit_colored_segments(
    segments: list[tuple[str, str]],
    room: int,
    now: float | None = None,
    speed: float = DETAIL_SCROLL_SPEED,
) -> list[tuple[str, str]]:
    if not segments:
        return [("waiting".ljust(room), "ST")]
    chars: list[tuple[str, str]] = []
    for text, style in segments:
        for ch in text:
            chars.append((ch, style))
    if len(chars) <= room:
        return merge_adjacent_segments([(text, style) for text, style in segments]) + (
            [(" " * (room - len(chars)), "SYS")] if len(chars) < room else []
        )
    if now is None:
        clipped = chars[:room]
    else:
        body = "".join(ch for ch, _style in chars) + "   "
        offset = int(now * speed) % len(body)
        loop_chars: list[tuple[str, str]] = chars + chars
        start = offset % len(chars)
        clipped = loop_chars[start : start + room]
    return merge_adjacent_segments(clipped)


def detail_kv_companion_segments(
    key: str,
    companions: list[Any],
    width: int = WIDTH,
    now: float | None = None,
    key_w: int = DETAIL_KEY_W,
) -> list[tuple[str, str]]:
    label = pad(key, key_w)[:key_w]
    room = kv_value_room(width, key_w)
    value_segments = companion_value_segments(sorted_companions(companions))
    value_disp = fit_colored_segments(value_segments, room, now=now)
    segments: list[tuple[str, str]] = [(f"{label} ", "ST"), *value_disp]
    total = sum(len(text) for text, _style in segments)
    if total < width:
        segments.append((" " * (width - total), "SYS"))
    elif total > width:
        trim = total - width
        last_text, last_style = segments[-1]
        segments[-1] = (last_text[: max(0, len(last_text) - trim)], last_style)
    return segments


def detail_kv(
    key: str,
    value: Any,
    width: int = WIDTH,
    now: float | None = None,
    scroll: bool = True,
    key_w: int = DETAIL_KEY_W,
    fill: bool = False,
) -> str:
    label = pad(key, key_w)[:key_w]
    room = kv_value_room(width, key_w)
    body = re.sub(r"\s+", " ", str(value or "")).strip()
    if scroll and now is not None and len(body) > room:
        body = marquee(body, room, speed=DETAIL_SCROLL_SPEED, now=now)
    elif fill:
        body = detail_kv_fill(body, room)
    else:
        body = fit(body, room)
    return pad(f"{label} {body}", width)


def telemetry_feed_summary(
    remote: dict[str, Any],
    celes: dict[str, Any] | None = None,
    heartbeat: dict[str, Any] | None = None,
    longest_label: str = "",
    longest_uptime: int = -1,
) -> str:
    age = remote.get("age_sec")
    remote_state = "FRESH" if remote.get("fresh") else "STALE"
    if age is None:
        bits = ["rmt age ?"]
    else:
        bits = [f"rmt {age}s {remote_state}"]
    if celes is not None:
        bits.append(f"CELES {'FRESH' if celes.get('fresh') else 'STALE'}")
    if heartbeat is not None:
        bits.append(f"hb {heartbeat.get('age_sec', '?')}s")
    if longest_uptime >= 0 and longest_label:
        bits.append(f"top {longest_label} {fmt_uptime(longest_uptime)}")
    return " | ".join(bits)


def mesh_sync_alert_summary(
    status: dict[str, Any],
    snapshot: dict[str, Any] | None = None,
    now: float | None = None,
) -> str:
    """Alert-oriented last-seen tokens — not live uptime telemetry."""
    _ = snapshot
    telemetry = as_dict(status.get("telemetry"))
    local = as_dict(telemetry.get("local"))
    remote = as_dict(telemetry.get("remote"))
    remote_hosts = as_dict(remote.get("hosts"))
    remote_age = remote.get("age_sec")
    noc = as_dict(status.get("noc"))
    parts: list[str] = []

    if local:
        parts.append("ZEA ok")
    else:
        parts.append("ZEA ?")

    for label, host_id in (("ZTW", "zealtower"), ("VEC", "vector")):
        host = as_dict(remote_hosts.get(host_id))
        if not host:
            parts.append(f"{label}!LOST")
            continue
        if not remote.get("fresh"):
            parts.append(f"{label}!STALE")
            continue
        parts.append(f"{label} {fmt_age_short(remote_age, 'ok')}")

    return " ".join(parts) or "mesh sync waiting"


def mesh_gateway_line(
    status: dict[str, Any],
    snapshot: dict[str, Any],
    width: int = WIDTH,
    now: float | None = None,
) -> str:
    noc = as_dict(status.get("noc"))
    wan = noc_ping_glyph(noc, "wan")
    nid = noc_ping_glyph(noc, "nidhogg")
    mid = noc_ping_glyph(noc, "midgard")
    celes = as_dict(snapshot.get("celes"))
    text = (
        f"WAN {wan}  NID {nid}  MID {mid}  "
        f"VEC {'OK' if status.get('vector_ok') else 'DN'}  "
        f"PBX {'OK' if status.get('pbx_api_ok') else 'DN'}  "
        f"HRM {'OK' if status.get('hermes_ok') else 'DN'}  "
        f"CELES {'FRESH' if celes.get('fresh') else 'STALE'}  "
        f"{joshua_defcon_ticker()}"
    )
    return scroll_line(text, width, now)


def scroll_window(items: tuple[Any, ...] | list[Any], count: int, now: float, period: float) -> list[Any]:
    if not items or count <= 0:
        return []
    start = int(now // max(0.5, period)) % len(items)
    return [items[(start + idx) % len(items)] for idx in range(min(count, len(items)))]


def pbx_agent_roster(bridge: dict[str, Any] | None = None) -> tuple[tuple[str, str], ...]:
    """Full PBX address book: core roster plus bridge route extensions."""
    rows = list(PBX_AGENT_ROSTER)
    seen = {ext for ext, _name in rows}
    routes = as_dict((bridge or {}).get("routes"))
    for name, route in routes.items():
        if not isinstance(route, dict):
            continue
        ext = str(route.get("preferred_extension") or "").strip()
        if not ext or ext in seen:
            continue
        rows.append((ext, short_text(name, AGENT_NAME_W)))
        seen.add(ext)
    return tuple(rows)


def agent_book_page(
    roster: tuple[tuple[str, str], ...] | list[tuple[str, str]],
    visible_count: int,
    now: float,
) -> tuple[list[tuple[str, str]], int, int]:
    """Page through the full address book within one mode period (18s)."""
    if not roster or visible_count <= 0:
        return [], 0, 0
    page_count = max(1, (len(roster) + visible_count - 1) // visible_count)
    elapsed = now % MODE_PERIOD_SEC
    page_period = MODE_PERIOD_SEC / page_count
    page = min(int(elapsed // page_period), page_count - 1)
    start = page * visible_count
    rows = [roster[(start + idx) % len(roster)] for idx in range(min(visible_count, len(roster)))]
    return rows, page + 1, page_count


def agent_visible_rows(
    roster: tuple[tuple[str, str], ...] | list[tuple[str, str]],
    visible_count: int,
    now: float,
    active_exts: set[str],
) -> tuple[list[tuple[str, str]], int, int]:
    """Pin on-call agents, then fill remaining slots from the address-book page."""
    page_rows, page_num, page_count = agent_book_page(roster, visible_count, now)
    pinned = [row for row in roster if row[0] in active_exts]
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for row in pinned:
        if row[0] in seen:
            continue
        out.append(row)
        seen.add(row[0])
    for row in page_rows:
        if len(out) >= visible_count:
            break
        if row[0] in seen:
            continue
        out.append(row)
        seen.add(row[0])
    if len(out) < visible_count:
        for row in roster:
            if len(out) >= visible_count:
                break
            if row[0] in seen:
                continue
            out.append(row)
            seen.add(row[0])
    return out[:visible_count], page_num, page_count


def pbx_phone_state_map(status: dict[str, Any]) -> dict[str, str]:
    phones = as_dict(status.get("pbx_phones"))
    out: dict[str, str] = {}
    for row in phones.get("phones") or []:
        if not isinstance(row, dict):
            continue
        ext = str(row.get("ext") or "").strip()
        if not ext:
            continue
        state = str(row.get("state") or row.get("connection") or "idle").strip().lower()
        out[ext] = state
    return out


def pbx_phone_last_call_ts_map(status: dict[str, Any]) -> dict[str, float]:
    phones = as_dict(status.get("pbx_phones"))
    out: dict[str, float] = {}
    for row in phones.get("phones") or []:
        if not isinstance(row, dict):
            continue
        ext = str(row.get("ext") or "").strip()
        last_call = str(row.get("last_call") or "").strip()
        if not ext or not last_call:
            continue
        ts = parse_iso_ts(last_call)
        if ts:
            out[ext] = max(out.get(ext, 0.0), ts)
    return out


def pbx_phone_last_seen_ts_map(status: dict[str, Any]) -> dict[str, float]:
    phones = as_dict(status.get("pbx_phones"))
    out: dict[str, float] = {}
    for row in phones.get("phones") or []:
        if not isinstance(row, dict):
            continue
        ext = str(row.get("ext") or "").strip()
        last_seen = str(row.get("last_seen") or "").strip()
        if not ext or not last_seen:
            continue
        ts = parse_iso_ts(last_seen)
        if ts:
            out[ext] = max(out.get(ext, 0.0), ts)
    return out


def merge_ext_ts_maps(*maps: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for mapping in maps:
        for ext, ts in mapping.items():
            out[ext] = max(out.get(ext, 0.0), float(ts))
    return out


def agent_table_header(width: int = WIDTH) -> str:
    return pad(
        f"{'EXT':<{AGENT_EXT_W}} {'AGENT':<{AGENT_NAME_W}} {'LAST SEEN'}",
        width,
    )


def agent_table_rule(width: int = WIDTH) -> str:
    return pad(
        f"{'-' * AGENT_EXT_W} {'-' * AGENT_NAME_W} {'-' * AGENT_LAST_W}",
        width,
    )


def agent_name_cell(name: str, now: float | None = None) -> str:
    clean = re.sub(r"\s+", " ", str(name or "")).strip()
    if now is not None and len(clean) > AGENT_NAME_W:
        return marquee(clean, AGENT_NAME_W, speed=DETAIL_SCROLL_SPEED, now=now)
    return pad(clean, AGENT_NAME_W)[:AGENT_NAME_W]


def agent_row(
    ext: str,
    name: str,
    last_col: str,
    width: int = WIDTH,
    now: float | None = None,
) -> str:
    ext_disp = pad(ext, AGENT_EXT_W)[:AGENT_EXT_W]
    name_disp = agent_name_cell(name, now=now)
    last_disp = pad(str(last_col or ""), AGENT_LAST_W)[:AGENT_LAST_W]
    return pad(f"{ext_disp} {name_disp} {last_disp}", width)


def fmt_age_short(seconds: Any, now_label: str = "now") -> str:
    try:
        age = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        return "?"
    if age <= 45:
        return now_label
    if age < 3600:
        return f"{age // 60}m" if age >= 60 else f"{age}s"
    if age < 86400:
        return f"{age // 3600}h"
    return fmt_duration_short(age)


def agent_last_label(
    ext: str,
    phone_states: dict[str, str],
    call_exts: set[str],
    call_ts_map: dict[str, float],
    now: float,
    seen_ts_map: dict[str, float] | None = None,
) -> tuple[str, str]:
    if ext in call_exts:
        return "ON CALL", "PBX_CALL"
    raw = phone_states.get(ext, "idle").lower()
    call_ts = call_ts_map.get(ext, 0.0)
    call_age = (now - call_ts) if call_ts else None
    seen_ts = (seen_ts_map or {}).get(ext, 0.0)
    seen_age = (now - seen_ts) if seen_ts else None
    is_human = ext in HUMAN_EXTS
    if raw in ("ring", "ringing", "inuse", "talking"):
        return "in call", "PBX_CALL"
    if call_age is not None and call_age <= 120:
        return f"call {fmt_age_short(call_age)}", "PBX_CALL"
    if is_human:
        if raw in ("online", "connected", "up"):
            return "seen now", "PBX"
        if raw in ("dnd", "busy"):
            return "busy", "YELLOW"
        if call_age is not None:
            return f"call {fmt_age_short(call_age)}", "PBX"
        if seen_age is not None:
            return f"seen {fmt_age_short(seen_age)}", "PBX"
        return "idle", "PBX"
    if call_age is not None:
        return f"call {fmt_age_short(call_age)}", "PBX"
    if seen_age is not None:
        return f"seen {fmt_age_short(seen_age)}", "PBX"
    if raw in ("service", "connected", "up"):
        return "svc up", "PBX"
    if raw in ("dnd", "busy"):
        return "busy", "YELLOW"
    return "idle", "PBX"


def agent_status_label(ext: str, phone_states: dict[str, str], call_exts: set[str]) -> tuple[str, str]:
    """Legacy status helper — prefer agent_last_label for the agents panel."""
    if ext in call_exts:
        return ">> ON CALL <<", "PBX_CALL"
    raw = phone_states.get(ext, "idle").lower()
    if raw in ("online", "connected", "up"):
        return "ONLINE", "PBX"
    if raw in ("dnd", "busy"):
        return "BUSY", "YELLOW"
    if raw in ("ring", "ringing", "inuse", "talking"):
        return "IN USE", "PBX_CALL"
    return "IDLE", "PBX"


def detail_table_header(width: int = WIDTH) -> str:
    return vitals_join("HOST", "UP-TIM", "CPU%", "MEM%", "DISK%", "BLOCK BAR", width)


def detail_table_rule(width: int = WIDTH) -> str:
    return vitals_join("-----", "------", "----", "----", "----", "----------", width)


def vitals_join(host: str, up: str, cpu: str, mem: str, disk: str, bar: str, width: int = WIDTH) -> str:
    """40-col detail grid: 5+6+4+4+4+12 with single-space gaps."""
    line = (
        f"{pad(host, 5)[:5]} "
        f"{pad(up, 6)[:6]} "
        f"{pad(cpu, 4)[:4]} "
        f"{pad(mem, 4)[:4]} "
        f"{pad(disk, 4)[:4]} "
        f"{pad(bar, VITALS_BAR_W)[:VITALS_BAR_W]}"
    )
    return pad(line, width)


def vitals_row(
    host: str,
    uptime: Any,
    cpu_pct: Any,
    mem_pct: Any,
    disk_pct: Any,
    width: int = WIDTH,
) -> str:
    up = fmt_uptime(uptime) if uptime is not None else "------"
    return vitals_join(
        host,
        up[:6],
        fmt_metric_cell(cpu_pct),
        fmt_metric_cell(mem_pct),
        fmt_metric_cell(disk_pct),
        bar(disk_pct if disk_pct is not None else 0, VITALS_BAR_W),
        width,
    )


def uptime_table_header(width: int = WIDTH) -> str:
    """Boot-age grid — uptime text only, no block bars (disk bars live on terrarium/NOC)."""
    line = (
        f"{'HOST':<5} "
        f"{'UP-TIME':<10} "
        f"{'CPU%':<4} "
        f"{'MEM%':<4} "
        f"{'LOD%':<4} "
        f"{'SERVICE':<8}"
    )
    return pad(line, width)


def uptime_table_rule(width: int = WIDTH) -> str:
    return pad(
        f"{'-----':<5} {'----------':<10} {'----':<4} {'----':<4} {'----':<4} {'--------':<8}",
        width,
    )


def _host_service_tag(host: dict[str, Any] | None) -> str:
    if not host:
        return "offline"
    if host.get("ok") is False:
        return "down"
    return "online"


def uptime_host_row(
    label: str,
    host: dict[str, Any] | None,
    width: int = WIDTH,
) -> str:
    if not host:
        line = f"{pad(label, 5)[:5]} {'------':<10} {' --':<4} {' --':<4} {' --':<4} {'offline':<8}"
        return pad(line, width)
    up = fmt_uptime(host.get("uptime_sec"))
    cpu = fmt_metric_cell(host.get("cpu_pct"))
    mem = fmt_metric_cell(host.get("mem_pct"))
    load = fmt_metric_cell(host_mesh_metric(host, "load1"))
    status = _host_service_tag(host)
    line = (
        f"{pad(label, 5)[:5]} "
        f"{pad(up, 10)[:10]} "
        f"{cpu} "
        f"{mem} "
        f"{load} "
        f"{pad(status, 8)[:8]}"
    )
    return pad(line, width)


def mode_tab_bar(active: str, width: int = WIDTH) -> str:
    return mode_section_bar(active, width)


def dashboard_header(snapshot: dict[str, Any], mode: str, now: float, tick: int, width: int = WIDTH) -> str:
    """Clock strip — centered local time, ISO week, unix epoch."""
    _ = snapshot, mode, tick
    dt = datetime.fromtimestamp(now)
    iso_week = max(1, min(52, int(dt.isocalendar().week)))
    epoch = int(now)
    text = f"ZEAL {dt:%H:%M:%S} Week{iso_week} [{epoch}]"
    return center(text, width)


def defcon_status_line(width: int = WIDTH) -> str:
    """Centered Joshua WOPR / DEFCON strip for the hybrid dashboard header."""
    return center(joshua_defcon_ticker(), width)


def compact_status_line(
    snapshot: dict[str, Any],
    mode: str,
    now: float,
    tick: int,
    width: int = WIDTH,
) -> str:
    """WOPR DEFCON + mode rotator (ZEAL clock lives on top row)."""
    _ = snapshot, tick
    return wopr_header_line(mode, now, width)


def lcd_frame_zones(frame_h: int) -> dict[str, int]:
    """Return absolute row indices for each dashboard zone."""
    input_row = max(8, frame_h - 1)
    events_min = max(4, min(LCD_EVENTS_MIN_ROWS, input_row - 16))
    row = 0
    header_start = row
    row += LCD_HEADER_ROWS
    mode_bar = row
    row += LCD_MODE_BAR_ROWS
    art_start = row
    row += LCD_ART_ROWS
    panel_start = row
    row += LCD_PANEL_MAX_ROWS
    calendar_row = row
    row += 1
    status_row = row
    row += 1
    fx_row = row
    row += LCD_FX_ROWS
    events_hdr = row
    row += LCD_EVENTS_HEADER_ROWS
    events_start = row
    events_end = input_row
    if events_end - events_start < events_min:
        panel_start = max(art_start + LCD_ART_ROWS, panel_start - (events_min - (events_end - events_start)))
    return {
        "input_row": input_row,
        "header_start": header_start,
        "mode_bar": mode_bar,
        "art_start": art_start,
        "panel_start": panel_start,
        "calendar_row": calendar_row,
        "status_row": status_row,
        "fx_row": fx_row,
        "events_hdr": events_hdr,
        "events_start": events_start,
        "events_end": events_end,
    }


MODE_ART_PICK: dict[str, tuple[int, ...]] = {
    "terrarium": (0, 1, 2),
    "ops": (0, 1, 2),
    "uptime": (0, 1, 2),
    "rpg": (0, 1, 2),
    "rgb": (0, 1, 2),
    "agents": (0, 1, 2),
    "bridge": (0, 1, 2),
    "lounge": (0, 1, 2),
}


def mode_art_compact(mode: str, now: float, width: int = WIDTH, max_rows: int = LCD_ART_ROWS) -> list[str]:
    rows = mode_art(mode, now, width)
    picks = MODE_ART_PICK.get(mode, tuple(range(max_rows)))
    picked = [rows[i] for i in picks if 0 <= i < len(rows)]
    if not picked:
        picked = rows[: max(1, max_rows)]
    return picked[: max(1, max_rows)]


def metric_pair(
    left_label: str,
    left_val: Any,
    right_label: str,
    right_val: Any,
    bar_w: int = 8,
    width: int = WIDTH,
) -> str:
    half = width // 2
    left = fit(f"{left_label} {fmt_pct(left_val)} {ascii_bar(left_val, bar_w)}", half)
    right = fit(f"{right_label} {fmt_pct(right_val)} {ascii_bar(right_val, bar_w)}", half)
    return pad(left[:half] + right[: width - half], width)


def host_metric_line(
    label: str,
    host: dict[str, Any],
    disk_path: str,
    width: int = WIDTH,
) -> str:
    disk_pct = first_disk_pct(host, disk_path)
    if disk_pct is None:
        disk_pct = first_disk_pct(host)
    gpus = host.get("gpus") if isinstance(host.get("gpus"), list) else []
    gpu = as_dict(gpus[0]) if gpus else {}
    gpu_bit = "g?"
    if gpu:
        gpu_bit = f"g{fmt_pct(gpu.get('util_pct'))} t{gpu.get('temp_c', '?')}C"
    return fit(
        f"{label} c{fmt_pct(host.get('cpu_pct'))} {ascii_bar(host.get('cpu_pct'), 5)} "
        f"d{fmt_pct(disk_pct)} {compact_bar(disk_pct, 4)} {gpu_bit}",
        width,
    )


MESH_TABLE_HOSTS: tuple[tuple[str, str, str, str | None], ...] = (
    ("ZEA", "zeal", "local", "/"),
    ("ZTW", "zealtower", "remote", "/mnt/cache"),
    ("VEC", "vector", "remote", "C:/"),
    ("NIF", "nifelheim", "noc", None),
    ("ASG", "asgard", "noc", None),
    ("LAI", "lain", "noc", None),
)
HOST_LONG_NAMES: dict[str, str] = {
    "ZEA": "zealpalace",
    "ZTW": "zealtower",
    "VEC": "vector",
    "NIF": "nifelheim",
    "ASG": "asgard",
    "LAI": "lain",
}
MESH_DNS_SUFFIX = ".yggdrasil.aday.net.au"
HOST_DNS_ALIASES: dict[str, tuple[str, ...]] = {
    "ZEA": ("zealpalace", f"zealpalace{MESH_DNS_SUFFIX}"),
    "ZTW": ("zealtower", f"zealtower{MESH_DNS_SUFFIX}"),
    "VEC": ("vector",),
    "NIF": ("nifelheim",),
    "ASG": ("asgard",),
    "LAI": ("lain",),
}


def noc_ping_glyph(noc: dict[str, Any], host_id: str) -> str:
    inet = as_dict(noc.get("internet"))
    if host_id == "nidhogg":
        return "1" if inet.get("nidhogg_up", True) else "X"
    if host_id == "midgard":
        return "1" if inet.get("midgard_up", True) else "X"
    if host_id == "wan":
        return "1" if inet.get("up", True) else "X"
    for row in noc.get("hosts") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("id") or "") == host_id:
            if row.get("up"):
                return "1"
            if row.get("recent_offline"):
                return "0"
            return "X"
    return "?"


def ping_row_style(ping: str) -> str:
    if ping == "X":
        return "RED"
    if ping == "0":
        return "YELLOW"
    if ping == "1":
        return "GREEN"
    return "SYS"


def mesh_bar_widths(width: int = WIDTH) -> tuple[int, int]:
    """Split remaining row width between ASCII and block metric bars."""
    # mesh_join: host(5) ping(1) sp up(6) sp ds(4) sp ascii sp uni = width
    fixed = 20
    bar_room = max(12, width - fixed)
    ascii_w = max(8, (bar_room * 10 + 8) // 18)
    uni_w = max(6, bar_room - ascii_w)
    while fixed + ascii_w + uni_w > width:
        if ascii_w > 8:
            ascii_w -= 1
        elif uni_w > 6:
            uni_w -= 1
        else:
            break
    return ascii_w, uni_w


def mesh_join(host: str, ping: str, up: str, ds: str, ascii_b: str, uni_b: str, width: int = WIDTH) -> str:
    """Pack columns to fill the full TFT row width."""
    ascii_w, uni_w = mesh_bar_widths(width)
    line = (
        f"{pad(host, 5)[:5]}"
        f"{ping[:1]} "
        f"{pad(up, 6)[:6]} "
        f"{pad(ds, 4)[:4]} "
        f"{pad(ascii_b, ascii_w)[:ascii_w]} "
        f"{pad(uni_b, uni_w)[:uni_w]}"
    )
    return pad(line, width)


def mesh_metric_id(now: float | None = None) -> str:
    ts = time.time() if now is None else now
    idx = int(ts // METRIC_CYCLE_SEC) % len(METRIC_CYCLE)
    return METRIC_CYCLE[idx][1]


def mesh_metric_headers(now: float | None = None) -> tuple[str, str, str]:
    """Return (pct_col, bar_label, metric_id) e.g. ('CPU%', 'CPU USAGE', 'cpu')."""
    ts = time.time() if now is None else now
    idx = int(ts // METRIC_CYCLE_SEC) % len(METRIC_CYCLE)
    pct_hdr, metric_id, bar_label = METRIC_CYCLE[idx]
    return pct_hdr, pad(bar_label, 10)[:10], metric_id


def host_mesh_metric(host: dict[str, Any], metric_id: str, disk_path: str | None = None) -> Any:
    if not host:
        return None
    if metric_id == "cpu":
        return host.get("cpu_pct")
    if metric_id == "mem":
        return host.get("mem_pct")
    if metric_id == "disk":
        root = host.get("root_disk_pct")
        if root is not None:
            return root
        if disk_path:
            pct = first_disk_pct(host, disk_path)
            if pct is not None:
                return pct
        return first_disk_pct(host)
    if metric_id == "gpu":
        gpus = host.get("gpus") if isinstance(host.get("gpus"), list) else []
        gpu = as_dict(gpus[0]) if gpus else {}
        return gpu.get("util_pct") if gpu else None
    if metric_id == "load1":
        try:
            load = float(host.get("load1"))
            cores = max(1, int(host.get("cores") or 1))
            return min(100.0, (load / cores) * 100.0)
        except (TypeError, ValueError):
            return None
    if metric_id == "temp":
        try:
            temp = float(host.get("temp_c"))
            return min(100.0, max(0.0, temp))
        except (TypeError, ValueError):
            return None
    if metric_id == "net":
        net = as_dict(host.get("net"))
        try:
            bps = float(net.get("rx_bps") or 0) + float(net.get("tx_bps") or 0)
        except (TypeError, ValueError):
            return None
        return min(100.0, bps / 1_048_576 * 100.0)
    return None


def fmt_metric_cell(value: Any) -> str:
    if value is None:
        return "  --"
    try:
        return f"{float(value):3.0f}%"
    except (TypeError, ValueError):
        return "  --"


def mesh_table_header(now: float | None = None, width: int = WIDTH) -> str:
    pct_hdr, _bar_label, _metric_id = mesh_metric_headers(now)
    return mesh_join("HOST", "P", "UP-TIM", pct_hdr, MESH_COL_ASCII, MESH_COL_BLOCK, width)


def mesh_table_rule(now: float | None = None, width: int = WIDTH) -> str:
    pct_hdr, bar_label, _metric_id = mesh_metric_headers(now)
    return mesh_join("-----", "-", "------", "----", "----------", "----------", width)


def mesh_table_row(
    label: str,
    ping: str,
    uptime: Any,
    metric_value: Any,
    width: int = WIDTH,
) -> str:
    up = fmt_uptime(uptime) if uptime is not None else "------"
    up = up[:6]
    ds = fmt_metric_cell(metric_value)
    ascii_w, uni_w = mesh_bar_widths(width)
    if metric_value is not None:
        ab = ascii_bar(metric_value, ascii_w)
        ub = bar(metric_value, uni_w)
    else:
        ab = "[" + ("." * max(1, ascii_w - 2)) + "]"
        ub = chr(0x2595) + (chr(0x2591) * max(1, uni_w - 2)) + chr(0x258F)
    return mesh_join(label, ping, up, ds, ab, ub, width)


def mesh_table_row_segments(
    label: str,
    ping: str,
    uptime: Any,
    metric_value: Any,
    width: int = WIDTH,
    metric_id: str | None = None,
) -> list[tuple[str, str]]:
    """Color host by identity; disk metric uses red/yellow/green usage bars."""
    host_style = host_label_style(label)
    ping_style = ping_row_style(ping)
    metric_style = usage_pct_style(metric_value) if metric_id == "disk" and metric_value is not None else "SYS"
    host_col = pad(label, 5)[:5]
    up = fmt_uptime(uptime) if uptime is not None else "------"
    up = up[:6]
    ds = fmt_metric_cell(metric_value)
    ascii_w, uni_w = mesh_bar_widths(width)
    if metric_value is not None:
        ab = pad(ascii_bar(metric_value, ascii_w), ascii_w)[:ascii_w]
        ub = pad(bar(metric_value, uni_w), uni_w)[:uni_w]
        bar_style = metric_style if metric_id == "disk" else "SYS"
    else:
        ab = pad("[" + ("." * max(1, ascii_w - 2)) + "]", ascii_w)[:ascii_w]
        ub = pad(chr(0x2595) + (chr(0x2591) * max(1, uni_w - 2)) + chr(0x258F), uni_w)[:uni_w]
        bar_style = "SYS"
    # Column widths must match mesh_join / mesh_table_header (no bracket prefix).
    return pad_colored_segments(
        [
            (host_col, host_style),
            (ping[:1], ping_style),
            (" ", "SYS"),
            (pad(up, 6)[:6], "SYS"),
            (" ", "SYS"),
            (pad(ds, 4)[:4], metric_style),
            (" ", "SYS"),
            (ab, bar_style),
            (" ", "SYS"),
            (ub, bar_style),
        ],
        width,
    )


MeshRow = str | list[tuple[str, str]]
DetailRow = str | list[tuple[str, str]]


def mesh_table_rows(
    status: dict[str, Any],
    snapshot: dict[str, Any],
    width: int = WIDTH,
    now: float | None = None,
) -> list[tuple[MeshRow, str]]:
    telemetry = as_dict(status.get("telemetry"))
    local = as_dict(telemetry.get("local"))
    remote = as_dict(telemetry.get("remote"))
    remote_hosts = as_dict(remote.get("hosts"))
    noc = as_dict(status.get("noc"))
    hist = as_dict(local.get("history"))
    net = as_dict(local.get("net"))

    ts = time.time() if now is None else now
    pct_hdr, bar_label, metric_id = mesh_metric_headers(ts)

    rows: list[tuple[str, str]] = [
        (mesh_table_header(ts, width), "CYAN"),
        (mesh_table_rule(ts, width), "SYS"),
    ]

    for label, host_id, source, disk_path in MESH_TABLE_HOSTS:
        ping = noc_ping_glyph(noc, host_id)
        uptime = None
        host: dict[str, Any] = {}
        if source == "local":
            host = local
            uptime = host.get("uptime_sec")
        elif source == "remote":
            host = as_dict(remote_hosts.get(host_id))
            if host:
                uptime = host.get("uptime_sec")
                if ping == "?":
                    ping = "1" if host.get("ok", True) else "X"
        metric_value = host_mesh_metric(host, metric_id, disk_path) if host else None
        rows.append(
            (
                mesh_table_row_segments(label, ping, uptime, metric_value, width, metric_id=metric_id),
                host_label_style(label),
            )
        )

    rows.append(
        (
            detail_kv(
                "LOCAL METRIC",
                f"{bar_label.strip()} {fmt_metric_cell(host_mesh_metric(local, metric_id))} "
                f"{ascii_bar(host_mesh_metric(local, metric_id), 8)} "
                f"CPU {fmt_pct(local.get('cpu_pct'))} MEM {fmt_pct(local.get('mem_pct'))} "
                f"TEMP {local.get('temp_c') or '?'}C",
                width,
                now=ts,
            ),
            "NOC",
        )
    )
    rows.append(
        (
            detail_kv(
                "HISTORY",
                f"CPU {spark(hist.get('cpu'), 11)}  MEM {spark(hist.get('mem'), 11)}",
                width,
                now=ts,
                scroll=False,
            ),
            "NOC",
        )
    )
    return rows[:9]


def pinned_vitals_rows(
    status: dict[str, Any],
    snapshot: dict[str, Any],
    width: int = WIDTH,
    now: float | None = None,
) -> list[tuple[str, str]]:
    return mesh_table_rows(status, snapshot, width, now)


def detail_panel_rows(
    snapshot: dict[str, Any],
    mode: str,
    width: int = WIDTH,
    now: float | None = None,
    call_exts: set[str] | None = None,
) -> list[tuple[DetailRow, str]]:
    rows = panel_lines(snapshot, mode, width, now=now, call_exts=call_exts)
    if rows and rows[0][1] == "PANEL":
        rows = rows[1:]
    if not rows:
        return [(fit("no detail feed", width), "SYS")]
    return rows[:7]


@lru_cache(maxsize=1)
def local_lan_ip() -> str:
    try:
        out = subprocess.check_output(["hostname", "-I"], text=True, timeout=0.6)
        return out.split()[0] if out.split() else ""
    except Exception:
        return ""


def lcd_host_ip_bit(snapshot: dict[str, Any]) -> str:
    telemetry = as_dict(as_dict(snapshot.get("status")).get("telemetry"))
    local = as_dict(telemetry.get("local"))
    host = str(local.get("host") or socket.gethostname()).split(".")[0][:6]
    ip = local_lan_ip()
    return f"{host} {ip}".strip()


def mesh_hosts_up_count(status: dict[str, Any]) -> tuple[int, int]:
    """Count mesh table hosts reporting up vs total."""
    telemetry = as_dict(status.get("telemetry"))
    local = as_dict(telemetry.get("local"))
    remote = as_dict(telemetry.get("remote"))
    remote_hosts = as_dict(remote.get("hosts"))
    noc = as_dict(status.get("noc"))
    up = 0
    for _label, host_id, source, _disk_path in MESH_TABLE_HOSTS:
        ping = noc_ping_glyph(noc, host_id)
        if source == "remote":
            host = as_dict(remote_hosts.get(host_id))
            if host and ping == "?":
                ping = "1" if host.get("ok", True) else "X"
        elif source == "local" and local and ping == "?":
            ping = "1"
        if ping == "1":
            up += 1
    return up, len(MESH_TABLE_HOSTS)


def _service_ok_token(label: str, ok: Any) -> str:
    return f"{label}:{'OK' if ok else 'DN'}"


def lcd_status_line(
    snapshot: dict[str, Any],
    mode: str,
    now: float | None = None,
    width: int = WIDTH,
) -> str:
    """Bottom curses row when IRC input is idle — mesh summary, not a bare '>'."""
    status = as_dict(snapshot.get("status"))
    up, total = mesh_hosts_up_count(status)
    noc = as_dict(status.get("noc"))
    mode_s = mode_tab_short(mode)
    parts = [
        mode_s,
        f"{up}/{total}",
        _service_ok_token("VEC", status.get("vector_ok")),
        _service_ok_token("PBX", status.get("pbx_api_ok")),
        f"WAN:{noc_ping_glyph(noc, 'wan')}",
    ]
    defcon = joshua_defcon_ticker()
    if defcon:
        parts.append(defcon)
    text = " ".join(parts)
    if len(text) > width:
        text = " ".join(parts[:5])
    if len(text) > width:
        text = f"{mode_s} {up}/{total} VEC PBX WAN"[:width]
    return fit(text, width)


def tmux_status_segments(
    snapshot: dict[str, Any] | None,
    mode: str | None,
) -> tuple[str, str]:
    """Plain-text left/right chunks for the physical tmux status row."""
    status = as_dict((snapshot or {}).get("status"))
    mode_s = mode_tab_short(mode or "terrarium")
    up, total = mesh_hosts_up_count(status)
    noc = as_dict(status.get("noc"))
    vec = _service_ok_token("VEC", status.get("vector_ok"))
    pbx = _service_ok_token("PBX", status.get("pbx_api_ok"))
    wan = f"WAN:{noc_ping_glyph(noc, 'wan')}"
    left = f"{mode_s} {up}/{total} {vec} {pbx} {wan}"
    ip = local_lan_ip()
    return left.strip(), ip


def dashboard_footer(snapshot: dict[str, Any], now: float, tick: int, width: int = WIDTH) -> str:
    return fit("".join(text for text, _style in dashboard_footer_segments(snapshot, now, tick, width)), width)


def dashboard_footer_segments(
    snapshot: dict[str, Any],
    now: float,
    tick: int,
    width: int = WIDTH,
) -> list[tuple[str, str]]:
    host_ip = lcd_host_ip_bit(snapshot)
    motive = stable_pick(
        PSEUDOCORP_MOTIVATORS,
        now,
        period=MOTIVE_PERIOD_SEC,
        salt="footer-motd",
    )
    frames: list[str] = []
    if host_ip:
        frames.append(host_ip)
    frames.append(normalize_line(motive))
    body = frames[int(now // FOOTER_FRAME_PERIOD_SEC) % len(frames)]
    speed = scroll_speed_for_text(body, FOOTER_FRAME_PERIOD_SEC, width)
    line = header_ticker_line(body, now, width, speed=speed)
    return [(line, "MOTD")]


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def anim_now(now: float | None = None, step: float = ANIM_STEP_SEC) -> float:
    ts = time.time() if now is None else now
    return float(int(ts // max(0.5, step)) * max(0.5, step))


def marquee(text: str, width: int, speed: float = MARQUEE_SPEED, now: float | None = None) -> str:
    body = re.sub(r"\s+", " ", text or "").strip()
    if not body:
        return " " * width
    body = body + "   "
    if len(body) <= width:
        return body.ljust(width)
    ts = time.time() if now is None else now
    offset = int(ts * speed) % len(body)
    loop = body + body
    return loop[offset : offset + width].ljust(width)


PSEUDOCORP_GREETZ = (
    "GREETZ TO CELES PBX, VECTOR, ZEALTOWER, HERMES, NAVI, CRYSTAL MESH",
    "PSEUDOCORP SYNERGY PIPELINE: ALIGN, MONETIZE, POST THE SLIDE",
    "HYPERBUSINESS MEMELULZ: Q4 VIBES, Q1 PIPE, INFINITE DECKWARE",
    "LINKEDIN THOUGHT LEADERSHIP CACHE HIT: DELIVERABLES ARE EMOTIONAL",
    "GPU LOCALITY STATUS: VECTOR SPINS, ZEALTOWER WAITS, KPI GLOWS",
    "GREETZ TO EVERY AGENT WHO JOINED THE CALL AND BECAME THE ROADMAP",
    "ENTERPRISE TERRARIUM: WATER THE SERVERS, PRUNE THE BACKLOG",
    "PSEUDOCORP BOARD UPDATE: ALL HANDS, NO HANDS, JUST PACKETS",
)

PSEUDOCORP_MOTIVATORS = (
    "Ship the weird useful thing before the deck invents gravity.",
    "A clean graph beats a heroic status meeting.",
    "Your edge is taste plus follow-through. Keep both online.",
    "Turn the noisy channel into a signal and invoice the universe.",
    "Do the smallest real deploy. Let the dashboard absorb the lore.",
    "The LAN is a garden. Metrics are irrigation. Keep pruning.",
    "If it has a health endpoint, it can become a ritual.",
    "Executive presence is just uptime with better lighting.",
)

RGB_QOTD = (
    "Red holds the line, Green repairs the route, Blue names the target.",
    "The RGB battle is won when signal, care, and clarity arrive together.",
    "A clean packet is a promise: send it once, verify it twice.",
    "When the lights split red/green/blue, choose the channel that helps.",
    "Lore is operational memory with better stage lighting.",
    "Blue watches the horizon, Green tends the mesh, Red keeps the gate.",
)

RGB_BATTLE_FRAMES = (
    (
        "   R-AXIOM     G-MENDER     B-LUX   ",
        "    /|\\         /|\\         /|\\     ",
        "   / | \\--==[ CRYSTAL BUS ]==--/\\   ",
        " red holds  green heals  blue sees  ",
    ),
    (
        " R>>>>>      G[[[+]]]      <<<<<B   ",
        "  shield       patch        prism    ",
        "  [RED]---packet oath---[BLUE]       ",
        "        GREEN signs the route        ",
    ),
    (
        "      .---- RGB BATTLE MAP ----.     ",
        " RED: gate  GREEN: mesh  BLUE: sky   ",
        "      '--- lore packets armed ---'   ",
        "        next turn: synchronize       ",
    ),
    (
        " RED CAPTAIN  GREEN OPS  BLUE ORACLE ",
        "    <== fire   <== fix   <== focus   ",
        "        [ ZEAL PALACE SIGNAL ]       ",
        "         courage / repair / read     ",
    ),
)


def stable_pick(rows: tuple[str, ...], now: float, period: int = 11, salt: str = "") -> str:
    if not rows:
        return ""
    bucket = int(now // max(1, period))
    idx = zlib.crc32(f"{bucket}:{salt}".encode("utf-8")) % len(rows)
    return rows[idx]


SCROLLER_FX_EDGE = "◢◣◤◥█▓▒░"
SCROLLER_FX_GLINT = "★☆✦✧◈◇◆◊«»═╬▁▂▃▄▅▆▇"


def demoscene_bottom_scroller(
    text: str,
    now: float,
    width: int = WIDTH,
    speed: float = 1.2,
) -> str:
    """Readable scroll — FX only on edges, message body stays plain."""
    core = re.sub(r"\s+", " ", str(text or "")).strip()
    if not core:
        core = "ZEALPALACE MOTD WARMING UP"
    tick = int(now * speed)
    left = SCROLLER_FX_EDGE[tick % len(SCROLLER_FX_EDGE)]
    right = SCROLLER_FX_EDGE[(tick + 2) % len(SCROLLER_FX_EDGE)]
    body = f"{left} {core} {right}   "
    if len(body) <= width:
        return pad(body, width)
    offset = int(now * speed * 2.0) % len(body)
    loop = body + body
    return pad(loop[offset : offset + width], width)


def chunky_scroller(text: str, now: float, width: int = WIDTH, speed: float = SCROLLER_SPEED) -> str:
    core = re.sub(r"\s+", " ", text or "").strip()
    return demoscene_bottom_scroller(core, now, width, speed=speed)


def raster_bar(now: float, width: int = WIDTH) -> str:
    bands = ("_", "-", "=", "#", "=", "-", "_", ".")
    tick = int(anim_now(now) * RASTER_SPEED)
    return pad("".join(bands[(idx + tick) % len(bands)] for idx in range(width)), width)


def static_rule(width: int = WIDTH) -> str:
    return xtree_hline(width, "=")


def cga_rule(width: int = WIDTH) -> str:
    return pad("+" + ("=" * 8) + "+" + ("-" * max(0, width - 18)) + "+" + ("=" * 6) + "+", width)


TUNNEL_FRAMES: tuple[str, ...] = (
    "<~~~~ CRYSTAL MESH BUS ~~~~>",
    "<<~~~ LAN TERRARIUM LINK ~~~>>",
    "<~~~ PSEUDOCORP NOC FEED ~~~>",
)


def tunnel_line(now: float, width: int = WIDTH) -> str:
    frame = TUNNEL_FRAMES[int(anim_now(now, 12.0) * TUNNEL_SPEED) % len(TUNNEL_FRAMES)]
    speed = scroll_speed_for_text(frame, FX_ROW_PERIOD_SEC, width)
    return header_ticker_line(frame, now, width, speed=speed)


def gpu_summary(snapshot: dict[str, Any]) -> str:
    remote = as_dict(as_dict(as_dict(snapshot.get("status")).get("telemetry")).get("remote"))
    hosts = as_dict(remote.get("hosts"))
    bits = []
    for name, label in (("vector", "VEC"), ("zealtower", "ZTW")):
        host = as_dict(hosts.get(name))
        gpus = host.get("gpus") if isinstance(host.get("gpus"), list) else []
        gpu = as_dict(gpus[0]) if gpus else {}
        if gpu:
            bits.append(
                f"{label} GPU {fmt_pct(gpu.get('util_pct'))} {gpu.get('mem_used_mb', '?')}/{gpu.get('mem_total_mb', '?')}M"
            )
    return " | ".join(bits) or "GPU telemetry warming up"


def demoscene_greetz(snapshot: dict[str, Any], now: float, width: int = WIDTH) -> str:
    greetz = stable_pick(PSEUDOCORP_GREETZ, now, period=GREETZ_PERIOD_SEC, salt="greetz")
    speed = scroll_speed_for_text(greetz, FX_ROW_PERIOD_SEC, width)
    return header_ticker_line(greetz, now, width, speed=speed)


FX_ROW_PERIOD_SEC = 9.0


def demoscene_fx_row(snapshot: dict[str, Any], now: float, width: int = WIDTH) -> str:
    """Rotating bottom-strip eye candy: greetz, tunnel bus, sparkle, raster."""
    phase = int(now // FX_ROW_PERIOD_SEC) % 4
    if phase == 0:
        return demoscene_greetz(snapshot, now, width)
    if phase == 1:
        return tunnel_line(now, width)
    if phase == 2:
        return sparkle_line(now, width)
    return raster_bar(now, width)


def motivational_line(snapshot: dict[str, Any], now: float, width: int = WIDTH) -> str:
    salt = str(as_dict(as_dict(snapshot.get("status")).get("telemetry")).get("remote", ""))
    text = stable_pick(PSEUDOCORP_MOTIVATORS, now, period=MOTIVE_PERIOD_SEC, salt=salt)
    return fit("CEO MODE: " + text, width)


def rgb_quote(now: float | None = None) -> str:
    ts = time.time() if now is None else now
    return stable_pick(RGB_QOTD, ts, period=30 * 60, salt="rgb-qotd")


MODE_ART: dict[str, tuple[str, ...]] = {
    "ops": (
        "+-NOC BUS-+-PBX PATCH-+",
        "|WAN|CELES|PHONES|ALERT|",
        "+---+-----+------+-----+",
        " routes  phones  pulses",
    ),
    "terrarium": (
        "+--- LAN TERRARIUM ---+",
        "|cpu mem disk gpu pkt |",
        "|roots in cache/logs  |",
        "+---------NOC---------+",
    ),
    "uptime": (
        "+---- BOOT AGE ----+",
        "|zealp|ztwr|vect   |",
        "| up  |load|service|",
        "+-- no reboot kabuki",
    ),
    "rpg": (
        "CRYSTAL MESH",
        "RGB TORCH",
        "IRC + BRIDGE",
        "quests live",
    ),
    "rgb": (
        "+---- RGB BATTLE ----+",
        "|RED gate|GRN mesh   |",
        "|BLU read|QOTD armed |",
        "+--- CGA palette ---+",
    ),
    "agents": (
        "  PBX BUS 111-117-122 ",
        " \\__ LAN BUS /__/     ",
        " 123-SIMON 130-LAWYER ",
        " agents in-band talk  ",
    ),
    "bridge": (
        "SillyTavern<=>ZealPalace",
        "cards/worlds->RPG state",
        "IRC #RPG<->bridge feed",
        " co-canon display pane",
    ),
    "lounge": (
        "+--- LIVE CHATTER ---+",
        "|ZealHangs|Palace|RPG|",
        "+-- scrollback log --+",
        " room hums, logs talk",
    ),
}


def sparkle_line(now: float, width: int = WIDTH) -> str:
    chars = ["."] * max(1, width)
    tick = int(anim_now(now) * SPARKLE_SPEED)
    glints = "*+o"
    for idx in range(7):
        pos = (tick + idx * 11) % width
        chars[pos] = glints[(tick + idx) % len(glints)]
    return pad("".join(chars), width)


def comet_line(label: str, now: float, width: int = WIDTH) -> str:
    chars = ["-"] * max(1, width)
    comet = ">>="
    pos = int(anim_now(now) * COMET_SPEED) % width
    for idx, char in enumerate(comet):
        chars[(pos + idx) % width] = char
    title = " " + fit(label, min(len(str(label)) + 1, width - 2)).strip() + " "
    start = max(0, (width - len(title)) // 2)
    for idx, char in enumerate(title[:width]):
        if start + idx < width:
            chars[start + idx] = char
    return pad("".join(chars), width)


def comet_line_segments(label: str, now: float, width: int = WIDTH) -> list[tuple[str, str]]:
    """Comet header — label + comet trail in magenta, rail dashes dim."""
    raw = comet_line(label, now, width)
    title = f" {label.strip()} "
    t_start = max(0, (width - len(title)) // 2)
    t_end = t_start + len(title)
    segments: list[tuple[str, str]] = []
    idx = 0
    while idx < len(raw):
        ch = raw[idx]
        if t_start <= idx < t_end and ch != " ":
            style = "MAG"
        elif ch in ">=":
            style = "MAG"
        else:
            style = "MOTD_FX"
        run = ch
        j = idx + 1
        while j < len(raw):
            cj = raw[j]
            if t_start <= j < t_end and cj != " ":
                sj = "MAG"
            elif cj in ">=":
                sj = "MAG"
            else:
                sj = "MOTD_FX"
            if sj != style:
                break
            run += cj
            j += 1
        segments.append((run, style))
        idx = j
    return pad_colored_segments(segments, width)


def mode_art(mode: str, now: float, width: int = WIDTH) -> list[str]:
    if mode == "rgb":
        rows = list(RGB_BATTLE_FRAMES[int(anim_now(now, RGB_FRAME_SEC) // RGB_FRAME_SEC) % len(RGB_BATTLE_FRAMES)])
    else:
        rows = list(MODE_ART.get(mode, MODE_ART["lounge"]))
    if mode == "rpg":
        tick = int(anim_now(now, 1.0))
        bands = "._-=*=-."
        out: list[str] = []
        for i, row in enumerate(rows):
            core = center(row.strip(), width)
            cells = list(core)
            for col in range(width):
                if cells[col] == " ":
                    cells[col] = bands[(tick + col + i) % len(bands)]
            out.append("".join(cells)[:width])
        return out
    # Block-center the ASCII box, then animate ANSI bands in the side margins.
    # (a one-column breathing gap keeps the centered text clean).
    block_w = max((len(row) for row in rows), default=0)
    left = max(0, (width - block_w) // 2)
    right = left + block_w
    bands = "._-=*=-."
    tick = int(anim_now(now, 1.0))
    out: list[str] = []
    for i, row in enumerate(rows):
        cells = list(pad(" " * left + row[:width], width))
        for col in range(0, max(0, left - 1)):
            cells[col] = bands[(tick + col + i) % len(bands)]
        for col in range(right + 1, width):
            cells[col] = bands[(tick - col + i) % len(bands)]
        out.append("".join(cells)[:width])
    return out


def transition_text(text: Any, now: float, row: int, width: int = WIDTH, window: float = 2.25) -> str:
    return fit(text, width)


def bar(value: Any, width: int = 10) -> str:
    try:
        pct = max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        pct = 0.0
    w = max(4, int(width))
    inner = max(0, w - 2)
    filled = int(round((pct / 100.0) * inner)) if inner else 0
    empty = max(0, inner - filled)
    return chr(0x2595) + (chr(0x2588) * filled) + (chr(0x2591) * empty) + chr(0x258F)


def compact_bar(value: Any, width: int = 6) -> str:
    try:
        pct = max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        pct = 0.0
    filled = int(round((pct / 100.0) * width))
    return (chr(0x2588) * filled) + (chr(0x2591) * (width - filled))


def ascii_bar(value: Any, width: int = 8) -> str:
    try:
        pct = max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        pct = 0.0
    inner = max(0, width - 2)
    filled = int(round((pct / 100.0) * inner))
    return "[" + ("#" * filled) + ("." * (inner - filled)) + "]"


def dual_disk_line(label: str, pct: Any, width: int = WIDTH) -> str:
    ds = fmt_pct(pct)
    return mesh_join(label, " ", ds, "  ", ascii_bar(pct, 10), bar(pct, 8), width)


def dual_disk_line_segments(label: str, pct: Any, width: int = WIDTH) -> list[tuple[str, str]]:
    """Colored DISK row — column widths match mesh_join HOST header in noc_disk_rows."""
    host_style = host_label_style(label)
    usage_style = usage_pct_style(pct)
    ascii_w, uni_w = mesh_bar_widths(width)
    ab = pad(ascii_bar(pct, ascii_w), ascii_w)[:ascii_w]
    ub = pad(bar(pct, uni_w), uni_w)[:uni_w]
    return pad_colored_segments(
        [
            (pad(label, 5)[:5], host_style),
            (" ", "SYS"),
            (pad(fmt_pct(pct), 6)[:6], usage_style),
            (" ", "SYS"),
            (pad("  ", 4)[:4], "SYS"),
            (ab, usage_style),
            (" ", "SYS"),
            (ub, usage_style),
        ],
        width,
    )


def spark(values: Any, width: int = 14) -> str:
    if not isinstance(values, list) or not values:
        return "." * width
    rows = []
    for item in values[-width:]:
        try:
            rows.append(max(0.0, min(100.0, float(item))))
        except (TypeError, ValueError):
            rows.append(0.0)
    levels = "▁▂▃▄▅▆▇█"
    out = []
    for value in rows:
        idx = int((value / 100.0) * (len(levels) - 1))
        out.append(levels[idx])
    return ("▁" * max(0, width - len(out)) + "".join(out))[-width:]


def fmt_pct(value: Any) -> str:
    try:
        return f"{float(value):.0f}%"
    except (TypeError, ValueError):
        return "?%"


def fmt_bps(value: Any) -> str:
    try:
        n = float(value)
    except (TypeError, ValueError):
        n = 0.0
    units = ("B/s", "K/s", "M/s", "G/s")
    unit = units[0]
    for unit in units:
        if n < 1024 or unit == units[-1]:
            break
        n /= 1024.0
    if n >= 10:
        return f"{n:.0f}{unit}"
    return f"{n:.1f}{unit}"


def fmt_uptime(value: Any) -> str:
    try:
        seconds = max(0, int(float(value)))
    except (TypeError, ValueError):
        return "?"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days >= 100:
        return f"{days}d"
    if days:
        return f"{days}d{hours:02d}h"
    if hours:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m"


def uptime_pct(value: Any, target_days: float = 30.0) -> float:
    try:
        seconds = max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0
    return min(100.0, seconds / max(1.0, target_days * 86400.0) * 100.0)


def first_disk_pct(host: dict[str, Any], path: str = "/") -> Any:
    disks = host.get("disks") or []
    if isinstance(disks, list):
        for disk in disks:
            if isinstance(disk, dict) and disk.get("path") == path:
                return disk.get("pct")
        for disk in disks:
            if isinstance(disk, dict) and disk.get("pct") is not None:
                return disk.get("pct")
    return None


def wrap_line(text: str, width: int = WIDTH, max_lines: int = 3, *, truncate: bool = True) -> list[str]:
    clean = re.sub(r"\s+", " ", text or "").strip()
    if not clean:
        return [""]
    chunks = textwrap.wrap(
        clean,
        width=width,
        break_long_words=True,
        break_on_hyphens=False,
    ) or [clean[:width]]
    if len(chunks) > max_lines:
        chunks = chunks[:max_lines]
        if truncate:
            chunks[-1] = fit(chunks[-1], width).rstrip()[: max(0, width - 1)] + "~"
        else:
            chunks[-1] = chunks[-1][:width]
    return chunks


def event_label(event: LcdEvent) -> str:
    if event.source == "ST":
        return "ST"
    if event.source == "GMQ":
        return "GMQ"
    if event.source == "PCORP":
        return "PC"
    return event.source[:4]


def event_time_prefix(event: LcdEvent) -> str:
    ts = event.sort_ts
    if ts <= 0 and event.ts:
        ts = parse_iso_ts(event.ts)
    if ts <= 0:
        return "??:??"
    return datetime.fromtimestamp(ts).strftime("%H:%M")


def event_canon_suffix(event: LcdEvent) -> str:
    if event.canon == "sillytavern":
        return "+"
    if event.canon == "queued":
        return ">"
    if event.stale:
        return "!"
    return ""


def compact_tail(text: str, width: int) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(clean) <= width:
        return clean
    if width <= 3:
        return clean[:width]
    return clean[: width - 3].rstrip() + "..."


def event_age_seconds(event: LcdEvent, now: float) -> float | None:
    ts = event.sort_ts
    if ts <= 0 and event.ts:
        ts = parse_iso_ts(event.ts)
    if ts <= 0:
        return None
    return max(0.0, now - ts)


def event_channel_bracket(channel: str) -> str:
    chan = str(channel or "").strip()
    if not chan:
        return ""
    if chan == "bridge:lore":
        return "[lore]"
    return f"[{chan}]"


def event_prefix_segments(
    event: LcdEvent,
    now: float,
    width: int = WIDTH,
) -> list[tuple[str, str]]:
    _ = width
    parts: list[tuple[str, str]] = []
    age = event_age_seconds(event, now)
    if age is not None:
        parts.append((f"[{fmt_age_short(age)}]", "IRC_TIME"))
    canon = event_canon_suffix(event)
    if canon:
        parts.append((canon, "SYS"))
    parts.extend(event_kind_badge(event))
    return parts


def _wrap_event_body(
    body: str,
    first_width: int,
    cont_width: int,
    max_lines: int,
) -> list[str]:
    clean = re.sub(r"\s+", " ", str(body or "")).strip()
    if not clean:
        return [""]
    lines: list[str] = []
    pos = 0
    for idx in range(max(1, max_lines)):
        room = first_width if idx == 0 else cont_width
        if pos >= len(clean):
            break
        wrapped = textwrap.wrap(
            clean[pos:],
            width=room,
            break_long_words=True,
            break_on_hyphens=False,
        )
        if not wrapped:
            break
        chunk = wrapped[0]
        lines.append(chunk)
        pos += len(chunk)
        while pos < len(clean) and clean[pos] == " ":
            pos += 1
    return lines or [""]


def _line_ends_complete_thought(text: str) -> bool:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean:
        return False
    if clean.endswith("..."):
        return True
    if clean[-1] in ".!?":
        return True
    if clean[-1] in ",;:":
        return True
    last = clean.rsplit(" ", 1)[-1].lower().rstrip(".,!?;:")
    return last not in LCD_EVENT_DANGLING_WORDS


def _mark_truncated_line(line: str, room: int, *, continued: bool = False) -> str:
    text = re.sub(r"\s+", " ", str(line or "")).strip()
    if not text or text.endswith("..."):
        return text[:room] if len(text) > room else text
    if len(text) <= room:
        if not continued and _line_ends_complete_thought(text):
            return text
        if len(text) + 3 <= room:
            return text + "..."
        return text[: max(0, room - 3)].rstrip() + "..."
    if len(text) + 3 <= room:
        return text + "..."
    return text[: max(0, room - 3)].rstrip() + "..."


def _fit_event_body_lines(
    body: str,
    first_width: int,
    cont_width: int,
    max_lines: int,
) -> list[str]:
    """Wrap body to max_lines; never leave a dangling 'battle against the' tail line."""
    clean = re.sub(r"\s+", " ", str(body or "")).strip()
    if not clean:
        return [""]
    full = _wrap_event_body(clean, first_width, cont_width, 999)
    if len(full) <= max(1, max_lines):
        return full[: max(1, max_lines)]

    # Roomy budgets: wrap across rows instead of early clip_sentence chop.
    if max_lines >= 6:
        lines = full[:max_lines]
        while len(lines) > 1 and not _line_ends_complete_thought(lines[-1]):
            lines.pop()
        if len(full) > len(lines) and lines:
            room = cont_width if len(lines) > 1 else first_width
            lines[-1] = _mark_truncated_line(lines[-1], room, continued=True)
        return lines

    budget = max(first_width, first_width + cont_width * max(0, max_lines - 1))
    while budget >= first_width:
        clipped = clip_sentence(clean, budget)
        lines = _wrap_event_body(clipped, first_width, cont_width, max(1, max_lines))
        if len(lines) <= max(1, max_lines) and _line_ends_complete_thought(lines[-1]):
            out = lines[: max(1, max_lines)]
            if clipped != clean and out:
                room = cont_width if len(out) > 1 else first_width
                out[-1] = _mark_truncated_line(out[-1], room, continued=True)
            return out
        budget = int(budget * 0.82)

    for take in range(min(max_lines, len(full)), 0, -1):
        lines = full[:take]
        if _line_ends_complete_thought(lines[-1]):
            if take < len(full) and lines:
                room = cont_width if take > 1 else first_width
                lines[-1] = _mark_truncated_line(lines[-1], room, continued=True)
            return lines

    one = clip_sentence(clean, first_width)
    lines = _wrap_event_body(one, first_width, cont_width, 1)[:1] or [""]
    if lines and len(clean) > len(lines[0].replace("...", "")):
        lines[0] = _mark_truncated_line(lines[0], first_width)
    return lines


EventDrawRow = tuple[
    list[tuple[str, str]],
    list[tuple[str, str]],
    str,
    str,
    float,
    bool,
]


def _row_text(row: EventDrawRow) -> str:
    prefix, body, *_rest = row
    return "".join(text for text, _style in prefix) + "".join(text for text, _style in body)


def _spawn_aware_tail(rows: list[EventDrawRow], slots: int) -> list[EventDrawRow]:
    if not rows:
        return rows
    if _event_base_kind(rows[0][3]) == "spawn":
        verb_rows = [row for row in rows if SPAWN_BODY_RE.search(_row_text(row))]
        if verb_rows:
            return verb_rows[-slots:]
    return rows[-slots:]


def compact_event_draw_rows(
    rows: list[EventDrawRow],
    slots: int,
    newest_base: str,
    *,
    older_tail_lines: int = LCD_EVENT_OLD_MAX_LINES,
) -> list[EventDrawRow]:
    """Keep the newest event intact; trim older chatter to tail lines so wraps are not lost."""
    if len(rows) <= slots or not newest_base:
        return rows[-slots:]
    grouped: dict[str, list[EventDrawRow]] = {}
    order: list[str] = []
    for row in rows:
        base = row[3]
        if base not in grouped:
            grouped[base] = []
            order.append(base)
        grouped[base].append(row)
    compact: list[EventDrawRow] = []
    for base in order:
        chunk = grouped[base]
        if base == newest_base:
            compact.extend(chunk)
        else:
            limit = (
                LCD_EVENT_OLD_NARRATIVE_LINES
                if _event_base_kind(base) in NARRATIVE_EVENT_KINDS
                else max(older_tail_lines, LCD_EVENT_OLD_CHATTER_LINES)
                if _event_base_kind(base) in ("message", "action")
                else older_tail_lines
            )
            compact.extend(_older_event_slice(chunk, base, limit))
    if len(compact) <= slots:
        return compact
    newest_rows = grouped.get(newest_base, [])
    if len(newest_rows) >= slots:
        tail = _spawn_aware_tail(newest_rows, slots)
        if len(newest_rows) > slots and tail:
            prefix, body, line_key, event_base, sort_ts, typeable = tail[-1]
            body_text = "".join(text for text, _style in body)
            if body_text and not body_text.endswith("..."):
                room = max(1, WIDTH - sum(len(text) for text, _style in prefix))
                marked = _mark_truncated_line(body_text, room, continued=True)
                if marked != body_text:
                    style = body[0][1] if body else "IRC_MSG"
                    tail[-1] = (prefix, [(marked, style)], line_key, event_base, sort_ts, typeable)
        return tail
    budget = slots - len(newest_rows)
    trimmed: list[EventDrawRow] = []
    for base in order:
        if base == newest_base:
            continue
        limit = (
            LCD_EVENT_OLD_NARRATIVE_LINES
            if _event_base_kind(base) in NARRATIVE_EVENT_KINDS
            else max(older_tail_lines, LCD_EVENT_OLD_CHATTER_LINES)
            if _event_base_kind(base) in ("message", "action")
            else older_tail_lines
        )
        for row in _older_event_slice(grouped[base], base, limit):
            if len(trimmed) >= budget:
                break
            trimmed.append(row)
    return trimmed + newest_rows


def _event_nick_label(event: LcdEvent) -> str:
    return (event.nick or event.channel.strip("#") or event.kind or "").strip()


def _event_is_realm(event: LcdEvent) -> bool:
    """Realm / world / bridge / system event (rendered light green, not chatter white)."""
    canon = str(getattr(event, "canon", "") or "").lower()
    return canon in ("bridge", "queued", "sillytavern", "lore", "realm", "gm", "ops", "world")


EVENT_KIND_STYLES: dict[str, str] = {
    "message": "IRC_MSG",
    "action": "GRAY",
    "lore": "ST",
    "battle": "RED",
    "travel": "CYAN",
    "weather": "ART",
    "realm": "GREEN",
    "realm_event": "GREEN",
    "meteor": "RED",
    "plague": "MAG",
    "blessing": "YELLOW",
    "eclipse": "RGB",
    "festival": "MOTD",
    "invasion": "RED",
    "earthquake": "YELLOW",
    "gold_rain": "MOTD",
    "death": "RED",
    "birth": "YELLOW",
    "marriage": "MAG",
    "notice": "LOG",
    "react": "ZH",
    "rebirth": "GREEN",
    "spawn": "GREEN",
    "gm_queue": "GMQ",
    "gm": "GMQ",
    "bridge": "ST",
    "status": "SYS",
    "pbx": "PBX",
    "rpg": "RPG",
}


def event_msg_style(event: LcdEvent) -> str:
    kind = str(event.kind or "message").lower()
    body = re.sub(r"\s+", " ", str(event.text or "")).strip().lower()
    if "atmosphere shifts" in body:
        return "ART"
    if kind in EVENT_KIND_STYLES:
        return EVENT_KIND_STYLES[kind]
    if kind == "message" and not _event_is_realm(event):
        return "IRC_MSG"
    idx = sum(ord(ch) for ch in (kind or "evt")) % len(COMPANION_LINE_COLORS)
    return COMPANION_LINE_COLORS[idx]


def event_kind_badge(event: LcdEvent) -> list[tuple[str, str]]:
    kind = str(event.kind or "message").lower()
    if kind in ("message", "presence", "status", "action"):
        return []
    label = kind.replace("_", " ")[:8].upper()
    return [(f"{label} ", event_msg_style(event))]


def event_nick_style(event: LcdEvent) -> str:
    nick = _event_nick_label(event).lower().rstrip("_")
    if nick in IRC_NICK_STYLES:
        return IRC_NICK_STYLES[nick]
    if nick:
        idx = sum(ord(ch) for ch in nick) % len(COMPANION_LINE_COLORS)
        return COMPANION_LINE_COLORS[idx]
    return {
        "ZP": "ZP",
        "ZH": "ZH",
        "RPG": "RPG",
        "ST": "ST",
        "PCORP": "PBX",
        "GMQ": "GMQ",
    }.get(event.source, "IRC_NICK")


def event_display_rows(
    event: LcdEvent,
    width: int = WIDTH,
    now: float | None = None,
    max_body_lines: int = LCD_EVENT_MAX_BODY_LINES,
) -> list[list[tuple[str, str]]]:
    now_ts = time.time() if now is None else now
    body = re.sub(r"\s+", " ", str(event.text or "")).strip()
    nick = _event_nick_label(event)
    nick_style = event_nick_style(event)

    if event.kind in ("presence", "status") and not body:
        body = f"{nick} {event.kind}".strip()

    meta = event_prefix_segments(event, now_ts, width)
    nick_segments: list[tuple[str, str]] = []
    msg_style = event_msg_style(event)
    # Bracketed bright nick ONLY for real chatter (someone speaking/acting).
    # Lore/GM/bridge/status events are narration, not a speaker -- no fake nick.
    if nick and event.kind in ("message", "action"):
        nick_segments = [("[", nick_style), (nick, nick_style), ("] ", nick_style)]

    # Reserve one column for the blinking typewriter cursor on complete chatter lines.
    cursor_eligible_base = bool(body) and event.kind not in ("presence", "status")
    cursor_reserve = 1 if cursor_eligible_base else 0
    prefix_len = sum(len(text) for text, _style in meta + nick_segments)
    first_room = max(1, width - prefix_len - cursor_reserve)
    cont_room = max(1, width - cursor_reserve)
    full_lines = _wrap_event_body(body, first_room, cont_room, 999)
    max_lines = max(1, max_body_lines)
    truncated = len(full_lines) > max_lines
    body_lines = _fit_event_body_lines(body, first_room, cont_room, max_lines)

    last_idx = len(body_lines) - 1
    rows: list[list[tuple[str, str]]] = []
    for idx, chunk in enumerate(body_lines):
        if idx == 0:
            segments = [*meta, *nick_segments, (chunk, msg_style)]
        else:
            segments = [(chunk, msg_style)]
        rows.append(pad_colored_segments(segments, width))
    if not rows:
        rows.append(pad_colored_segments([*meta, *nick_segments], width))
    return rows


def _event_body_key(event: LcdEvent) -> str:
    body = re.sub(r"\s+", " ", str(event.text or "")).strip()
    return f"{event.source}|{event.channel}|{event.nick}|{event.kind}|{event.sort_ts}|{body[:96]}"


def _event_base_kind(event_base: str) -> str:
    parts = str(event_base or "").split("|")
    return parts[3].lower() if len(parts) > 3 else "message"


def event_old_max_lines(event: LcdEvent) -> int:
    kind = str(event.kind or "message").lower()
    if kind in ("spawn", "birth", "rebirth", "rpg"):
        return LCD_EVENT_OLD_NARRATIVE_LINES
    if kind in ("message", "action"):
        return LCD_EVENT_OLD_CHATTER_LINES
    if kind in NARRATIVE_EVENT_KINDS or event.source in ("ST", "GMQ"):
        return LCD_EVENT_OLD_NARRATIVE_LINES
    return LCD_EVENT_OLD_MAX_LINES


def _older_event_slice(chunk: list[EventDrawRow], event_base: str, limit: int) -> list[EventDrawRow]:
    """Narration and spawn lines keep the tail so 'materializes at X' survives compaction."""
    take = max(1, limit)
    kind = _event_base_kind(event_base)
    if kind in NARRATIVE_EVENT_KINDS or kind in ("spawn", "birth", "rebirth", "rpg"):
        return chunk[-take:]
    if kind in ("message", "action"):
        return chunk[:take]
    return chunk[-take:]


def event_wrap_line_count(
    event: LcdEvent,
    width: int = WIDTH,
    now: float | None = None,
) -> int:
    ts = time.time() if now is None else now
    return len(event_display_entries(event, width, now=ts, max_body_lines=999))


def build_event_zone_rows(
    events: list[LcdEvent],
    slots: int,
    width: int = WIDTH,
    now: float | None = None,
) -> list[EventDrawRow]:
    """Fill the EVENTS zone bottom-up: expand newest wraps to use spare rows."""
    ts = time.time() if now is None else now
    if slots <= 0 or not events:
        return []
    cap = max(8, min(len(events), LCD_EVENTS_ON_SCREEN))
    batch = list(events)[-cap:]
    newest_base = _event_body_key(batch[-1])
    newest_full = event_wrap_line_count(batch[-1], width, ts)
    reserve = max(0, len(batch) - 1)
    newest_budget = min(newest_full, max(1, slots - reserve))

    def _assemble(newest_lines: int) -> list[EventDrawRow]:
        rows: list[EventDrawRow] = []
        for event in batch:
            is_newest = _event_body_key(event) == newest_base
            max_lines = newest_lines if is_newest else event_old_max_lines(event)
            rows.extend(event_display_entries(event, width, now=ts, max_body_lines=max_lines))
        return compact_event_draw_rows(rows, slots, newest_base)

    out = _assemble(newest_budget)
    spare = slots - len(out)
    if spare > 0 and newest_budget < newest_full:
        out = _assemble(min(newest_full, newest_budget + spare))
    return out


def event_display_entries(
    event: LcdEvent,
    width: int = WIDTH,
    now: float | None = None,
    max_body_lines: int = LCD_EVENT_MAX_BODY_LINES,
) -> list[tuple[list[tuple[str, str]], list[tuple[str, str]], str, str, float, bool]]:
    """Prefix/body split, line key, event base, sort_ts, and typeable flag."""
    now_ts = time.time() if now is None else now
    body = re.sub(r"\s+", " ", str(event.text or "")).strip()
    nick = _event_nick_label(event)
    nick_style = event_nick_style(event)

    if event.kind in ("presence", "status") and not body:
        body = f"{nick} {event.kind}".strip()

    meta = event_prefix_segments(event, now_ts, width)
    nick_segments: list[tuple[str, str]] = []
    msg_style = event_msg_style(event)
    if nick and event.kind in ("message", "action"):
        nick_segments = [("[", nick_style), (nick, nick_style), ("] ", nick_style)]

    typeable = bool(body) and event.kind in ("message", "action")
    cursor_reserve = 1 if typeable else 0
    prefix_len = sum(len(text) for text, _style in meta + nick_segments)
    first_room = max(1, width - prefix_len - cursor_reserve)
    cont_room = max(1, width - cursor_reserve)
    body_lines = _fit_event_body_lines(body, first_room, cont_room, max(1, max_body_lines))

    event_base = _event_body_key(event)
    out: list[tuple[list[tuple[str, str]], list[tuple[str, str]], str, str, float, bool]] = []
    for idx, chunk in enumerate(body_lines):
        prefix = [*meta, *nick_segments] if idx == 0 else []
        body_seg = [(chunk, msg_style)] if chunk else []
        line_key = f"{event_base}|{idx}"
        out.append((prefix, body_seg, line_key, event_base, float(event.sort_ts or 0.0), typeable))
    if not out:
        out.append(([*meta, *nick_segments], [], f"{event_base}|0", event_base, float(event.sort_ts or 0.0), typeable))
    return out


LCD_TYPEWRITER_CPS = 32.0
LCD_CURSOR_BLINK_SEC = 0.45
LCD_CURSOR_CHAR = "\u2588"
LCD_CURSOR_STYLE = "CURSOR"


def _segments_content_chars(segments: list[tuple[str, str]], width: int) -> list[tuple[str, str]]:
    chars: list[tuple[str, str]] = []
    col = 0
    for text, style in segments:
        for ch in text:
            if col >= width:
                break
            chars.append((ch, style))
            col += 1
    while chars and chars[-1][0] == " " and chars[-1][1] == "SYS":
        chars.pop()
    return chars


def _chars_to_segments(chars: list[tuple[str, str]], width: int) -> list[tuple[str, str]]:
    if not chars:
        return pad_colored_segments([("", "SYS")], width)
    out: list[tuple[str, str]] = []
    for ch, style in chars:
        if out and out[-1][1] == style:
            out[-1] = (out[-1][0] + ch, style)
        else:
            out.append((ch, style))
    return pad_colored_segments(out, width)


class LcdTypewriter:
    """Type-in newly pinned EVENT rows with a solid blinking block cursor."""

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._started: dict[str, float] = {}
        self._primed = False

    def prime(self, keys: Iterable[str], now: float) -> None:
        past = now - 9999.0
        for key in keys:
            self._seen.add(key)
            self._started[key] = past
        self._primed = True

    def prune(self, active: set[str]) -> None:
        for key in list(self._started):
            if key not in active:
                del self._started[key]
        self._seen.intersection_update(active)

    def cursor_blink_on(self, now: float) -> bool:
        return int(now / LCD_CURSOR_BLINK_SEC) % 2 == 0

    def prepare(self, rows: list[tuple[str, int]], now: float) -> None:
        """Register staggered start times for rows being typed: (line_key, body_len)."""
        if not self._primed:
            self.prime([key for key, _length in rows], now)
            return
        delay = 0.0
        for key, length in rows:
            if key in self._started:
                continue
            self._seen.add(key)
            self._started[key] = now + delay
            delay += max(1, length) / LCD_TYPEWRITER_CPS + 0.06

    def reveal(
        self,
        prefix_segments: list[tuple[str, str]],
        body_segments: list[tuple[str, str]],
        line_key: str,
        now: float,
        width: int,
        *,
        animate: bool,
    ) -> list[tuple[str, str]]:
        full = pad_colored_segments([*prefix_segments, *body_segments], width)
        if not animate or not self._primed:
            return full

        prefix_chars = _segments_content_chars(prefix_segments, width)
        prefix_len = len(prefix_chars)
        body_chars = _segments_content_chars(body_segments, width)
        body_len = len(body_chars)
        if body_len <= 0:
            return full

        start = self._started.get(line_key, now)
        elapsed = max(0.0, now - start)
        visible = min(body_len, int(elapsed * LCD_TYPEWRITER_CPS))

        if visible >= body_len:
            return _chars_to_segments(prefix_chars + body_chars, width)

        if visible <= 0:
            return _chars_to_segments(prefix_chars, width)

        out = prefix_chars + body_chars[:visible]
        if self.cursor_blink_on(now) and len(out) < width:
            out.append((LCD_CURSOR_CHAR, LCD_CURSOR_STYLE))
        return _chars_to_segments(out, width)


def event_channel_short(channel: str) -> str:
    chan = str(channel or "").strip()
    if not chan:
        return ""
    if chan.startswith("#"):
        name = chan[1:]
        if len(name) > 9:
            return "#" + name[:8] + "~"
        return "#" + name
    if chan == "bridge:lore":
        return "lore"
    if ":" in chan:
        head, tail = chan.split(":", 1)
        short = f"{head[:2]}:{tail[:5]}"
        return short[:9]
    return chan[:9]


def event_segments(
    event: LcdEvent,
    width: int = WIDTH,
    now: float | None = None,
) -> list[tuple[str, str]]:
    rows = event_display_rows(event, width, now=now, max_body_lines=1)
    if rows:
        return rows[0]
    return [("", "SYS")]


def event_head(event: LcdEvent) -> str:
    nick = event.nick or event.channel.strip("#") or event.kind
    canon = event_canon_suffix(event)
    chan = event_channel_short(event.channel)
    prefix = canon
    if chan:
        prefix += (" " if prefix else "") + chan
    if event.kind == "action":
        return prefix + " *" + nick + " "
    if event.kind in ("presence", "status"):
        return prefix + " "
    return prefix + (" " if prefix else "") + (nick + ": " if nick else "")


def event_lines(
    event: LcdEvent,
    width: int = WIDTH,
    now: float | None = None,
    max_body_lines: int = LCD_EVENT_MAX_BODY_LINES,
) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for segments in event_display_rows(event, width, now=now, max_body_lines=max_body_lines):
        text = "".join(part for part, _style in segments)
        rows.append((pad(text, width), event.source))
    return rows


def newest(events: list[LcdEvent], source: str | None = None, n: int = 3) -> list[LcdEvent]:
    rows = events
    if source:
        rows = [event for event in events if event.source == source]
    return sorted(rows, key=lambda event: event.sort_ts)[-n:]


def mode_name(now: float, modes: tuple[str, ...] = XTREE_MODES) -> str:
    return modes[int(now // MODE_PERIOD_SEC) % len(modes)]


def header_title(snapshot: dict[str, Any], mode: str, width: int = WIDTH) -> str:
    bridge = snapshot.get("bridge") or {}
    celes = snapshot.get("celes") or {}
    direct = snapshot.get("direct_irc") or {}
    badges = []
    if bridge.get("ok"):
        badges.append("BR")
    else:
        badges.append("BR!")
    if direct.get("ok"):
        badges.append("IRC")
    elif celes.get("fresh"):
        badges.append("LOG")
    else:
        badges.append("LOCAL")
    if not celes.get("fresh"):
        badges.append("STALE")
    label = XTREE_LABELS.get(mode, mode[:4].upper())
    return center(f"ZEALTREE {label} {'/'.join(badges)}", width)


def pbx_phone_summary_map(status: dict[str, Any]) -> dict[str, str]:
    phones = as_dict(status.get("pbx_phones"))
    out: dict[str, str] = {}
    for row in phones.get("phones") or []:
        if not isinstance(row, dict):
            continue
        ext = str(row.get("ext") or "").strip()
        summary = str(row.get("last_call_summary") or "").strip()
        if ext and summary:
            out[ext] = summary
    return out


def _agent_ticker_idle(summary: str) -> bool:
    clean = re.sub(r"\s+", " ", str(summary or "")).strip()
    return not clean or bool(AGENT_TICKER_IDLE_RE.search(clean))


def _agent_summary_fresh(ext: str, summary: str, status: dict[str, Any], now: float) -> bool:
    """Show agent ticker lines only after a recent call or a newly changed summary."""
    if _agent_ticker_idle(summary):
        return False
    last_call_ts = pbx_phone_last_call_ts_map(status).get(ext, 0.0)
    if last_call_ts and now - last_call_ts <= AGENT_CALL_FRESH_SEC:
        _AGENT_TICKER_SEEN[ext] = (summary, now)
        return True
    if ext == "122":
        navi = as_dict(status.get("navi"))
        navi_ts = parse_iso_ts(str(navi.get("updated") or navi.get("ts") or ""))
        if navi_ts and now - navi_ts <= AGENT_TICKER_SHOW_SEC:
            _AGENT_TICKER_SEEN[ext] = (summary, now)
            return True
    prev = _AGENT_TICKER_SEEN.get(ext)
    if not prev or prev[0] != summary:
        _AGENT_TICKER_SEEN[ext] = (summary, now)
        return True
    if now - prev[1] <= AGENT_TICKER_SHOW_SEC:
        return True
    return False


def agent_ticker_bits(status: dict[str, Any], now: float | None = None) -> list[str]:
    """Call-summary one-liners for mesh PBX agents — only while fresh."""
    ts = time.time() if now is None else now
    bits: list[str] = []
    agent_tickers = as_dict(status.get("agent_tickers"))
    agents = agent_tickers.get("agents") if isinstance(agent_tickers.get("agents"), dict) else {}
    phone_summaries = pbx_phone_summary_map(status)
    navi = as_dict(status.get("navi"))
    navi_line = str(navi.get("ticker") or "").strip()
    for ext, label in AGENT_TICKER_ROSTER:
        block = agents.get(ext) if isinstance(agents, dict) else None
        summary = ""
        if isinstance(block, dict):
            summary = str(block.get("summary") or "").strip()
        if not summary and ext == "122" and navi_line:
            summary = navi_line
        if not summary:
            summary = phone_summaries.get(ext, "")
        if summary and _agent_summary_fresh(ext, summary, status, ts):
            bits.append(f"{label} {normalize_line(summary)}")
    return bits


def lan_bus_status_line(status: dict[str, Any], width: int = WIDTH) -> str:
    states = pbx_phone_state_map(status)
    bits: list[str] = []
    for ext, tag in (("111", "HER"), ("117", "HOL"), ("122", "NAV"), ("123", "SIM"), ("130", "LAW")):
        raw = states.get(ext, "?")
        st = raw[:4] if raw else "?"
        bits.append(f"{tag}:{st}")
    vec = "VEC+" if status.get("vector_ok") else "VEC-"
    pbx = "PBX+" if status.get("pbx_api_ok") else "PBX-"
    return fit(f"LAN BUS {' '.join(bits)} {vec} {pbx}", width)


def agents_art_live(snapshot: dict[str, Any], width: int = WIDTH, now: float | None = None) -> list[str]:
    """PBX agents slide: animated LAN BUS rails + live mesh strip + scrolling roster."""
    ts = time.time() if now is None else now
    status = snapshot.get("status") or {}
    tick = int(anim_now(ts, 1.0))
    rail = "".join("=" if (idx + tick) % 4 else ">" for idx in range(width))
    roster = "PBX BUS 111 HERMES / 117 HOLYBELL / 122 NAVI / 123 SIMON / 130 LAWYER"
    return [
        pad(rail, width),
        lan_bus_status_line(status, width),
        demoscene_bottom_scroller(roster, ts, width, speed=1.4),
    ]


def ticker_text(snapshot: dict[str, Any], now: float | None = None) -> str:
    status = snapshot.get("status") or {}
    bridge = snapshot.get("bridge") or {}
    ts = time.time() if now is None else now
    bits: list[str] = [
        f"tkr {LCD_TICKER_VERSION}",
        "VEC " + ("OK" if status.get("vector_ok") else "DOWN"),
        "PBX " + ("OK" if status.get("pbx_api_ok") else "DOWN"),
        f"zone {short_text(bridge.get('hot_zone') or '?', 14)}",
        f"npc {bridge.get('npc_count', 0)}",
    ]
    bits.extend(agent_ticker_bits(status, now=ts))
    return " · ".join(bit for bit in bits if bit)


def banner_text(snapshot: dict[str, Any]) -> str:
    bridge = snapshot.get("bridge") or {}
    battle = bridge.get("battle") or {}
    if battle.get("active"):
        monster = battle.get("monster", {}).get("name", "threat")
        return f"ACTIVE BATTLE: {monster}"
    realm = bridge.get("realm_event")
    if isinstance(realm, dict) and realm.get("name"):
        return "REALM EVENT: " + short_text(realm.get("name"), 28)
    era = str(bridge.get("era") or "pre-meteor").replace("2026-06-15-end-of-day-", "eod-")
    return f"RPG {short_text(era, 18)} | {short_text(bridge.get('hot_zone'), 15)}"


def panel_lines(
    snapshot: dict[str, Any],
    mode: str,
    width: int = WIDTH,
    now: float | None = None,
    call_exts: set[str] | None = None,
    sip_flash: Any | None = None,
    max_rows: int | None = None,
) -> list[tuple[DetailRow, str]]:
    status = snapshot.get("status") or {}
    bridge = snapshot.get("bridge") or {}
    ts = time.time() if now is None else now
    if mode == "terrarium":
        rows = terrarium_panel(status, snapshot, width, now=ts)
    elif mode == "uptime":
        rows = uptime_panel(status, snapshot, width, now=ts)
    elif mode == "ops":
        rows = ops_panel(status, snapshot, width, now=ts)
    elif mode == "rpg":
        rows = rpg_panel(bridge, width, now=ts)
    elif mode == "rgb":
        rows = rgb_battle_panel(snapshot, width, now=ts)
    elif mode == "agents":
        rows = agents_panel(bridge, status, width, now=ts, call_exts=call_exts, sip_flash=sip_flash)
    elif mode == "bridge":
        rows = bridge_panel(bridge, width, now=ts)
    elif mode == "lounge":
        rows = lounge_panel(snapshot.get("events") or [], width, now=ts)
    else:
        rows = bridge_panel(bridge, width, now=ts)
    if max_rows is not None:
        return rows[: max(1, max_rows)]
    return rows


def terrarium_panel(
    status: dict[str, Any],
    snapshot: dict[str, Any],
    width: int,
    now: float | None = None,
) -> list[tuple[str, str]]:
    telemetry = as_dict(status.get("telemetry"))
    local = as_dict(telemetry.get("local"))
    remote = as_dict(telemetry.get("remote"))
    remote_hosts = as_dict(remote.get("hosts"))
    hist = as_dict(local.get("history"))
    net = as_dict(local.get("net"))
    noc = as_dict(status.get("noc"))

    rows: list[tuple[str, str]] = [
        (detail_table_header(width), "CYAN"),
        (detail_table_rule(width), "SYS"),
        (
            vitals_row(
                "ZEA",
                local.get("uptime_sec"),
                local.get("cpu_pct"),
                local.get("mem_pct"),
                local.get("root_disk_pct") or first_disk_pct(local, "/"),
                width,
            ),
            "NOC",
        ),
    ]
    for name, label, style, disk_path in (
        ("zealtower", "ZTW", "ST", "/mnt/cache"),
        ("vector", "VEC", "RPG", "C:/"),
    ):
        host = as_dict(remote_hosts.get(name))
        if not host:
            rows.append((vitals_row(label, None, None, None, None, width), "SYS"))
            continue
        disk_pct = first_disk_pct(host, disk_path) or first_disk_pct(host)
        rows.append(
            (
                vitals_row(
                    label,
                    host.get("uptime_sec"),
                    host.get("cpu_pct"),
                    host.get("mem_pct"),
                    disk_pct,
                    width,
                ),
                style,
            )
        )
    ts = time.time() if now is None else now
    terr_key_w = TERRARIUM_DETAIL_KEY_W
    rows.extend(
        [
            (
                detail_kv(
                    "TXRX",
                    f"Rx {fmt_bps(net.get('rx_bps'))} Tx {fmt_bps(net.get('tx_bps'))} "
                    f"temp {local.get('temp_c') or '?'}C",
                    width,
                    now=ts,
                    scroll=False,
                    key_w=terr_key_w,
                    fill=True,
                ),
                "NOC",
            ),
            (
                detail_kv(
                    "SYNC",
                    mesh_sync_alert_summary(status, snapshot, ts),
                    width,
                    now=ts,
                    key_w=terr_key_w,
                ),
                "SYS",
            ),
        ]
    )
    return rows[:7]


def uptime_panel(
    status: dict[str, Any],
    snapshot: dict[str, Any],
    width: int,
    now: float | None = None,
) -> list[tuple[str, str]]:
    telemetry = as_dict(status.get("telemetry"))
    local = as_dict(telemetry.get("local"))
    remote = as_dict(telemetry.get("remote"))
    remote_hosts = as_dict(remote.get("hosts"))
    host_specs = (
        ("ZEA", local, "NOC", "/"),
        ("ZTW", as_dict(remote_hosts.get("zealtower")), "ST", "/mnt/cache"),
        ("VEC", as_dict(remote_hosts.get("vector")), "RPG", "C:/"),
    )

    rows: list[tuple[str, str]] = [
        (uptime_table_header(width), "CYAN"),
        (uptime_table_rule(width), "SYS"),
    ]
    longest_label = "?"
    longest_host: dict[str, Any] = {}
    longest_uptime = -1
    for label, host, style, _disk_path in host_specs:
        if not host:
            rows.append((uptime_host_row(label, None, width), "SYS"))
            continue
        uptime = host.get("uptime_sec")
        try:
            uptime_value = int(float(uptime))
        except (TypeError, ValueError):
            uptime_value = -1
        if uptime_value > longest_uptime:
            longest_label = label
            longest_host = host
            longest_uptime = uptime_value
        rows.append((uptime_host_row(label, host, width), style))

    ts = time.time() if now is None else now
    if longest_uptime >= 0:
        longest_bit = (
            f"{longest_label} {host_long_name(longest_label, longest_host)} "
            f"{fmt_uptime(longest_uptime)}"
        )
    else:
        longest_bit = "waiting for telemetry"
    rows.append(
        (
            detail_kv("LONGEST UP", longest_bit, width, now=ts, scroll=False),
            "NOC",
        )
    )
    rows.append(
        (
            detail_kv(
                "SYNC",
                mesh_sync_alert_summary(status, snapshot, ts),
                width,
                now=ts,
            ),
            "SYS",
        )
    )
    return rows[:7]


def noc_mesh_host_line(noc: dict[str, Any], width: int) -> str:
    inet = as_dict(noc.get("internet"))
    wan = "1" if inet.get("up", True) else "X"
    nid = "1" if inet.get("nidhogg_up", True) else "X"
    mid = "1" if inet.get("midgard_up", True) else "X"
    bits = [f"WAN{wan}", f"NID{nid}", f"MID{mid}"]
    for host in noc.get("hosts") or []:
        if not isinstance(host, dict):
            continue
        label = str(host.get("name") or host.get("id") or "?")[:3].upper()
        if host.get("up"):
            state = "1"
        elif host.get("recent_offline"):
            state = "0"
        else:
            state = "X"
        bits.append(f"{label}{state}")
    return fit(" ".join(bits) or "NOC waiting for CELES push", width)


def _mesh_host_record(
    short: str,
    host_id: str,
    source: str,
    noc: dict[str, Any],
    status: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if source == "local" and status:
        telemetry = as_dict(status.get("telemetry"))
        return as_dict(telemetry.get("local")) or None
    if source == "remote" and status:
        telemetry = as_dict(status.get("telemetry"))
        remote = as_dict(telemetry.get("remote"))
        remote_hosts = as_dict(remote.get("hosts"))
        return as_dict(remote_hosts.get(host_id)) or None
    if source == "noc":
        for row in noc.get("hosts") or []:
            if isinstance(row, dict) and str(row.get("id") or "") == host_id:
                return row
    return None


def noc_mesh_dns_line(noc: dict[str, Any], status: dict[str, Any] | None = None) -> str:
    """Scrollable mesh hostnames — ping state already lives in the HOST TABLE P column."""
    bits: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        token = re.sub(r"\s+", " ", str(name or "")).strip()
        if not token:
            return
        key = token.lower()
        if key in seen:
            return
        seen.add(key)
        bits.append(token)

    add(f"celes{MESH_DNS_SUFFIX}")
    add("nidhogg")
    add("midgard")
    for short, host_id, source, _disk_path in MESH_TABLE_HOSTS:
        host = _mesh_host_record(short, host_id, source, noc, status)
        add(host_long_name(short, host))
        for alias in HOST_DNS_ALIASES.get(short, ()):
            add(alias)
        if host:
            reported = str(host.get("host") or host.get("name") or "").strip()
            if reported:
                add(reported)
    for row in noc.get("hosts") or []:
        if not isinstance(row, dict):
            continue
        add(str(row.get("host") or row.get("name") or row.get("id") or "").strip())
    return "  ".join(bits) or "mesh hostnames waiting for CELES push"


def noc_disk_rows(status: dict[str, Any], width: int) -> list[tuple[MeshRow, str]]:
    telemetry = as_dict(status.get("telemetry"))
    local = as_dict(telemetry.get("local"))
    remote = as_dict(telemetry.get("remote"))
    remote_hosts = as_dict(remote.get("hosts"))
    specs = (
        ("ZEA", local, "/"),
        ("ZTW", as_dict(remote_hosts.get("zealtower")), "/mnt/cache"),
        ("VEC", as_dict(remote_hosts.get("vector")), "C:/"),
    )
    rows: list[tuple[str, str]] = [
        (mesh_join("HOST", " ", "DISK%", "  ", MESH_COL_ASCII, MESH_COL_BLOCK, width), "CYAN"),
        (mesh_join("-----", "-", "----", "  ", "----------", "----------", width), "SYS"),
    ]
    for label, host, disk_path in specs:
        if not host:
            empty = chr(0x2595) + (chr(0x2591) * 8) + chr(0x258F)
            rows.append((mesh_join(label, " ", "  --", "  ", "[........]", empty, width), "SYS"))
            continue
        pct = first_disk_pct(host, disk_path) or first_disk_pct(host)
        rows.append((dual_disk_line_segments(label, pct, width), host_label_style(label)))
    return rows


def ops_panel(
    status: dict[str, Any],
    snapshot: dict[str, Any],
    width: int,
    now: float | None = None,
) -> list[tuple[DetailRow, str]]:
    """NOC slide — colored HOST TABLE with ping bars (primary mesh view)."""
    ts = time.time() if now is None else now
    return mesh_table_rows(status, snapshot, width, now=ts)[:7]


def rpg_panel(bridge: dict[str, Any], width: int, now: float | None = None) -> list[tuple[str, str]]:
    npcs = bridge.get("npc_active") or []
    npc_bits = []
    for row in npcs[:4]:
        npc_bits.append(
            f"{row.get('name')} L{row.get('level')} {short_text(row.get('location'), 10)}"
        )
    battle = bridge.get("battle") or {}
    battle_line = "none"
    if battle.get("active"):
        battle_line = short_text(battle.get("monster", {}).get("name"), 28)
    ts = time.time() if now is None else now
    pop_value = (
        f"NPC {bridge.get('npc_count', 0)} "
        f"PL {bridge.get('players_total', 0)} "
        f"GMQ {len(bridge.get('gm_pending') or [])}"
    )
    return [
        (detail_kv_header(width), "CYAN"),
        (detail_kv_rule(width), "SYS"),
        (detail_kv("ERA", short_text(bridge.get("era"), 24), width, now=ts, scroll=False), "RPG"),
        (detail_kv("HOT ZONE", short_text(bridge.get("hot_zone"), 24), width, now=ts, scroll=False), "RPG"),
        (detail_kv("POPULATION", pop_value, width, now=ts, scroll=False), "RPG"),
        (detail_kv("BATTLE", short_text(battle_line, 24), width, now=ts, scroll=False), "RPG"),
        (detail_kv("ACTIVE NPC", short_text(" | ".join(npc_bits) or "waiting", 26), width, now=ts, scroll=False), "RPG"),
    ]


def rgb_battle_panel(snapshot: dict[str, Any], width: int, now: float | None = None) -> list[tuple[str, str]]:
    bridge = as_dict(snapshot.get("bridge"))
    status = as_dict(snapshot.get("status"))
    quote_rows = wrap_line(rgb_quote(), width - 6, max_lines=2)
    zone = short_text(bridge.get("hot_zone") or "Crystal Mesh", 18)
    era = str(bridge.get("era") or "pre-meteor").replace("2026-06-15-end-of-day-", "eod-")
    vec = "online" if status.get("vector_ok") else "offline"
    pbx = "online" if status.get("pbx_api_ok") else "offline"
    ts = time.time() if now is None else now
    rows: list[tuple[str, str]] = [
        (detail_kv_header(width), "CYAN"),
        (detail_kv_rule(width), "SYS"),
        (detail_kv("QOTD", quote_rows[0], width, now=ts), "MAG"),
    ]
    rows.extend(
        [
            (
                detail_kv(
                    "RGB ROLES",
                    "GATE hold  MESH repair  SKY read signal",
                    width,
                    now=ts,
                ),
                "MAG",
            ),
            (detail_kv("ZONE / ERA", f"{zone} / {short_text(era, 40)}", width, now=ts), "ST"),
            (detail_kv("OBJECTIVE", f"VEC {vec}  PBX {pbx}", width, now=ts), "NOC"),
        ]
    )
    if len(quote_rows) > 1:
        rows.insert(3, (detail_kv("QOTD MORE", quote_rows[1], width, now=ts), "MAG"))
    while len(rows) < 7:
        rows.append((detail_kv("STORY WAIT", "packet waiting for next tick", width, now=ts), "SYS"))
    return rows[:7]


def _sip_transcript_live(sip_flash: Any | None) -> bool:
    if sip_flash is None:
        return False
    active_fn = getattr(sip_flash, "active", None)
    if not callable(active_fn) or not active_fn():
        return False
    try:
        return max(0, int(getattr(sip_flash, "active_lines", 0) or 0)) > 0
    except (TypeError, ValueError):
        return True


def agents_panel(
    bridge: dict[str, Any],
    status: dict[str, Any],
    width: int,
    now: float | None = None,
    call_exts: set[str] | None = None,
    sip_flash: Any | None = None,
) -> list[tuple[DetailRow, str]]:
    ts = time.time() if now is None else now
    roster = pbx_agent_roster(bridge)
    active_exts = set(call_exts or ())
    active_exts.update(read_active_call_exts_highlight())
    phone_states = pbx_phone_state_map(status)
    call_ts_map = merge_ext_ts_maps(
        read_ext_last_call_ts(),
        pbx_phone_last_call_ts_map(status),
    )
    seen_ts_map = pbx_phone_last_seen_ts_map(status)
    transcript_live = _sip_transcript_live(sip_flash)
    visible_slots = PBX_AGENT_VISIBLE_CALL if transcript_live else PBX_AGENT_VISIBLE
    visible, page_num, page_count = agent_visible_rows(
        roster,
        visible_slots,
        ts,
        active_exts,
    )
    rows: list[tuple[str, str]] = []
    rows.extend(
        [
            (agent_table_header(width), "CYAN"),
            (agent_table_rule(width), "SYS"),
        ]
    )
    for ext, name in visible:
        last_text, style = agent_last_label(
            ext, phone_states, active_exts, call_ts_map, ts, seen_ts_map
        )
        rows.append((agent_row(ext, name, last_text, width, now=ts), style))
    agent_hits = sorted(ext for ext, _name in roster if ext in active_exts)
    book_bit = f"BOOK {page_num}/{page_count}"
    if agent_hits:
        footer = f"ON CALL {', '.join(agent_hits)} | {book_bit}"
        footer_style = "PBX_CALL"
    elif active_exts:
        footer = f"CALL {', '.join(sorted(active_exts))} | {book_bit}"
        footer_style = "PBX_CALL"
    else:
        footer = (
            f"{book_bit}  VECTOR {'online' if status.get('vector_ok') else 'offline'}  "
            f"{len(roster)} AGENTS"
        )
        footer_style = "NOC"
    rows.append((detail_kv("PBX STATUS", footer, width, now=ts, scroll=False), footer_style))
    if transcript_live:
        rows.append((section_bar("CALL LOG", width), "PBX_CALL"))
        turns = list(getattr(sip_flash, "turns", None) or [])
        for segments, row_style in transcript_panel_segment_rows(
            turns,
            width,
            PBX_TRANSCRIPT_ROWS,
            now=ts,
        ):
            rows.append((segments, row_style))
    return rows[:7]


def bridge_panel(bridge: dict[str, Any], width: int, now: float | None = None) -> list[tuple[DetailRow, str]]:
    companions = bridge.get("companions") or []
    raw = bridge.get("bridge") or {}
    shared = raw.get("shared_memories", []) if isinstance(raw, dict) else []
    relationships = raw.get("relationships", {}) if isinstance(raw, dict) else {}
    ts = time.time() if now is None else now
    return [
        (detail_kv_header(width), "CYAN"),
        (detail_kv_rule(width), "SYS"),
        (detail_kv("BRIDGE", "online" if bridge.get("ok") else "offline", width, now=ts, scroll=False), "ST"),
        (detail_kv("DISPLAY", "SillyTavern + IRC co-canon", width, now=ts, scroll=False), "ST"),
        (detail_kv("POLICY", "GM confirms actions", width, now=ts, scroll=False), "GMQ"),
        (detail_kv_companion_segments("COMPANIONS", companions, width, now=ts), "ST"),
        (
            detail_kv(
                "STATE SIZE",
                f"mem {len(shared)} rel {len(relationships)}",
                width,
                now=ts,
                scroll=False,
            ),
            "ST",
        ),
    ]


def lounge_panel(events: list[LcdEvent], width: int, now: float | None = None) -> list[tuple[DetailRow, str]]:
    """IRC LOUNGE: the latest live chatter, colored per character, pinned to the bottom."""
    ts = time.time() if now is None else now
    slots = LCD_PANEL_MAX_ROWS
    chosen = [
        event
        for event in events
        if event.source in ("ZH", "ZP", "ST", "RPG", "PCORP", "IRC", "GMQ")
        and event.kind not in ("presence", "status")
    ][-slots:]
    rows: list[tuple[DetailRow, str]] = []
    for event in chosen:
        for seg_row in event_display_rows(event, width, now=ts, max_body_lines=2):
            rows.append((seg_row, event_nick_style(event)))
    rows = rows[-slots:]
    # Bottom-pin: blank scrollback at top, freshest chatter near the panel floor.
    pad_rows: list[tuple[DetailRow, str]] = [(pad("", width), "SYS")] * (slots - len(rows))
    return (pad_rows + rows)[:slots]


def render_text_frame(snapshot: dict[str, Any], now: float | None = None, tick: int = 0) -> list[str]:
    ts = time.time() if now is None else now
    mode = mode_name(ts)
    rows: list[str] = []
    rows.append(comet_line(header_title(snapshot, mode).strip(), ts))
    rows.append(dashboard_header(snapshot, mode, ts, tick, WIDTH))
    rows.append(defcon_status_line(WIDTH))
    rows.append(demoscene_greetz(snapshot, ts, WIDTH))
    rows.append(chunky_scroller(ticker_text(snapshot) + " // " + gpu_summary(snapshot), anim_now(ts), WIDTH, speed=SCROLLER_SPEED))
    rows.append(mode_section_bar(mode, WIDTH, ts))
    rows.append(section_bar(panel_section_label(mode), WIDTH))
    rows.extend(mode_art(mode, ts, WIDTH))
    rows.extend(line for line, _style in panel_lines(snapshot, mode, WIDTH))
    rows.append(calendar_line(ts, WIDTH))
    rows.append(dashboard_footer(snapshot, ts, tick, WIDTH))
    rows.append(marquee(banner_text(snapshot), WIDTH, MARQUEE_SPEED, ts))
    rows.append(tunnel_line(ts, WIDTH))
    rows.append(comet_line("EVENTS", ts + 2.0, WIDTH))
    event_rows: list[str] = []
    for event in snapshot.get("events") or []:
        event_rows.extend(row for row, _style in event_lines(event, WIDTH, now=ts))
    event_rows = event_rows[-(HEIGHT - len(rows) - 1) :]
    rows.extend(event_rows)
    while len(rows) < HEIGHT - 1:
        rows.append(" " * WIDTH)
    rows.append(lcd_status_line(snapshot, mode, ts, WIDTH))
    return rows[:HEIGHT]
