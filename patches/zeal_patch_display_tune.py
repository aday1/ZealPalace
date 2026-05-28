#!/usr/bin/env python3
"""Tune ZealPalace LCD: more SIP/NOC screen time, smoother idle animations."""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

DISPLAY = Path.home() / ".local/bin" / "zealot_display.py"
MARKER = "lcd_cycle_v2"

NEW_MODE = """def _lcd_display_mode(sip_flash, pbx_phones, battle_flash, noc_mesh):
    if sip_flash.active():
        return 'call'
    slot = int((time.time() - _lcd_cycle_t0) // 8) % 5  # """ + MARKER + """
    if slot <= 2:
        return 'phones'
    if slot == 3:
        return 'noc'
    if battle_flash.active():
        return 'battle'
    return 'idle'
"""

MODE_RE = re.compile(
    r"def _lcd_display_mode\(sip_flash, pbx_phones, battle_flash, noc_mesh\):.*?"
    r"(?=\n(?:def |from |sys\.path|os\.environ|# ─))",
    re.DOTALL,
)

OLD_POLL = """            pbx_phones.poll()
            noc_mesh.poll()
            poll_sip_call_flash(sip_flash)
            lcd_mode = _lcd_display_mode(sip_flash, pbx_phones, battle_flash, noc_mesh)"""

NEW_POLL = """            if now - _lcd_poll_t > 2.0:
                pbx_phones.poll()
                noc_mesh.poll()
                _lcd_poll_t = now
            poll_sip_call_flash(sip_flash)
            lcd_mode = _lcd_display_mode(sip_flash, pbx_phones, battle_flash, noc_mesh)"""

OLD_FLASH = """            if noc_mesh.router_flashbang(stdscr):
                try:
                    stdscr.refresh()
                except Exception:
                    pass
                continue  # router_flashbang.hook"""

NEW_FLASH = """            if noc_mesh.router_flashbang(stdscr):
                try:
                    stdscr.refresh()
                except Exception:
                    pass
                time.sleep(0.08)
                continue  # router_flashbang.hook"""


def main() -> int:
    if not DISPLAY.is_file():
        print("missing", DISPLAY)
        return 1
    text = DISPLAY.read_text(encoding="utf-8", errors="replace")
    if MARKER not in text:
        shutil.copy2(DISPLAY, DISPLAY.with_suffix(f".bak.tune.{int(time.time())}"))
    if not MODE_RE.search(text):
        print("lcd_display_mode block not found", DISPLAY)
        return 1
    text = MODE_RE.sub(NEW_MODE + "\n", text, count=1)
    if "_lcd_poll_t" not in text and "while True:" in text:
        text = text.replace("    while True:", "    _lcd_poll_t = 0.0\n\n    while True:", 1)
    if OLD_POLL in text:
        text = text.replace(OLD_POLL, NEW_POLL, 1)
    elif "if now - _lcd_poll_t" not in text and "lcd_mode = _lcd_display_mode" in text:
        print("poll block anchor missing", DISPLAY)
        return 1
    if OLD_FLASH in text:
        text = text.replace(OLD_FLASH, NEW_FLASH, 1)
    text = text.replace("'loop_tick_ms': 200,", "'loop_tick_ms': 120,")
    DISPLAY.write_text(text, encoding="utf-8")
    print("patched lcd tune", DISPLAY)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
