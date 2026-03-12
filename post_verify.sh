#!/bin/bash
echo '=== POST-REBOOT VERIFICATION ==='
for svc in ngircd nginx zealot-bot zealot-rpg zealot-hangs zealot-web-api zealot-admin zealot-blog.timer; do
    printf '  %-18s %s\n' "$svc:" "$(sudo systemctl is-active $svc)"
done
echo
echo '=== WEB CHECK ==='
curl -s -o /dev/null -w 'HTTP %{http_code}' http://localhost/
echo
echo
echo '=== UNICODE CHECK ==='
curl -s http://localhost/world/ 2>/dev/null | grep -c '\\U0001f\|\\u2014' && echo 'FAIL: unicode escape literals found!' || echo 'PASS: no unicode escape literals'
echo
echo '=== STATE CHECK ==='
echo "State dir:"
ls -la ~/.cache/zealot/ 2>&1
echo "RPG dir:"
ls ~/.cache/zealot/rpg/ 2>&1
echo "NPC dir:"
ls ~/.cache/zealot/npc/ 2>&1
echo "World web:"
ls /var/www/ZealPalace/world/ 2>&1
echo
echo '=== DONE ==='
