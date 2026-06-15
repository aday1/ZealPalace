#!/usr/bin/env python3
"""Pure text rendering helpers for the ZealPalace LCD."""
from __future__ import annotations

import re
import textwrap
import time
from typing import Any

from zealot_lcd_feeds import LcdEvent, short_text


WIDTH = 40
HEIGHT = 34


def fit(text: Any, width: int = WIDTH) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(value) > width:
        value = value[: max(0, width - 1)] + "~"
    return value.ljust(width)


def center(text: Any, width: int = WIDTH) -> str:
    return fit(str(text or "")[:width].center(width), width)


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def marquee(text: str, width: int, speed: float = 14.0, now: float | None = None) -> str:
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


def wrap_line(text: str, width: int = WIDTH, max_lines: int = 3) -> list[str]:
    clean = re.sub(r"\s+", " ", text or "").strip()
    if not clean:
        return [""]
    return textwrap.wrap(
        clean,
        width=width,
        break_long_words=True,
        break_on_hyphens=False,
    )[:max_lines] or [clean[:width]]


def event_label(event: LcdEvent) -> str:
    if event.source == "ST":
        return "ST"
    if event.source == "GMQ":
        return "GMQ"
    if event.source == "PCORP":
        return "PC"
    return event.source[:4]


def event_lines(event: LcdEvent, width: int = WIDTH) -> list[tuple[str, str]]:
    tag = event_label(event)
    nick = event.nick or event.channel.strip("#") or event.kind
    canon = ""
    if event.canon == "sillytavern":
        canon = "+"
    elif event.canon == "queued":
        canon = ">"
    elif event.stale:
        canon = "!"
    prefix = f"[{tag}{canon}] "
    if event.kind == "action":
        head = prefix + "* " + nick + " "
    elif event.kind in ("presence", "status"):
        head = prefix
    else:
        head = prefix + (nick + ": " if nick else "")

    room = max(8, width - len(head))
    body = short_text(event.text, 260)
    chunks = wrap_line(body, room, max_lines=3)
    out: list[tuple[str, str]] = []
    out.append((fit(head + chunks[0], width), event.source))
    for chunk in chunks[1:]:
        out.append((fit("  " + chunk, width), event.source))
    return out


def newest(events: list[LcdEvent], source: str | None = None, n: int = 3) -> list[LcdEvent]:
    rows = events
    if source:
        rows = [event for event in events if event.source == source]
    return sorted(rows, key=lambda event: event.sort_ts)[-n:]


