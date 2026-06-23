#!/usr/bin/env python3
"""ZealPalace terrarium heartbeat — GM pulse, sanity checks, lore compile, world rebuild.

Runs every few minutes via zealot-terrarium.timer. Keeps the digital terrarium
breathing: Ollama/NPC sanity, lore.md growth, realm event nudges, web mirror.
"""
from __future__ import annotations

import json
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

BIN = Path.home() / ".local/bin"
CACHE = Path.home() / ".cache" / "zealot"
HEARTBEAT = CACHE / "terrarium_heartbeat"
STATUS = CACHE / "terrarium_status.json"
GM_QUEUE = CACHE / "gm_queue.json"


def _load_rpg():
    sys.path.insert(0, str(BIN))
    import zealot_rpg as rpg  # noqa: WPS433

    return rpg


def ollama_reachable(url: str, timeout: float = 4.0) -> bool:
    try:
        req = urllib.request.Request(f"{url.rstrip('/')}/api/tags", method="HEAD")
        urllib.request.urlopen(req, timeout=timeout)
        return True
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def queue_gm_announce(text: str) -> None:
    row = {
        "id": f"terrarium-{int(time.time())}",
        "action": "announce",
        "message": text[:400],
        "ts": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "terrarium",
    }
    try:
        rows = json.loads(GM_QUEUE.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            rows = []
    except (OSError, json.JSONDecodeError, ValueError):
        rows = []
    rows.append(row)
    rows = rows[-40:]
    CACHE.mkdir(parents=True, exist_ok=True)
    GM_QUEUE.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def maybe_realm_pulse(rpg) -> str:
    """Occasionally nudge a realm event when the terrarium has been quiet."""
    if not rpg.is_ollama_up():
        return "ollama_down"
    if random.random() > 0.12:
        return "skip"
    try:
        evt = rpg.gen_realm_event_ollama()
        if not evt:
            return "no_event"
        try:
            rpg.append_lore_md(
                f"{evt.get('name', 'event').replace('_', ' ')}: {evt.get('description', '')}",
                topic="realm_event",
            )
        except Exception:
            pass
        queue_gm_announce(
            f"REALM PULSE: {evt.get('name', 'event').replace('_', ' ')} — {evt.get('description', '')[:200]}"
        )
        return "spawned"
    except Exception as exc:
        return f"err:{type(exc).__name__}"


def journal_freshness() -> dict:
    npc_dir = CACHE / "npc"
    out = {"files": 0, "stale_sec": None}
    if not npc_dir.is_dir():
        return out
    newest = 0.0
    count = 0
    for path in npc_dir.glob("*_journal.jsonl"):
        count += 1
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            pass
    out["files"] = count
    if newest:
        out["stale_sec"] = int(time.time() - newest)
    return out


def main() -> int:
    CACHE.mkdir(parents=True, exist_ok=True)
    rpg = _load_rpg()
    ollama_url = getattr(rpg, "OLLAMA", "http://127.0.0.1:11434")
    checks: dict = {
        "ts": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ollama_up": rpg.is_ollama_up(),
        "ollama_url": ollama_url,
        "ollama_tags": ollama_reachable(ollama_url),
        "journals": journal_freshness(),
    }

    try:
        rpg.compile_lore_md()
        checks["lore_md"] = True
    except Exception as exc:
        checks["lore_md"] = str(exc)

    try:
        rpg.rebuild_world_pages()
        checks["world_pages"] = True
    except Exception as exc:
        checks["world_pages"] = str(exc)

    checks["realm_pulse"] = maybe_realm_pulse(rpg)

    try:
        checks["party_blogs"] = rpg.nudge_party_blogs(limit=2)
    except Exception as exc:
        checks["party_blogs"] = str(exc)

    try:
        from zealot_world_pulse import tick_world_pulse
        checks["world_pulse"] = tick_world_pulse(spawn_chance=0.10)
    except Exception as exc:
        checks["world_pulse"] = str(exc)

    # Refresh soul.md for every known persona key
    souls = 0
    try:
        personas = getattr(rpg, "NPC_PERSONAS", {}) or {}
        for nick in list(personas.keys())[:32]:
            try:
                rpg.update_npc_soul_md(nick, personas[nick])
                souls += 1
            except Exception:
                pass
        checks["souls_refreshed"] = souls
    except Exception as exc:
        checks["souls_refreshed"] = str(exc)

    HEARTBEAT.write_text(str(time.time()), encoding="utf-8")
    STATUS.write_text(json.dumps(checks, indent=2), encoding="utf-8")
    print(json.dumps(checks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
