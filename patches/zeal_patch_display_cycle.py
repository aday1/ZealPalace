#!/usr/bin/env python3
"""Patch zealot_display.py: cycle PBX phones / animations / call flash; IRC tags; yellow SIP."""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

DISPLAY = Path.home() / ".local/bin" / "zealot_display.py"
MARKER = "pbx_phones.cycle_mode"

IMPORTS = """
sys.path.insert(0, str(Path.home() / ".local/bin"))
from zealot_sip_flash import SipCallFlash, poll_sip_call_flash
from zealot_pbx_phones import PbxPhoneStatus
from zealot_irc_tail import read_irc_tail, irc_line_tag
_lcd_cycle_t0 = time.time()

def _lcd_display_mode(sip_flash, pbx_phones, battle_flash):
    if sip_flash.active():
        return 'call'
    if int((time.time() - _lcd_cycle_t0) // 10) % 2 == 0:
        return 'phones'
    if battle_flash.active():
        return 'battle'
    return 'idle'
"""

INIT_PAIR = """    C_PBX = 9
    curses.init_pair(C_PBX, curses.COLOR_YELLOW, curses.COLOR_BLACK)
"""

INIT_MARKER = "curses.init_pair(C_MOOD"

SIP_INIT = """    sip_flash = SipCallFlash(figlet_lines)
    pbx_phones = PbxPhoneStatus()"""

OLD_READ = re.compile(r"def read_irc_tail\(.*?\n(?:    .*\n)+?    return.*?\n", re.DOTALL)

OLD_DRAW = """            if sip_flash.active():
                sip_flash.draw(stdscr, 2, dw, C_INFO, C_MOOD)
            elif battle_flash.active():"""

MODE_BLOCK = """            pbx_phones.poll()
            poll_sip_call_flash(sip_flash)
            lcd_mode = _lcd_display_mode(sip_flash, pbx_phones, battle_flash)
"""

NEW_DRAW = """            if lcd_mode == 'call':
                sip_flash.draw(stdscr, 2, dw, C_INFO, C_MOOD)
            elif lcd_mode == 'phones':
                pbx_phones.draw(stdscr, 2, dw, C_PBX)
            elif lcd_mode == 'battle' and battle_flash.active():
                battle_flash.draw(stdscr, 3, dw)"""

CLEAN_DRAW = """            # ─── Battle Flash Overlay (pyfiglet action words) ───
            if battle_flash.active():
                battle_flash.draw(stdscr, 3, dw)"""

CLEAN_NEW = """            # ─── Battle Flash Overlay (pyfiglet action words) ───
            if lcd_mode == 'call':
                sip_flash.draw(stdscr, 2, dw, C_INFO, C_MOOD)
            elif lcd_mode == 'phones':
                pbx_phones.draw(stdscr, 2, dw, C_PBX)
            elif lcd_mode == 'battle' and battle_flash.active():
                battle_flash.draw(stdscr, 3, dw)"""

TITLE_HOOK = "            # Overlay title centered (include theme name)"

OLD_TITLE = """            elif sip_flash.active() and sip_flash.header_title(dw):
                title = sip_flash.header_title(dw)"""

NEW_TITLE = """            elif lcd_mode == 'call' and sip_flash.header_title(dw):
                title = sip_flash.header_title(dw)
            elif lcd_mode == 'phones':
                title = pbx_phones.header(dw)"""

OLD_TAG = """        # ── Channel tag:"""

NEW_TAG = """        tag = irc_line_tag(line)
        if tag == '[PBX]':
            try:
                stdscr.addnstr(row, 0, line[:dw], dw, curses.color_pair(C_PBX) | curses.A_BOLD)
            except Exception:
                pass
            return
        if tag == '[ZP]':
            try:
                stdscr.addnstr(row, 0, line[:4], 4, curses.color_pair(C_INFO) | curses.A_BOLD)
            except Exception:
                pass
            col = 5
            rest = line[5:].lstrip()
        elif tag in ('[RPG]', '[ZH]'):
            try:
                stdscr.addnstr(row, 0, line[:5], 5, curses.color_pair(C_MOOD) | curses.A_BOLD)
            except Exception:
                pass
            col = 6
            rest = line[6:].lstrip()
        else:
            col = 0
            rest = line

        # ── Channel tag (legacy):"""


