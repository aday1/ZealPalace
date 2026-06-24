#!/bin/bash
# METEOR WIPE — fresh universe reset on the Pi
#   Default:  state, web, zealot cache, IRC/RPG logs, nginx/ngircd, journals
#   -genesis: also system logs, login history, bash history, /tmp deploy junk
set -e

GENESIS=false
if [[ "$1" == "-genesis" ]]; then
    GENESIS=true
fi

BIN="$HOME/.local/bin"
POST_METEOR_FLAG="/tmp/.zealot_post_meteor_boot_$(id -u)"
METEOR_WIPE_FLAG="/tmp/.zealot_meteor_wipe_in_progress"

run_lcd_anim() {
    local script="$1"
    local py="$BIN/$script"
    local log="/tmp/zealot_${script%.py}.log"
    [ -f "$py" ] || { echo "missing $py" >"$log"; return 0; }
    : >"$log"
    echo "start $(date -u +%FT%TZ) $script" >>"$log"
    export TERM=linux
    export PYTHONPATH="$BIN${PYTHONPATH:+:$PYTHONPATH}"

    sudo chvt 1 >>"$log" 2>&1 || true
    sudo setterm -term linux -clear all >/dev/tty1 2>>"$log" \
        || sudo sh -c 'printf "\033[2J\033[H\033[?25l" > /dev/tty1' 2>>"$log" \
        || true

    run_as_user() {
        if command -v runuser >/dev/null 2>&1; then
            runuser -u "$USER" -- "$@"
        else
            sudo -u "$USER" "$@"
        fi
    }

    # openvt -u is for init login-as-VT-owner — never combine with -c (openvt(1)).
    if command -v openvt >/dev/null 2>&1 && [ -e /dev/tty1 ]; then
        if sudo openvt -c 1 -s -f -- \
            run_as_user env TERM=linux COLUMNS=40 LINES=34 HOME="$HOME" USER="$USER" \
                PATH="$PATH" PYTHONPATH="$PYTHONPATH" \
                python3 "$py" >>"$log" 2>&1; then
            echo "openvt ok" >>"$log"
        else
            echo "openvt failed exit=$?" >>"$log"
            run_as_user env TERM=linux COLUMNS=40 LINES=34 PYTHONPATH="$PYTHONPATH" \
                python3 "$py" >>"$log" 2>&1 || true
        fi
    elif [ -z "${SSH_CONNECTION:-}" ] && [ "$(tty 2>/dev/null || echo)" = "/dev/tty1" ]; then
        run_as_user env TERM=linux COLUMNS=40 LINES=34 PYTHONPATH="$PYTHONPATH" \
            python3 "$py" >>"$log" 2>&1 || true
    else
        echo "no tty1 path" >>"$log"
    fi
    echo "done $(date -u +%FT%TZ)" >>"$log"
}

# Hold lcd-boot off tty1 until reboot (tmpfs cleared on reboot)
touch "$METEOR_WIPE_FLAG"

if $GENESIS; then
    STEPS=7
    echo 'METEOR STRIKE — GENESIS MODE'
    echo 'Factory wipe. System logs and history purged too.'
else
    STEPS=7
    echo 'METEOR STRIKE'
    echo 'Fresh start. State, web, and all service logs wiped.'
fi
echo ''

purge_service_logs() {
    sudo rm -f /var/log/nginx/access.log /var/log/nginx/error.log
    sudo rm -f /var/log/nginx/access.log.* /var/log/nginx/error.log.*
    sudo rm -f /var/log/ngircd.log /var/log/ngircd.log.*
    sudo rm -f /var/log/ollama*.log 2>/dev/null || true
    sudo touch /var/log/nginx/access.log /var/log/nginx/error.log 2>/dev/null || true
    sudo chown www-data:adm /var/log/nginx/access.log /var/log/nginx/error.log 2>/dev/null || true
}

# 1. Stop ALL services
echo "[1/$STEPS] Stopping all services..."
for svc in zealot-bot zealot-rpg zealot-hangs zealot-web-api zealot-admin zealot-blog.timer; do
    sudo systemctl stop "$svc" 2>/dev/null || true
done
tmux kill-session -t lcd 2>/dev/null || true
echo '  Services stopped.'

echo ''
echo 'METEOR IMPACT SEQUENCE (~10s on TFT)...'
run_lcd_anim boot_meteor.py
echo ''

# 2. Wipe ALL zealot cache (soul.json lives in ~/.local/bin — not touched)
echo "[2/$STEPS] Wiping zealot cache and logs..."
rm -rf ~/.cache/zealot
rm -f /tmp/zealot_display_err.log
rm -f /tmp/zealot_display.log
rm -rf /tmp/zeal_deploy /tmp/zeal_terrarium_deploy 2>/dev/null || true
echo '  Cache and local logs destroyed.'

# 3. Wipe ALL web content
echo "[3/$STEPS] Wiping all web content..."
sudo rm -rf /var/www/ZealPalace/world/*
sudo rm -rf /var/www/ZealPalace/tavern/*
sudo rm -rf /var/www/ZealPalace/cult/*
sudo rm -rf /var/www/ZealPalace/blog/*
sudo rm -rf /var/www/ZealPalace/npc/*/
echo '  Web content obliterated.'

