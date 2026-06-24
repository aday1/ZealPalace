#!/usr/bin/env python3
"""ZealPalace world pulse — mesh weather, world events, PBX/NOC memory, living lore.

Feeds IRC party RP, souls, journals, and lore from:
  - LAN / NOC telemetry (latency as weather, alerts as storms)
  - PBX call ledger + SIP transcripts
  - Scheduled world events (battles, tournaments, LAN parties, cyberspace)
"""
from __future__ import annotations

import json
import random
import time
from datetime import datetime
from pathlib import Path

CACHE = Path.home() / ".cache" / "zealot"
RPG_DIR = CACHE / "rpg"
NPC_DIR = CACHE / "npc"
STATE_FILE = CACHE / "world_pulse_state.json"
WORLD_EVENTS_FILE = RPG_DIR / "world_events.jsonl"
HUMANS_JOURNAL = NPC_DIR / "humans_channel.jsonl"
PBX_LEDGER = CACHE / "pbx_last_calls.json"
SIP_FLASH = CACHE / "sip_call_flash.json"
MESH_PULSE_PATHS = (
    Path("/var/cache/celes/network_pulse.json"),
    CACHE / "network_pulse.json",
)
CRYSTAL_PARTY_FILE = CACHE / "crystal-mesh-party.json"


def _rpg():
    import zealot_rpg as rpg  # noqa: WPS433

    return rpg


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _ext_party_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for path in (CRYSTAL_PARTY_FILE, Path(__file__).resolve().parent / "crystal-mesh-party.json"):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for row in data.get("companions") or []:
                ext = str(row.get("ext") or "").strip()
                nick = str(row.get("irc_nick") or "").strip()
                if ext and nick:
                    out[ext] = nick
        except (OSError, json.JSONDecodeError, ValueError):
            pass
    return out


WORLD_EVENT_CATALOG: dict[str, list[dict]] = {
    "weather": [
        {
            "title": "Mesh atmosphere shift",
            "prompt": "Describe a sudden shift in digital weather across a LAN mesh terrarium — latency, packet loss, or clear throughput as mood.",
            "system": "Cyberpunk filesystem realm weather narrator. One vivid sentence.",
            "duration": 3,
        },
    ],
    "battle": [
        {
            "title": "Colosseum clash",
            "prompt": "A spontaneous battle erupts in the Colosseum sector — corrupt processes spawn. Describe the opening clash.",
            "system": "Epic MMO battle herald on a homelab LAN. 2 short sentences.",
            "duration": 4,
            "monster_mod": 1.4,
        },
        {
            "title": "Raid on /proc",
            "prompt": "Adventurers launch a raid into the Hall of Processes. Describe the first wave of enemies.",
            "system": "LAN RPG battle narrator. 2 sentences.",
            "duration": 5,
            "monster_mod": 1.3,
        },
    ],
    "tournament": [
        {
            "title": "Uptime Tavern bracket",
            "prompt": "A tournament bracket is posted at the Uptime Tavern — NPCs and mesh agents sign up. Describe the hype.",
            "system": "Anime-fantasy MMO tournament announcer on IRC. 2 sentences.",
            "duration": 6,
        },
        {
            "title": "Crystal Mesh duel cup",
            "prompt": "The Crystal Mesh guild opens a duel cup — one-on-one IRC challenges at the guild hall.",
            "system": "Guild tournament crier. 2 sentences.",
            "duration": 5,
        },
    ],
    "lan_party": [
        {
            "title": "LAN party at the guild hall",
            "prompt": "A LAN party gathers in the Crystal Mesh guild hall — bots and humans share snacks, shaders, and gossip.",
            "system": "Warm homelab LAN party narrator. 2 sentences.",
            "duration": 4,
        },
        {
            "title": "Wire hangout",
            "prompt": "Mesh nodes throw an impromptu wire hangout — IRC, voice, and shared quests.",
            "system": "Chill LAN social narrator. 2 sentences.",
            "duration": 3,
        },
    ],
    "noc": [
        {
            "title": "NOC incident pulse",
            "prompt": "The PSEUDOCORP NOC war room lights up — probes flicker, dashboards scream. Describe the incident vibe.",
            "system": "NOC realm narrator translating ops alerts into fantasy. 2 sentences.",
            "duration": 4,
        },
        {
            "title": "Watchdog patrol",
            "prompt": "Hermes-warden patrols the mesh — something is degraded but not dead yet.",
            "system": "NOC guardian voice. 2 sentences.",
            "duration": 3,
        },
    ],
    "cyberspace": [
        {
            "title": "Cyberspace tear",
            "prompt": "A tear opens in cyberspace — packets leak between VLANs like aurora.",
            "system": "Surreal cyberspace event narrator. 2 sentences.",
            "duration": 3,
        },
        {
            "title": "Shader storm",
            "prompt": "A shader storm rolls through Vector Dreamforge — GPUs hum like distant thunder.",
            "system": "Digital art-ops narrator. 2 sentences.",
            "duration": 4,
        },
    ],
    "lore": [
        {
            "title": "Realm whisper",
            "prompt": "A lore fragment surfaces from the archives — old IRC logs become prophecy.",
            "system": "Lorekeeper narrator for a living terrarium. 2 sentences.",
            "duration": 5,
        },
    ],
    "pbx": [
        {
            "title": "SIP bell tolls",
            "prompt": "The SIP bell tower rings — a voice quest crosses from phone bridge into IRC memory.",
            "system": "PBX-to-IRC bridge narrator. 1-2 sentences.",
            "duration": 2,
        },
    ],
}