def main() -> int:
    if not DISPLAY.is_file():
        print("missing", DISPLAY)
        return 1
    text = DISPLAY.read_text(encoding="utf-8", errors="replace")
    if MARKER in text:
        print("already patched", DISPLAY)
        return 0
    shutil.copy2(DISPLAY, DISPLAY.with_suffix(f".bak.{int(time.time())}"))

    if "from zealot_pbx_phones import" not in text:
        anchor = "from zealot_sip_flash import SipCallFlash, poll_sip_call_flash"
        if anchor in text:
            text = text.replace(anchor, anchor + IMPORTS + anchor, 1)
        elif "from zealot_sip_flash import" in text:
            print("broken sip import line -- restore display backup first", DISPLAY)
            return 1
        elif "from pathlib import Path" in text:
            text = text.replace("from pathlib import Path\n", "from pathlib import Path\n" + IMPORTS, 1)
        else:
            text = IMPORTS + "\n" + text

    if "C_PBX" not in text and INIT_MARKER in text:
        text = text.replace(
            INIT_MARKER,
            INIT_PAIR.strip() + "\n    " + INIT_MARKER,
            1,
        )

    if "pbx_phones = PbxPhoneStatus()" not in text:
        if "    sip_flash = SipCallFlash(figlet_lines)" in text:
            text = text.replace(
                "    sip_flash = SipCallFlash(figlet_lines)",
                SIP_INIT,
                1,
            )
        elif "    battle_flash = BattleFlash()" in text and "sip_flash = SipCallFlash" not in text:
            text = text.replace(
                "    mood_flash = MoodFlash()\n"
                "    existential_flash = ExistentialFlash()\n"
                "    battle_flash = BattleFlash()",
                "    mood_flash = MoodFlash()\n"
                "    existential_flash = ExistentialFlash()\n"
                "    battle_flash = BattleFlash()\n"
                "    sip_flash = SipCallFlash(figlet_lines)\n"
                "    pbx_phones = PbxPhoneStatus()",
                1,
            )

    if "poll_sip_call_flash(sip_flash)" not in text and "battle_flash.check_battle(battle_cache)" in text:
        text = text.replace(
            "battle_flash.check_battle(battle_cache)",
            "battle_flash.check_battle(battle_cache)\n                poll_sip_call_flash(sip_flash)",
            1,
        )

    if "def read_irc_tail(" in text and "zealot_irc_tail import read_irc_tail" not in text:
        text = OLD_READ.sub("", text, count=1)

    if "lcd_mode = _lcd_display_mode" not in text and TITLE_HOOK in text:
        text = text.replace(TITLE_HOOK, MODE_BLOCK + TITLE_HOOK, 1)

    if OLD_DRAW in text:
        text = text.replace(OLD_DRAW, NEW_DRAW, 1)
    elif CLEAN_DRAW in text:
        text = text.replace(CLEAN_DRAW, CLEAN_NEW, 1)
    else:
        alt = """            if sip_flash.active():
                sip_flash.draw(stdscr, 2, dw, C_INFO, C_MOOD)
            elif battle_flash.active():"""
        if alt in text:
            text = text.replace(alt, NEW_DRAW, 1)
        else:
            print("draw block not found -- manual merge")
            return 1

    if OLD_TITLE in text:
        text = text.replace(OLD_TITLE, NEW_TITLE, 1)
    elif "sip_flash.header_title(dw)" in text:
        pass

    if OLD_TAG in text and "tag == '[PBX]'" not in text:
        text = text.replace(OLD_TAG, NEW_TAG, 1)

    if MARKER not in text:
        text = text.replace(
            "def _lcd_display_mode(sip_flash, pbx_phones, battle_flash):",
            "def _lcd_display_mode(sip_flash, pbx_phones, battle_flash):  # " + MARKER,
            1,
        )

    DISPLAY.write_text(text, encoding="utf-8")
    print("patched", DISPLAY)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
