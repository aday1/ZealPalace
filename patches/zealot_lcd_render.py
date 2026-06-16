#!/usr/bin/env python3
"""Pure text rendering helpers for the ZealPalace LCD."""
from __future__ import annotations

import re
import textwrap
import time
import zlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from zealot_lcd_feeds import LcdEvent, short_text


WIDTH = 40
HEIGHT = 34
MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def fit(text: Any, width: int = WIDTH) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(value) > width:
        value = value[: max(0, width - 1)] + "~"
    return value.ljust(width)


def pad(text: Any, width: int = WIDTH) -> str:
    value = str(text or "")
    if len(value) > width:
        value = value[:width]
    return value.ljust(width)


def center(text: Any, width: int = WIDTH) -> str:
    return fit(str(text or "")[:width].center(width), width)


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


def stable_pick(rows: tuple[str, ...], now: float, period: int = 11, salt: str = "") -> str:
    if not rows:
        return ""
    bucket = int(now // max(1, period))
    idx = zlib.crc32(f"{bucket}:{salt}".encode("utf-8")) % len(rows)
    return rows[idx]


def chunky_scroller(text: str, now: float, width: int = WIDTH, speed: float = 5.0) -> str:
    body = "  ***  " + re.sub(r"\s+", " ", text or "").strip().upper() + "  ///  "
    if len(body) <= width:
        return pad(body, width)
    tick = int(now * speed) % len(body)
    loop = body + body
    return pad(loop[tick : tick + width], width)


def raster_bar(now: float, width: int = WIDTH) -> str:
    bands = ("_", "-", "=", "#", "=", "-", "_", ".")
    tick = int(now * 3)
    return pad("".join(bands[(idx + tick) % len(bands)] for idx in range(width)), width)


def tunnel_line(now: float, width: int = WIDTH) -> str:
    frames = (
        "<((((((((((((((((((((((((((((((((((((<>",
        "<<((((((((((((((((((((((((((((((((((()))>",
        "<<<(((((((((((((((((((((((((((((((())))>",
        "<<<<((((((((((((((((((((((((((((()))))>",
        ">>>>>))))))))))))))))))))))))))))(((((<",
        ">>>>))))))))))))))))))))))))))))))((((<",
    )
    return pad(frames[int(now * 2) % len(frames)], width)


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
    greetz = stable_pick(PSEUDOCORP_GREETZ, now, period=9, salt=salt)
    return chunky_scroller(greetz + " // " + salt, now, width, speed=4.0)


def motivational_line(snapshot: dict[str, Any], now: float, width: int = WIDTH) -> str:
    salt = str(as_dict(as_dict(snapshot.get("status")).get("telemetry")).get("remote", ""))
    text = stable_pick(PSEUDOCORP_MOTIVATORS, now, period=17, salt=salt)
    return fit("CEO MODE: " + text, width)


MODE_ART: dict[str, tuple[str, ...]] = {
    "ops": (
        "   .---- NOC ----.    .-- PBX --.  ",
        "---| WAN LAN CE |----| 100-199 |--",
        "   '------------'    '---------'   ",
        "      packets, phones, watchdogs   ",
    ),
    "terrarium": (
        "     .------------------------.     ",
        "    / LAN TERRARIUM: live NOC /     ",
        "   / cpu mem disk gpu packets /     ",
        "  '-------------------------'       ",
    ),
    "uptime": (
        "      .---- BOOT AGE GRID ----.     ",
        " zealp  | zealtower | vector  |     ",
        " uptime | load      | service |     ",
        "      '---- no reboot kabuki --'    ",
    ),
    "rpg": (
        "        /\\      CRYSTAL MESH       ",
        "   /\\  /  \\ /\\   RPG CANON         ",
        "  /  \\/____\\/ \\  IRC + BRIDGE      ",
        "      | [] |      quests live       ",
    ),
    "agents": (
        " [111]--[117]--[122]--[128]       ",
        "    \\        PBX LAN        /      ",
        " [690]--CRYSTAL MESH--[698]       ",
        "      agents talking in-band       ",
    ),
    "bridge": (
        " SillyTavern <====> ZealPalace     ",
        " cards/worlds ---> RPG state       ",
        " IRC #RPG <-----> bridge feed      ",
        "      co-canon display surface     ",
    ),
    "lounge": (
        " .------------------------------.  ",
        " | ZealHangs / Palace / RPG     |  ",
        " '------ live chatter bus ------'  ",
        "      scrollback with stage lights ",
    ),
}


def sparkle_line(now: float, width: int = WIDTH) -> str:
    chars = ["."] * max(1, width)
    tick = int(now * 5)
    glints = "*+o"
    for idx in range(7):
        pos = (tick + idx * 11) % width
        chars[pos] = glints[(tick + idx) % len(glints)]
    return pad("".join(chars), width)


def comet_line(label: str, now: float, width: int = WIDTH) -> str:
    chars = ["-"] * max(1, width)
    comet = ">>="
    pos = int(now * 12) % width
    for idx, char in enumerate(comet):
        chars[(pos + idx) % width] = char
    title = " " + fit(label, min(len(str(label)) + 1, width - 2)).strip() + " "
    start = max(0, (width - len(title)) // 2)
    for idx, char in enumerate(title[:width]):
        if start + idx < width:
            chars[start + idx] = char
    return pad("".join(chars), width)


def mode_art(mode: str, now: float, width: int = WIDTH) -> list[str]:
    rows = list(MODE_ART.get(mode, MODE_ART["lounge"]))
    glint = "<>" if int(now * 2) % 2 else "[]"
    if rows:
        rows[0] = glint[0] + rows[0][1 : max(1, width - 1)] + glint[1]
    return [pad(row, width) for row in rows]


def transition_text(text: Any, now: float, row: int, width: int = WIDTH, window: float = 2.25) -> str:
    clean = fit(text, width)
    phase = now % 9
    if phase >= window:
        return clean
    reveal = max(0, min(width, int(width * (phase / window))))
    fill = raster_bar(now + row * 0.19, width).replace("#", "=")
    if reveal <= 0:
        return fill
    return pad(clean[:reveal] + fill[reveal:], width)


def bar(value: Any, width: int = 10) -> str:
    try:
        pct = max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        pct = 0.0
    filled = int(round((pct / 100.0) * width))
    return "[" + "#" * filled + "." * (width - filled) + "]"


def spark(values: Any, width: int = 14) -> str:
    if not isinstance(values, list) or not values:
        return "." * width
    rows = []
    for item in values[-width:]:
        try:
            rows.append(max(0.0, min(100.0, float(item))))
        except (TypeError, ValueError):
            rows.append(0.0)
    levels = " .:-=+*#%@"
    out = []
    for value in rows:
        idx = int((value / 100.0) * (len(levels) - 1))
        out.append(levels[idx])
    return ("." * max(0, width - len(out)) + "".join(out))[-width:]


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


def mode_name(now: float, modes: tuple[str, ...] = ("terrarium", "uptime", "ops", "rpg", "agents", "bridge", "lounge")) -> str:
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
    if mode == "terrarium":
        return terrarium_panel(status, snapshot, width)
    if mode == "uptime":
        return uptime_panel(status, width)
    if mode == "ops":
        return ops_panel(status, snapshot, width)
    if mode == "rpg":
        return rpg_panel(bridge, width)
    if mode == "agents":
        return agents_panel(bridge, status, width)
    if mode == "bridge":
        return bridge_panel(bridge, width)
    return lounge_panel(events, width)


def terrarium_panel(status: dict[str, Any], snapshot: dict[str, Any], width: int) -> list[tuple[str, str]]:
    telemetry = as_dict(status.get("telemetry"))
    local = as_dict(telemetry.get("local"))
    remote = as_dict(telemetry.get("remote"))
    remote_hosts = as_dict(remote.get("hosts"))
    hist = as_dict(local.get("history"))
    net = as_dict(local.get("net"))
    disks = local.get("disks") if isinstance(local.get("disks"), list) else []
    root_pct = local.get("root_disk_pct")
    home_pct = None
    for disk in disks:
        if isinstance(disk, dict) and disk.get("path") == str(Path.home()):
            home_pct = disk.get("pct")
            break

    noc = as_dict(status.get("noc"))
    hosts = noc.get("hosts") if isinstance(noc.get("hosts"), list) else []
    up_count = sum(1 for host in hosts if isinstance(host, dict) and host.get("up"))
    total_count = len(hosts)
    alert = as_dict(noc.get("alert"))
    alert_text = short_text(alert.get("slug") or alert.get("target_id") or "none", 24)

    rows: list[tuple[str, str]] = [
        (fit("TERRARIUM / LAN VITALS", width), "NOC"),
        (fit(f"zeal cpu {fmt_pct(local.get('cpu_pct'))} {bar(local.get('cpu_pct'), 8)} mem {fmt_pct(local.get('mem_pct'))}", width), "NOC"),
        (fit("cpu " + spark(hist.get("cpu"), 16) + " mem " + spark(hist.get("mem"), 10), width), "NOC"),
        (fit(f"disk / {fmt_pct(root_pct)} {bar(root_pct, 8)} home {fmt_pct(home_pct)}", width), "NOC"),
        (fit(f"net rx {fmt_bps(net.get('rx_bps'))} tx {fmt_bps(net.get('tx_bps'))} temp {local.get('temp_c') or '?'}C", width), "NOC"),
        (fit(f"lan hosts {up_count}/{total_count or '?'} up alert {alert_text}", width), "NOC"),
    ]

    for name, label in (("zealtower", "ztwr"), ("vector", "vect")):
        host = as_dict(remote_hosts.get(name))
        if not host:
            rows.append((fit(f"{label} telemetry waiting", width), "SYS"))
            continue
        gpus = host.get("gpus") if isinstance(host.get("gpus"), list) else []
        gpu = as_dict(gpus[0]) if gpus else {}
        disk_pct = first_disk_pct(host, "/mnt/cache" if name == "zealtower" else "/mnt/c")
        if disk_pct is None:
            disk_pct = first_disk_pct(host)
        gpu_text = "g?"
        if gpu:
            gpu_text = f"g{fmt_pct(gpu.get('util_pct'))} m{gpu.get('mem_used_mb', '?')}/{gpu.get('mem_total_mb', '?')} t{gpu.get('temp_c', '?')}C"
        rows.append((fit(f"{label} cpu {fmt_pct(host.get('cpu_pct'))} disk {fmt_pct(disk_pct)} {gpu_text}", width), "ST" if name == "zealtower" else "RPG"))

    age = remote.get("age_sec")
    if age is not None:
        rows.append((fit(f"remote telemetry age {age}s {'fresh' if remote.get('fresh') else 'stale'}", width), "SYS"))
    return rows[:9]


def uptime_panel(status: dict[str, Any], width: int) -> list[tuple[str, str]]:
    telemetry = as_dict(status.get("telemetry"))
    local = as_dict(telemetry.get("local"))
    remote = as_dict(telemetry.get("remote"))
    remote_hosts = as_dict(remote.get("hosts"))
    host_specs = (
        ("zealp", local, "NOC", "/"),
        ("ztwr", as_dict(remote_hosts.get("zealtower")), "ST", "/mnt/cache"),
        ("vect", as_dict(remote_hosts.get("vector")), "RPG", "/mnt/c"),
    )

    rows: list[tuple[str, str]] = [(fit("SERVER UPTIME / BOOT AGE", width), "NOC")]
    longest_label = "?"
    longest_uptime = -1
    for label, host, style, disk_path in host_specs:
        if not host:
            rows.append((fit(f"{label} telemetry waiting", width), "SYS"))
            rows.append((fit(f"{label} no uptime sample yet", width), "SYS"))
            continue
        uptime = host.get("uptime_sec")
        try:
            uptime_value = int(float(uptime))
        except (TypeError, ValueError):
            uptime_value = -1
        if uptime_value > longest_uptime:
            longest_label = label
            longest_uptime = uptime_value
        disk_pct = first_disk_pct(host, disk_path)
        if disk_pct is None:
            disk_pct = first_disk_pct(host)
        rows.append(
            (
                fit(f"{label} up {fmt_uptime(uptime)} {bar(uptime_pct(uptime), 8)} cpu {fmt_pct(host.get('cpu_pct'))}", width),
                style,
            )
        )
        rows.append(
            (
                fit(
                    f"{label} load {host.get('load1', '?')}/{host.get('load5', '?')} mem {fmt_pct(host.get('mem_pct'))} disk {fmt_pct(disk_pct)}",
                    width,
                ),
                style,
            )
        )

    age = remote.get("age_sec")
    freshness = f"remote age {age}s {'fresh' if remote.get('fresh') else 'stale'}" if age is not None else "remote age unknown"
    if longest_uptime >= 0:
        freshness += f" longest {longest_label} {fmt_uptime(longest_uptime)}"
    rows.append((fit(freshness, width), "SYS"))
    return rows[:9]


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
    rows.append(comet_line(header_title(snapshot, mode).strip(), ts))
    rows.append(raster_bar(ts))
    rows.append(demoscene_greetz(snapshot, ts, WIDTH))
    rows.append(chunky_scroller(ticker_text(snapshot) + " // " + gpu_summary(snapshot), ts, WIDTH, speed=3.0))
    rows.extend(mode_art(mode, ts, WIDTH))
    rows.extend(transition_text(line, ts, idx, WIDTH) for idx, (line, _style) in enumerate(panel_lines(snapshot, mode, WIDTH)))
    rows.append(calendar_line(ts, WIDTH))
    rows.append(motivational_line(snapshot, ts, WIDTH))
    rows.append(marquee(banner_text(snapshot), WIDTH, 10, ts))
    rows.append(tunnel_line(ts, WIDTH))
    rows.append(comet_line("EVENTS", ts + 2.0, WIDTH))
    event_rows: list[str] = []
    for event in snapshot.get("events") or []:
        event_rows.extend(row for row, _style in event_lines(event, WIDTH))
    event_rows = event_rows[-(HEIGHT - len(rows) - 1) :]
    rows.extend(event_rows)
    while len(rows) < HEIGHT - 1:
        rows.append(" " * WIDTH)
    rows.append(fit("> ", WIDTH))
    return rows[:HEIGHT]
