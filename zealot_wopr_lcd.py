#!/usr/bin/env python3
"""WarGames WOPR full-screen LCD mode during Joshua ext 124 calls."""
from __future__ import annotations

import curses
import json
import math
import re
import sys
import textwrap
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_LCD_DIR = Path(__file__).resolve().parent
if str(_LCD_DIR) not in sys.path:
    sys.path.insert(0, str(_LCD_DIR))
from joshua_wopr_menu import (  # noqa: E402
    map_mode_for_game,
    sim_status_line,
    tft_keypad_table,
)

JOSHUA_WOPR = Path.home() / ".cache" / "zealot" / "joshua_wopr.json"
MAX_AGE_SEC = 20 * 60
MAP_H = 8
FACTION_PERIOD_SEC = 14.0

# x in 0..39, y in 0..7
CITIES: dict[str, tuple[int, int]] = {
    "ALASKA": (4, 1),
    "CONUS": (9, 3),
    "UK": (15, 2),
    "EUROPE": (19, 3),
    "MOSCOW": (31, 2),
    "SIBERIA": (33, 3),
    "PRC": (30, 4),
    "INDIA": (27, 5),
    "AUSSIE": (24, 7),
}

REGION_TARGETS: dict[str, tuple[str, str]] = {
    "moscow": ("CONUS", "MOSCOW"),
    "soviet": ("CONUS", "MOSCOW"),
    "russia": ("CONUS", "MOSCOW"),
    "europe": ("CONUS", "EUROPE"),
    "uk": ("MOSCOW", "UK"),
    "pacific": ("PRC", "CONUS"),
    "china": ("CONUS", "PRC"),
    "india": ("MOSCOW", "INDIA"),
    "siberia": ("CONUS", "SIBERIA"),
    "alaska": ("MOSCOW", "ALASKA"),
    "australia": ("PRC", "AUSSIE"),
    "aussie": ("PRC", "AUSSIE"),
}

# Faction terrain keys per theme (one char per cell)
# A=allies blue/cyan  S=soviet red  U=usa  R=russia  Z=australia  ~=water  .=fog
RED_ALERT_MAP = (
    "~~~~~AAAAA~~~~~~~SSSSSS~~~~~AAAA~~~~~~",
    "~~~~AAAAAAA~~~~~~SSSSSSS~~~~AAAAA~~~~~",
    "~~~AAAAUKAAA~~~~SSSMOSCOW~~~AAAAAA~~~~",
    "~~AAAAEUROPEAA~~~SSSIBERIA~~AAAAAAA~~~",
    "~~~AAAAA~~~~~~~~SSSPRC~~~~~AAAA~~~~~~",
    "~~~~AA~~~~~~~~~~SSINDIA~~~~AA~~~~~~~~",
    "~~~~~A~~~~~~~~~~~SS~~~~~~~~A~~~~~~~~~",
    "~~~~~~AUSSIE~~~~~SS~~~~~~~~AUSSIE~~~~",
)

REAL_WORLD_MAP = (
    "~~~~~UUUUU~~~~~~~RRRRRR~~~~~UUUU~~~~~~",
    "~~~~UUUUUUU~~~~~~RRRRRRR~~~~UUUUU~~~~~",
    "~~~UUUKUUUU~~~~~~RRMOSCOW~~~UUUUUU~~~~",
    "~~UUEUROPEUU~~~~~RRSIBERIA~~UUUUUUU~~~",
    "~~~UUUU~~~~~~~~~~RRPRC~~~~~UUUU~~~~~~",
    "~~~~UU~~~~~~~~~~~RRINDIA~~~~UU~~~~~~~~",
    "~~~~~U~~~~~~~~~~~~RR~~~~~~~~Z~~~~~~~~~",
    "~~~~~~AUSSIE~~~~~RR~~~~~~~~AUSSIE~~~~",
)

FACTION_LABELS = (
    ("SOVIETS", "ALLIES", "RED ALERT"),
    ("RUSSIA", "USA/ALLIES", "REAL WORLD"),
)

TERRAIN_PAIR = {
    "A": "ally",
    "S": "enemy",
    "U": "ally",
    "R": "enemy",
    "Z": "neutral",
    "~": "water",
    ".": "dim",
}


@dataclass
class Missile:
    src: str
    dst: str
    born: float
    duration: float = 2.2
    trail: str = "*"
    faction: str = "enemy"

    def progress(self, now: float) -> float:
        return max(0.0, min(1.0, (now - self.born) / self.duration))


