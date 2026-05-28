#!/usr/bin/env python3
"""Patch zealot_display.py: NOC mesh screen (green 1 / flashing X offline / yellow 0 / WAN-X flash)."""
from __future__ import annotations

import shutil
import time
from pathlib import Path

DISPLAY = Path.home() / ".local/bin" / "zealot_display.py"
MARKER = "noc_mesh.cycle_mode"

IMPORTS = """
from zealot_noc_mesh import NocMeshStatus
"""

OLD_MODE = """def _lcd_display_mode(sip_flash, pbx_phones, battle_flash):
    if sip_flash.active():
        return 'call'
    if int((time.time() - _lcd_cycle_t0) // 10) % 2 == 0:
        return 'phones'
    if battle_flash.active():
        return 'battle'
    return 'idle'"""

NEW_MODE = """def _lcd_display_mode(sip_flash, pbx_phones, battle_flash, noc_mesh):
    if sip_flash.active():
        return 'call'
    slot = int((time.time() - _lcd_cycle_t0) // 8) % 5
    if slot <= 2:
        return 'phones'
    if slot == 3:
        return 'noc'
    if battle_flash.active():
        return 'battle'
    return 'idle'"""

INIT_PAIR = """    C_NOC_OK = 10
    C_NOC_WARN = 11
    C_NOC_BAD = 12
    curses.init_pair(C_NOC_OK, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(C_NOC_WARN, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    curses.init_pair(C_NOC_BAD, curses.COLOR_RED, curses.COLOR_BLACK)
"""

INIT_ANCHOR = "curses.init_pair(C_PBX"

SIP_INIT = """    sip_flash = SipCallFlash(figlet_lines)
    pbx_phones = PbxPhoneStatus()
    noc_mesh = NocMeshStatus()"""

OLD_SIP_INIT = """    sip_flash = SipCallFlash(figlet_lines)
    pbx_phones = PbxPhoneStatus()"""

MODE_POLL = """            pbx_phones.poll()
            noc_mesh.poll()
            poll_sip_call_flash(sip_flash)
            lcd_mode = _lcd_display_mode(sip_flash, pbx_phones, battle_flash, noc_mesh)"""

OLD_MODE_POLL = """            pbx_phones.poll()
            poll_sip_call_flash(sip_flash)
            lcd_mode = _lcd_display_mode(sip_flash, pbx_phones, battle_flash)"""

DRAW_PHONES = """            elif lcd_mode == 'phones':
                pbx_phones.draw(stdscr, 2, dw, C_PBX)"""

NEW_DRAW = """            elif lcd_mode == 'phones':
                pbx_phones.draw(stdscr, 2, dw, C_PBX)
            elif lcd_mode == 'noc':
                noc_mesh.draw(stdscr, 2, dw, C_NOC_OK, C_NOC_WARN, C_NOC_BAD)"""

TITLE_PHONES = """            elif lcd_mode == 'phones':
                title = pbx_phones.header(dw)"""

NEW_TITLE = """            elif lcd_mode == 'phones':
                title = pbx_phones.header(dw)
            elif lcd_mode == 'noc':
                title = noc_mesh.header(dw)"""


def main() -> int:
    if not DISPLAY.is_file():
        print("missing", DISPLAY)
        return 1
    text = DISPLAY.read_text(encoding="utf-8", errors="replace")
    if MARKER in text:
        print("already patched noc", DISPLAY)
        return 0
    shutil.copy2(DISPLAY, DISPLAY.with_suffix(f".bak.noc.{int(time.time())}"))

    if "from zealot_noc_mesh import" not in text:
        anchor = "from zealot_pbx_phones import PbxPhoneStatus"
        if anchor in text:
            text = text.replace(anchor, anchor + "\n" + IMPORTS.strip(), 1)
        elif "from pathlib import Path" in text:
            text = text.replace("from pathlib import Path\n", "from pathlib import Path\n" + IMPORTS, 1)
        else:
            text = IMPORTS + text

    if "C_NOC_OK" not in text and INIT_ANCHOR in text:
        text = text.replace(INIT_ANCHOR, INIT_PAIR.strip() + "\n    " + INIT_ANCHOR, 1)

    if "noc_mesh = NocMeshStatus()" not in text:
        if OLD_SIP_INIT in text:
            text = text.replace(OLD_SIP_INIT, SIP_INIT, 1)
        elif "pbx_phones = PbxPhoneStatus()" in text:
            text = text.replace(
                "pbx_phones = PbxPhoneStatus()",
                "pbx_phones = PbxPhoneStatus()\n    noc_mesh = NocMeshStatus()",
                1,
            )

    if OLD_MODE in text:
        text = text.replace(OLD_MODE, NEW_MODE + "  # " + MARKER, 1)
    elif "def _lcd_display_mode(sip_flash, pbx_phones, battle_flash):" in text:
        text = text.replace(
            "def _lcd_display_mode(sip_flash, pbx_phones, battle_flash):",
            NEW_MODE + "  # " + MARKER,
            1,
        )

    if OLD_MODE_POLL in text:
        text = text.replace(OLD_MODE_POLL, MODE_POLL, 1)

    if DRAW_PHONES in text and "lcd_mode == 'noc'" not in text:
        text = text.replace(DRAW_PHONES, NEW_DRAW, 1)

    if TITLE_PHONES in text and "noc_mesh.header" not in text:
        text = text.replace(TITLE_PHONES, NEW_TITLE, 1)

    DISPLAY.write_text(text, encoding="utf-8")
    print("patched noc mesh", DISPLAY)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
