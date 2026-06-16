#!/usr/bin/env python3
"""Joshua WOPR dial menu — ext 124 DTMF map shared by PBX, TFT, and web console."""
from __future__ import annotations

import re
from typing import Any

JOSHUA_EXT = "124"

# digit, game_id, label, short (ticker), map_mode
DTMF_ENTRIES: tuple[tuple[str, str, str, str, str], ...] = (
    ("1", "chess", "Chess", "CHESS", "chess"),
    ("2", "thermonuclear", "Global Thermonuclear War", "GTW", "thermo"),
    ("3", "hacking", "Hacking NORAD subnet", "HACK", "hack"),
    ("5", "falken_maze", "Falken's Maze", "MAZE", "maze"),
)

DTMF_UTIL: tuple[tuple[str, str | None, str, str], ...] = (
    ("4", None, "List games", "LIST"),
    ("0", None, "Keypad help", "HELP"),
)

# Voice-only games (no DTMF digit on ext 124)
VOICE_ONLY: tuple[tuple[str, str, str, str], ...] = (
    ("tic_tac_toe", "Tic-Tac-Toe", "TICTAC", "board"),
    ("backgammon", "Backgammon", "BACKGAM", "board"),
    ("checkers", "Checkers", "CHECK", "board"),
    ("poker", "Poker", "POKER", "table"),
    ("bridge", "Bridge", "BRIDGE", "table"),
    ("fighter_combat", "Fighter Combat", "FIGHTER", "fighter"),
)

MAP_MODE_DEFAULT = "menu"

# digit -> spoken command (in-game, ext 124 call already active)
IN_GAME_DTMF: dict[str, tuple[tuple[str, str], ...]] = {
    "thermonuclear": (
        ("1", "strike Moscow"),
        ("2", "strike Eastern Europe"),
        ("3", "strike Pacific theater"),
        ("4", "escalate full salvo"),
        ("5", "hold fire de-escalate"),
        ("9", "WOPR auto strike"),
    ),
    "hacking": (
        ("1", "probe NORAD subnet"),
        ("2", "trace personnel file"),
        ("3", "login joshua"),
    ),
    "chess": (
        ("1", "pawn to king four"),
        ("2", "knight to bishop three"),
        ("3", "castle kingside"),
    ),
    "falken_maze": (
        ("1", "turn left"),
        ("2", "go forward"),
        ("3", "turn right"),
    ),
}

_WOPR_AUTO_STRIKES: tuple[str, ...] = (
    "launch at Soviet command Moscow",
    "strike Eastern Europe",
    "escalate Pacific theater",
    "ICBM salvo continental United States",
    "retaliatory strike Soviet Union",
    "full escalation all sectors",
)

_ALL_GAME_IDS = {row[1] for row in DTMF_ENTRIES} | {row[0] for row in VOICE_ONLY}


def _norm_enabled(enabled: list[str] | None) -> set[str]:
    if not enabled:
        return set(_ALL_GAME_IDS)
    return {g for g in enabled if g in _ALL_GAME_IDS}


def _short_label(label: str, max_len: int = 28) -> str:
    clean = re.sub(r"\s+", " ", str(label or "")).strip().upper()
    if len(clean) <= max_len:
        return clean
    return clean[: max_len - 3] + "..."


def build_game_menu(enabled_games: list[str] | None = None) -> dict[str, Any]:
    enabled = _norm_enabled(enabled_games)
    dtmf: list[dict[str, Any]] = []
    for digit, gid, label, short, map_mode in DTMF_ENTRIES:
        if gid not in enabled:
            continue
        dtmf.append(
            {
                "dtmf": digit,
                "id": gid,
                "label": label,
                "short": short,
                "map_mode": map_mode,
                "dial": f"DIAL {JOSHUA_EXT} PRESS {digit}",
            }
        )
    for digit, gid, label, short in DTMF_UTIL:
        dtmf.append(
            {
                "dtmf": digit,
                "id": gid,
                "label": label,
                "short": short,
                "map_mode": None,
                "dial": f"DIAL {JOSHUA_EXT} PRESS {digit}",
            }
        )
    voice: list[dict[str, Any]] = []
    for gid, label, short, map_mode in VOICE_ONLY:
        if gid not in enabled:
            continue
        voice.append(
            {
                "id": gid,
                "label": label,
                "short": short,
                "map_mode": map_mode,
                "dial": f"DIAL {JOSHUA_EXT} SAY {label}",
            }
        )
    return {
        "ext": JOSHUA_EXT,
        "dtmf": dtmf,
        "voice_only": voice,
    }