@dataclass
class WoprPalette:
    title: int
    green: int
    yellow: int
    red: int
    dim: int
    input: int
    cyan: int = 0
    magenta: int = 0


@dataclass
class WoprEngine:
    missiles: list[Missile] = field(default_factory=list)
    blasts: list[tuple[str, float]] = field(default_factory=list)
    last_pct: int = -1
    ticker_offset: int = 0
    ambient_spawn: float = 0.0
    log_scroll: int = 0
    maze_x: int = 4
    maze_y: int = 3
    chess_pulse: int = 0
    hack_scan_y: int = 0
    board_mark: int = 0
    fighter_spawn: float = 0.0
    news_feed: list[str] = field(default_factory=list)
    last_news_sig: str = ""

    def sync(self, session: dict, now: float) -> None:
        pct = int(session.get("thermonuclear_pct") or 0)
        game = str(session.get("active_game") or "")
        region = str(session.get("last_region") or "")
        mode = map_mode_for_game(game) if game else "menu"
        if mode == "thermo":
            if pct > self.last_pct:
                src, dst = _pick_route(region)
                self.missiles.append(Missile(src=src, dst=dst, born=now, trail=">", faction="enemy"))
                if pct >= 15:
                    self.missiles.append(
                        Missile(
                            src=dst,
                            dst=src,
                            born=now + 0.45,
                            trail="<",
                            faction="ally",
                            duration=2.0,
                        )
                    )
            elif pct > 0 and now - self.ambient_spawn > 1.1:
                self.ambient_spawn = now
                src, dst = _pick_route(region)
                self.missiles.append(Missile(src=src, dst=dst, born=now, trail="*", faction="enemy"))
        if mode == "hack" and session.get("last_outcome"):
            self.ticker_offset += 1
            self.hack_scan_y = (self.hack_scan_y + 1) % MAP_H
        if mode == "maze":
            if int(now * 2) % 2 == 0:
                self.maze_x = (self.maze_x + 1) % 38
            if int(now * 3) % 4 == 0:
                self.maze_y = (self.maze_y + 1) % MAP_H
        if mode == "chess":
            self.chess_pulse = int(now * 2) % 8
        if mode == "board":
            self.board_mark = int(now * 1.5) % len(CITIES)
        if mode == "fighter":
            if now - self.fighter_spawn > 1.4:
                self.fighter_spawn = now
                keys = list(CITIES.keys())
                if len(keys) >= 2:
                    src = keys[int(now) % len(keys)]
                    dst = keys[(int(now) + 3) % len(keys)]
                    self.missiles.append(
                        Missile(src=src, dst=dst, born=now, trail=">", faction="enemy", duration=1.2)
                    )
        self.last_pct = pct
        self.missiles = [m for m in self.missiles if now - m.born < m.duration + 0.5]
        self.blasts = [(name, ts) for name, ts in self.blasts if now - ts < 3.0]
        for m in self.missiles:
            if m.progress(now) >= 0.97:
                self.blasts.append((m.dst, now))
        self.blasts = list(dict.fromkeys(self.blasts))
        self.log_scroll = int(now * 0.35)
        _refresh_war_news(self, session, now)


_ENGINE = WoprEngine()

WAR_WIRE_SOURCES = ("AP", "REUTERS", "BBC", "CNN", "UPI", "WOPR")


def _parse_ts(value) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _pick_route(region: str) -> tuple[str, str]:
    key = (region or "").lower()
    for token, pair in REGION_TARGETS.items():
        if token in key:
            return pair
    return ("CONUS", "MOSCOW")


def read_joshua_session(path: Path | None = None) -> tuple[dict, float]:
    target = JOSHUA_WOPR if path is None else path
    try:
        st = target.stat()
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}, 0.0
    if not isinstance(data, dict):
        return {}, 0.0
    event_ts = _parse_ts(data.get("ts") or data.get("updated"))
    return data, max(st.st_mtime, event_ts)


def _wopr_live_session(data: dict) -> bool:
    """True only during an in-progress simulation on a live ext 124 call."""
    if data.get("wopr_live") is False:
        return False
    phase = str(data.get("phase") or "").lower()
    if phase in ("epilogue", "standby", "boot", "main_menu"):
        return False
    turns = int(data.get("turns_this_call") or 0)
    if turns <= 0:
        return False
    game = str(data.get("active_game") or "").strip()
    if not game:
        return False
    return phase in ("playing", "hacking")


