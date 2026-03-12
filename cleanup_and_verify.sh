#!/bin/bash
set -e

echo "=== 1. DEPLOY BASHRC ==="
# Copy the correct bashrc from /tmp/zeal_deploy if it exists, otherwise write it
cat > /home/aday/.bashrc << 'BASHRC'
# ~/.bashrc - Zeal (Zealot AI host)
export PATH="$HOME/.local/bin:$PATH"
export TERM=linux

# Non-interactive shells (scp, rsync, ssh "command") - bail out early
case "$-" in
    *i*) ;;
    *) return 0 2>/dev/null || exit 0 ;;
esac

# Allow bypassing auto-attach with NO_AUTO_TMUX=1
if [ -n "$NO_AUTO_TMUX" ]; then
    export PS1='\u@\h:\w\$ '
    return 0 2>/dev/null || exit 0
fi

# Don't attach if already inside tmux
if [ -n "$TMUX" ]; then
    export PS1='\u@\h:\w\$ '
    return 0 2>/dev/null || exit 0
fi

should_attach() {
    [ -n "$SSH_CONNECTION" ] && return 0
    if [ -t 0 ]; then
        TTY=$(tty)
        [[ "$TTY" == /dev/tty[12] ]] && return 0
    fi
    return 1
}

if should_attach; then
    exec ~/.local/bin/lcd-boot
fi

export PS1='\u@\h:\w\$ '
BASHRC
chown aday:aday /home/aday/.bashrc
echo "bashrc deployed OK"

echo "=== 2. VERIFY BASHRC GUARD ==="
grep -c 'case "\$-"' /home/aday/.bashrc && echo "interactive guard present" || echo "WARNING: guard missing!"

echo "=== 3. REMOVE OLD SCRIPTS ==="
for f in lcd-cycle lcd-status lcd-net lcd-users zealot_ai.py irc_zealot_chat; do
    if [ -f /home/aday/.local/bin/$f ]; then
        rm -f /home/aday/.local/bin/$f
        echo "removed $f"
    else
        echo "already gone: $f"
    fi
done
# old memory file
rm -f /home/aday/.cache/zealot_memory.json 2>/dev/null && echo "removed old zealot_memory.json" || true

echo "=== 4. KILL OLD PROCESSES ==="
pkill -f lcd-cycle 2>/dev/null && echo "killed lcd-cycle" || echo "lcd-cycle not running"

echo "=== 5. LIST REMAINING SCRIPTS ==="
ls -la /home/aday/.local/bin/

echo "=== 6. ZEALOT-BOT STATUS ==="
systemctl status zealot-bot --no-pager -l 2>&1 | head -20

echo "=== 7. ZEALOT-BOT LOGS ==="
journalctl -u zealot-bot --no-pager -n 30 2>&1

echo "=== 8. NGINX TEST ==="
curl -s -o /dev/null -w "HTTP %{http_code}" http://localhost/ && echo " OK" || echo " FAIL"

echo "=== 9. IRC TEST ==="
echo "NICK test_probe
USER test 0 * :test
JOIN #ZealPalace
QUIT :done" | nc -w3 localhost 6667 2>&1 | head -10

echo "=== 10. SERVICES SUMMARY ==="
for svc in ngircd nginx pihole-FTL zealot-bot zealot-blog.timer; do
    active=$(systemctl is-active $svc 2>/dev/null)
    enabled=$(systemctl is-enabled $svc 2>/dev/null)
    printf "%-20s active=%-10s enabled=%s\n" "$svc" "$active" "$enabled"
done

echo "=== ALL DONE ==="
