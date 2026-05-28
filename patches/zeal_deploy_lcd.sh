#!/bin/bash
# Deploy LCD patches without re-running IRC wrap (safe refresh).
set -euo pipefail
PATCH_DIR="${1:-/tmp/zealpalace-patches}"
BIN="$HOME/.local/bin"
export PATH=/usr/bin:/bin:/usr/local/bin:$PATH
export TERM=linux
mkdir -p "$HOME/.cache/zealot"

for f in zealot_noc_mesh.py zealot_pbx_phones.py zealot_sip_flash.py; do
  [ -f "$PATCH_DIR/$f" ] && cp "$PATCH_DIR/$f" "$BIN/"
done

python3 "$PATCH_DIR/zeal_rebuild_display.py"
python3 -m py_compile "$BIN/zealot_display.py"
cp "$PATCH_DIR/zeal_lcd_watchdog.sh" "$BIN/"
chmod +x "$BIN/zeal_lcd_watchdog.sh"
"$BIN/zeal_lcd_watchdog.sh"
sleep 3
pgrep -af 'python3.*zealot_display' || "$BIN/lcd-init"
echo "lcd deploy done"
