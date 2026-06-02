# ZealPalace rebuild reference

Canonical repo: `C:/aday.repo/ZealPalace`

## Architecture

```
Holybell (Windows)
  clone/build -> tarball -> ssh celes -> ssh zealpalace -> /tmp/zeal_deploy/deploy.sh

ZealPalace Pi (10.13.37.76)
  ngircd :6667
  nginx :80  -> /var/www/ZealPalace, proxy /admin /api
  zealot_* -> ~/.local/bin/*.py
  LCD tty1 -> tmux lcd -> zealot_display.py
  state    -> ~/.cache/zealot/

ZealTower (10.13.37.5)
  Ollama :11434  <- soul.json ollama.host

CELES (10.13.37.37)
  nginx zealpalace.yggdrasil -> Pi :80 paths
  pbx-zealpalace-noc-push.py -> Pi ~/.cache/zealot/noc_mesh.json
  /opt/voip/zealpalace-remote-update.sh
```

## Ports and URLs

| Service | Pi | On-net (via CELES) |
| --- | --- | --- |
| IRC | :6667 | zealpalace.yggdrasil.aday.net.au:6667 |
| HTTP | :80 | https://zealpalace.yggdrasil.aday.net.au/ |
| Admin | :9666 | .../admin/ |
| API | :8888 | .../api/ (health /api/status) |
| Ollama | — | http://10.13.37.5:11434 (ZealTower only) |

Public gate: https://zealpalace.aday.net.au/ (Cloudflare Pages + CELES)

## Systemd units

| Unit | Script |
| --- | --- |
| ngircd | /etc/ngircd/ngircd.conf |
| nginx | sites-enabled/zealpalace |
| zealot-bot.service | zealot_bot.py |
| zealot-rpg.service | zealot_rpg.py |
| zealot-hangs.service | zealot_hangs.py |
| zealot-web-api.service | zealot_web_api.py |
| zealot-admin.service | zealot_admin.py |
| zealot-blog.timer | zealot_blog.py daily |
| lcd-dashboard.service | lcd-init (oneshot) |

Console login runs lcd-boot via .bashrc (attach tmux on real TTY).

## deploy.sh steps (Pi)

1. CRLF fix on deploy tree
2. apt: ngircd, nginx
3. Stop services, kill lcd tmux
4. mkdir ~/.local/bin, ~/.cache/zealot, /var/www/ZealPalace
5. Copy zealot_*.py, boot_plasma.py, lcd-* to ~/.local/bin
6. bashrc + Terminus console font
7. ngircd.conf, motd
8. nginx site + site/ + Docs images
9. systemd unit install + enable
10. start all + verify; run patches/apply-on-zeal.sh if present

## State files

| Path | Purpose |
| --- | --- |
| soul.json (repo + ~/.cache/zealot/) | Personality, Ollama models, prompts |
| ~/.cache/zealot/state.json | Runtime mood, plot |
| ~/.cache/zealot/npc_state.json | RPG NPCs |
| ~/.cache/zealot/noc_mesh.json | LCD NOC slot (CELES push) |
| ~/.cache/zealot/rpg/*.json | World, graveyard, settlements |
| /var/www/ZealPalace/ | Generated blog, world pages |

## Key repo files

| File | Role |
| --- | --- |
| zealot_bot.py | #ZealPalace Jungian engine |
| zealot_rpg.py | #RPG dungeon |
| zealot_hangs.py | #ZealHangs seven bots |
| zealot_display.py | LCD curses UI |
| zealot_web_api.py | REST API |
| zealot_admin.py | Admin dashboard |
| zealot_blog.py | Daily blog |
| boot_plasma.py | Boot animation |
| lcd-init, lcd-boot | tmux LCD session |
| ngircd.conf | IRC |
| zealpalace.nginx | nginx site (deploy renames) |
| patches/ | Homelab LCD + soul merge |
| meteor_wipe.sh | Soft or -genesis reset |
| site/ | GitHub Pages static site |

## Holybell deploy (gitignored temp_/)

| Script | Action |
| --- | --- |
| deploy-zealpalace-to-pi.ps1 | build sites, tarball repo, celes->pi, fix-zeal-deploy-lf.sh -> deploy.sh |
| deploy-zealpalace-to-celes.ps1 | pseudocorp-deploy site/nginx to CELES |
| deploy-zealpalace-all.ps1 | CELES + Pi + wrangler Pages |
| fix-zeal-deploy-lf.sh | Strip CRLF, run deploy.sh |
| build-zealpalace-sites.py | Sync site HTML into pseudocorp-deploy |

## Maintenance scripts (Pi)

| Script | Purpose |
| --- | --- |
| deploy.sh | Full install |
| cleanup_and_verify.sh | Post-deploy health |
| verify_reboot.sh | After reboot |
| meteor_wipe.sh | Clear world state |
| patches/apply-on-zeal.sh | Merge prompts + LCD helpers |

## LCD patches (homelab)

| File | Role |
| --- | --- |
| zealot_noc_mesh.py | NOC mesh display slot |
| zealot_pbx_phones.py | PBX phone list slot |
| zeal_patch_display_noc.py | Third 10s cycle slot |
| zeal_apply_lcd_fixes.py | Copy helpers to ~/.local/bin |

See [[09-network-homelab/PSEUDOCORP-NOC-Watchdog#ZealPalace LCD (10.13.37.76)|NOC Watchdog LCD section]].

## Operator docs

| Doc | Location |
| --- | --- |
| Full rebuild / deploy (human) | YomikosPapers 09-network-homelab/ZealPalace-Rebuild-and-Deploy.md |
| Homelab hub | 09-network-homelab/ZealPalace.md |
| Upstream README | ZealPalace/README.md |
