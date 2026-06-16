#!/bin/bash
# Run ON ZealPalace (10.13.37.76) as aday -- restart services after deploy
set -euo pipefail

PATCH_DIR="${1:-/tmp/zealpalace-patches}"
SOUL="$HOME/.cache/zealot/soul.json"

echo "=== ZealPalace post-deploy restart ==="

if [ -f "$PATCH_DIR/soul-prompts-patch.json" ] && [ -f "$SOUL" ]; then
  python3 - "$SOUL" "$PATCH_DIR/soul-prompts-patch.json" <<'PY'
import json, sys
from datetime import datetime
soul_path, patch_path = sys.argv[1], sys.argv[2]
with open(soul_path, encoding="utf-8") as f:
    soul = json.load(f)
with open(patch_path, encoding="utf-8") as f:
    patch = json.load(f)
for k, v in patch.get("prompts", {}).items():
    soul.setdefault("prompts", {})[k] = v
for k, v in patch.get("ollama", {}).get("models", {}).items():
    soul.setdefault("ollama", {}).setdefault("models", {})[k] = v
soul["last_modified"] = datetime.now().isoformat()
soul["modified_by"] = "zealpalace-patch"
with open(soul_path, "w", encoding="utf-8") as f:
    json.dump(soul, f, indent=2)
print("  merged soul.json")
PY
fi

sudo systemctl restart zealot-bot zealot-rpg zealot-hangs 2>/dev/null || true

for f in zealot_display.py lcd-init zealot_sip_flash.py zealot_pbx_phones.py zealot_irc_tail.py zealot_noc_mesh.py \
         zealot_lcd_feeds.py zealot_lcd_render.py zealot_navi_ticker.py zealot_wopr_lcd.py joshua_wopr_menu.py zealot_pbx_pull.py lcd_tmux_bar.py zealot_display_loop.sh; do
  [ -f "$PATCH_DIR/$f" ] && cp "$PATCH_DIR/$f" "$HOME/.local/bin/" && chmod +x "$HOME/.local/bin/$f"
done

if [ -f "$PATCH_DIR/zeal_lcd_watchdog.sh" ]; then
  bash "$PATCH_DIR/zeal_lcd_watchdog.sh" || true
fi

if [ -x "$HOME/.local/bin/lcd-init" ]; then
  pkill -f 'python3.*zealot_display.py' 2>/dev/null || true
  "$HOME/.local/bin/lcd-init" >/dev/null 2>&1 || true
fi

echo "=== done ==="
