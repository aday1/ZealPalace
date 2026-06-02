# AGENT-REBUILD — ZealPalace

Rebuild this project from scratch. Read this file and `DOCS/AGENT-REBUILD-REFERENCE.md` before writing code. Preserve all Non-negotiables.

This document is a **from-scratch rebuild runbook**, not a high-level summary. Follow the phases below in order.

## Voice and aesthetics

- **Family:** CGA IRC terrarium (see YomikosPapers `.cursor/skills/regenerate-zealpalace/` and `regenerate-shared/OPERATOR-VOICE-AND-PREFERENCES.md`)
- **Visual:** Demoscene boot, 40x34 LCD, Geocities `site/`, ngircd MOTD — never flatten to SaaS landing
- **Copy:** Jungian Zealot, Aussie Ego, lowercase SuperEgo, CAPS Id, ZealHangs drama, filesystem RPG — accurate IRC/Ollama specs underneath
- **Prefs:** No emoji; scratch under `temp_/`; no new root markdown files

## Rebuild from scratch

### Prerequisites

- Raspberry Pi (ZealPalace) on LAN, SSH as `aday`
- Ollama on ZealTower `10.13.37.5:11434` reachable from Pi
- Python 3, ngircd, nginx on Pi (deploy.sh installs them)
- Optional: 3.5" TFT LCD for `zealot_display.py`

### Path A (recommended): clone and regenerate in place

    git clone https://github.com/aday1/ZealPalace.git
    cd ZealPalace

Regenerate using **Phased rebuild** below. Keep `soul.json`, `soul.md`, `LICENSE`, and `patches/` until replacements exist.

### Path B: deploy tree on Pi

    scp -r . pi:/tmp/zeal_deploy/
    ssh pi 'bash /tmp/zeal_deploy/deploy.sh'

Use when the repo on Holybell is already correct and you only need runtime install.

### Phased rebuild (implement in order)

| Phase | What to build | Done when |
| --- | --- | --- |
| 0 | `ngircd.conf`, `ngircd.motd`, channel names | `ngircd --configtest` OK; :6667 listens |
| 1 | `soul.json` with `ollama.host` = ZealTower; curl tags from Pi | `curl http://10.13.37.5:11434/api/tags` succeeds |
| 2 | `zealot_bot.py` + `zealot-bot.service` | Bot joins `#ZealPalace`; one Ollama reply |
| 3 | `zealot_rpg.py` + `zealot-rpg.service` | `/new` or natural language works on `#RPG` |
| 4 | `zealot_hangs.py` + `zealot-hangs.service` | Bots idle/speak on `#ZealHangs` |
| 5 | `zealot_web_api.py` :8888 + `zealot-admin.service` :9666 | `curl localhost/api/status` returns JSON |
| 6 | nginx site + `site/` static + `/var/www/ZealPalace` | `curl localhost/` returns retro homepage |
| 7 | `zealot_blog.py` + `zealot-blog.timer` | Timer enabled; manual run creates blog file |
| 8 | `zealot_display.py`, `lcd-init`, `lcd-boot`, `lcd-dashboard.service` | tty1 shows IRC ticker or boot plasma |
| 9 | `patches/apply-on-zeal.sh` — NOC, PBX phones, soul merge | LCD third slot / homelab headers if CELES push active |
| 10 | Homelab CELES nginx proxy (operator) | https://zealpalace.yggdrasil.aday.net.au/api/status 200 |
| 11 | `soul.md`, prompt theatre, MOTD copy | Voice matches README; no emoji in repo |
| 12 | Full `deploy.sh` idempotent re-run + smoke gates | All units active after reboot |

**MVP (ship-blocking minimum):** phases 0-5. IRC speaks on `#ZealPalace` with Ollama on ZealTower.

**Full parity:** phases 6-12 and homelab deploy.

## Canonical paths

| Field | Value |
| --- | --- |
| GitHub | https://github.com/aday1/ZealPalace |
| Local | `C:/aday.repo/ZealPalace` |
| Vault | YomikosPapers `09-network-homelab/ZealPalace.md` |
| Human deploy | YomikosPapers `09-network-homelab/ZealPalace-Rebuild-and-Deploy.md` |
| Cursor skill | YomikosPapers `.cursor/skills/regenerate-zealpalace/` |
| Pi | 10.13.37.76 — SSH `zealpalace` from CELES |
| Ollama | 10.13.37.5:11434 (ZealTower) |

## Non-negotiables

| Layer | Requirement |
| --- | --- |
| Platform | Raspberry Pi IRC MUD — **not** Minecraft (removed 2026-05-28) |
| Stack | Python bots + ngircd + nginx + systemd |
| LLM | Ollama on ZealTower only — never on Pi or CELES |
| State | JSON files — no database |
| IRC | `#ZealPalace`, `#ZealHangs`, `#RPG` |
| LCD | 40x34 CGA curses, Terminus, demoscene boot |
| Tone | Zealot terrarium voice; no emoji in source |

## Build and run (dev)

On Pi: copy tree to `/tmp/zeal_deploy`, run `deploy.sh`. LCD patches: `bash patches/apply-on-zeal.sh patches`.

## Test gates

- `systemctl is-active ngircd nginx zealot-bot zealot-rpg zealot-hangs zealot-web-api zealot-admin zealot-blog.timer`
- `curl -s http://127.0.0.1/api/status`
- IRC: `echo NICK t | nc -q1 127.0.0.1 6667 | head -3`
- Optional LCD: NOC mesh slot when `noc_mesh.json` present

## Deploy (Holybell)

    powershell temp_/deploy-zealpalace-all.ps1

CELES only: `deploy-zealpalace-to-celes.ps1`  
Pi only: `deploy-zealpalace-to-pi.ps1`  
Soul sync on CELES: `sudo bash /opt/voip/zealpalace-remote-update.sh`

## URLs

| Surface | URL |
| --- | --- |
| On-net | https://zealpalace.yggdrasil.aday.net.au/ |
| Public CF | https://zealpalace.aday.net.au/ |
| Pages | https://aday1.github.io/ZealPalace/ |

## Visual contract (CGA terrarium)

Do not replace Geocities site with generic landing. Keep demoscene boot + LCD ticker. MOTD and bot replies use Zealot voice formula in operator prefs.

## Personality (Zealot)

- `soul.json` — source of truth for models, moods, prompts
- `soul.md` — narrative voice reference
- `patches/soul-prompts-patch.json` — homelab merge without overwriting whole soul
- Do not rename `zealot_*` modules without explicit user ask

## Feature parity rebuild order

1. ngircd + soul + Ollama reachability
2. zealot_bot
3. zealot_rpg
4. zealot_hangs
5. web-api + admin + nginx
6. blog timer
7. display + LCD boot
8. patches + homelab CELES
9. copy and MOTD last

Full file map: `DOCS/AGENT-REBUILD-REFERENCE.md`.

## Anti-patterns

- No Minecraft / RCON
- No database
- No Ollama on Pi
- No emoji in Python/HTML
- No throwaway tests outside `temp_/`
- No extra markdown in repo root

## Operator docs

`README.md`, `soul.md`, vault `ZealPalace-Rebuild-and-Deploy.md`
