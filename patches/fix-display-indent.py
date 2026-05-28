#!/usr/bin/env python3
from pathlib import Path
import py_compile

p = Path.home() / ".local/bin/zealot_display.py"
t = p.read_text(encoding="utf-8")
old = """                # Check for battle round changes → trigger battle flash
                poll_sip_call_flash(sip_flash)
            battle_flash.check_battle(battle_cache)
                # Check for existential crisis in any NPC
                for npc_name, npc_data in npc_cache.items():"""
new = """                # Check for battle round changes → trigger battle flash
                battle_flash.check_battle(battle_cache)
                poll_sip_call_flash(sip_flash)
                # Check for existential crisis in any NPC
                for npc_name, npc_data in npc_cache.items():"""
if old not in t:
    raise SystemExit("pattern not found")
p.write_text(t.replace(old, new, 1), encoding="utf-8")
py_compile.compile(str(p), doraise=True)
print("fixed OK")
