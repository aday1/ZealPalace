#!/bin/bash
# deploy.sh - Deploy entire Zealot system to Zeal
# Run with: bash /tmp/zeal_deploy/deploy.sh
set -e

echo "=== ZEALOT SYSTEM DEPLOYMENT ==="
echo "================================"

DEPLOY_DIR="/tmp/zeal_deploy"
BIN_DIR="$HOME/.local/bin"
CACHE_DIR="$HOME/.cache/zealot"
WEB_DIR="/var/www/ZealPalace"
BLOG_DIR="$WEB_DIR/blog"

# ─── Fix line endings on all deployed files ─────
echo "[1/10] Fixing line endings..."
for f in "$DEPLOY_DIR"/*; do
    if file "$f" | grep -q text; then
        sed -i 's/\r$//' "$f"
    fi
done
echo "  Done."

# ─── Install packages ───────────────────────────
echo "[2/10] Installing ngircd + nginx..."
sudo apt-get update -qq
sudo apt-get install -y -qq ngircd nginx-light 2>/dev/null || sudo apt-get install -y -qq ngircd nginx
echo "  Done."

# ─── Stop services for safe deploy ──────────────
echo "[3/10] Stopping services..."
for svc in zealot-bot zealot-rpg zealot-hangs zealot-web-api zealot-admin ngircd nginx; do
    sudo systemctl stop "$svc" 2>/dev/null || true
done
tmux kill-session -t lcd 2>/dev/null || true
echo "  Done."

# ─── Create directories ─────────────────────────
echo "[4/10] Creating directories..."
mkdir -p "$BIN_DIR"
mkdir -p "$CACHE_DIR"
sudo mkdir -p "$WEB_DIR"
sudo mkdir -p "$BLOG_DIR"
sudo mkdir -p "$WEB_DIR/tavern"
sudo mkdir -p "$WEB_DIR/cult"
sudo mkdir -p "$WEB_DIR/world"
for npc in Pixel CHMOD n0va glitchgrl Lyric Riff Vendor Cleric Sybil Vex Index; do
    sudo mkdir -p "$WEB_DIR/npc/$npc"
done
sudo chown -R aday:aday "$WEB_DIR"
echo "  Done."

# ─── Deploy scripts to ~/.local/bin ─────────────
echo "[5/10] Deploying scripts..."
for script in zealot_bot.py zealot_display.py boot_plasma.py boot_meteor.py boot_genesis.py boot_anim_common.py zealot_blog.py \
             zealot_rpg.py zealot_hangs.py zealot_web_api.py zealot_admin.py \
             zealot_terrarium.py zealot_world_pulse.py zealot_sip_flash.py zealot_pbx_phones.py zealot_irc_tail.py zealot_noc_mesh.py \
             zealot_lcd_feeds.py zealot_lcd_render.py zealot_navi_ticker.py zealot_wopr_lcd.py \
             joshua_wopr_menu.py zealot_pbx_pull.py lcd_tmux_bar.py zealot_display_loop.sh \
             lcd-init lcd-boot meteor_wipe.sh; do
    if [ -f "$DEPLOY_DIR/$script" ]; then
        cp "$DEPLOY_DIR/$script" "$BIN_DIR/$script"
        chmod +x "$BIN_DIR/$script"
    fi
done
# Deploy soul.json to cache dir if not already present
if [ -f "$DEPLOY_DIR/soul.json" ] && [ ! -f "$CACHE_DIR/soul.json" ]; then
    cp "$DEPLOY_DIR/soul.json" "$CACHE_DIR/soul.json"
fi
if [ -f "$DEPLOY_DIR/crystal-mesh-party.json" ]; then
    cp "$DEPLOY_DIR/crystal-mesh-party.json" "$CACHE_DIR/crystal-mesh-party.json"
fi
echo "  Done."

# ─── Deploy bashrc ──────────────────────────────
echo "[6/10] Deploying bashrc + console font..."
cp "$HOME/.bashrc" "$HOME/.bashrc.bak.$(date +%s)" 2>/dev/null || true
cp "$DEPLOY_DIR/bashrc" "$HOME/.bashrc"
# Set console font for TFT density (8x14 Terminus = 40x34 on 320x480)
# Uni3 gives broader unicode coverage; regular weight reads cleaner than bold.
sudo sed -i 's/^FONTFACE=.*/FONTFACE="Terminus"/' /etc/default/console-setup
sudo sed -i 's/^FONTSIZE=.*/FONTSIZE="14"/' /etc/default/console-setup
# Apply font immediately on tty1
sudo setfont Uni3-Terminus14.psf.gz -C /dev/tty1 2>/dev/null \
  || sudo setfont Uni2-Terminus14.psf.gz -C /dev/tty1 2>/dev/null || true
echo "  Done."

