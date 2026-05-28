#!/usr/bin/env python3
"""One-shot: fix known zealot_display.py corruption and restart LCD."""
from __future__ import annotations

import py_compile
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

DISPLAY = Path.home() / ".local/bin" / "zealot_display.py"
BIN = Path.home() / ".local/bin"
LCD_INIT = BIN / "lcd-init"


def compiles(path: Path) -> bool:
    try:
        py_compile.compile(str(path), doraise=True)
        return True
    except py_compile.PyCompileError:
        return False


def newest_compiling_backup() -> Path | None:
    for path in sorted(DISPLAY.parent.glob(f"{DISPLAY.name}.bak*"), key=lambda p: p.stat().st_mtime, reverse=True):
        if compiles(path):
            return path
    return None


def scrub(text: str) -> str:
    text = re.sub(
        r"^(\s*)head = prefix \+ heade\s*$",
        r"\1head = prefix + header",
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(
        r"^(\s*)head = prefix \+ header+r+\s*$",
        r"\1head = prefix + header",
        text,
        flags=re.MULTILINE,
    )
    text = text.replace("from zealot_pbx_phones import\n", "")
    text = text.replace("from zealot_sip_flash import\n", "")
    text = text.replace(
        "from zealot_pbx_phones import PbxPhoneStatusfrom zealot_noc_mesh import NocMeshStatus",
        "from zealot_pbx_phones import PbxPhoneStatus\nfrom zealot_noc_mesh import NocMeshStatus",
    )
    text = re.sub(
        r"def _lcd_display_mode\([^)]+\)\s+#",
        lambda m: m.group(0).replace(")  #", "):") if ":  #" not in m.group(0) else m.group(0),
        text,
        count=1,
    )
    text = text.replace(
        "def _lcd_display_mode(sip_flash, pbx_phones, battle_flash, noc_mesh)  #",
        "def _lcd_display_mode(sip_flash, pbx_phones, battle_flash, noc_mesh):  #",
    )
    text = text.replace(
        """            pbx_phones.poll()
                noc_mesh.poll()
                poll_sip_call_flash(sip_flash)
                lcd_mode = _lcd_display_mode(sip_flash, pbx_phones, battle_flash, noc_mesh)""",
        """            pbx_phones.poll()
            noc_mesh.poll()
            poll_sip_call_flash(sip_flash)
            lcd_mode = _lcd_display_mode(sip_flash, pbx_phones, battle_flash, noc_mesh)""",
    )
    text = text.replace(
        """            pbx_phones.poll()
                poll_sip_call_flash(sip_flash)
                lcd_mode = _lcd_display_mode(sip_flash, pbx_phones, battle_flash)""",
        """            pbx_phones.poll()
            poll_sip_call_flash(sip_flash)
            lcd_mode = _lcd_display_mode(sip_flash, pbx_phones, battle_flash)""",
    )
    if "from zealot_noc_mesh import NocMeshStatus" not in text:
        anchor = "from zealot_pbx_phones import PbxPhoneStatus"
        if anchor in text:
            text = text.replace(anchor, anchor + "\nfrom zealot_noc_mesh import NocMeshStatus", 1)
    if "noc_mesh = NocMeshStatus()" not in text and "pbx_phones = PbxPhoneStatus()" in text:
        text = text.replace(
            "pbx_phones = PbxPhoneStatus()",
            "pbx_phones = PbxPhoneStatus()\n    noc_mesh = NocMeshStatus()",
            1,
        )
    if "router_flashbang.hook" not in text and "stdscr.erase()" in text and "noc_mesh.poll()" in text:
        old = """            stdscr.erase()
            now = time.time()"""
        new = """            stdscr.erase()
            now = time.time()
            noc_mesh.poll()
            if noc_mesh.router_flashbang(stdscr):
                try:
                    stdscr.refresh()
                except Exception:
                    pass
                continue  # router_flashbang.hook"""
        if old in text:
            text = text.replace(old, new, 1)
    return text


def main() -> int:
    if not DISPLAY.is_file():
        print("missing", DISPLAY)
        return 1

    text = DISPLAY.read_text(encoding="utf-8", errors="replace")
    cleaned = scrub(text)
    if not compiles(DISPLAY) or cleaned != text:
        if not compiles(DISPLAY):
            backup = newest_compiling_backup()
            if backup:
                shutil.copy2(backup, DISPLAY)
                print("restored", backup.name)
                cleaned = scrub(DISPLAY.read_text(encoding="utf-8", errors="replace"))
        DISPLAY.write_text(cleaned, encoding="utf-8")
        print("scrubbed display")

    if not compiles(DISPLAY):
        print("still broken after scrub")
        return 1

    patch_dir = Path("/tmp/zealpalace-patches")
    if not patch_dir.is_dir():
        patch_dir = Path(__file__).resolve().parent
    noc_mesh = patch_dir / "zealot_noc_mesh.py"
    if noc_mesh.is_file():
        shutil.copy2(noc_mesh, BIN / "zealot_noc_mesh.py")

    subprocess.run(["pkill", "-f", "zealot_display.py"], check=False)
    time.sleep(0.5)
    if LCD_INIT.is_file():
        subprocess.run([str(LCD_INIT)], check=False)
    print("lcd restarted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
