#!/usr/bin/env python3
"""Periodic lore / battle / realm animations on the ZealPalace TFT."""
from __future__ import annotations

import json
import random
import subprocess
import time
from pathlib import Path
from typing import Any

BIN = Path.home() / ".local/bin"
STATE_FILE = Path.home() / ".cache" / "zealot" / "lcd_lore_state.json"

MIN_RANDOM_SEC = 300.0   # 5 min
MAX_RANDOM_SEC = 900.0   # 15 min
COOLDOWN_SEC = 120.0
BATTLE_COOLDOWN_SEC = 600.0
REALM_COOLDOWN_SEC = 900.0

SCENES: dict[str, tuple[str, float]] = {
    "battle": ("boot_battle.py", 12.0),
    "realm": ("boot_realm.py", 12.0),
    "boss": ("boot_boss.py", 14.0),
    "meteor": ("boot_meteor.py", 10.0),
    "genesis": ("boot_genesis.py", 10.0),
    "portal": ("boot_portal.py", 8.0),
}
RANDOM_POOL = ("battle", "realm", "boss", "portal", "meteor", "genesis")


def _load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict[str, Any]) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError:
        pass


def play_tty_scene(scene_id: str) -> bool:
    script, _dur = SCENES.get(scene_id, SCENES["portal"])
    py = BIN / script
    if not py.is_file():
        return False
    cmd = (
        f"env TERM=linux COLUMNS=40 LINES=34 PYTHONPATH='{BIN}' "
        f"python3 '{py}' > /dev/tty1"
    )
    try:
        subprocess.run(
            ["sudo", "sh", "-c", cmd],
            timeout=SCENES.get(scene_id, ("", 20.0))[1] + 8.0,
            check=False,
        )
        return True
    except (subprocess.TimeoutExpired, OSError):
        return False


class LoreAnimScheduler:
    """Pick and play ambient lore animations on a jittered timer."""

    def __init__(self) -> None:
        state = _load_state()
        now = time.time()
        self.next_random = float(state.get("next_random") or (now + random.uniform(MIN_RANDOM_SEC, MAX_RANDOM_SEC)))
        self.cooldown_until = float(state.get("cooldown_until") or 0.0)
        self.last_battle_anim = float(state.get("last_battle_anim") or 0.0)
        self.last_realm_anim = float(state.get("last_realm_anim") or 0.0)
        self._last_battle_sig = str(state.get("last_battle_sig") or "")
        self._last_realm_sig = str(state.get("last_realm_sig") or "")
        self.playing = False

    def _persist(self) -> None:
        _save_state(
            {
                "next_random": self.next_random,
                "cooldown_until": self.cooldown_until,
                "last_battle_anim": self.last_battle_anim,
                "last_realm_anim": self.last_realm_anim,
                "last_battle_sig": self._last_battle_sig,
                "last_realm_sig": self._last_realm_sig,
            }
        )

    def _schedule_next(self, now: float) -> None:
        self.next_random = now + random.uniform(MIN_RANDOM_SEC, MAX_RANDOM_SEC)
        self.cooldown_until = now + COOLDOWN_SEC
        self._persist()

    def _battle_sig(self, bridge: dict[str, Any]) -> str:
        battle = bridge.get("battle") if isinstance(bridge, dict) else {}
        if not isinstance(battle, dict) or not battle.get("active"):
            return ""
        monster = battle.get("monster") or {}
        loc = battle.get("location") or "?"
        if isinstance(monster, dict):
            name = monster.get("name") or "?"
        else:
            name = str(monster)
        return f"{loc}:{name}:{battle.get('turn', 0)}"

    def _realm_sig(self, bridge: dict[str, Any]) -> str:
        evt = bridge.get("realm_event") if isinstance(bridge, dict) else None
        if not isinstance(evt, dict):
            return ""
        return str(evt.get("name") or evt.get("type") or evt.get("id") or "")

    def pick_scene(self, snapshot: dict[str, Any], now: float) -> str | None:
        if self.playing or now < self.cooldown_until:
            return None

        bridge = snapshot.get("bridge") or {}

        bsig = self._battle_sig(bridge)
        if bsig and bsig != self._last_battle_sig and now - self.last_battle_anim >= BATTLE_COOLDOWN_SEC:
            return "battle"

        rsig = self._realm_sig(bridge)
        if rsig and rsig != self._last_realm_sig and now - self.last_realm_anim >= REALM_COOLDOWN_SEC:
            return "realm"

        gm = bridge.get("gm_pending") if isinstance(bridge, dict) else []
        if isinstance(gm, list):
            for row in gm:
                if not isinstance(row, dict):
                    continue
                if row.get("action") == "realm_event":
                    target = str(row.get("target") or "").lower()
                    if "boss" in target:
                        return "boss"
                    if "meteor" in target:
                        return "meteor"
                    return "realm"

        if now >= self.next_random:
            return random.choice(RANDOM_POOL)

        return None

    def maybe_play(self, snapshot: dict[str, Any], now: float) -> bool:
        scene = self.pick_scene(snapshot, now)
        if not scene:
            return False

        self.playing = True
        bridge = snapshot.get("bridge") or {}
        bsig = self._battle_sig(bridge)
        rsig = self._realm_sig(bridge)

        ok = play_tty_scene(scene)
        self.playing = False

        if bsig:
            self.last_battle_anim = now
            self._last_battle_sig = bsig
        if rsig:
            self.last_realm_anim = now
            self._last_realm_sig = rsig

        self._schedule_next(now)
        return ok
