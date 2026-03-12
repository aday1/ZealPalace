#!/bin/bash
set -e

# Change Pi-hole webserver from port 80 to 8080
sudo sed -i 's|port = "80o,443os,\[::\]:80o,\[::\]:443os"|port = "8080o,[::]:8080o"|' /etc/pihole/pihole.toml

# Verify the change
echo "=== PIHOLE PORT AFTER ==="
sudo grep '^\s*port' /etc/pihole/pihole.toml | head -5

# Restart pihole-FTL to pick up new port
sudo systemctl restart pihole-FTL
sleep 2

# Verify pihole is on 8080 now
echo "=== PIHOLE LISTENING ==="
sudo ss -tlnp | grep pihole

# Now start nginx on port 80
echo "=== NGINX STATUS ==="
sudo systemctl start nginx 2>&1 || true
sudo systemctl status nginx --no-pager -l 2>&1 | head -15

# Check what's on port 80 now
echo "=== PORT 80 ==="
sudo ss -tlnp | grep ':80 '

echo "=== DONE ==="
