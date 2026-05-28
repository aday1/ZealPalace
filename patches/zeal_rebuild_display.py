#!/usr/bin/env python3
"""Rebuild zealot_display.py from clean backup and apply LCD patches safely."""
from __future__ import annotations

import re
import importlib.util
import py_compile
import shutil
import subprocess
import sys
import time
from pathlib import Path

BIN = Path.home() / ".local/bin"
DISPLAY = BIN / "zealot_display.py"
CLEAN_BACKUP = BIN / "zealot_display.py.bak.1779690877"
PATCH_DIR = Path("/tmp/zealpalace-patches")
if not PATCH_DIR.is_dir():
    PATCH_DIR = Path(__file__).resolve().parent

MODULES = (
    "zealot_sip_flash.py",
    "zealot_pbx_phones.py",
    "zealot_irc_tail.py",
    "zealot_noc_mesh.py",
)

PATCH_ORDER = (
    "zeal_patch_display_cycle.py",
    "zeal_patch_pbx_header.py",
    "zeal_patch_display_noc.py",
    "zeal_patch_display_router_flash.py",
    "zeal_patch_display_unstick.py",
)


def compiles(path: Path) -> bool:
    try:
        py_compile.compile(str(path), doraise=True)
        return True
    except py_compile.PyCompileError as exc:
        print("compile fail:", exc)
        return False


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
    text = text.replace(
        "    battle_flash = BattleFlash()\n        sip_flash = SipCallFlash(figlet_lines)",
        "    battle_flash = BattleFlash()\n    sip_flash = SipCallFlash(figlet_lines)",
    )
    text = text.replace("from zealot_pbx_phones import\n", "")
    text = text.replace("from zealot_sip_flash import\n", "")
    text = text.replace(
        "from zealot_pbx_phones import PbxPhoneStatusfrom zealot_noc_mesh import NocMeshStatus",
        "from zealot_pbx_phones import PbxPhoneStatus\nfrom zealot_noc_mesh import NocMeshStatus",
    )
    bad = """            pbx_phones.poll()
                noc_mesh.poll()
                poll_sip_call_flash(sip_flash)
                lcd_mode = _lcd_display_mode(sip_flash, pbx_phones, battle_flash, noc_mesh)"""
    good = """            pbx_phones.poll()
            noc_mesh.poll()
            poll_sip_call_flash(sip_flash)
            lcd_mode = _lcd_display_mode(sip_flash, pbx_phones, battle_flash, noc_mesh)"""
    return text.replace(bad, good)


def load_patch_display():
    path = PATCH_DIR / "zeal_apply_lcd_fixes.py"
    spec = importlib.util.spec_from_file_location("zeal_apply_lcd_fixes", path)
    if not spec or not spec.loader:
        raise RuntimeError("cannot load zeal_apply_lcd_fixes.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.patch_display


def restore_clean() -> None:
    if not CLEAN_BACKUP.is_file():
        raise SystemExit(f"missing clean backup: {CLEAN_BACKUP}")
    if DISPLAY.is_file():
        shutil.copy2(DISPLAY, DISPLAY.with_suffix(f".bak.rebuild.{int(time.time())}"))
    shutil.copy2(CLEAN_BACKUP, DISPLAY)
    print("restored", CLEAN_BACKUP.name)


def main() -> int:
    print("=== zeal_rebuild_display ===")
    restore_clean()

    for name in MODULES:
        src = PATCH_DIR / name
        if src.is_file():
            shutil.copy2(src, BIN / name)
            (BIN / name).chmod(0o755)

    patch_display = load_patch_display()
    text = scrub(patch_display(DISPLAY.read_text(encoding="utf-8", errors="replace")))
    DISPLAY.write_text(text, encoding="utf-8")
    print("applied base display patch")

    for name in PATCH_ORDER:
        script = PATCH_DIR / name
        if not script.is_file():
            print("skip missing", name)
            continue
        rc = subprocess.run([sys.executable, str(script)], check=False).returncode
        if rc:
            print("patch failed:", name)
            return rc

    cleaned = scrub(DISPLAY.read_text(encoding="utf-8", errors="replace"))
    if cleaned != DISPLAY.read_text(encoding="utf-8", errors="replace"):
        DISPLAY.write_text(cleaned, encoding="utf-8")
        print("scrubbed corruption")

    if not compiles(DISPLAY):
        print("rebuild failed compile check")
        return 1

    wd = PATCH_DIR / "zeal_lcd_watchdog.sh"
    if wd.is_file():
        shutil.copy2(wd, BIN / "zeal_lcd_watchdog.sh")
        (BIN / "zeal_lcd_watchdog.sh").chmod(0o755)

    subprocess.run(["pkill", "-f", "zealot_display.py"], check=False)
    time.sleep(0.5)
    lcd_init = BIN / "lcd-init"
    if lcd_init.is_file():
        subprocess.run([str(lcd_init)], check=False)
        time.sleep(2)
    wd_sh = BIN / "zeal_lcd_watchdog.sh"
    if wd_sh.is_file():
        subprocess.run([str(wd_sh)], check=False)

    if subprocess.run(["pgrep", "-f", "python3.*zealot_display"], check=False).returncode == 0:
        print("display running")
    else:
        print("WARN: display process not found after restart")
        return 2

    print("rebuild complete", DISPLAY)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
