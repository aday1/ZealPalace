# ZealPalace agent rebuild reference

Companion to `AGENT-REBUILD.md`. Edit this file when ports, paths, or homelab contracts change.

## Architecture

```
Holybell (Windows)
  C:/aday.repo/ZealPalace -> tarball -> ssh celes -> ssh zealpalace
  -> /tmp/zeal_deploy/deploy.sh

ZealPalace Pi (10.13.37.76)
  ngircd :6667
  nginx :80 -> /var/www/ZealPalace, proxy /admin /api
  ~/.local/bin/zealot_*.py
  LCD tty1 -> tmux lcd -> zealot_display.py
  ~/.cache/zealot/

ZealTower (10.13.37.5)
  Ollama :11434 <- soul.json ollama.host

CELES (10.13.37.37)
  nginx zealpalace.yggdrasil -> Pi :80
  pbx-zealpalace-noc-push.py -> noc_mesh.json
  /opt/voip/zealpalace-remote-update.sh
```

## Ports and URLs

| Service | Pi | On-net (via CELES) |
| --- | --- | --- |
| IRC | :6667 | zealpalace.yggdrasil.aday.net.au:6667 |
| HTTP | :80 | https://zealpalace.yggdrasil.aday.net.au/ |
| Admin | :9666 | .../admin/ |
| API | :8888 | .../api/status |
| Ollama | — | http://10.13.37.5:11434 only |

Public gate: https://zealpalace.aday.net.au/

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
| zealot-blog.timer | zealot_blog.py |
| lcd-dashboard.service | lcd-init |

## deploy.sh (10 steps)

1. CRLF fix  2. apt ngircd nginx  3. stop services  4. mkdir dirs
5. copy scripts to ~/.local/bin  6. bashrc + Terminus font
7. ngircd  8. nginx + site/  9. systemd enable  10. start + verify
Post: patches/apply-on-zeal.sh if present.

## State files

| Path | Purpose |
| --- | --- |
| soul.json | Persona, Ollama models, prompts |
| ~/.cache/zealot/state.json | Mood, plot stage |
| ~/.cache/zealot/npc_state.json | RPG NPCs |
| ~/.cache/zealot/noc_mesh.json | LCD NOC (CELES push) |
| ~/.cache/zealot/rpg/*.json | World, graveyard |
| /var/www/ZealPalace/ | Blog, world HTML |

## Key files

| File | Role |
| --- | --- |
| zealot_bot.py | #ZealPalace Jungian engine |
| zealot_rpg.py | #RPG filesystem MUD |
| zealot_hangs.py | #ZealHangs seven bots |
| zealot_display.py | LCD curses UI |
| zealot_web_api.py | REST |
| zealot_admin.py | Admin :9666 |
| zealot_blog.py | Daily blog |
| boot_plasma.py | Boot animation |
| lcd-init, lcd-boot | tmux LCD |
| ngircd.conf, ngircd.motd | IRC |
| patches/ | Homelab LCD + soul merge |
| meteor_wipe.sh | Soft or -genesis reset |

## Holybell deploy (YomikosPapers temp_/)

| Script | Action |
| --- | --- |
| deploy-zealpalace-to-pi.ps1 | Tarball repo, deploy.sh on Pi |
| deploy-zealpalace-to-celes.ps1 | Site + nginx on CELES |
| deploy-zealpalace-all.ps1 | Pi + CELES + Cloudflare Pages |
| fix-zeal-deploy-lf.sh | CRLF then deploy.sh |

## LCD patches

zealot_noc_mesh.py, zealot_pbx_phones.py, zeal_patch_display_noc.py, zeal_apply_lcd_fixes.py, apply-on-zeal.sh

## Personality files

soul.md, soul.json, patches/soul-prompts-patch.json, README philosophy section.