# 4. Vacuum systemd journals
echo "[4/$STEPS] Vacuuming systemd journals..."
sudo journalctl --vacuum-time=1s 2>/dev/null || true
echo '  Journals vacuumed.'

# 5. Purge nginx / ngircd / ollama logs (every meteor strike)
echo "[5/$STEPS] Purging service logs..."
purge_service_logs
echo '  Service logs purged.'

# 6. Genesis-only: system-wide log scorched earth
if $GENESIS; then
    echo "[6/$STEPS] GENESIS: purging system logs and history..."
    sudo rm -f /var/log/syslog /var/log/syslog.*
    sudo rm -f /var/log/auth.log /var/log/auth.log.*
    sudo rm -f /var/log/daemon.log /var/log/daemon.log.*
    sudo rm -f /var/log/kern.log /var/log/kern.log.*
    sudo rm -f /var/log/messages /var/log/messages.*
    sudo rm -f /var/log/user.log /var/log/user.log.*
    sudo rm -f /var/log/dpkg.log /var/log/dpkg.log.*
    sudo rm -f /var/log/apt/history.log /var/log/apt/term.log
    sudo rm -f /var/log/apt/history.log.* /var/log/apt/term.log.*
    sudo truncate -s 0 /var/log/btmp 2>/dev/null || true
    sudo truncate -s 0 /var/log/wtmp 2>/dev/null || true
    sudo truncate -s 0 /var/log/lastlog 2>/dev/null || true
    sudo rm -f /var/log/fail2ban.log /var/log/fail2ban.log.*
    sudo rm -f /var/log/pihole.log /var/log/pihole-FTL.log 2>/dev/null || true
    rm -f ~/.bash_history
    rm -rf /tmp/meteor_wipe.sh /tmp/boot_plasma.py 2>/dev/null || true
    echo '  System logs and history purged.'
fi

# Recreate empty directory structure
STEP_DIRS=$( $GENESIS && echo 7 || echo 6 )
echo "[$STEP_DIRS/$STEPS] Recreating empty directories..."
mkdir -p ~/.cache/zealot/rpg
mkdir -p ~/.cache/zealot/npc
mkdir -p ~/.cache/zealot/guestbooks
mkdir -p ~/.cache/zealot/chat_in
sudo mkdir -p /var/www/ZealPalace/world
sudo mkdir -p /var/www/ZealPalace/tavern
sudo mkdir -p /var/www/ZealPalace/cult
sudo mkdir -p /var/www/ZealPalace/blog
sudo mkdir -p /var/www/ZealPalace/npc
sudo chown -R aday:aday /var/www/ZealPalace/ 2>/dev/null || true
echo '  Fresh directories created.'

# Verify clean slate
STEP_VERIFY=$STEPS
echo "[$STEP_VERIFY/$STEPS] Verifying clean slate..."
state_files=$(find ~/.cache/zealot/rpg/ ~/.cache/zealot/npc/ -name '*.json' -o -name '*.jsonl' 2>/dev/null | wc -l)
web_files=$(find /var/www/ZealPalace/world/ /var/www/ZealPalace/tavern/ /var/www/ZealPalace/cult/ /var/www/ZealPalace/blog/ -type f 2>/dev/null | wc -l)
cache_logs=$(find ~/.cache/zealot -name '*.log' -o -name '*.jsonl' 2>/dev/null | wc -l)
echo "  State files remaining: $state_files"
echo "  Web files remaining: $web_files"
echo "  Cache log files remaining: $cache_logs"

TIMESTAMP_FILE="$HOME/.cache/zealot/wipe_timestamps.json"
NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
if $GENESIS; then
    echo "{\"last_genesis\": \"$NOW\", \"last_meteor\": \"$NOW\"}" > "$TIMESTAMP_FILE"
else
    OLD_GENESIS=""
    if [ -f "$TIMESTAMP_FILE" ]; then
        OLD_GENESIS=$(python3 -c "import json; d=json.load(open('$TIMESTAMP_FILE')); print(d.get('last_genesis',''))" 2>/dev/null || echo "")
    fi
    if [ -n "$OLD_GENESIS" ]; then
        echo "{\"last_genesis\": \"$OLD_GENESIS\", \"last_meteor\": \"$NOW\"}" > "$TIMESTAMP_FILE"
    else
        echo "{\"last_genesis\": \"\", \"last_meteor\": \"$NOW\"}" > "$TIMESTAMP_FILE"
    fi
fi
echo "  Wipe timestamps recorded."

echo ''
echo 'GENESIS SEQUENCE (~10s on TFT)...'
run_lcd_anim boot_genesis.py
touch "$POST_METEOR_FLAG"
echo ''

echo ''
if $GENESIS; then
    echo 'GENESIS COMPLETE — factory clean. Reboot to begin era 0.'
else
    echo 'METEOR IMPACT COMPLETE — fresh universe. Reboot to begin.'
fi
