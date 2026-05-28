#!/usr/bin/env python3
"""Restore broken zealot_display.py and re-apply LCD/NOC/router patches."""
from __future__ import annotations

import py_compile
import shutil
import subprocess
import sys
import time
from pathlib import Path

DISPLAY = Path.home() / ".local/bin" / "zealot_display.py"
PATCH_DIR = Path("/tmp/zealpalace-patches")
if not PATCH_DIR.is_dir():
    PATCH_DIR = Path(__file__).resolve().parent

PATCH_ORDER = (
    "zeal_patch_display_cycle.py",
    "zeal_patch_pbx_header.py",
    "zeal_patch_display_noc.py",
    "zeal_patch_display_router_flash.py",
)


def compiles(path: Path) -> bool:
    try:
        py_compile.compile(str(path), doraise=True)
        return True
    except py_compile.PyCompileError:
        return False


def newest_good_backup() -> Path | None:
    candidates = sorted(DISPLAY.parent.glob(f"{DISPLAY.name}.bak*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in candidates:
        if compiles(path):
            return path
    return None


def scrub_broken_imports(text: str) -> str:
    text = text.replace("from zealot_pbx_phones import\n", "")
    text = text.replace("from zealot_sip_flash import\n", "")
    text = text.replace(
        "from zealot_pbx_phones import PbxPhoneStatusfrom zealot_noc_mesh import NocMeshStatus",
        "from zealot_pbx_phones import PbxPhoneStatus\nfrom zealot_noc_mesh import NocMeshStatus",
    )
    return text


def fix_mode_poll_indent(text: str) -> str:
    bad = """            pbx_phones.poll()
                noc_mesh.poll()
                poll_sip_call_flash(sip_flash)
                lcd_mode = _lcd_display_mode(sip_flash, pbx_phones, battle_flash, noc_mesh)"""
    good = """            pbx_phones.poll()
            noc_mesh.poll()
            poll_sip_call_flash(sip_flash)
            lcd_mode = _lcd_display_mode(sip_flash, pbx_phones, battle_flash, noc_mesh)"""
    text = text.replace(bad, good)
    bad2 = """            pbx_phones.poll()
                poll_sip_call_flash(sip_flash)
                lcd_mode = _lcd_display_mode(sip_flash, pbx_phones, battle_flash)"""
    good2 = """            pbx_phones.poll()
            poll_sip_call_flash(sip_flash)
            lcd_mode = _lcd_display_mode(sip_flash, pbx_phones, battle_flash)"""
    return text.replace(bad2, good2)


def main() -> int:
    if not DISPLAY.is_file():
        print("missing", DISPLAY)
        return 1

    if not compiles(DISPLAY):
        backup = newest_good_backup()
        if not backup:
            print("display broken and no compiling backup found")
            return 1
        shutil.copy2(backup, DISPLAY)
        print("restored", backup.name)

    for name in (
        "zealot_sip_flash.py",
        "zealot_pbx_phones.py",
        "zealot_irc_tail.py",
        "zealot_noc_mesh.py",
    ):
        src = PATCH_DIR / name
        if src.exists():
            shutil.copy2(src, DISPLAY.parent / name)
            (DISPLAY.parent / name).chmod(0o755)

    for name in PATCH_ORDER:
        script = PATCH_DIR / name
        if not script.is_file():
            continue
        rc = subprocess.run([sys.executable, str(script)], check=False).returncode
        if rc:
            print("patch failed:", name)
            return rc

    cleaned = fix_mode_poll_indent(scrub_broken_imports(DISPLAY.read_text(encoding="utf-8", errors="replace")))
    if cleaned != DISPLAY.read_text(encoding="utf-8", errors="replace"):
        DISPLAY.write_text(cleaned, encoding="utf-8")
        print("scrubbed broken import lines")

    if not compiles(DISPLAY):
        print("display still broken after repair")
        return 1

    subprocess.run(["pkill", "-f", "zealot_display.py"], check=False)
    time.sleep(0.5)
    lcd_init = Path.home() / ".local/bin" / "lcd-init"
    if lcd_init.is_file():
        subprocess.run([str(lcd_init)], check=False)
    print("repair complete", DISPLAY)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