def read_mesh_pulse() -> dict | None:
    for path in MESH_PULSE_PATHS:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError, ValueError):
            pass
    return None


def append_world_event(category: str, title: str, body: str, source: str = "pulse", meta: dict | None = None) -> dict:
    RPG_DIR.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": datetime.now().isoformat(),
        "category": category,
        "title": title,
        "body": str(body or "")[:500],
        "source": source,
        "meta": meta or {},
    }
    with open(WORLD_EVENTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    return row


def load_recent_world_events(limit: int = 12, category: str | None = None) -> list[dict]:
    if not WORLD_EVENTS_FILE.is_file():
        return []
    try:
        lines = WORLD_EVENTS_FILE.read_text(encoding="utf-8").strip().split("\n")
    except OSError:
        return []
    out: list[dict] = []
    for line in lines[-limit * 3 :]:
        try:
            row = json.loads(line)
            if category and row.get("category") != category:
                continue
            out.append(row)
        except json.JSONDecodeError:
            pass
    return out[-limit:]


HOST_LOOP_KEYWORDS = (
    "jellyfin", "steamdeck", "steam deck", "zealtower", "navidrome", "immich",
)


def _blurb_part_ok(text: str) -> bool:
    low = str(text or "").lower()
    return not any(kw in low for kw in HOST_LOOP_KEYWORDS)


def world_context_blurb(limit: int = 4) -> str:
    """Weather + active realm event + recent pulses for LLM prompts."""
    rpg = _rpg()
    parts: list[str] = []
    try:
        w = rpg.load_weather()
        if w.get("description"):
            mesh = w.get("mesh") or {}
            rtt = mesh.get("rtt_ms")
            rtt_bit = f" RTT {rtt}ms." if rtt else ""
            parts.append(f"Weather ({w.get('type', '?')}): {w['description'][:100]}.{rtt_bit}")
    except Exception:
        pass
    try:
        ev = rpg.load_realm_event()
        if ev:
            parts.append(
                f"Active event {ev.get('name', '?').replace('_', ' ')}: {ev.get('description', '')[:100]}"
            )
    except Exception:
        pass
    try:
        evdata = rpg.load_events()
        for upcoming in (evdata.get("upcoming") or [])[:2]:
            parts.append(f"Upcoming {upcoming.get('type')}: {upcoming.get('name', '')[:80]}")
    except Exception:
        pass
    for row in load_recent_world_events(limit * 2):
        # Never feed NOC/PBX outage pulses into NPC narration prompts -- that made
        # every companion riff "host stands cold and silent" in unison.
        if row.get("category") in ("noc", "pbx"):
            continue
        bit = f"{row.get('category')}: {row.get('title')} — {row.get('body', '')[:70]}"
        if _blurb_part_ok(bit):
            parts.append(bit)
        if len(parts) >= limit + 3:
            break
    return " | ".join(parts[:limit])


def _broadcast_party_memory(category: str, body: str) -> None:
    # Do NOT fan outage/incident pulses out to every NPC -- that primed the whole
    # party to narrate the same "host stands cold and silent" doom in unison.
    if category in ("noc", "pbx"):
        return
    rpg = _rpg()
    try:
        rpg._ensure_crystal_mesh_party()
        snippet = f"[{category}] {str(body)[:160]}"
        for nick in list(rpg.NPC_PERSONAS.keys())[:20]:
            rpg.npc_journal(nick, "world", snippet)
    except Exception:
        pass


def record_channel_memory(
    nick: str,
    text: str,
    source: str = "irc",
    channel: str = "rpg",
    other: str | None = None,
) -> None:
    """Unified memory for IRC humans, bots, PBX, NOC — feeds souls and journals."""
    rpg = _rpg()
    nick = str(nick or "").strip()
    text = str(text or "").strip()
    if not nick or not text:
        return
    NPC_DIR.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": datetime.now().isoformat(),
        "nick": nick,
        "source": source,
        "channel": channel,
        "text": text[:300],
        "other": other,
    }
    try:
        with open(HUMANS_JOURNAL, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except OSError:
        pass
    persona = rpg.resolve_irc_persona(nick)
    if persona:
        rpg.npc_journal(nick, source, text[:200])
    p = rpg.load_player(nick)
    if p:
        rpg.append_player_history(nick, f"[{source}] {text[:120]}")
    if source in ("pbx", "noc", "world", "sip"):
        _broadcast_party_memory(source, text)


def sync_weather_from_mesh() -> dict | None:
    """Map LAN latency / alerts to realm weather (packet frost = cold day, etc.)."""
    pulse = read_mesh_pulse()
    if not pulse:
        return None
    rtt = float(
        pulse.get("wan_rtt_ms")
        or pulse.get("rtt_ms")
        or pulse.get("latency_ms")
        or pulse.get("wan", {}).get("rtt_ms")
        or 0
    )
    loss = float(pulse.get("packet_loss") or pulse.get("loss_pct") or 0)
    alerts = pulse.get("alerts") or pulse.get("prometheus_alerts") or pulse.get("firing") or []
    alert_n = len(alerts) if isinstance(alerts, list) else 0

    if alert_n > 0:
        wtype = "noc storm"
        desc = f"NOC alerts pulse across the mesh ({alert_n} firing) — routes flicker like heat lightning."
    elif rtt > 180 or loss > 8:
        wtype = "packet frost"
        desc = (
            f"A cold day on the wire — RTT {rtt:.0f}ms, loss {loss:.1f}%. "
            "Packets huddle for warmth between hops."
        )
    elif rtt > 90 or loss > 3:
        wtype = "signal drizzle"
        desc = f"Humid latency hangs over the LAN — RTT {rtt:.0f}ms, everything feels sluggish."
    elif rtt > 0 and rtt < 25 and loss < 1.5:
        wtype = "clear throughput"
        desc = "The mesh hums warm and fast; green routes glow on every map."
    else:
        return None

    weather = {
        "type": wtype,
        "description": desc,
        "since": datetime.now().isoformat(),
        "mesh": {"rtt_ms": rtt, "loss_pct": loss, "alerts": alert_n},
    }
    rpg = _rpg()
    rpg.save_weather(weather)
    append_world_event("weather", wtype.replace("_", " ").title(), desc, source="mesh", meta=weather.get("mesh"))
    return weather


def ingest_noc_pulse(announce=None) -> int:
    """Turn mesh NOC pulse into world events + party memory."""
    pulse = read_mesh_pulse()
    if not pulse:
        return 0
    state = _load_state()
    sig = json.dumps(
        {
            "alerts": pulse.get("alerts") or pulse.get("firing"),
            "rtt": pulse.get("wan_rtt_ms") or pulse.get("rtt_ms"),
            "ts": pulse.get("ts") or pulse.get("updated"),
        },
        sort_keys=True,
    )[:200]
    if state.get("last_noc_sig") == sig:
        return 0
    state["last_noc_sig"] = sig
    _save_state(state)

    alerts = pulse.get("alerts") or pulse.get("prometheus_alerts") or []
    if isinstance(alerts, list) and alerts:
        titles = []
        for a in alerts[:3]:
            if isinstance(a, dict):
                titles.append(str(a.get("name") or a.get("alertname") or a)[:40])
            else:
                titles.append(str(a)[:40])
        body = f"NOC pulse: {', '.join(titles)}"
        append_world_event("noc", "Mesh alert pulse", body, source="noc", meta={"alerts": titles})
        record_channel_memory("noc-watchdog", body, source="noc", channel="mesh")
        _broadcast_party_memory("noc", body)
        if announce:
            announce(f"NOC PULSE: {body[:200]}")
        return 1
    return 0


def ingest_pbx_signals(announce=None) -> int:
    """PBX call ledger + SIP flash -> world events + character memory."""
    state = _load_state()
    seen = set(state.get("pbx_seen_ids") or [])
    ext_map = _ext_party_map()
    rpg = _rpg()
    new = 0

    if PBX_LEDGER.is_file():
        try:
            raw = json.loads(PBX_LEDGER.read_text(encoding="utf-8"))
            calls = raw if isinstance(raw, list) else raw.get("calls") or raw.get("entries") or []
            for call in calls[-30:]:
                if not isinstance(call, dict):
                    continue
                cid = str(
                    call.get("id")
                    or call.get("call_id")
                    or f"{call.get('ext')}-{call.get('ended') or call.get('ts')}"
                )
                if cid in seen:
                    continue
                seen.add(cid)
                ext = str(call.get("ext") or call.get("extension") or "")
                agent = str(call.get("agent") or call.get("label") or call.get("name") or "")
                summary = str(
                    call.get("summary")
                    or call.get("last_line")
                    or call.get("snippet")
                    or call.get("subject")
                    or ""
                ).strip()
                if not summary and call.get("turns"):
                    turns = call.get("turns")
                    if isinstance(turns, list) and turns:
                        summary = str(turns[-1].get("text") or "")[:160]
                if not summary:
                    summary = f"call on ext {ext}"
                title = f"PBX {ext} {agent}".strip()
                append_world_event("pbx", title, summary, source="pbx", meta={"ext": ext, "id": cid})
                nick = ext_map.get(ext) or agent.split()[0] if agent else ""
                if nick:
                    record_channel_memory(nick, summary, source="pbx", channel="sip", other=ext)
                    try:
                        sp = rpg.resolve_irc_persona(nick)
                        if sp:
                            rpg.update_npc_soul_md(nick, sp)
                    except Exception:
                        pass
                else:
                    record_channel_memory(agent or f"ext{ext}", summary, source="pbx", channel="sip")
                new += 1
        except (OSError, json.JSONDecodeError, ValueError):
            pass

    if SIP_FLASH.is_file():
        try:
            flash = json.loads(SIP_FLASH.read_text(encoding="utf-8"))
            st = str(flash.get("state") or flash.get("status") or "").lower()
            if st in ("talking", "connected", "answered", "active", "ringing", "ring"):
                turns = flash.get("turns") or []
                if turns:
                    last = turns[-1]
                    line = str(last.get("text") or "")[:200]
                    label = str(last.get("label") or last.get("role") or "PBX")
                    sig = f"sip-{label}-{line[:80]}"
                    if sig not in seen and line:
                        seen.add(sig)
                        append_world_event("pbx", f"SIP {label}", line, source="sip", meta=flash.get("meta"))
                        record_channel_memory(label, line, source="sip", channel="voice")
                        new += 1
        except (OSError, json.JSONDecodeError, ValueError):
            pass

    state["pbx_seen_ids"] = list(seen)[-300:]
    _save_state(state)
    if new and announce:
        announce(f"PBX bridge: {new} voice moment(s) woven into realm memory.")
    return new


def _gen_event_body(prompt: str, system: str) -> str | None:
    rpg = _rpg()
    persona = {
        "model": rpg.DM_MODEL,
        "system": system or "ZealPalace world event narrator. Stay in-universe.",
    }
    return rpg.npc_gen(prompt, persona, maxn=100)


def spawn_world_event(category: str | None = None, announce=None) -> dict | None:
    """Spawn a generative world event — lore, timeline, realm modifiers, party memory."""
    rpg = _rpg()
    if not category:
        category = random.choice(
            ["battle", "tournament", "lan_party", "noc", "cyberspace", "lore", "weather"]
        )
    templates = WORLD_EVENT_CATALOG.get(category) or WORLD_EVENT_CATALOG["lore"]
    template = random.choice(templates)
    ctx = world_context_blurb(3)
    prompt = template["prompt"]
    if ctx:
        prompt += f" Context: {ctx}"
    body = _gen_event_body(prompt, template.get("system", ""))
    if not body:
        return None

    title = template["title"]
    row = append_world_event(category, title, body, source="terrarium", meta={"template": title})
    try:
        rpg.append_lore_md(f"{title}: {body}", topic=category)
        rpg.add_timeline_event(category, f"{title} — {body[:120]}", recorded_by="world_pulse")
    except Exception:
        pass

    duration = int(template.get("duration", 4))
    if category in ("battle", "noc", "cyberspace", "lan_party", "tournament"):
        try:
            event = {
                "name": f"{category}_{int(time.time())}",
                "category": category,
                "title": title,
                "description": body,
                "started": datetime.now().isoformat(),
                "duration": duration,
                "xp_mod": float(template.get("xp_mod", 1.1)),
                "monster_mod": float(template.get("monster_mod", 1.0)),
            }
            rpg.REALM_EVENT_FILE.write_text(json.dumps(event))
        except Exception:
            pass

    if category == "tournament":
        ev = rpg.load_events()
        ev.setdefault("upcoming", []).append(
            {
                "type": "tournament",
                "name": title,
                "scheduled": datetime.now().isoformat(),
                "description": body[:200],
            }
        )
        ev["upcoming"] = ev["upcoming"][-12:]
        rpg.save_events(ev)

    if category == "lan_party":
        ev = rpg.load_events()
        ev.setdefault("upcoming", []).append(
            {
                "type": "lan_party",
                "name": title,
                "scheduled": datetime.now().isoformat(),
                "description": body[:200],
            }
        )
        ev["upcoming"] = ev["upcoming"][-12:]
        rpg.save_events(ev)

    _broadcast_party_memory(category, body)
    if announce:
        icon = {
            "battle": "BATTLE",
            "tournament": "TOURNAMENT",
            "lan_party": "LAN PARTY",
            "noc": "NOC",
            "cyberspace": "CYBERSPACE",
            "weather": "WEATHER",
            "pbx": "PBX",
            "lore": "LORE",
        }.get(category, "EVENT")
        announce(f"{icon}: {title} — {body[:220]}")

    try:
        if random.random() < 0.25:
            rpg.compile_lore_md()
    except Exception:
        pass
    return row


def tick_world_pulse(announce=None, spawn_chance: float = 0.08) -> dict:
    """Heartbeat tick: mesh weather, PBX/NOC ingest, occasional world event."""
    out: dict = {"ts": datetime.now().isoformat()}
    try:
        w = sync_weather_from_mesh()
        out["weather_mesh"] = bool(w)
    except Exception as exc:
        out["weather_mesh"] = str(exc)
    try:
        out["noc_ingest"] = ingest_noc_pulse(announce=announce)
    except Exception as exc:
        out["noc_ingest"] = str(exc)
    try:
        out["pbx_ingest"] = ingest_pbx_signals(announce=announce)
    except Exception as exc:
        out["pbx_ingest"] = str(exc)
    if random.random() < spawn_chance:
        try:
            row = spawn_world_event(announce=announce)
            out["spawned"] = row.get("category") if row else "none"
        except Exception as exc:
            out["spawned"] = str(exc)
    else:
        out["spawned"] = "skip"
    return out