def joshua_wopr_active(path: Path | None = None) -> bool:
    data, newest = read_joshua_session(path)
    if not data:
        return False
    if newest and time.time() - newest > MAX_AGE_SEC:
        return False
    if data.get("wopr_live") is False or data.get("active") is False:
        return False
    if data.get("wopr_live") is True:
        return _wopr_live_session(data)
    return bool(data.get("active")) and _wopr_live_session(data)


def poll_joshua_wopr(path: Path | None = None) -> dict | None:
    if not joshua_wopr_active(path):
        return None
    data, _ = read_joshua_session(path)
    return data


def joshua_defcon_ticker(path: Path | None = None) -> str:
    """One-line DEFCON status for the normal CGA dashboard (not full-screen WOPR)."""
    data, _ = read_joshua_session(path)
    if not data:
        return "J124 DEFCON 5 STANDBY"
    defcon = max(1, min(5, int(data.get("defcon") or 5)))
    if _wopr_live_session(data):
        game = str(data.get("active_game") or "game").replace("_", " ").upper()[:14]
        pct = int(data.get("thermonuclear_pct") or 0)
        if game == "THERMONUCLEAR" and pct > 0:
            return f"J124 WARGAMES DEFCON {defcon} THERMO {pct}%"
        return f"J124 WARGAMES DEFCON {defcon} {game}"
    turns = int(data.get("turns_this_call") or 0)
    if turns > 0:
        return f"J124 DEFCON {defcon} JOSHUA ONLINE"
    return f"J124 DEFCON {defcon} STANDBY"


def _fmt_cas(n: int) -> str:
    n = max(0, int(n or 0))
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1000:
        return f"{n // 1000}K"
    return str(n)


def _pct_bar(value: int, scale: int, width: int, fill: str = "█", empty: str = "░") -> str:
    width = max(1, int(width or 1))
    if scale <= 0:
        return empty * width
    ratio = max(0.0, min(1.0, float(value) / float(scale)))
    filled = int(round(ratio * width))
    return (fill * filled + empty * max(0, width - filled))[:width]


def _clip_words(text: str, width: int) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(clean) <= width:
        return clean
    return clean[: max(0, width - 3)].rstrip() + "..."


def _compose_war_headline(session: dict, engine: WoprEngine, now: float) -> str:
    game = str(session.get("active_game") or "")
    region = str(session.get("last_region") or "theater").strip() or "theater"
    pct = int(session.get("thermonuclear_pct") or 0)
    defcon = int(session.get("defcon") or 5)
    us_c = int(session.get("casualties_us") or 0)
    su_c = int(session.get("casualties_ussr") or 0)
    outcome = _clip_words(str(session.get("last_outcome") or ""), 42)
    beat = int(session.get("story_beat") or 0)
    msl = len(engine.missiles)
    blst = len({name for name, ts in engine.blasts if now - ts <= 2.5})
    src = WAR_WIRE_SOURCES[beat % len(WAR_WIRE_SOURCES)]

    if game == "thermonuclear" and pct > 0:
        templates = (
            f"{src}: BREAKING strike on {region} — DEFCON {defcon}",
            f"{src}: US {_fmt_cas(us_c)} / Soviet {_fmt_cas(su_c)} reported KIA",
            f"{src}: escalation {pct}% — {outcome}",
            f"{src}: {msl} inbound tracks, {blst} detonations over {region}",
            f"{src}: WOPR shows no winning branch at {pct}% exchange",
            f"{src}: NATO flash traffic — {region} grid under ICBM salvo",
        )
        return templates[beat % len(templates)]
    if game == "hacking":
        depth = int(session.get("hacking_depth") or 0)
        breach = int(session.get("breach_count") or 0)
        templates = (
            f"{src}: NORAD subnet probe depth {depth}",
            f"{src}: packet trace routed to Cheyenne Mountain",
            f"{src}: breach count {breach} — Falken file fragment leaked",
            f"{src}: Joshua backdoor acknowledged on milnet",
        )
        return templates[beat % len(templates)]
    if game:
        label = game.replace("_", " ").upper()
        return f"{src}: WOPR simulation active — {label}"
    return f"{src}: DIAL {124} — SHALL WE PLAY A GAME?"