# ─── Deploy ngircd config ───────────────────────
echo "[7/10] Configuring ngircd..."
sudo cp "$DEPLOY_DIR/ngircd.conf" /etc/ngircd/ngircd.conf
sudo cp "$DEPLOY_DIR/ngircd.motd" /etc/ngircd/ngircd.motd
sudo chown irc:irc /etc/ngircd/ngircd.conf /etc/ngircd/ngircd.motd
sudo chmod 640 /etc/ngircd/ngircd.conf
# Test config
if sudo ngircd --configtest 2>&1 | grep -qi error; then
    echo "  WARNING: ngircd config has errors:"
    sudo ngircd --configtest 2>&1
else
    echo "  ngircd config OK."
fi
echo "  Done."

# ─── Deploy nginx config ────────────────────────
echo "[8/10] Configuring nginx..."
sudo cp "$DEPLOY_DIR/zealpalace_nginx" /etc/nginx/sites-available/zealpalace
sudo ln -sf /etc/nginx/sites-available/zealpalace /etc/nginx/sites-enabled/zealpalace
sudo rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true
# Deploy web content (GitHub Pages canonical site/)
if [ -d "$DEPLOY_DIR/site" ]; then
  cp -r "$DEPLOY_DIR/site/"* "$WEB_DIR/"
fi
mkdir -p "$WEB_DIR/images"
for img in "$DEPLOY_DIR"/Docs/*.jpg "$DEPLOY_DIR"/Docs/*.png "$DEPLOY_DIR"/Docs/*.jpeg; do
  [ -f "$img" ] && cp "$img" "$WEB_DIR/images/"
done
cp "$DEPLOY_DIR/soul.md" "$WEB_DIR/soul.md"
# Test config
if sudo nginx -t 2>&1 | grep -qi 'test failed'; then
    echo "  WARNING: nginx config has errors:"
    sudo nginx -t 2>&1
else
    echo "  nginx config OK."
fi
echo "  Done."

# ─── Deploy systemd services ────────────────────
echo "[9/10] Setting up systemd services..."
for svcfile in zealot-bot.service zealot-blog.service zealot-blog.timer \
               zealot-rpg.service zealot-hangs.service zealot-web-api.service \
               zealot-admin.service zealot-terrarium.service zealot-terrarium.timer; do
    if [ -f "$DEPLOY_DIR/$svcfile" ]; then
        sudo cp "$DEPLOY_DIR/$svcfile" /etc/systemd/system/"$svcfile"
    fi
done
sudo systemctl daemon-reload
for svc in ngircd nginx zealot-bot zealot-rpg zealot-hangs zealot-web-api \
           zealot-admin zealot-blog.timer zealot-terrarium.timer; do
    sudo systemctl enable "$svc" 2>/dev/null || true
done
echo "  Done."

# ─── Start everything ───────────────────────────
echo "[10/10] Starting services..."
sudo systemctl start ngircd
sleep 1
sudo systemctl start nginx
sudo systemctl start zealot-web-api
sudo systemctl start zealot-admin
sleep 1
sudo systemctl start zealot-bot
sudo systemctl start zealot-rpg
sudo systemctl start zealot-hangs
sudo systemctl start zealot-blog.timer
echo "  Done."

# ─── Verify ─────────────────────────────────────
echo ""
echo "=== VERIFICATION ==="
for svc in ngircd nginx zealot-bot zealot-rpg zealot-hangs zealot-web-api \
           zealot-admin zealot-blog.timer zealot-terrarium.timer; do
    printf '  %-18s %s\n' "$svc:" "$(sudo systemctl is-active $svc)"
done

# Quick port check
echo ""
echo "=== PORT CHECK ==="
ss -tlnp 2>/dev/null | grep -E ':6667|:80' || netstat -tlnp 2>/dev/null | grep -E ':6667|:80' || echo "(ss/netstat not available)"

echo ""
echo "=== WEB CHECK ==="
curl -s -o /dev/null -w "HTTP %{http_code}" http://localhost/ 2>/dev/null || echo "curl not available"

echo ""
echo "=== IRC CHECK ==="
echo "NICK test_deploy" | timeout 3 nc -q1 localhost 6667 2>/dev/null | head -5 || echo "(nc check skipped)"

echo ""
echo "=== FILES DEPLOYED ==="
ls -la "$BIN_DIR"/zealot_* "$BIN_DIR"/boot_plasma.py "$BIN_DIR"/lcd-init "$BIN_DIR"/lcd-boot 2>/dev/null

echo ""
echo "=== DEPLOYMENT COMPLETE ==="
if [ -d "$DEPLOY_DIR/patches" ] && [ -f "$DEPLOY_DIR/patches/apply-on-zeal.sh" ]; then
  echo "[post] Applying patches/ (soul merge + LCD helpers)..."
  cp -r "$DEPLOY_DIR/patches" /tmp/zealpalace-patches
  bash /tmp/zealpalace-patches/apply-on-zeal.sh /tmp/zealpalace-patches || true
fi
echo "Reboot recommended: sudo reboot"
