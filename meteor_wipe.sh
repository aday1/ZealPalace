#!/bin/bash
# ═══════════════════════════════════════════════════════
# METEOR WIPE — Universe reset script
#   Default:  Wipes game state + web content (soft reset)
#   -genesis: FACTORY WIPE — scorched earth, all logs,
#             all caches, all history. Nothing survives.
# ═══════════════════════════════════════════════════════
set -e

GENESIS=false
if [[ "$1" == "-genesis" ]]; then
    GENESIS=true
fi

if $GENESIS; then
    STEPS=7
    echo '☄️ ☄️ ☄️  METEOR STRIKE — GENESIS MODE  ☄️ ☄️ ☄️'
    echo 'FACTORY WIPE. All logs. All state. All history. Nothing survives.'
else
    STEPS=6
    echo '☄️ ☄️ ☄️  METEOR STRIKE  ☄️ ☄️ ☄️'
    echo 'Universe reset. Game state wiped, logs preserved.'
fi
echo ''

# 1. Stop ALL services
echo "[1/$STEPS] Stopping all services..."
for svc in zealot-bot zealot-rpg zealot-hangs zealot-web-api zealot-admin zealot-blog.timer; do
    sudo systemctl stop "$svc" 2>/dev/null || true
done
# Kill LCD display
tmux kill-session -t lcd 2>/dev/null || true
echo '  Services stopped.'

# 2. Wipe ALL state data (entire ~/.cache/zealot)
echo "[2/$STEPS] Wiping all state data..."
rm -f ~/.cache/zealot/state.json
rm -f ~/.cache/zealot/journal.jsonl
rm -f ~/.cache/zealot/irc.log
rm -f ~/.cache/zealot/hangs.log
rm -f ~/.cache/zealot/rpg.log
rm -f ~/.cache/zealot/hangs_state.json
rm -f ~/.cache/zealot/gm_queue.json
rm -f ~/.cache/zealot/gm_results.json
# Wipe ALL rpg data — including era.json (no history preserved)
rm -rf ~/.cache/zealot/rpg/
# Wipe ALL npc data
rm -rf ~/.cache/zealot/npc/
# Wipe guestbooks and chat input
rm -rf ~/.cache/zealot/guestbooks
rm -rf ~/.cache/zealot/chat_in
# NOTE: soul.json is NOT deleted — personality config is preserved
echo '  State data destroyed.'

# 3. Wipe ALL web content
echo "[3/$STEPS] Wiping all web content..."
sudo rm -rf /var/www/ZealPalace/world/*
sudo rm -rf /var/www/ZealPalace/tavern/*
sudo rm -rf /var/www/ZealPalace/cult/*
sudo rm -rf /var/www/ZealPalace/blog/*
sudo rm -rf /var/www/ZealPalace/npc/*/
echo '  Web content obliterated.'

# 4. Vacuum system journals
echo "[4/$STEPS] Vacuuming system journals..."
sudo journalctl --vacuum-time=1s 2>/dev/null || true
echo '  Journals vacuumed.'

# ── Genesis-only: nuke ALL logs ──
if $GENESIS; then
    echo "[5/$STEPS] GENESIS: Purging ALL logs..."
    # nginx access/error logs
    sudo rm -f /var/log/nginx/access.log /var/log/nginx/error.log
    sudo rm -f /var/log/nginx/access.log.* /var/log/nginx/error.log.*
    # ngircd logs
    sudo rm -f /var/log/ngircd.log /var/log/ngircd.log.*
    # syslog, auth, daemon, kern, messages
    sudo rm -f /var/log/syslog /var/log/syslog.*
    sudo rm -f /var/log/auth.log /var/log/auth.log.*
    sudo rm -f /var/log/daemon.log /var/log/daemon.log.*
    sudo rm -f /var/log/kern.log /var/log/kern.log.*
    sudo rm -f /var/log/messages /var/log/messages.*
    sudo rm -f /var/log/user.log /var/log/user.log.*
    # dpkg/apt logs
    sudo rm -f /var/log/dpkg.log /var/log/dpkg.log.*
    sudo rm -f /var/log/apt/history.log /var/log/apt/term.log
    sudo rm -f /var/log/apt/history.log.* /var/log/apt/term.log.*
    # btmp/wtmp/lastlog (login history)
    sudo truncate -s 0 /var/log/btmp 2>/dev/null || true
    sudo truncate -s 0 /var/log/wtmp 2>/dev/null || true
    sudo truncate -s 0 /var/log/lastlog 2>/dev/null || true
    # fail2ban
    sudo rm -f /var/log/fail2ban.log /var/log/fail2ban.log.*
    # pihole if present
    sudo rm -f /var/log/pihole.log /var/log/pihole-FTL.log 2>/dev/null || true
    # ollamad / any zealot-specific logs left over
    sudo rm -f /var/log/ollama*.log 2>/dev/null || true
    # bash history
    rm -f ~/.bash_history
    # tmp cleanup
    rm -rf /tmp/zeal_deploy/ /tmp/meteor_wipe.sh /tmp/boot_plasma.py 2>/dev/null || true
    echo '  All logs purged. Factory clean.'
fi

# Recreate empty directory structure
STEP_DIRS=$( $GENESIS && echo 6 || echo 5 )
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
if $GENESIS; then
    # Recreate log files so services don't complain
    sudo touch /var/log/nginx/access.log /var/log/nginx/error.log
    sudo chown www-data:adm /var/log/nginx/access.log /var/log/nginx/error.log 2>/dev/null || true
fi
echo '  Fresh directories created.'

# Verify clean slate
STEP_VERIFY=$( $GENESIS && echo 7 || echo 6 )
echo "[$STEP_VERIFY/$STEPS] Verifying clean slate..."
state_files=$(find ~/.cache/zealot/rpg/ ~/.cache/zealot/npc/ -name '*.json' -o -name '*.jsonl' 2>/dev/null | wc -l)
web_files=$(find /var/www/ZealPalace/world/ /var/www/ZealPalace/tavern/ /var/www/ZealPalace/cult/ /var/www/ZealPalace/blog/ -type f 2>/dev/null | wc -l)
echo "  State files remaining: $state_files"
echo "  Web files remaining: $web_files"
if $GENESIS; then
    log_count=$(find /var/log/nginx/ -name '*.log.*' 2>/dev/null | wc -l)
    echo "  Old nginx log files: $log_count"
fi

# Record wipe timestamps for LCD display
TIMESTAMP_FILE="$HOME/.cache/zealot/wipe_timestamps.json"
NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
if $GENESIS; then
    echo "{\"last_genesis\": \"$NOW\", \"last_meteor\": \"$NOW\"}" > "$TIMESTAMP_FILE"
else
    # Preserve genesis timestamp if it exists
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
if $GENESIS; then
    echo '☄️ ☄️ ☄️  GENESIS COMPLETE  ☄️ ☄️ ☄️'
    echo 'Factory wipe done. Era 0. Deploy and reboot to begin.'
else
    echo '☄️ ☄️ ☄️  METEOR IMPACT COMPLETE  ☄️ ☄️ ☄️'
    echo 'Universe reset. Deploy and reboot to begin.'
fi
