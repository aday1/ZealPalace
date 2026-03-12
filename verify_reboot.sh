#!/bin/bash
echo "=== UPTIME ==="
uptime
echo
echo "=== SERVICES ==="
for svc in ngircd nginx pihole-FTL zealot-bot zealot-rpg zealot-hangs \
           zealot-web-api zealot-admin zealot-blog.timer; do
    printf '%-20s active=%-10s enabled=%-10s\n' "$svc" "$(systemctl is-active $svc)" "$(systemctl is-enabled $svc)"
done
echo
echo "=== KEY PORTS ==="
sudo ss -tlnp | grep -E ':80 |:8080|:6667'
echo
echo "=== SERVICE LOGS (last 3 lines each) ==="
for svc in zealot-bot zealot-rpg zealot-hangs zealot-web-api zealot-admin; do
    echo "--- $svc ---"
    sudo journalctl -u $svc --no-pager -n 3 2>/dev/null
done
echo
echo "=== NGINX TEST ==="
curl -sI localhost | head -1
echo
echo "=== IRC TEST ==="
echo 'QUIT' | nc -w2 localhost 6667 2>&1 | head -2
echo
echo "=== IRC CHANNELS ==="
sudo grep -c 'JOIN' /var/log/syslog 2>/dev/null || echo "no syslog grep"
echo
echo "=== ZEALOT STATE ==="
cat /home/aday/.cache/zealot/state.json 2>/dev/null | python3 -m json.tool 2>/dev/null | head -20
echo
echo "=== DONE ==="
