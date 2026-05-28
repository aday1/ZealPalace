#!/usr/bin/env python3
"""Install a known-good lcd-boot (fixes broken fi stripping from earlier patch)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

BIN = Path.home() / ".local/bin"
LCD_BOOT = BIN / "lcd-boot"
PATCH_DIR = Path("/tmp/zealpalace-patches")
if not PATCH_DIR.is_dir():
    PATCH_DIR = Path(__file__).resolve().parent
SOURCE = PATCH_DIR / "lcd-boot"


def main() -> int:
    if not SOURCE.is_file():
        print("missing", SOURCE)
        return 1
    BIN.mkdir(parents=True, exist_ok=True)
    if LCD_BOOT.is_file():
        shutil.copy2(LCD_BOOT, LCD_BOOT.with_suffix(".bak.broken"))
    shutil.copy2(SOURCE, LCD_BOOT)
    LCD_BOOT.chmod(0o755)
    rc = subprocess.run(["bash", "-n", str(LCD_BOOT)], check=False).returncode
    if rc:
        print("bash -n failed on", LCD_BOOT)
        return rc
    print("installed", LCD_BOOT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