def _refresh_war_news(engine: WoprEngine, session: dict, now: float) -> None:
    sig = "|".join(
        str(session.get(k) or "")
        for k in (
            "active_game",
            "story_beat",
            "last_region",
            "thermonuclear_pct",
            "last_outcome",
            "casualties_us",
            "casualties_ussr",
            "hacking_depth",
        )
    ) + f"|{len(engine.missiles)}|{len(engine.blasts)}"
    if sig != engine.last_news_sig:
        engine.last_news_sig = sig
        headline = _compose_war_headline(session, engine, now)
        if not engine.news_feed or engine.news_feed[-1] != headline:
            engine.news_feed.append(headline)
    engine.news_feed = engine.news_feed[-12:]


def _warwire_scroll(session: dict, engine: WoprEngine, width: int, now: float) -> str:
    if not engine.news_feed:
        _refresh_war_news(engine, session, now)
    body = " *** ".join(engine.news_feed) or "WARWIRE standby"
    prefix = "WARWIRE "
    return _marquee(f"{prefix}{body}", width, now, speed=9.0)


def _telemetry_ascii_lines(
    session: dict,
    engine: WoprEngine,
    width: int,
    now: float,
) -> list[str]:
    us_c = int(session.get("casualties_us") or 0)
    su_c = int(session.get("casualties_ussr") or 0)
    pct = int(session.get("thermonuclear_pct") or 0)
    defcon = int(session.get("defcon") or 5)
    msl = len(engine.missiles)
    blst = len({name for name, ts in engine.blasts if now - ts <= 2.5})
    bar_w = max(4, min(8, (width - 22) // 2))

    us_bar = _pct_bar(us_c, 900_000, bar_w)
    su_bar = _pct_bar(su_c, 900_000, bar_w)
    esc_bar = _pct_bar(pct, 100, max(4, width - 28), fill="▓", empty="░")

    line1 = (
        f"US{us_bar}{_fmt_cas(us_c):>4} "
        f"SU{su_bar}{_fmt_cas(su_c):>4} "
        f"TOT{_fmt_cas(us_c + su_c):>4}"
    )
    pulse = ("|", "/", "-", "\\")[int(now * 4) % 4]
    msl_glyphs = ("▲" * min(msl, 3) + "·" * max(0, 3 - min(msl, 3)))[:3]
    blst_glyphs = ("◈" * min(blst, 3) + "·" * max(0, 3 - min(blst, 3)))[:3]
    line2 = f"{pulse}M{msl_glyphs}{msl:02d} B{blst_glyphs}{blst:02d} E{esc_bar}{pct:2d}%D{defcon}"
    return [_pad_line(line1, width), _pad_line(line2, width)]


def _pad_line(text: str, width: int) -> str:
    value = (text or "")[:width]
    return value + (" " * max(0, width - len(value)))


def _hline(width: int, ch: str = "=") -> str:
    return (ch * width)[:width]


def _center_line(text: str, width: int) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(clean) >= width:
        return clean[:width]
    pad = width - len(clean)
    left = pad // 2
    return (" " * left) + clean + (" " * (pad - left))


def _faction_theme(now: float) -> int:
    return int(now // FACTION_PERIOD_SEC) % 2


def _defcon_bar(defcon: int, width: int) -> str:
    lvl = max(1, min(5, int(defcon or 5)))
    filled = max(0, 6 - lvl)
    return ("#" * filled + "-" * max(0, width - filled))[:width]


def _marquee(text: str, width: int, now: float, speed: float = 2.0) -> str:
    body = re.sub(r"\s+", " ", str(text or "")).strip()
    if not body:
        return " " * width
    body = body + "   "
    if len(body) <= width:
        return _pad_line(body, width)
    offset = int(now * speed) % len(body)
    loop = body + body
    return _pad_line(loop[offset : offset + width], width)


def _wrap_lines(text: str, width: int, max_lines: int) -> list[str]:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean:
        return []
    chunks = textwrap.wrap(clean, width=width, break_long_words=True, break_on_hyphens=False)
    if len(chunks) > max_lines:
        start = len(chunks) - max_lines
        chunks = chunks[start:]
        if chunks:
            chunks[0] = "..." + chunks[0][3:]
    return [_pad_line(row, width) for row in chunks[:max_lines]]


def _pair_for_terrain(style: str, palette: WoprPalette, flash: bool) -> int:
    if style == "enemy":
        return palette.red
    if style == "ally":
        return palette.cyan or palette.green
    if style == "neutral":
        return palette.yellow
    if style == "water":
        return palette.magenta or palette.dim
    if style == "missile":
        return palette.red
    if style == "blast":
        return palette.red
    if style == "city":
        return palette.yellow
    return palette.dim


def _missile_trail_char(progress: float, head: bool) -> str:
    if head:
        return ">" if progress < 0.5 else "*"
    idx = int(progress * 6) % 4
    return ("'", ".", "`", "o")[idx]


def _missile_points(
    sx: int,
    sy: int,
    dx: int,
    dy: int,
    steps: int = 24,
) -> list[tuple[int, int]]:
    pts: list[tuple[int, int]] = []
    for i in range(steps + 1):
        t = i / steps
        # slight arc bulge for theater curve
        arc = math.sin(t * math.pi) * 1.2
        x = int(sx + (dx - sx) * t)
        y = int(sy + (dy - sy) * t - arc)
        pts.append((x, y))
    return pts


def _enabled_from_session(session: dict) -> list[str] | None:
    cfg = session.get("config") if isinstance(session.get("config"), dict) else {}
    raw = cfg.get("enabled_games")
    if isinstance(raw, list):
        return [str(g) for g in raw]
    return None


def _build_map_canvas(
    width: int,
    theme_idx: int,
    missiles: list[Missile],
    blasts: set[str],
    now: float,
    flash: bool,
    *,
    game: str = "",
    engine: WoprEngine | None = None,
) -> list[list[tuple[str, str]]]:
    template = REAL_WORLD_MAP if theme_idx else RED_ALERT_MAP
    rows: list[list[tuple[str, str]]] = []
    for y in range(MAP_H):
        base = (template[y] if y < len(template) else "." * width)[:width]
        base = base + ("." * max(0, width - len(base)))
        row: list[tuple[str, str]] = []
        for x, ch in enumerate(base[:width]):
            style = TERRAIN_PAIR.get(ch, "dim")
            if flash and style == "enemy" and int(now * 3 + x) % 3 == 0:
                style = "blast"
            row.append((ch if ch != "~" else "~", style))
        rows.append(row)

    for name, (cx, cy) in CITIES.items():
        if 0 <= cy < MAP_H and 0 <= cx < width:
            label = name[:5]
            start = max(0, min(cx - len(label) // 2, width - len(label)))
            for i, ch in enumerate(label):
                px = start + i
                if 0 <= px < width:
                    rows[cy][px] = (ch, "city")

    for m in missiles:
        sx, sy = CITIES.get(m.src, (4, 3))
        dx, dy = CITIES.get(m.dst, (30, 2))
        pts = _missile_points(sx, sy, dx, dy)
        prog = m.progress(now)
        head_idx = int(prog * (len(pts) - 1))
        for idx, (x, y) in enumerate(pts):
            if not (0 <= y < MAP_H and 0 <= x < width):
                continue
            if idx == head_idx:
                rows[y][x] = (_missile_trail_char(prog, True), "missile")
            elif idx < head_idx and head_idx - idx <= 3:
                rows[y][x] = (_missile_trail_char(prog, False), "missile")

    blast_pulse = ("@", "#", "%", "X")[int(now * 4) % 4]
    for name in blasts:
        cx, cy = CITIES.get(name, (0, 0))
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                x, y = cx + dx, cy + dy
                if 0 <= y < MAP_H and 0 <= x < width:
                    rows[y][x] = (blast_pulse, "blast")

    eng = engine or _ENGINE
    mode = map_mode_for_game(game) if game else "menu"
    if mode == "hack":
        scan_y = eng.hack_scan_y % MAP_H
        scan_ch = ("|", "!", "|", "!")[int(now * 6) % 4]
        for x in range(width):
            if 0 <= scan_y < MAP_H:
                rows[scan_y][x] = (scan_ch, "missile")
    if mode == "maze":
        mx = max(0, min(eng.maze_x, width - 1))
        my = max(0, min(eng.maze_y, MAP_H - 1))
        rows[my][mx] = ("@", "city")
    if mode == "chess":
        city_names = list(CITIES.keys())
        for idx, name in enumerate(city_names):
            cx, cy = CITIES[name]
            if 0 <= cy < MAP_H and 0 <= cx < width:
                ch = rows[cy][cx][0]
                if (idx + eng.chess_pulse) % 3 == 0:
                    rows[cy][cx] = (ch, "ally")
    if mode == "board":
        city_names = list(CITIES.keys())
        if city_names:
            mark = city_names[eng.board_mark % len(city_names)]
            cx, cy = CITIES[mark]
            if 0 <= cy < MAP_H and 0 <= cx < width:
                rows[cy][cx] = ("O", "city")

    return rows


def _latest_speak_lines(session: dict, width: int, max_rows: int) -> list[str]:
    speak = str(session.get("last_speak") or "").strip()
    if not speak:
        log = session.get("log") or []
        if log and isinstance(log[-1], dict):
            speak = str(log[-1].get("assistant") or "").strip()
    if not speak:
        return [_pad_line("AWAITING JOSHUA", width)]
    lines = _wrap_lines(speak, max(1, width - 2), max_rows)
    return [_pad_line(f">{line}", width) for line in lines[:max_rows]]


def _history_lines(session: dict, width: int, max_rows: int) -> list[str]:
    rows: list[str] = []
    for entry in reversed(session.get("log") or []):
        if not isinstance(entry, dict):
            continue
        user = str(entry.get("user") or "").strip()
        if user and not user.startswith("DTMF:"):
            rows.append(f"YOU: {user[: width - 6]}")
        assistant = str(entry.get("assistant") or "").strip()
        if assistant:
            rows.append(assistant)
        if len(rows) >= max_rows * 2:
            break
    if not rows:
        region = str(session.get("last_region") or "").strip()
        if region:
            return [_pad_line(f"THEATER: {region}", width)]
        return [_pad_line("AWAITING WOPR EVENTS", width)]
    wrapped: list[str] = []
    for line in rows:
        wrapped.extend(_wrap_lines(line, max(1, width - 2), 2))
        if len(wrapped) >= max_rows:
            break
    return [_pad_line(f" {row}", width) for row in wrapped[:max_rows]]


def _put_line(stdscr, row: int, text: str, width: int, pair: int, flags: int = 0) -> None:
    try:
        stdscr.addnstr(row, 0, _pad_line(text, width), width, curses.color_pair(pair) | flags)
    except curses.error:
        pass


def _put_segments(
    stdscr,
    row: int,
    segments: list[tuple[str, int, int]],
    width: int,
) -> None:
    col = 0
    for text, pair, flags in segments:
        if col >= width:
            break
        chunk = text[: max(0, width - col)]
        if not chunk:
            continue
        try:
            stdscr.addnstr(row, col, chunk, len(chunk), curses.color_pair(pair) | flags)
        except curses.error:
            pass
        col += len(chunk)


def _map_row_segments(
    canvas_row: list[tuple[str, str]],
    palette: WoprPalette,
    flash: bool,
    now: float,
) -> list[tuple[str, int, int]]:
    segments: list[tuple[str, int, int]] = []
    for ch, style in canvas_row:
        pair = _pair_for_terrain(style, palette, flash)
        flags = curses.A_BOLD if style in ("missile", "blast", "city") else 0
        if style == "missile" and int(now * 8) % 2:
            flags |= curses.A_REVERSE
        segments.append((ch, pair, flags))
    return segments


def draw_wopr_overlay(
    stdscr,
    session: dict,
    now: float,
    input_row: int,
    width: int,
    *,
    pair_title: int,
    pair_green: int,
    pair_yellow: int,
    pair_red: int,
    pair_dim: int,
    pair_input: int,
    draw_fn,
    pair_cyan: int = 0,
    pair_magenta: int = 0,
) -> None:
    """Full-screen WarGames console (40x34) — CGA palette, full-width panels."""
    _ENGINE.sync(session, now)
    footer_row = max(0, input_row - 1)
    usable = max(10, footer_row)
    palette = WoprPalette(
        title=pair_title,
        green=pair_green,
        yellow=pair_yellow,
        red=pair_red,
        dim=pair_dim,
        input=pair_input,
        cyan=pair_cyan or pair_title,
        magenta=pair_magenta or pair_yellow,
    )

    defcon = int(session.get("defcon") or 5)
    flash = int(now * 2) % 2 == 0 and defcon <= 2
    theme_idx = _faction_theme(now)
    enemy_lbl, ally_lbl, mode_lbl = FACTION_LABELS[theme_idx]

    caller = str(session.get("caller_ext") or "?")
    pct = int(session.get("thermonuclear_pct") or 0)
    game = str(session.get("active_game") or "menu").upper()
    phase = str(session.get("phase") or "main_menu").upper()
    enabled = _enabled_from_session(session)

    bg_pair = palette.red if flash else palette.dim
    bg_flags = curses.A_REVERSE | curses.A_BOLD if flash else curses.A_DIM
    for row in range(usable):
        try:
            stdscr.addnstr(row, 0, " " * width, width, curses.color_pair(bg_pair) | bg_flags)
        except curses.error:
            pass

    blasts = {name for name, ts in _ENGINE.blasts if now - ts <= 2.5}
    map_canvas = _build_map_canvas(
        width,
        theme_idx,
        _ENGINE.missiles,
        blasts,
        now,
        flash,
        game=str(session.get("active_game") or ""),
        engine=_ENGINE,
    )

    keypad_rows = 5
    telem_rows = 2
    status_rows = 1
    speak_rows = 2
    log_rows = 2
    news_rows = 1
    row = 0

    _put_line(stdscr, row, _hline(width, "="), width, palette.cyan, curses.A_BOLD)
    row += 1
    title = f"WOPR J124@{caller} {enemy_lbl}vs{ally_lbl}"
    _put_line(stdscr, row, _center_line(title, width), width, palette.title, curses.A_BOLD)
    row += 1
    _put_line(stdscr, row, _hline(width, "="), width, palette.cyan, curses.A_BOLD)
    row += 1

    defcon_line = (
        f"DEFCON {defcon} [{_defcon_bar(defcon, 8)}] ESC{pct:3d}% "
        f"{game[:9]:<9} {phase[:7]:<7}"
    )
    _put_line(stdscr, row, _pad_line(defcon_line, width), width, palette.yellow, curses.A_BOLD)
    row += 1

    _put_line(stdscr, row, _hline(width, "-"), width, palette.magenta, curses.A_BOLD)
    row += 1
    _put_line(stdscr, row, _center_line(f"THEATER MAP {mode_lbl}", width), width, palette.red, curses.A_BOLD)
    row += 1

    for y in range(MAP_H):
        if row > usable:
            break
        segments = _map_row_segments(map_canvas[y], palette, flash, now)
        _put_segments(stdscr, row, segments, width)
        row += 1

    _put_line(stdscr, row, _hline(width, "-"), width, palette.magenta, curses.A_BOLD)
    row += 1
    _put_line(stdscr, row, _center_line("KEYPAD", width), width, palette.cyan, curses.A_BOLD)
    row += 1
    for keypad_line in tft_keypad_table(session, enabled, width, keypad_rows):
        if row > usable:
            break
        _put_line(stdscr, row, keypad_line, width, palette.cyan, 0)
        row += 1

    _put_line(stdscr, row, _center_line("TELEMETRY", width), width, palette.green, curses.A_BOLD)
    row += 1
    for telem_line in _telemetry_ascii_lines(session, _ENGINE, width, now)[:telem_rows]:
        if row > usable:
            break
        _put_line(stdscr, row, telem_line, width, palette.green, curses.A_BOLD)
        row += 1

    for _ in range(status_rows):
        if row > usable:
            break
        _put_line(stdscr, row, _pad_line(sim_status_line(session, width), width), width, palette.yellow, 0)
        row += 1

    _put_line(stdscr, row, _center_line("JOSHUA", width), width, palette.title, curses.A_BOLD)
    row += 1
    for speak_line in _latest_speak_lines(session, width, speak_rows):
        if row > usable:
            break
        _put_line(stdscr, row, speak_line, width, palette.green, curses.A_BOLD)
        row += 1

    _put_line(stdscr, row, _hline(width, "-"), width, palette.dim, 0)
    row += 1
    for hist_line in _history_lines(session, width, log_rows):
        if row > usable:
            break
        pair = palette.red if flash and row % 2 else palette.dim
        _put_line(stdscr, row, hist_line, width, pair, 0)
        row += 1

    for _ in range(news_rows):
        if row > footer_row:
            break
        _put_line(
            stdscr,
            row,
            _warwire_scroll(session, _ENGINE, width, now),
            width,
            palette.magenta,
            curses.A_BOLD,
        )
        row += 1

    while row <= footer_row:
        _put_line(stdscr, row, " " * width, width, palette.dim, 0)
        row += 1

    footer = f"J124 @{caller} WOPR {mode_lbl} TURN {session.get('turns_this_call', 0)}"[:width]
    draw_fn(stdscr, input_row, footer.ljust(width), palette.input, curses.A_BOLD)
    stdscr.refresh()