def mode_name(now: float, modes: tuple[str, ...] = ("ops", "rpg", "agents", "bridge", "lounge")) -> str:
    return modes[int(now // 6) % len(modes)]


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
    return center(f"ZEAL LCD {mode.upper()} {'/'.join(badges)}", width)


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


def panel_lines(snapshot: dict[str, Any], mode: str, width: int = WIDTH) -> list[tuple[str, str]]:
    status = snapshot.get("status") or {}
    bridge = snapshot.get("bridge") or {}
    events: list[LcdEvent] = snapshot.get("events") or []
    if mode == "ops":
        return ops_panel(status, snapshot, width)
    if mode == "rpg":
        return rpg_panel(bridge, width)
    if mode == "agents":
        return agents_panel(bridge, status, width)
    if mode == "bridge":
        return bridge_panel(bridge, width)
    return lounge_panel(events, width)


def ops_panel(status: dict[str, Any], snapshot: dict[str, Any], width: int) -> list[tuple[str, str]]:
    noc = as_dict(status.get("noc"))
    inet = as_dict(noc.get("internet"))
    hosts = noc.get("hosts") or []
    host_rows = []
    if isinstance(hosts, list):
        for host in hosts[:5]:
            if not isinstance(host, dict):
                continue
            state = "1" if host.get("up") else ("0" if host.get("recent_offline") else "X")
            host_rows.append(f"{host.get('name') or host.get('id')}:{state}")
    phones = as_dict(status.get("pbx_phones"))
    phone_rows = []
    for phone in phones.get("phones", []) if isinstance(phones, dict) else []:
        if isinstance(phone, dict):
            phone_rows.append(f"{phone.get('ext')} {phone.get('name') or phone.get('state')}")
    celes = as_dict(snapshot.get("celes"))
    heartbeat = as_dict(status.get("lcd_heartbeat"))
    return [
        (fit("OPS STATUS", width), "SYS"),
        (fit("WAN " + ("1" if inet.get("up", True) else "X") + " NID " + ("1" if inet.get("nidhogg_up", True) else "X"), width), "NOC"),
        (fit("HOST " + (" ".join(host_rows) or "waiting for CELES push"), width), "NOC"),
        (fit("VEC " + ("OK" if status.get("vector_ok") else "NO") + " HERMES " + ("OK" if status.get("hermes_ok") else "NO"), width), "NOC"),
        (fit("PBX API " + ("OK" if status.get("pbx_api_ok") else "NO") + " 9104 " + ("OK" if status.get("ce_api_ok") else "NO"), width), "PBX"),
        (fit("LINES " + (" | ".join(phone_rows) if phone_rows else "none reported"), width), "PBX"),
        (fit("CELES LOG " + ("fresh" if celes.get("fresh") else "stale/fallback"), width), "SYS"),
        (fit("LCD heartbeat " + str(heartbeat.get("age_sec", "?")) + "s", width), "SYS"),
    ]


def rpg_panel(bridge: dict[str, Any], width: int) -> list[tuple[str, str]]:
    npcs = bridge.get("npc_active") or []
    npc_bits = []
    for row in npcs[:4]:
        npc_bits.append(
            f"{row.get('name')} L{row.get('level')} {short_text(row.get('location'), 10)}"
        )
    battle = bridge.get("battle") or {}
    battle_line = "battle none"
    if battle.get("active"):
        battle_line = "battle " + short_text(battle.get("monster", {}).get("name"), 28)
    return [
        (fit("RPG / IRC CANON SURFACE", width), "RPG"),
        (fit("Era " + short_text(bridge.get("era"), 34), width), "RPG"),
        (fit("Hot " + short_text(bridge.get("hot_zone"), 34), width), "RPG"),
        (fit(f"NPC {bridge.get('npc_count', 0)} Player {bridge.get('players_total', 0)} GM {len(bridge.get('gm_pending') or [])}", width), "RPG"),
        (fit(battle_line, width), "RPG"),
        (fit(" | ".join(npc_bits) or "NPC state waiting", width), "RPG"),
        (fit("Co-canon: IRC + bridge pulses", width), "ST"),
        (fit("Real actions still need confirm", width), "ST"),
    ]


def agents_panel(bridge: dict[str, Any], status: dict[str, Any], width: int) -> list[tuple[str, str]]:
    routes = bridge.get("routes") or {}
    route_rows = []
    if isinstance(routes, dict):
        for name, route in list(routes.items())[:4]:
            if isinstance(route, dict):
                route_rows.append(
                    f"{route.get('preferred_extension', '?')} {short_text(name, 14)}"
                )
    companions = bridge.get("companions") or []
    comp_rows = []
    for comp in companions[:3]:
        if isinstance(comp, dict):
            comp_rows.append(
                f"{short_text(comp.get('name'), 14)} L{comp.get('level', '?')} B{comp.get('bond', '?')} T{comp.get('trust', '?')}"
            )
    return [
        (fit("LAN AGENTS / PBX", width), "PBX"),
        (fit("Hermes 111 Navi 122 Composer 117", width), "PBX"),
        (fit("Grok 112-120,123,126", width), "PBX"),
        (fit("Crystal " + (" | ".join(route_rows[:2]) or "routes via bridge"), width), "ST"),
        (fit("Crystal " + (" | ".join(route_rows[2:4]) or "690-698 ready"), width), "ST"),
        (fit("Comp " + (" | ".join(comp_rows[:1]) or "none"), width), "ST"),
        (fit("Comp " + (" | ".join(comp_rows[1:3]) or "waiting"), width), "ST"),
        (fit("Vector " + ("online" if status.get("vector_ok") else "offline"), width), "NOC"),
    ]


def bridge_panel(bridge: dict[str, Any], width: int) -> list[tuple[str, str]]:
    companions = bridge.get("companions") or []
    latest = []
    for comp in companions[:4]:
        if isinstance(comp, dict):
            latest.append(
                f"{short_text(comp.get('name'), 12)} XP{comp.get('xp', 0)}"
            )
    raw = bridge.get("bridge") or {}
    shared = raw.get("shared_memories", []) if isinstance(raw, dict) else []
    relationships = raw.get("relationships", {}) if isinstance(raw, dict) else {}
    return [
        (fit("SILLYTAVERN BRIDGE", width), "ST"),
        (fit("Status " + ("online" if bridge.get("ok") else "offline"), width), "ST"),
        (fit("Policy co-canon display", width), "ST"),
        (fit("Private memory can be visible", width), "ST"),
        (fit("Public action still GM-confirmed", width), "GMQ"),
        (fit("Comp " + (" | ".join(latest[:2]) or "none"), width), "ST"),
        (fit("Comp " + (" | ".join(latest[2:4]) or "waiting"), width), "ST"),
        (fit(f"Memory {len(shared)} Rel {len(relationships)}", width), "ST"),
    ]


def lounge_panel(events: list[LcdEvent], width: int) -> list[tuple[str, str]]:
    chosen = [
        event
        for event in events
        if event.source in ("ZH", "ZP", "ST", "RPG") and event.kind != "presence"
    ][-3:]
    lines: list[tuple[str, str]] = [(fit("LOUNGE / LATEST", width), "ZP")]
    for event in chosen:
        rows = event_lines(event, width)
        lines.extend(rows[:2])
    while len(lines) < 8:
        lines.append((fit("listening for ZealPalace chatter", width), "SYS"))
    return lines[:8]


def render_text_frame(snapshot: dict[str, Any], now: float | None = None) -> list[str]:
    ts = time.time() if now is None else now
    mode = mode_name(ts)
    rows: list[str] = []
    rows.append(header_title(snapshot, mode))
    rows.append(marquee(ticker_text(snapshot), WIDTH, 18, ts))
    rows.extend(line for line, _style in panel_lines(snapshot, mode, WIDTH))
    rows.append(marquee(banner_text(snapshot), WIDTH, 10, ts))
    rows.append(fit("-" * 12 + " EVENTS " + "-" * 20, WIDTH))
    event_rows: list[str] = []
    for event in snapshot.get("events") or []:
        event_rows.extend(row for row, _style in event_lines(event, WIDTH))
    event_rows = event_rows[-(HEIGHT - len(rows) - 1) :]
    rows.extend(event_rows)
    while len(rows) < HEIGHT - 1:
        rows.append(" " * WIDTH)
    rows.append(fit("> ", WIDTH))
    return rows[:HEIGHT]
