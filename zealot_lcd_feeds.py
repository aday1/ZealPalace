#!/usr/bin/env python3
"""Typed feed adapters for the ZealPalace LCD.

The LCD intentionally consumes read-only sources. It may connect to IRC to
listen, and it may read the Crystal Mesh bridge, CELES log API, and local JSON
cache files, but it does not mutate bridge canon or place PBX actions.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    import psutil
except Exception:  # pragma: no cover - optional dependency on development hosts
    psutil = None


CACHE = Path.home() / ".cache" / "zealot"
RPG_DIR = CACHE / "rpg"
LAN_TELEMETRY = CACHE / "lan_telemetry.json"
LAN_TELEMETRY_SOURCES = CACHE / "lan_telemetry_sources.json"
LOCAL_LOGS = (
    ("ZP", "#ZealPalace", CACHE / "irc.log"),
    ("RPG", "#RPG", CACHE / "rpg.log"),
    ("ZH", "#ZealHangs", CACHE / "hangs.log"),
    ("PBX", "#pseudocorp", CACHE / "pbx.log"),
)

IRC_HOST = "10.13.37.76"
IRC_PORT = 6667
IRC_NICK = "lcd-ticker"
IRC_CHANNELS = (
    "#pseudocorp",
    "#RPG",
    "#slacking-off",
    "#macroverse-rpg",
    "#ZealPalace",
    "#ZealHangs",
    "#yggdrasil",
)

CELES_LOG_API = "http://10.13.37.37:9104/recent.json"
BRIDGE_STATE_URL = "http://127.0.0.1:8890/rpg/state"
BRIDGE_HEALTH_URL = "http://127.0.0.1:8890/health"
CELES_FRESH_SEC = 15 * 60
REMOTE_TELEMETRY_FRESH_SEC = 10 * 60
REMOTE_PULL_INTERVAL_SEC = 15

METRIC_HISTORY: dict[str, deque[float]] = {
    "cpu": deque(maxlen=32),
    "mem": deque(maxlen=32),
    "disk": deque(maxlen=32),
    "rx": deque(maxlen=32),
    "tx": deque(maxlen=32),
}
_NET_LAST: dict[str, float] = {}
_REMOTE_LAST_PULL = 0.0
_REMOTE_LAST_DATA: dict[str, Any] | None = None
_CELES_STALE_WARN_TS = 0.0
CELES_STALE_WARN_COOLDOWN_SEC = 900.0
LCD_EVENT_TEXT_CLIP = 140

FEED_NOISE_RE = re.compile(
    r"(?i)(export\s+TERM|zealot_display|display_loop(?:\.sh)?|lcd-init|"
    r"\.local/bin/|tmux\s|bash\s+[\"']?\$|python3?\s+.*zealot_display)"
)
FEED_NOISE_NICKS = frozenset({"aday", "lcd-ticker", "lcd_ticker"})


@dataclass
class LcdEvent:
    source: str
    channel: str
    nick: str
    text: str
    kind: str = "message"
    canon: str = "live"
    ts: str = ""
    sort_ts: float = 0.0
    priority: int = 0
    stale: bool = False

    def key(self) -> tuple[str, str, str, str]:
        return (
            self.source,
            self.channel,
            self.nick,
            re.sub(r"\s+", " ", self.text.strip())[:120],
        )


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def short_text(value: Any, limit: int = 120) -> str:
    text = re.sub(r"[\r\n\t]+", " ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 3)].rstrip() + "..."


def clip_words(value: Any, limit: int = 200) -> str:
    """Length cap on a word boundary -- no '...' truncation artifact."""
    text = re.sub(r"\s+", " ", re.sub(r"[\r\n\t]+", " ", str(value or ""))).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return cut or text[:limit]


def clip_sentence(value: Any, limit: int = 210) -> str:
    """Keep whole sentences. Over the limit, end on the last . ! ? so the line
    reads complete (never a mid-sentence chop); fall back to a word boundary."""
    text = re.sub(r"\s+", " ", re.sub(r"[\r\n\t]+", " ", str(value or ""))).strip()
    if len(text) <= limit:
        return text
    window = text[:limit]
    ends = list(re.finditer(r"[.!?]", window))
    if ends:
        return window[: ends[-1].end()].strip()
    for idx in range(min(len(text), limit) - 1, -1, -1):
        if text[idx] in ".!?":
            return text[: idx + 1].strip()
    cut = window.rsplit(" ", 1)[0].rstrip(" ,;:-")
    return cut or window


def parse_iso_ts(value: str) -> float:
    if not value:
        return 0.0
    try:
        clean = value.replace("Z", "+00:00")
        return datetime.fromisoformat(clean).timestamp()
    except ValueError:
        return 0.0


def read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return fallback


def _pct(used: float, total: float) -> float:
    if total <= 0:
        return 0.0
    return max(0.0, min(100.0, (used / total) * 100.0))


def _remember(key: str, value: float) -> list[float]:
    row = METRIC_HISTORY.setdefault(key, deque(maxlen=32))
    row.append(float(value))
    return list(row)


def _proc_mem_pct() -> float:
    values: dict[str, float] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, _, rest = line.partition(":")
            values[key] = float(rest.strip().split()[0]) * 1024.0
    except (OSError, ValueError, IndexError):
        return 0.0
    total = values.get("MemTotal", 0.0)
    avail = values.get("MemAvailable", 0.0)
    return _pct(total - avail, total)


def _disk_row(path: str) -> dict[str, Any]:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return {"path": path, "ok": False, "pct": 0}
    return {
        "path": path,
        "ok": True,
        "total": usage.total,
        "used": usage.used,
        "free": usage.free,
        "pct": round(_pct(usage.used, usage.total), 1),
    }


def _temperature_c() -> float | None:
    if psutil is not None:
        try:
            temps = psutil.sensors_temperatures(fahrenheit=False)
            for rows in temps.values():
                for row in rows:
                    current = getattr(row, "current", None)
                    if current is not None:
                        return round(float(current), 1)
        except Exception:
            pass
    for path in ("/sys/class/thermal/thermal_zone0/temp",):
        try:
            return round(float(Path(path).read_text(encoding="utf-8").strip()) / 1000.0, 1)
        except (OSError, ValueError):
            continue
    return None


def _net_counters() -> tuple[int, int]:
    if psutil is not None:
        try:
            counters = psutil.net_io_counters()
            return int(counters.bytes_recv), int(counters.bytes_sent)
        except Exception:
            pass
    rx = 0
    tx = 0
    try:
        for line in Path("/proc/net/dev").read_text(encoding="utf-8").splitlines()[2:]:
            iface, _, rest = line.partition(":")
            if iface.strip() == "lo":
                continue
            parts = rest.split()
            rx += int(parts[0])
            tx += int(parts[8])
    except (OSError, ValueError, IndexError):
        pass
    return rx, tx


def _uptime_sec(now: float) -> int:
    if psutil is not None:
        try:
            return max(0, int(now - float(psutil.boot_time())))
        except Exception:
            pass
    try:
        return max(0, int(float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])))
    except (OSError, ValueError, IndexError):
        return 0


def local_system_stats() -> dict[str, Any]:
    now = time.time()
    if psutil is not None:
        try:
            cpu_pct = float(psutil.cpu_percent(interval=None))
        except Exception:
            cpu_pct = 0.0
        try:
            mem_pct = float(psutil.virtual_memory().percent)
        except Exception:
            mem_pct = _proc_mem_pct()
    else:
        cpu_pct = 0.0
        mem_pct = _proc_mem_pct()

    load = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
    root_disk = _disk_row("/")
    home_disk = _disk_row(str(Path.home()))
    rx, tx = _net_counters()
    last_ts = _NET_LAST.get("ts", now)
    elapsed = max(0.2, now - last_ts)
    rx_rate = max(0.0, (rx - _NET_LAST.get("rx", rx)) / elapsed)
    tx_rate = max(0.0, (tx - _NET_LAST.get("tx", tx)) / elapsed)
    _NET_LAST.update({"ts": now, "rx": float(rx), "tx": float(tx)})

    return {
        "ok": True,
        "host": socket.gethostname(),
        "uptime_sec": _uptime_sec(now),
        "cpu_pct": round(cpu_pct, 1),
        "load1": round(float(load[0]), 2),
        "load5": round(float(load[1]), 2),
        "load15": round(float(load[2]), 2),
        "mem_pct": round(mem_pct, 1),
        "temp_c": _temperature_c(),
        "disks": [root_disk, home_disk],
        "root_disk_pct": root_disk.get("pct", 0),
        "net": {
            "rx_bps": int(rx_rate),
            "tx_bps": int(tx_rate),
        },
        "history": {
            "cpu": _remember("cpu", cpu_pct),
            "mem": _remember("mem", mem_pct),
            "disk": _remember("disk", float(root_disk.get("pct") or 0)),
            "rx": _remember("rx", min(100.0, rx_rate / 1024.0 / 30.0)),
            "tx": _remember("tx", min(100.0, tx_rate / 1024.0 / 30.0)),
        },
    }


def telemetry_source_token(source: dict[str, Any]) -> str:
    token = str(source.get("token") or "")
    if token:
        return token
    token_file = source.get("token_file") or source.get("tokenFile")
    if token_file:
        try:
            return Path(str(token_file)).read_text(encoding="utf-8").strip()
        except OSError:
            return ""
    return ""


def fetch_telemetry_source(source: dict[str, Any]) -> tuple[str, dict[str, Any] | None, str]:
    name = short_text(source.get("name") or source.get("url") or "remote", 32)
    url = str(source.get("url") or "")
    if not url:
        return name, None, "missing url"
    headers = {}
    token = telemetry_source_token(source)
    if token:
        headers["X-Zeal-Telemetry-Token"] = token
    try:
        request = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(request, timeout=float(source.get("timeout", 0.8))) as response:
            data = response.read(192 * 1024)
        parsed = json.loads(data.decode("utf-8", "replace"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError) as exc:
        return name, None, str(exc)[:160]
    if not isinstance(parsed, dict) or not parsed.get("ok"):
        return name, None, "invalid telemetry response"
    parsed["host"] = name
    parsed.setdefault("name", name)
    return name, parsed, ""


def cache_telemetry() -> dict[str, Any]:
    data = read_json(LAN_TELEMETRY, {})
    if not isinstance(data, dict):
        return {"ok": False, "error": "invalid telemetry cache", "hosts": {}}
    generated = data.get("generated_ts")
    try:
        age = int(time.time() - float(generated))
    except (TypeError, ValueError):
        age = 999999
    hosts = data.get("hosts") if isinstance(data.get("hosts"), dict) else {}
    return {
        "ok": bool(hosts),
        "fresh": bool(hosts) and age <= REMOTE_TELEMETRY_FRESH_SEC,
        "age_sec": age if hosts else None,
        "generated_at": data.get("generated_at", ""),
        "hosts": hosts,
        "source": data.get("source", ""),
    }


def pull_remote_telemetry() -> dict[str, Any] | None:
    sources_doc = read_json(LAN_TELEMETRY_SOURCES, {})
    sources = sources_doc.get("sources") if isinstance(sources_doc, dict) else None
    if not isinstance(sources, list) or not sources:
        return None

    cache = cache_telemetry()
    cache_hosts = cache.get("hosts") if isinstance(cache.get("hosts"), dict) else {}
    hosts = dict(cache_hosts)
    errors: dict[str, str] = {}
    pulled = 0
    for source in sources:
        if not isinstance(source, dict):
            continue
        name, data, error = fetch_telemetry_source(source)
        if data:
            hosts[name] = data
            pulled += 1
        elif error:
            errors[name] = error

    now = time.time()
    if pulled:
        payload = {
            "generated_at": now_iso(),
            "generated_ts": int(now),
            "source": "json-pull",
            "hosts": hosts,
        }
        try:
            LAN_TELEMETRY.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            pass
        return {
            "ok": True,
            "fresh": True,
            "age_sec": 0,
            "generated_at": payload["generated_at"],
            "hosts": hosts,
            "source": "json-pull",
            "errors": errors,
        }
    if cache.get("ok"):
        cache["errors"] = errors
        return cache
    return {"ok": False, "fresh": False, "hosts": {}, "errors": errors}


def remote_telemetry() -> dict[str, Any]:
    global _REMOTE_LAST_DATA, _REMOTE_LAST_PULL
    now = time.time()
    if _REMOTE_LAST_DATA is not None and now - _REMOTE_LAST_PULL < REMOTE_PULL_INTERVAL_SEC:
        return _REMOTE_LAST_DATA
    pulled = pull_remote_telemetry()
    data = pulled if pulled is not None else cache_telemetry()
    _REMOTE_LAST_DATA = data
    _REMOTE_LAST_PULL = now
    return data


def fetch_json(url: str, timeout: float = 1.2) -> tuple[Any | None, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            data = response.read(256 * 1024)
        return json.loads(data.decode("utf-8", "replace")), ""
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError) as exc:
        return None, str(exc)[:160]


def tcp_ok(host: str, port: int, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def tail_lines(path: Path, limit: int = 40) -> list[str]:
    if not path.is_file():
        return []
    try:
        rows = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return [row.strip() for row in rows[-limit:] if row.strip()]


def feed_line_is_noise(nick: str, text: str) -> bool:
    body = re.sub(r"\s+", " ", str(text or "")).strip()
    if not body:
        return True
    if str(nick or "").strip().lower() in FEED_NOISE_NICKS and FEED_NOISE_RE.search(body):
        return True
    return False


def parse_local_line(tag: str, channel: str, line: str, sort_ts: float) -> LcdEvent | None:
    text = line.strip()
    if FEED_NOISE_RE.search(text):
        return None
    if tag == "PBX" and text.startswith("[PBX]"):
        text = text[5:].strip()

    nick = ""
    kind = "message"
    body = text
    ts = ""

    first, _, rest = body.partition(" ")
    if ":" in first and first[-1:].lower() in ("a", "p"):
        ts = first
        body = rest.strip()

    if body.startswith("<") and ">" in body:
        end = body.find(">")
        nick = body[1:end]
        body = body[end + 1 :].strip()
    elif body.startswith("* "):
        kind = "action"
        parts = body[2:].split(" ", 1)
        nick = parts[0] if parts else ""
        body = parts[1] if len(parts) > 1 else body[2:]
    elif " joined " in body or " has left " in body:
        kind = "presence"
        nick = body.split(" ", 1)[0]
    elif tag == "PBX":
        nick = "CELES-PBX"
        kind = "pbx"
    elif tag == "RPG":
        nick = "DungeonMaster"
        kind = "rpg"

    event = LcdEvent(
        source=tag,
        channel=channel,
        nick=short_text(nick, 24),
        text=short_text(body, 260),
        kind=kind,
        canon="irc" if tag != "PBX" else "ops",
        ts=ts,
        sort_ts=sort_ts,
        priority=2 if tag in ("PBX", "RPG") else 1,
    )
    if feed_line_is_noise(event.nick, event.text):
        return None
    return event


def local_events(limit: int = 64) -> list[LcdEvent]:
    events: list[LcdEvent] = []
    now = time.time()
    for tag, channel, path in LOCAL_LOGS:
        rows = tail_lines(path, max(12, limit // len(LOCAL_LOGS) + 8))
        base = now - (len(rows) * 0.2)
        for idx, row in enumerate(rows):
            event = parse_local_line(tag, channel, row, base + idx * 0.2)
            if event is not None:
                events.append(event)
    return events[-limit:]


def celes_events(limit: int = 80) -> tuple[list[LcdEvent], dict[str, Any]]:
    url = CELES_LOG_API + "?" + urllib.parse.urlencode({"limit": str(limit)})
    data, error = fetch_json(url, timeout=1.0)
    status = {
        "ok": data is not None,
        "error": error,
        "fresh": False,
        "latest_ts": "",
        "count": 0,
    }
    if not isinstance(data, dict):
        return [], status

    rows = data.get("entries") or []
    if not isinstance(rows, list):
        rows = []
    events: list[LcdEvent] = []
    latest = 0.0
    for row in rows[-limit:]:
        if not isinstance(row, dict):
            continue
        ts = str(row.get("ts") or "")
        sort_ts = parse_iso_ts(ts)
        latest = max(latest, sort_ts)
        source = "IRC"
        chan = str(row.get("chan") or "")
        if chan == "#RPG":
            source = "RPG"
        elif chan == "#ZealHangs":
            source = "ZH"
        elif chan == "#ZealPalace":
            source = "ZP"
        elif chan == "#pseudocorp":
            source = "PCORP"
        nick = short_text(row.get("nick"), 24)
        text = short_text(row.get("text"), 260)
        if feed_line_is_noise(nick, text):
            continue
        events.append(
            LcdEvent(
                source=source,
                channel=chan,
                nick=nick,
                text=text,
                kind=str(row.get("type") or "message"),
                canon="irc",
                ts=ts,
                sort_ts=sort_ts or time.time(),
                priority=2 if chan in ("#RPG", "#pseudocorp") else 1,
            )
        )
    status["count"] = len(events)
    if latest:
        age = time.time() - latest
        status["fresh"] = age <= CELES_FRESH_SEC
        status["latest_ts"] = datetime.fromtimestamp(latest, timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        status["age_sec"] = int(age)
    return events, status


_LAST_BRIDGE_GOOD: dict[str, Any] = {}


def bridge_snapshot() -> dict[str, Any]:
    global _LAST_BRIDGE_GOOD
    health, health_error = fetch_json(BRIDGE_HEALTH_URL, timeout=0.7)
    state, state_error = fetch_json(BRIDGE_STATE_URL, timeout=2.5)
    ok = isinstance(state, dict) and bool(state.get("ok"))
    bridge = state.get("sillytavern_bridge", {}) if isinstance(state, dict) else {}
    world = state.get("world", {}) if isinstance(state, dict) else {}
    npc_state = state.get("npc_state", {}) if isinstance(state, dict) else {}
    battle = state.get("active_battle", {}) if isinstance(state, dict) else {}
    gm_pending = state.get("gm_pending", []) if isinstance(state, dict) else []
    lore_recent = state.get("lore_recent", []) if isinstance(state, dict) else []
    timeline_recent = state.get("timeline_recent", []) if isinstance(state, dict) else []
    rpg_log_tail = state.get("rpg_log_tail", []) if isinstance(state, dict) else []

    zones = world.get("zones") if isinstance(world, dict) else []
    hot_zone = "Crystal Mesh"
    if isinstance(zones, list):
        for entry in zones:
            if isinstance(entry, dict) and entry.get("heat") == "spawn":
                hot_zone = str(entry.get("name") or hot_zone)
                break
        else:
            for entry in zones:
                if isinstance(entry, dict) and entry.get("name"):
                    hot_zone = str(entry["name"])
                    break

    companions = []
    if isinstance(bridge, dict):
        raw_companions = bridge.get("companions", {})
        if isinstance(raw_companions, dict):
            companions = list(raw_companions.values())
            companions.sort(key=lambda item: str(item.get("last_seen") or ""), reverse=True)

    active_npcs = []
    if isinstance(npc_state, dict):
        for name, row in npc_state.items():
            if name.startswith("_") or not isinstance(row, dict):
                continue
            if row.get("connected"):
                active_npcs.append(
                    {
                        "name": name,
                        "level": row.get("level", "?"),
                        "hp": row.get("hp", "?"),
                        "location": row.get("location") or "?",
                        "action": row.get("action") or "idle",
                        "alive": row.get("alive", True),
                    }
                )

    # Fetch hiccup: keep showing the last known population instead of blanking to 0.
    if not ok and _LAST_BRIDGE_GOOD:
        if not active_npcs:
            active_npcs = _LAST_BRIDGE_GOOD.get("npc_active") or []
        if not companions:
            companions = _LAST_BRIDGE_GOOD.get("companions") or []

    result: dict[str, Any] = {
        "ok": ok,
        "health_ok": isinstance(health, dict) and bool(health.get("ok")),
        "error": state_error or health_error,
        "ts": state.get("ts") if isinstance(state, dict) else "",
        "era": world.get("era_id") or world.get("name") or "pre-meteor"
        if isinstance(world, dict)
        else "pre-meteor",
        "hot_zone": hot_zone,
        "npc_active": active_npcs,
        "npc_count": len(active_npcs),
        "players_total": (state.get("players_total", 0) if isinstance(state, dict) else 0)
        or (_LAST_BRIDGE_GOOD.get("players_total", 0) if not ok else 0),
        "battle": battle if isinstance(battle, dict) else {},
        "realm_event": state.get("realm_event") if isinstance(state, dict) else None,
        "gm_pending": gm_pending if isinstance(gm_pending, list) else [],
        "lore_recent": lore_recent if isinstance(lore_recent, list) else [],
        "timeline_recent": timeline_recent if isinstance(timeline_recent, list) else [],
        "rpg_log_tail": rpg_log_tail if isinstance(rpg_log_tail, list) else [],
        "bridge": bridge if isinstance(bridge, dict) else {},
        "companions": companions,
        "routes": bridge.get("persona_routes", {}) if isinstance(bridge, dict) else {},
    }
    if ok:
        _LAST_BRIDGE_GOOD = result
    return result


def bridge_events(snapshot: dict[str, Any], limit: int = 16) -> list[LcdEvent]:
    events: list[LcdEvent] = []
    now = time.time()
    if not snapshot.get("ok"):
        return [
            LcdEvent(
                source="ST",
                channel="bridge",
                nick="CrystalMesh",
                text="Bridge unavailable: " + short_text(snapshot.get("error"), 120),
                kind="status",
                canon="bridge",
                ts=now_iso(),
                sort_ts=now,
                priority=4,
                stale=True,
            )
        ]

    for idx, row in enumerate(snapshot.get("lore_recent", [])[-1:]):
        if not isinstance(row, dict):
            continue
        ts = str(row.get("ts") or row.get("created_at") or "")
        events.append(
            LcdEvent(
                source="ST",
                channel="bridge:lore",
                nick="lore",
                text=clip_sentence(row.get("text"), LCD_EVENT_TEXT_CLIP),
                kind="lore",
                canon="sillytavern",
                ts=ts,
                sort_ts=parse_iso_ts(ts) or (now - 3 + idx * 0.1),
                priority=2,
            )
        )

    bridge = snapshot.get("bridge") or {}
    raw_events = bridge.get("events", []) if isinstance(bridge, dict) else []
    if isinstance(raw_events, list):
        for idx, row in enumerate(raw_events[-1:]):
            if not isinstance(row, dict):
                continue
            ts = str(row.get("ts") or "")
            actor = row.get("character") or row.get("actor") or row.get("kind") or "bridge"
            bits = []
            for key in ("kind", "zone", "move", "target"):
                if row.get(key):
                    bits.append(str(row[key]))
            text = " | ".join(bits) or json.dumps(row, ensure_ascii=False)
            events.append(
                LcdEvent(
                    source="ST",
                    channel="bridge:event",
                    nick="bridge",
                    text=clip_sentence(text, LCD_EVENT_TEXT_CLIP),
                    kind=str(row.get("kind") or "bridge"),
                    canon="sillytavern",
                    ts=ts,
                    sort_ts=parse_iso_ts(ts) or (now - 2 + idx * 0.1),
                    priority=2,
                )
            )

    for idx, row in enumerate(snapshot.get("gm_pending", [])[-2:]):
        if not isinstance(row, dict):
            continue
        ts = str(row.get("ts") or row.get("created_at") or "")
        events.append(
            LcdEvent(
                source="GMQ",
                channel="#RPG",
                nick="gm",
                text=clip_sentence(row.get("message") or row.get("target") or row, LCD_EVENT_TEXT_CLIP),
                kind="gm_queue",
                canon="queued",
                ts=ts,
                sort_ts=parse_iso_ts(ts) or (now - 1 + idx * 0.1),
                priority=3,
            )
        )

    return sorted(events, key=lambda item: item.sort_ts)[-limit:]


class IrcTap:
    """Small read-only IRC listener used by the LCD for fresh LAN chatter."""

    def __init__(
        self,
        host: str = IRC_HOST,
        port: int = IRC_PORT,
        nick: str = IRC_NICK,
        channels: Iterable[str] = IRC_CHANNELS,
        max_events: int = 120,
    ) -> None:
        self.host = host
        self.port = port
        self.nick = nick
        self.channels = tuple(channels)
        self.events: deque[LcdEvent] = deque(maxlen=max_events)
        self.lock = threading.Lock()
        self.status = {"ok": False, "error": "", "last_seen": 0.0}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_forever, name="lcd-irc-tap", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def snapshot(self) -> tuple[list[LcdEvent], dict[str, Any]]:
        with self.lock:
            return list(self.events), dict(self.status)

    def _record(self, event: LcdEvent) -> None:
        with self.lock:
            self.events.append(event)
            self.status["last_seen"] = time.time()

    def _send(self, sock: socket.socket, line: str) -> None:
        sock.sendall((line + "\r\n").encode("utf-8", "replace"))

    def _run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                self._run_once()
            except OSError as exc:
                with self.lock:
                    self.status.update({"ok": False, "error": str(exc)[:120]})
            except Exception as exc:  # keep the LCD alive no matter what
                with self.lock:
                    self.status.update({"ok": False, "error": type(exc).__name__})
            self._stop.wait(5.0)

    def _run_once(self) -> None:
        with socket.create_connection((self.host, self.port), timeout=6) as sock:
            sock.settimeout(1.0)
            nick = self.nick
            self._send(sock, f"NICK {nick}")
            self._send(sock, f"USER {nick} 0 * :ZealPalace LCD ticker")
            buffer = ""
            registered = False
            with self.lock:
                self.status.update({"ok": True, "error": ""})
            while not self._stop.is_set():
                try:
                    chunk = sock.recv(8192)
                except socket.timeout:
                    continue
                if not chunk:
                    raise OSError("irc disconnected")
                buffer += chunk.decode("utf-8", "replace")
                lines = buffer.split("\r\n")
                buffer = lines.pop()
                for line in lines:
                    if line.startswith("PING"):
                        self._send(sock, "PONG " + line.split(" ", 1)[-1])
                        continue
                    if " 433 " in line:
                        nick += "_"
                        self._send(sock, f"NICK {nick}")
                        continue
                    if not registered and " 001 " in line:
                        registered = True
                        for channel in self.channels:
                            self._send(sock, "JOIN " + channel)
                        continue
                    event = parse_irc_protocol_line(line)
                    if event:
                        self._record(event)


def parse_irc_protocol_line(line: str) -> LcdEvent | None:
    if not line.startswith(":"):
        return None
    try:
        prefix, rest = line[1:].split(" ", 1)
    except ValueError:
        return None
    nick = prefix.split("!", 1)[0]
    parts = rest.split(" ")
    cmd = parts[0] if parts else ""
    now = time.time()
    if cmd == "PRIVMSG" and len(parts) >= 3:
        chan = parts[1]
        msg = " ".join(parts[2:]).lstrip(":")
        kind = "message"
        if msg.startswith("\x01ACTION") and msg.endswith("\x01"):
            kind = "action"
            msg = msg.replace("\x01ACTION", "", 1).strip("\x01 ").strip()
        source = {
            "#RPG": "RPG",
            "#ZealHangs": "ZH",
            "#ZealPalace": "ZP",
            "#pseudocorp": "PCORP",
        }.get(chan, "IRC")
        return LcdEvent(
            source=source,
            channel=chan,
            nick=short_text(nick, 24),
            text=clip_sentence(msg, LCD_EVENT_TEXT_CLIP),
            kind=kind,
            canon="irc",
            ts=now_iso(),
            sort_ts=now,
            priority=3 if chan in ("#RPG", "#pseudocorp") else 2,
        )
    if cmd in ("JOIN", "PART") and parts:
        chan = (parts[-1] if cmd == "JOIN" else parts[1] if len(parts) > 1 else "").lstrip(":")
        if nick.lower().startswith("lcd-ticker"):
            return None
        return LcdEvent(
            source="IRC",
            channel=chan,
            nick=short_text(nick, 24),
            text=f"{cmd.lower()} {chan}",
            kind="presence",
            canon="irc",
            ts=now_iso(),
            sort_ts=now,
            priority=0,
        )
    return None


def status_files() -> dict[str, Any]:
    try:
        from zealot_pbx_pull import ensure_pbx_phones_fresh

        ensure_pbx_phones_fresh()
    except Exception:
        pass
    telemetry = {
        "local": local_system_stats(),
        "remote": remote_telemetry(),
    }
    return {
        "noc": read_json(CACHE / "noc_mesh.json", {}),
        "pbx_phones": read_json(CACHE / "pbx_phones.json", {}),
        "navi": read_json(CACHE / "navi_ticker.json", {}),
        "agent_tickers": read_json(CACHE / "agent_tickers.json", {}),
        "lcd_heartbeat": read_heartbeat(),
        "telemetry": telemetry,
        "vector_ok": tcp_ok("10.13.37.60", 11434),
        "hermes_ok": tcp_ok("10.13.37.60", 8090),
        "pbx_api_ok": tcp_ok("10.13.37.37", 9101),
        "ce_api_ok": tcp_ok("10.13.37.37", 9104),
    }


def read_heartbeat() -> dict[str, Any]:
    path = CACHE / "lcd_heartbeat"
    try:
        raw = float(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return {"ok": False}
    return {"ok": True, "age_sec": int(time.time() - raw)}


def _event_norm_tokens(text: str) -> tuple[str, set[str]]:
    norm = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", str(text or "").lower())).strip()
    return norm, set(norm.split())


def dedupe_events(items: Iterable[LcdEvent], limit: int = 80) -> list[LcdEvent]:
    seen: set[tuple[str, str, str, str]] = set()
    content_seen: set[tuple[str, str]] = set()
    text_seen: set[str] = set()
    kept_norms: list[tuple[str, set[str]]] = []
    out: list[LcdEvent] = []
    for item in sorted(items, key=lambda ev: (ev.sort_ts, ev.priority)):
        key = item.key()
        if key in seen:
            continue
        norm, toks = _event_norm_tokens(item.text)
        # Same words from any nick/source/channel -> show once (kills tap+log double feed).
        if norm and len(norm) >= 12:
            if norm in text_seen:
                continue
            text_seen.add(norm)
        nick_l = str(getattr(item, "nick", "") or "").rstrip("_").lower()
        if norm:
            csig = (nick_l, norm)
            if csig in content_seen:
                continue
            content_seen.add(csig)
        # Collapse near-duplicate prose (e.g. "<keep> stands cold and silent"
        # repeated across hosts/personas). Conservative: long lines, high overlap.
        if len(norm) > 30 and toks:
            dup = False
            for prev_norm, prev_toks in kept_norms[-12:]:
                if norm == prev_norm or norm in prev_norm or prev_norm in norm:
                    dup = True
                    break
                union = len(toks | prev_toks)
                if union and (len(toks & prev_toks) / union) >= 0.72:
                    dup = True
                    break
            if dup:
                continue
            kept_norms.append((norm, toks))
        seen.add(key)
        out.append(item)
    return out[-limit:]


def event_is_recurring_noise(event: LcdEvent) -> bool:
    if event.stale:
        return True
    if event.kind == "presence":
        return True
    if feed_line_is_noise(event.nick, event.text):
        return True
    body = re.sub(r"\s+", " ", str(event.text or "")).strip().lower()
    if body.startswith("join #") or body.startswith("part #"):
        return True
    if event.kind == "status" and any(
        token in body
        for token in (
            "irc log stale",
            "irc log unavailable",
            "bridge unavailable",
            "using pi/direct feeds",
        )
    ):
        return True
    return False


def collect_snapshot(irc_tap: IrcTap | None = None, limit: int = 80) -> dict[str, Any]:
    global _CELES_STALE_WARN_TS
    direct_events: list[LcdEvent] = []
    direct_status: dict[str, Any] = {"ok": False, "error": "disabled"}
    if irc_tap:
        direct_events, direct_status = irc_tap.snapshot()

    c_events, c_status = celes_events(limit=limit)
    bridge = bridge_snapshot()
    b_events = bridge_events(bridge)
    local = local_events(limit=limit)
    statuses = status_files()

    source_events: list[LcdEvent] = []
    tap_ok = bool(direct_events) and bool(direct_status.get("ok"))
    if tap_ok:
        source_events.extend(direct_events)
    elif c_status.get("fresh"):
        source_events.extend(c_events)
    else:
        now_ts = time.time()
        if now_ts - _CELES_STALE_WARN_TS >= CELES_STALE_WARN_COOLDOWN_SEC:
            if c_status.get("ok") and c_status.get("latest_ts"):
                _CELES_STALE_WARN_TS = now_ts
                source_events.append(
                    LcdEvent(
                        source="SYS",
                        channel="celes",
                        nick="irc-log-api",
                        text=f"CELES IRC log stale since {c_status['latest_ts']}; using Pi/direct feeds",
                        kind="status",
                        canon="ops",
                        ts=now_iso(),
                        sort_ts=now_ts,
                        priority=4,
                        stale=True,
                    )
                )
            elif c_status.get("error"):
                _CELES_STALE_WARN_TS = now_ts
                source_events.append(
                    LcdEvent(
                        source="SYS",
                        channel="celes",
                        nick="irc-log-api",
                        text="CELES IRC log unavailable: " + short_text(c_status.get("error"), 120),
                        kind="status",
                        canon="ops",
                        ts=now_iso(),
                        sort_ts=now_ts,
                        priority=4,
                        stale=True,
                    )
                )
        source_events.extend(local)

    source_events.extend(b_events)

    events = [
        event
        for event in dedupe_events(source_events, limit=limit)
        if not event_is_recurring_noise(event)
    ]
    return {
        "ts": now_iso(),
        "events": events,
        "bridge": bridge,
        "status": statuses,
        "celes": c_status,
        "direct_irc": direct_status,
    }
