#!/usr/bin/env python3
"""Pure text rendering helpers for the ZealPalace LCD."""
from __future__ import annotations

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
from typing import Any

from zealot_lcd_feeds import LcdEvent, parse_iso_ts, short_text

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

MESH_COL_ASCII = "ASCII BAR "
MESH_COL_BLOCK = "BLOCK BAR "
DETAIL_KEY_W = 12
OPS_DETAIL_KEY_W = 10
TERRARIUM_DETAIL_KEY_W = 10
VITALS_BAR_W = 12
# ~10 chars/s: long detail lines finish well inside the 18s mode window.
DETAIL_SCROLL_SPEED = 10.0
IRC_SCROLL_SPEED = 9.0
PBX_AGENT_VISIBLE = 4
PBX_AGENT_VISIBLE_CALL = 2
PBX_TRANSCRIPT_ROWS = 6
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
    "ST",
    "PBX",
    "RPG",
    "ZP",
    "NOC",
    "MAG",
    "ZH",
    "YELLOW",
    "CYAN",
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
    value = str(text or "")[:width]
    if len(value) >= width:
        return value[:width]
    pad_total = width - len(value)
    left = pad_total // 2
    return " " * left + value + " " * (pad_total - left)


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


def calendar_line(now: float | None = None, width: int = WIDTH) -> str:
    ts = time.time() if now is None else now
    dt = datetime.fromtimestamp(ts)
    month = MONTH_NAMES[max(0, min(11, dt.month - 1))]
    iso_week = max(1, min(52, int(dt.isocalendar().week)))
    weeks_left = max(0, 52 - iso_week)
    week_start = (dt - timedelta(days=dt.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    next_week = week_start + timedelta(days=7)
    seconds_left = max(0, int((next_week - dt).total_seconds()))
    weekbeats_left = max(0, min(9999, int(round(seconds_left / (7 * 86400) * 10000))))
    text = f"{dt:%a} {dt.day:02d} {month} W{iso_week:02d}/52 Y-{weeks_left:02d}w WK{fmt_duration_short(seconds_left)} WB{weekbeats_left:04d}"
    return fit(text, width)


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
        bar(disk_pct if disk_pct is not None else 0, VITALS_BAR_W - 2),
        width,
    )


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
    prefix_len = 5 + 1 + 1 + 6 + 1 + 4 + 1  # host ping up ds + spaces
    bar_room = max(12, width - prefix_len)
    ascii_w = max(8, (bar_room * 10 + 8) // 18)
    uni_w = max(6, bar_room - ascii_w)
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
        salt=str(int(now)),
    )
    core = f"{host_ip} | {short_text(motive, 24)}"
    fx_tick = int(now * 1.2)
    left = SCROLLER_FX_EDGE[fx_tick % len(SCROLLER_FX_EDGE)]
    right = SCROLLER_FX_EDGE[(fx_tick + 1) % len(SCROLLER_FX_EDGE)]
    prefix = left + " "
    room = max(8, width - len(prefix) - len(right) - 1)
    scroll = marquee(core + "   ", room, speed=1.0, now=now)
    segments: list[tuple[str, str]] = [
        (prefix, "MOTD_FX"),
        (scroll, "MOTD"),
        (" " + right, "MOTD_FX"),
    ]
    line = fit("".join(text for text, _style in segments), width)
    used = 0
    out: list[tuple[str, str]] = []
    for text, style in segments:
        if used >= width:
            break
        chunk = text[: max(0, width - used)]
        if chunk:
            out.append((chunk, style))
            used += len(chunk)
    if not out:
        return [(line, "MOTD")]
    return out


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


def tunnel_line(now: float, width: int = WIDTH) -> str:
    frames = (
        "<~~~~ CRYSTAL MESH BUS ~~~~>",
        "<<~~~ LAN TERRARIUM LINK ~~~>>",
        "<~~~ PSEUDOCORP NOC FEED ~~~>",
    )
    return pad(frames[int(anim_now(now, 12.0) * TUNNEL_SPEED) % len(frames)], width)


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
    salt = gpu_summary(snapshot)
    greetz = stable_pick(PSEUDOCORP_GREETZ, now, period=GREETZ_PERIOD_SEC, salt=salt)
    body = greetz + " // " + salt
    if len(body) <= width:
        return fit(body, width)
    return chunky_scroller(body, anim_now(now, GREETZ_PERIOD_SEC), width, speed=SCROLLER_SPEED * 0.5)


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
        "  /\\  CRYSTAL MESH  /\\ ",
        " /  \\/  RGB TORCH  /  \\",
        "| [__] IRC+BRIDGE [__] |",
        "  \\__/  quests live \\__/",
    ),
    "rgb": (
        "+---- RGB BATTLE ----+",
        "|RED gate|GRN mesh   |",
        "|BLU read|QOTD armed |",
        "+--- CGA palette ---+",
    ),
    "agents": (
        "111-117-128-129 PBX",
        " \\__ LAN BUS /__/   ",
        "690-CRYSTAL MESH-698",
        " agents in-band talk ",
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


def mode_art(mode: str, now: float, width: int = WIDTH) -> list[str]:
    if mode == "rgb":
        rows = list(RGB_BATTLE_FRAMES[int(anim_now(now, RGB_FRAME_SEC) // RGB_FRAME_SEC) % len(RGB_BATTLE_FRAMES)])
    else:
        rows = list(MODE_ART.get(mode, MODE_ART["lounge"]))
    glint = "<>" if int(anim_now(now, 8.0) // 8) % 2 else "[]"
    out: list[str] = []
    for idx, row in enumerate(rows):
        line = center(row, width)
        if idx == 0 and len(line) >= 2:
            chars = list(line)
            chars[0] = glint[0]
            chars[-1] = glint[1]
            line = "".join(chars)
        out.append(fit(line, width))
    return out


def transition_text(text: Any, now: float, row: int, width: int = WIDTH, window: float = 2.25) -> str:
    return fit(text, width)


def bar(value: Any, width: int = 10) -> str:
    try:
        pct = max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        pct = 0.0
    filled = int(round((pct / 100.0) * width))
    return chr(0x2595) + (chr(0x2588) * filled) + (chr(0x2591) * (width - filled)) + chr(0x258F)


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


def wrap_line(text: str, width: int = WIDTH, max_lines: int = 3) -> list[str]:
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
        chunks[-1] = fit(chunks[-1], width).rstrip()[: max(0, width - 1)] + "~"
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


def event_nick_style(event: LcdEvent) -> str:
    return {
        "ZP": "ZP",
        "ZH": "ZH",
        "RPG": "RPG",
        "ST": "ST",
        "PCORP": "PBX",
        "GMQ": "GMQ",
    }.get(event.source, "IRC_NICK")


def event_segments(
    event: LcdEvent,
    width: int = WIDTH,
    now: float | None = None,
) -> list[tuple[str, str]]:
    canon = event_canon_suffix(event)
    chan = event_channel_short(event.channel)
    nick = event.nick or ""
    body = re.sub(r"\s+", " ", str(event.text or "")).strip()

    segments: list[tuple[str, str]] = []
    if canon:
        segments.append((canon, "SYS"))
    if chan:
        segments.append((" " + chan if segments else chan, "IRC_CHAN"))

    if event.kind == "action":
        segments.append((" ", "SYS"))
        if nick:
            segments.append(("*" + nick[:8] + " ", event_nick_style(event)))
        msg_style = "IRC_ACT"
    elif event.kind in ("presence", "status"):
        msg_style = "IRC_MSG"
        if not body:
            body = f"{nick} {event.kind}".strip()
    else:
        if nick:
            segments.append((" " + nick[:10] + ": ", event_nick_style(event)))
        msg_style = "IRC_MSG"

    prefix = "".join(text for text, _style in segments)
    room = max(1, width - len(prefix))
    if now is not None and len(body) > room:
        body_disp = marquee(body, room, speed=IRC_SCROLL_SPEED, now=now)
    else:
        body_disp = fit(body, room)
    segments.append((body_disp, msg_style))

    total = sum(len(text) for text, _style in segments)
    if total > width:
        trim = total - width
        last_text, last_style = segments[-1]
        segments[-1] = (last_text[: max(0, len(last_text) - trim)], last_style)
    return segments


def event_head(event: LcdEvent) -> str:
    nick = event.nick or event.channel.strip("#") or event.kind
    canon = event_canon_suffix(event)
    chan = event_channel_short(event.channel)
    prefix = canon
    if chan:
        prefix += (" " if prefix else "") + chan
    if event.kind == "action":
        return prefix + " *" + nick[:8] + " "
    if event.kind in ("presence", "status"):
        return prefix + " "
    return prefix + (" " if prefix else "") + (nick[:10] + ": " if nick else "")


def event_lines(
    event: LcdEvent,
    width: int = WIDTH,
    now: float | None = None,
) -> list[tuple[str, str]]:
    if now is not None:
        return [(fit("".join(text for text, _style in event_segments(event, width, now)), width), event.source)]

    head = event_head(event)
    body = re.sub(r"\s+", " ", str(event.text or "")).strip()
    room = max(6, width - len(head))
    body = short_text(body, 400)
    chunks = wrap_line(body, room, max_lines=3)
    out: list[tuple[str, str]] = []
    out.append((fit(head + chunks[0], width), event.source))
    for chunk in chunks[1:]:
        out.append((fit(" " * len(head) + chunk, width), event.source))
    return out


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


def ticker_text(snapshot: dict[str, Any]) -> str:
    status = snapshot.get("status") or {}
    bridge = snapshot.get("bridge") or {}
    bits = [
        "ZealPalace hybrid ticker",
        f"mode co-canon",
        f"zone {bridge.get('hot_zone') or '?'}",
        f"npc {bridge.get('npc_count', 0)}",
        f"players {bridge.get('players_total', 0)}",
        f"gm {len(bridge.get('gm_pending') or [])}",
        "VEC " + ("OK" if status.get("vector_ok") else "NO"),
        "PBX " + ("OK" if status.get("pbx_api_ok") else "NO"),
    ]
    navi = status.get("navi") or {}
    navi_line = navi.get("ticker") if isinstance(navi, dict) else ""
    if navi_line:
        bits.append("NAVI " + short_text(navi_line, 120))
    bits.append(joshua_defcon_ticker())
    return "  >  ".join(bits)


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
) -> list[tuple[DetailRow, str]]:
    status = snapshot.get("status") or {}
    bridge = snapshot.get("bridge") or {}
    events: list[LcdEvent] = snapshot.get("events") or []
    ts = time.time() if now is None else now
    if mode == "terrarium":
        return terrarium_panel(status, snapshot, width, now=ts)
    if mode == "uptime":
        return uptime_panel(status, snapshot, width, now=ts)
    if mode == "ops":
        return ops_panel(status, snapshot, width, now=ts)
    if mode == "rpg":
        return rpg_panel(bridge, width, now=ts)
    if mode == "rgb":
        return rgb_battle_panel(snapshot, width, now=ts)
    if mode == "agents":
        return agents_panel(bridge, status, width, now=ts, call_exts=call_exts, sip_flash=sip_flash)
    if mode == "bridge":
        return bridge_panel(bridge, width, now=ts)
    return bridge_panel(bridge, width, now=ts)


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
        (detail_table_header(width), "CYAN"),
        (detail_table_rule(width), "SYS"),
    ]
    longest_label = "?"
    longest_host: dict[str, Any] = {}
    longest_uptime = -1
    for label, host, style, disk_path in host_specs:
        if not host:
            rows.append((vitals_row(label, None, None, None, None, width), "SYS"))
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
        disk_pct = first_disk_pct(host, disk_path) or first_disk_pct(host)
        rows.append(
            (
                vitals_row(
                    label,
                    uptime,
                    host.get("cpu_pct"),
                    host.get("mem_pct"),
                    disk_pct,
                    width,
                ),
                style,
            )
        )

    ts = time.time() if now is None else now
    rows.append(
        (
            detail_kv(
                "LONGEST UP",
                f"{host_long_name(longest_label, longest_host)} "
                f"{fmt_uptime(longest_uptime)} {bar(uptime_pct(longest_uptime), 8)}",
                width,
                now=ts,
                scroll=False,
            ),
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
    noc = as_dict(status.get("noc"))
    phones = as_dict(status.get("pbx_phones"))
    phone_rows = []
    for phone in phones.get("phones", []) if isinstance(phones, dict) else []:
        if isinstance(phone, dict):
            phone_rows.append(f"{phone.get('ext')} {phone.get('name') or phone.get('state')}")
    celes = as_dict(snapshot.get("celes"))
    heartbeat = as_dict(status.get("lcd_heartbeat"))
    telemetry = as_dict(status.get("telemetry"))
    local = as_dict(telemetry.get("local"))
    remote = as_dict(telemetry.get("remote"))
    remote_hosts = as_dict(remote.get("hosts"))
    ts = time.time() if now is None else now
    ops_key_w = OPS_DETAIL_KEY_W
    detail_room = kv_value_room(width, ops_key_w)
    rows: list[tuple[DetailRow, str]] = [
        (detail_kv_header(width, ops_key_w), "CYAN"),
        (detail_kv_rule(width, ops_key_w), "SYS"),
        (
            detail_kv(
                "MESH HOSTS",
                noc_mesh_dns_line(noc, status),
                width,
                now=ts,
                key_w=ops_key_w,
            ),
            "NOC",
        ),
        (
            detail_kv(
                "SERVICES",
                " ".join(
                    [
                        f"VEC {'OK' if status.get('vector_ok') else 'DN'}",
                        f"HERMES {'OK' if status.get('hermes_ok') else 'DN'}",
                        f"PBX {'OK' if status.get('pbx_api_ok') else 'DN'}",
                        f"API9104 {'OK' if status.get('ce_api_ok') else 'DN'}",
                        f"CELES {'FRESH' if celes.get('fresh') else 'STALE'}",
                        f"LCD HB {heartbeat.get('age_sec', '?')}s",
                        f"PHONES {' | '.join(phone_rows[:3]) if phone_rows else 'none'}",
                    ]
                ),
                width,
                now=ts,
                key_w=ops_key_w,
            ),
            "NOC",
        ),
        (
            detail_kv(
                "J124 WOPR",
                joshua_defcon_ticker(),
                width,
                now=ts,
                key_w=ops_key_w,
            ),
            "PBX",
        ),
    ]
    for label, host, disk_path in (
        ("ZEA", local, "/"),
        ("ZTW", as_dict(remote_hosts.get("zealtower")), "/mnt/cache"),
        ("VEC", as_dict(remote_hosts.get("vector")), "C:/"),
    ):
        if not host:
            rows.append(
                (
                    detail_kv(
                        f"DISK {label}",
                        "telemetry waiting",
                        width,
                        key_w=ops_key_w,
                        fill=True,
                    ),
                    "SYS",
                )
            )
            continue
        pct = first_disk_pct(host, disk_path) or first_disk_pct(host)
        rows.append(
            (
                ops_disk_detail_segments(label, pct, width, key_w=ops_key_w),
                host_label_style(label),
            )
        )
    return rows[:7]


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
    return [
        (detail_kv_header(width), "CYAN"),
        (detail_kv_rule(width), "SYS"),
        (detail_kv("ERA", short_text(bridge.get("era"), 80), width, now=ts), "RPG"),
        (detail_kv("HOT ZONE", short_text(bridge.get("hot_zone"), 80), width, now=ts), "RPG"),
        (
            detail_kv(
                "POPULATION",
                f"NPC {bridge.get('npc_count', 0)}  PLAYERS {bridge.get('players_total', 0)}  "
                f"GM QUEUE {len(bridge.get('gm_pending') or [])}",
                width,
                now=ts,
            ),
            "RPG",
        ),
        (detail_kv("BATTLE", battle_line, width, now=ts), "RPG"),
        (detail_kv("ACTIVE NPC", " | ".join(npc_bits) or "waiting", width, now=ts), "RPG"),
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
    rows: list[tuple[str, str]] = [
        (agent_table_header(width), "CYAN"),
        (agent_table_rule(width), "SYS"),
    ]
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
        return rows
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
        (detail_kv("BRIDGE", "online" if bridge.get("ok") else "offline", width, now=ts), "ST"),
        (detail_kv("DISPLAY", "co-canon SillyTavern + IRC", width, now=ts), "ST"),
        (detail_kv("POLICY", "private memory visible; GM confirms actions", width, now=ts), "GMQ"),
        (detail_kv_companion_segments("COMPANIONS", companions, width, now=ts), "ST"),
        (
            detail_kv(
                "STATE SIZE",
                f"memories {len(shared)}  relations {len(relationships)}",
                width,
                now=ts,
            ),
            "ST",
        ),
    ]


def lounge_panel(events: list[LcdEvent], width: int, now: float | None = None) -> list[tuple[str, str]]:
    ts = time.time() if now is None else now
    chosen = [
        event
        for event in events
        if event.source in ("ZH", "ZP", "ST", "RPG", "PCORP", "IRC")
        and event.kind not in ("presence", "status")
    ][-3:]
    lines: list[tuple[str, str]] = [
        (detail_kv_header(width), "CYAN"),
        (detail_kv_rule(width), "SYS"),
    ]
    for event in chosen:
        lines.extend(event_lines(event, width, now=ts)[:1])
    while len(lines) < 7:
        lines.append((pad("", width), "SYS"))
    return lines[:7]


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
