#!/usr/bin/env python3
"""Patch zealot_display.py: row-0 title shows PBX LINE(S) ACTIVE during SIP calls."""
from __future__ import annotations

import shutil
import time
from pathlib import Path

DISPLAY = Path.home() / ".local/bin" / "zealot_display.py"
MARKER = "sip_flash.header_title"

OLD = """            else:
                title = '\\u2591\\u2592\\u2593 ZEALOT \\u2593\\u2592\\u2591'
            tx = max(0, (dw - len(title)) // 2)"""

NEW = """            elif lcd_mode == 'call' and sip_flash.active() and sip_flash.header_title(dw):
                title = sip_flash.header_title(dw)
            elif lcd_mode == 'phones':
                title = pbx_phones.header(dw)
            else:
                title = '\\u2591\\u2592\\u2593 ZEALOT \\u2593\\u2592\\u2591'
            tx = max(0, (dw - len(title)) // 2)"""


def main() -> int:
    if not DISPLAY.is_file():
        print("missing", DISPLAY)
        return 1
    text = DISPLAY.read_text(encoding="utf-8", errors="replace")
    if MARKER in text or "sip_flash.header_title(dw)" in text:
        print("already patched", DISPLAY)
        return 0
    if OLD not in text:
        print("pattern not found -- manual merge needed")
        return 1
    shutil.copy2(DISPLAY, DISPLAY.with_suffix(f".bak.{int(time.time())}"))
    DISPLAY.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
    print("patched", DISPLAY)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
