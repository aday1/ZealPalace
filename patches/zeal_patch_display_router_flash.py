#!/usr/bin/env python3
"""Patch zealot_display.py: full-screen B/W flashbangs when NIDHOGG (10.13.37.1) is down."""
from __future__ import annotations

import shutil
import time
from pathlib import Path

DISPLAY = Path.home() / ".local/bin" / "zealot_display.py"
MARKER = "router_flashbang.hook"

OLD = """            stdscr.erase()
            now = time.time()"""

NEW = """            stdscr.erase()
            now = time.time()
            noc_mesh.poll()
            if noc_mesh.router_flashbang(stdscr):
                try:
                    stdscr.refresh()
                except Exception:
                    pass
                time.sleep(0.08)
                continue  # """ + MARKER


def main() -> int:
    if not DISPLAY.is_file():
        print("missing", DISPLAY)
        return 1
    text = DISPLAY.read_text(encoding="utf-8", errors="replace")
    if MARKER in text:
        print("already patched router flash", DISPLAY)
        return 0
    if "noc_mesh = NocMeshStatus()" not in text:
        print("noc mesh init missing; run zeal_patch_display_noc.py first", DISPLAY)
        return 1
    if OLD not in text:
        print("erase anchor not found", DISPLAY)
        return 1
    shutil.copy2(DISPLAY, DISPLAY.with_suffix(f".bak.rflash.{int(time.time())}"))
    text = text.replace(OLD, NEW, 1)
    DISPLAY.write_text(text, encoding="utf-8")
    print("patched router flashbang", DISPLAY)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