def dtmf_for_game(game_id: str, enabled_games: list[str] | None = None) -> str:
    enabled = _norm_enabled(enabled_games)
    for digit, gid, _label, _short, _mode in DTMF_ENTRIES:
        if gid == game_id and gid in enabled:
            return digit
    return ""


def map_mode_for_game(game_id: str) -> str:
    for _digit, gid, _label, _short, mode in DTMF_ENTRIES:
        if gid == game_id:
            return mode
    for gid, _label, _short, mode in VOICE_ONLY:
        if gid == game_id:
            return mode
    return MAP_MODE_DEFAULT


def idle_combat_log_lines(enabled_games: list[str] | None = None) -> list[str]:
    menu = build_game_menu(enabled_games)
    lines = [
        "SHALL WE PLAY A GAME?",
        f"DIAL {JOSHUA_EXT} -- JOSHUA WOPR",
    ]
    for row in menu["dtmf"]:
        gid = row.get("id")
        if gid is None:
            continue
        digit = row["dtmf"]
        label = _short_label(row.get("label") or row.get("short") or "")
        lines.append(f"PRESS {digit} {label}")
    util = [r for r in menu["dtmf"] if r.get("id") is None]
    if util:
        parts = [f"PRESS {r['dtmf']} {r['short']}" for r in util]
        lines.append("  ".join(parts))
    voice = menu.get("voice_only") or []
    if voice:
        names = ", ".join(r["short"].lower() for r in voice[:6])
        if len(voice) > 6:
            names += ", ..."
        lines.append(f"OR SAY: {names}")
    return lines


def active_game_hint(game_id: str, enabled_games: list[str] | None = None) -> str:
    gid = str(game_id or "").strip()
    if not gid:
        return f"DIAL {JOSHUA_EXT} TO SELECT A GAME"
    digit = dtmf_for_game(gid, enabled_games)
    menu = build_game_menu(enabled_games)
    for row in menu["dtmf"] + menu["voice_only"]:
        if row.get("id") == gid:
            label = row.get("label") or row.get("short") or gid
            if digit:
                return f"ACTIVE: {label.upper()} (DIAL {JOSHUA_EXT} PRESS {digit})"
            return f"ACTIVE: {label.upper()} (DIAL {JOSHUA_EXT} SAY {label})"
    return f"ACTIVE: {gid.replace('_', ' ').upper()} (DIAL {JOSHUA_EXT})"


def in_game_dtmf_line(game_id: str, width: int = 120) -> str:
    """Spoken/TFT keypad map during an active simulation."""
    gid = str(game_id or "").strip()
    rows = IN_GAME_DTMF.get(gid)
    if not rows:
        return "Press star for game list."
    parts = [f"press {d} {label}" for d, label in rows]
    parts.append("press 0 help")
    parts.append("star menu")
    line = ". ".join(parts) + "."
    if len(line) <= width:
        return line
    short = [f"{d}={label.split()[-1][:6]}" for d, label in rows]
    return ("Keys: " + " ".join(short) + " 0=help *=menu")[:width]


def in_game_dtmf_command(game_id: str, digit: str) -> str:
    d = str(digit or "").strip()[:1]
    if d == "9" and game_id == "thermonuclear":
        return "WOPR auto strike"
    for row_digit, cmd in IN_GAME_DTMF.get(str(game_id or ""), ()):
        if row_digit == d:
            return cmd
    return ""


def wopr_auto_strike_sequence() -> tuple[str, ...]:
    return _WOPR_AUTO_STRIKES


def _short_key_label(label: str, max_len: int = 8) -> str:
    clean = re.sub(r"\s+", " ", str(label or "")).strip().upper()
    for prefix in ("STRIKE ", "PRESS ", "LOGIN ", "GO ", "TURN "):
        if clean.startswith(prefix):
            clean = clean[len(prefix) :]
    aliases = (
        ("EASTERN EUROPE", "EUROPE"),
        ("PACIFIC THEATER", "PACIFIC"),
        ("FULL SALVO", "SALVO"),
        ("DE-ESCALATE", "HOLD"),
        ("WOPR AUTO STRIKE", "AUTO"),
        ("NORAD SUBNET", "PROBE"),
        ("PERSONNEL FILE", "TRACE"),
        ("KING FOUR", "P-K4"),
        ("BISHOP THREE", "N-B3"),
        ("KINGSIDE", "CASTLE"),
    )
    for needle, short in aliases:
        if needle in clean:
            return short[:max_len]
    if clean.startswith("HOLD"):
        return "HOLD"[:max_len]
    if len(clean) <= max_len:
        return clean
    return clean[:max_len]


