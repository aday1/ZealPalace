#!/bin/bash
# ZealPalace LCD: kill undervoltage overlay + console spam. Run on the Pi as aday.
set -euo pipefail
export PATH=/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin

PATCH_DIR="${1:-/tmp/zealpalace-patches}"
BIN="$HOME/.local/bin"
INSTALL="$BIN/disable-pi-voltage-warnings.sh"
LCD_BOOT="$BIN/lcd-boot"
MARKER="zeal_voltage_quiet"

SRC="$PATCH_DIR/disable-pi-voltage-warnings.sh"
[ -f "$SRC" ] || SRC="/opt/voip/disable-pi-voltage-warnings.sh"
[ -f "$SRC" ] || { echo "missing disable-pi-voltage-warnings.sh" >&2; exit 1; }

mkdir -p "$BIN"
cp "$SRC" "$INSTALL"
chmod +x "$INSTALL"
sudo "$INSTALL"

FIX="$PATCH_DIR/zeal_fix_lcd_boot.py"
if [ -f "$FIX" ]; then
  python3 "$FIX"
elif [ -f "$PATCH_DIR/lcd-boot" ]; then
  cp "$PATCH_DIR/lcd-boot" "$LCD_BOOT"
  chmod +x "$LCD_BOOT"
  echo "installed lcd-boot from patch dir"
fi

echo "done -- reboot if config.txt or cmdline.txt changed"

UNIT=/etc/systemd/system/zeal-voltage-quiet.service
if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
  sudo tee "$UNIT" >/dev/null <<EOF
[Unit]
Description=Suppress Pi undervoltage framebuffer and console warnings
DefaultDependencies=no
After=local-fs.target
Before=getty.target

[Service]
Type=oneshot
ExecStart=$INSTALL
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
  sudo systemctl daemon-reload
  sudo systemctl enable zeal-voltage-quiet.service
  sudo systemctl start zeal-voltage-quiet.service
  echo "installed zeal-voltage-quiet.service"
fi
