#!/usr/bin/env python3
"""Fix LCD freeze: interleave idle animation, heartbeat file, lighter flash hook."""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

DISPLAY = Path.home() / ".local/bin" / "zealot_display.py"
MARKER = "lcd_cycle_v3"

NEW_MODE = """_LCD_CYCLE = ('phones', 'idle', 'phones', 'noc', 'idle')

def _lcd_display_mode(sip_flash, pbx_phones, battle_flash, noc_mesh):
    if sip_flash.active():
        return 'call'
    idx = int((time.time() - _lcd_cycle_t0) // 6) % len(_LCD_CYCLE)  # """ + MARKER + """
    mode = _LCD_CYCLE[idx]
    if mode == 'idle' and battle_flash.active():
        return 'battle'
    return mode
"""

MODE_RE = re.compile(
    r"(?:_LCD_CYCLE = .*?\n)?def _lcd_display_mode\(sip_flash, pbx_phones, battle_flash, noc_mesh\):.*?"
    r"(?=\n(?:def |from |sys\.path|os\.environ|# ─))",
    re.DOTALL,
)

OLD_FLASH_BLOCK = """            noc_mesh.poll()
            if noc_mesh.router_flashbang(stdscr):"""

NEW_FLASH_BLOCK = """            if noc_mesh.router_flashbang(stdscr):"""

LOOP_HEARTBEAT_OLD = """            now = time.time()
            if noc_mesh.router_flashbang(stdscr):"""

LOOP_HEARTBEAT_NEW = """            now = time.time()
            try:
                Path.home().joinpath('.cache/zealot/lcd_heartbeat').write_text(str(now))
            except Exception:
                pass
            if noc_mesh.router_flashbang(stdscr):"""

OLD_POLL = """            if now - _lcd_poll_t > 2.0:
                pbx_phones.poll()
                noc_mesh.poll()
                _lcd_poll_t = now"""

NEW_POLL = """            if now - _lcd_poll_t > 1.0:
                pbx_phones.poll()
                noc_mesh.poll()
                _lcd_poll_t = now"""

HEARTBEAT_ANCHOR = "            stdscr.refresh()"
HEARTBEAT_SNIP = """            stdscr.refresh()
            try:
                Path.home().joinpath('.cache/zealot/lcd_heartbeat').write_text(str(time.time()))
            except Exception:
                pass"""


def main() -> int:
    if not DISPLAY.is_file():
        print("missing", DISPLAY)
        return 1
    text = DISPLAY.read_text(encoding="utf-8", errors="replace")
    if MARKER not in text:
        shutil.copy2(DISPLAY, DISPLAY.with_suffix(f".bak.unstick.{int(time.time())}"))
    if not MODE_RE.search(text):
        print("mode block not found", DISPLAY)
        return 1
    text = MODE_RE.sub(NEW_MODE + "\n", text, count=1)
    if OLD_FLASH_BLOCK in text:
        text = text.replace(OLD_FLASH_BLOCK, NEW_FLASH_BLOCK, 1)
    elif LOOP_HEARTBEAT_OLD not in text and "router_flashbang(stdscr)" in text:
        text = text.replace(
            "            now = time.time()\n            if noc_mesh.router_flashbang(stdscr):",
            LOOP_HEARTBEAT_NEW,
            1,
        )
    if OLD_POLL in text:
        text = text.replace(OLD_POLL, NEW_POLL, 1)
    if "lcd_heartbeat" not in text and HEARTBEAT_ANCHOR in text:
        # last refresh in main loop (keep IRC sub-refreshes untouched)
        idx = text.rfind(HEARTBEAT_ANCHOR)
        if idx >= 0:
            text = text[:idx] + HEARTBEAT_SNIP + text[idx + len(HEARTBEAT_ANCHOR) :]
    if "_lcd_poll_t" not in text and "while True:" in text:
        text = text.replace("    while True:", "    _lcd_poll_t = 0.0\n\n    while True:", 1)
    DISPLAY.write_text(text, encoding="utf-8")
    print("patched lcd unstick", DISPLAY)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