def _keypad_pairs(session: dict, enabled_games: list[str] | None = None) -> list[tuple[str, str]]:
    phase = str(session.get("phase") or "")
    game = str(session.get("active_game") or "").strip()
    pairs: list[tuple[str, str]] = []
    if game and phase in ("playing", "hacking"):
        for digit, label in IN_GAME_DTMF.get(game, ()):
            pairs.append((digit, _short_key_label(label)))
        pairs.extend([("0", "HELP"), ("*", "MENU")])
        return pairs
    menu = build_game_menu(enabled_games)
    for row in menu.get("dtmf") or []:
        digit = str(row.get("dtmf") or "")
        short = str(row.get("short") or row.get("label") or "")[:8]
        if digit and short:
            pairs.append((digit, short))
    pairs.append(("*", "MENU"))
    return pairs


def tft_keypad_table(
    session: dict,
    enabled_games: list[str] | None = None,
    width: int = 40,
    max_rows: int = 4,
) -> list[str]:
    """Two-column DTMF table for the TFT (fixed rows, no scroll)."""
    width = max(20, int(width or 40))
    pairs = _keypad_pairs(session, enabled_games)
    col_w = max(10, width // 2)
    cell = max(4, col_w - 3)
    lines: list[str] = []
    header = f"── DIAL {JOSHUA_EXT} ──"[:width]
    lines.append(header.center(width)[:width])
    data_budget = max(1, int(max_rows) - 1)
    data_rows = 0
    for i in range(0, len(pairs), 2):
        left_d, left_l = pairs[i]
        left = f"{left_d} {left_l[:cell]:<{cell}}"
        if i + 1 < len(pairs):
            right_d, right_l = pairs[i + 1]
            right = f"{right_d} {right_l[:cell]}"
            line = f"{left}{right}"[:width]
        else:
            line = left[:width]
        lines.append(line.ljust(width)[:width])
        data_rows += 1
        if data_rows >= data_budget:
            break
    while len(lines) < 2:
        lines.append(" " * width)
    return lines[: max(2, int(max_rows))]


def tft_keys_line(session: dict, enabled_games: list[str] | None = None, width: int = 40) -> str:
    """TFT KEYS row: in-game map when sim running, else main menu."""
    phase = str(session.get("phase") or "")
    game = str(session.get("active_game") or "").strip()
    if game and phase in ("playing", "hacking"):
        rows = IN_GAME_DTMF.get(game, ())
        parts = [f"{d}={lbl.split()[-1][:5].upper()}" for d, lbl in rows]
        if game == "thermonuclear":
            parts.append("9=AUTO")
        parts.extend(["0=HLP", "*=MENU"])
        line = " ".join(parts)
        return line[:width] if len(line) > width else line
    return compact_dtmf_line(enabled_games, width)


def compact_dtmf_line(enabled_games: list[str] | None = None, width: int = 40) -> str:
    """One-line keypad map for the ZealPalace TFT."""
    menu = build_game_menu(enabled_games)
    parts: list[str] = []
    for row in menu.get("dtmf") or []:
        digit = str(row.get("dtmf") or "")
        short = str(row.get("short") or row.get("label") or "")[:4]
        if digit and short:
            parts.append(f"{digit}={short}")
    parts.append("*=MENU")
    line = " ".join(parts)
    if len(line) <= width:
        return line
    return line[: width - 3] + "..."


def sim_status_line(session: dict, width: int = 40) -> str:
    """Region / escalation / outcome for TFT status row."""
    game = str(session.get("active_game") or "").replace("_", " ")[:12]
    pct = int(session.get("thermonuclear_pct") or 0)
    region = str(session.get("last_region") or "").strip()
    outcome = re.sub(r"\s+", " ", str(session.get("last_outcome") or "")).strip()
    bits: list[str] = []
    if game:
        bits.append(game.upper())
    if pct > 0:
        bits.append(f"ESC{pct}%")
    if region:
        bits.append(region[:14])
    if outcome:
        bits.append(outcome[: width // 2])
    line = " | ".join(bits) if bits else "AWAITING COMMAND"
    return line[:width]


def menu_ticker(enabled_games: list[str] | None = None) -> str:
    menu = build_game_menu(enabled_games)
    parts: list[str] = []
    for row in menu["dtmf"]:
        gid = row.get("id")
        if gid is None:
            continue
        parts.append(f"{row['short']}={row['dtmf']}")
    for row in menu.get("voice_only") or []:
        parts.append(row["short"])
    parts.append(f"EXT {JOSHUA_EXT}")
    return " | ".join(parts) + " | "