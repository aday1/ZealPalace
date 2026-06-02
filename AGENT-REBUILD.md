# AGENT-REBUILD — ZealPalace

Rebuild this project from scratch. Read this file before writing code. Preserve all Non-negotiables.

This is a **from-scratch rebuild runbook** for the Pi IRC MUD stack (not Minecraft).

## Rebuild from scratch

### Prerequisites

- Raspberry Pi (or Linux VM) on LAN
- Python 3.10+, ngIRCd, systemd
- Ollama reachable at 10.13.37.5:11434 for bot replies (ZealTower)
- Optional: 3.5" LCD + patches in `patches/`

### Path A (recommended): clone on Pi

    git clone https://github.com/aday1/ZealPalace.git
    cd ZealPalace

### Path B: empty directory

Create minimum files:

    ZealPalace/
      ngircd.conf
      soul.json
      zealot_bot.py
      zealot_rpg.py
      zealot_hangs.py
      zealot_web_api.py
      zealot-admin.service   # unit templates
      site/index.html
      deploy.sh

Copy systemd units from this repo's `*.service` files as reference.

### Phased rebuild

| Phase | What to build | Done when |
| --- | --- | --- |
| 0 | `ngircd.conf` + motd; ngIRCd listens :6667 | `nc host 6667` connects |
| 1 | `zealot_bot.py`: connect IRC, respond on `#ZealPalace` with Ollama | Bot joins channel and replies |
| 2 | `soul.json` persona + `zealot_admin.py` / admin HTTP | `/admin/` loads on Pi :80 |
| 3 | `zealot_rpg.py`: filesystem-backed RPG commands | `#RPG` commands mutate world state |
| 4 | `zealot_hangs.py`: relationship/drama loop on `#ZealHangs` | Hangs channel shows autonomous drama |
| 5 | `zealot_web_api.py` + `zealot-blog.service` timer | `GET /api/status` returns JSON |
| 6 | `site/` static pages; GitHub Pages workflow | https://aday1.github.io/ZealPalace/ works |
| 7 | CELES nginx proxy + `deploy-zealpalace-*.ps1` from vault | https://zealpalace.yggdrasil.aday.net.au/ proxies Pi |

**MVP:** phases 0-1 (IRC + one bot).

**Done when (full):** all systemd units active, LCD optional, public + on-net URLs 200.

## Canonical paths

| Field | Value |
| --- | --- |
| GitHub | https://github.com/aday1/ZealPalace |
| Local | `YomikosPapers/temp_/ZealPalace` (deploy clone) |
| Vault | `09-network-homelab/ZealPalace.md` |
| Pi | 10.13.37.76 — SSH `ssh zealpalace` from CELES |
| Ollama | 10.13.37.5:11434 (ZealTower) |

## Non-negotiables

| Item | Requirement |
| --- | --- |
| Platform | Raspberry Pi IRC MUD — **not** Minecraft (removed 2026-05-28) |
| Stack | Python bots + ngIRCd + systemd units + optional 3.5" LCD |
| Personas | Jungian Zealot engine, RPG on filesystem, ZealHangs drama |
| Channels | `#ZealPalace`, `#ZealHangs`, `#RPG`, `#pseudocorp`, `#slacking-off` |
| Public site | GitHub Pages + CELES nginx proxy to Pi |

## Core services (systemd on Pi)

| Unit | Script | Role |
| --- | --- | --- |
| zealot-bot | `zealot_bot.py` | Main Zealot IRC |
| zealot-rpg | `zealot_rpg.py` | Filesystem RPG |
| zealot-hangs | `zealot_hangs.py` | Drama / relationships |
| zealot-blog | `zealot_blog.py` | Daily blog timer |
| zealot-web-api | `zealot_web_api.py` | HTTP API |
| zealot-admin | `zealot_admin.py` | Admin / soul |
| lcd-dashboard | display scripts | TFT status |

## Build and run (dev)

On Pi or staging: install Python deps per `README.md`, configure `ngircd.conf`, `soul.json` / `soul.md`.

LCD patches under `patches/` — apply via `patches/apply-on-zeal.sh` on device.

## Deploy (Holybell)

Full pipeline from vault:

    powershell temp_/deploy-zealpalace-all.ps1

CELES only: `deploy-zealpalace-to-celes.ps1`  
Pi only: `deploy-zealpalace-to-pi.ps1`  
Site build: `python temp_/pseudocorp-deploy/build-zealpalace-sites.py`  
Soul sync on CELES: `sudo bash /opt/voip/zealpalace-remote-update.sh`

## URLs

| Surface | URL |
| --- | --- |
| On-net | https://zealpalace.yggdrasil.aday.net.au/ |
| Public CF | https://zealpalace.aday.net.au/ |
| Pages | https://aday1.github.io/ZealPalace/ |
| API health | `/api/status` via CELES proxy |

## Smoke gates

- IRC connect :6667 on LAN
- `/api/status` 200 via nginx
- zealot-bot and zealot-rpg active (`systemctl`)
- One Ollama-backed reply on `#ZealPalace` (model on ZealTower)

## File map

| Path | Role |
| --- | --- |
| `zealot_bot.py` | Main bot |
| `zealot_rpg.py` | RPG simulation |
| `zealot_hangs.py` | Social drama |
| `zealot_web_api.py` | REST API |
| `soul.json` | Persona config |
| `ngircd.conf` | IRC server |
| `site/` | Static site sources |
| `deploy.sh` | Pi deploy helper |
| `.github/workflows/pages.yml` | Pages CI |

## Anti-patterns

- Do not reintroduce Minecraft / RCON integration
- No emoji in Python or HTML
- Do not point Ollama at wrong host (must be ZealTower for zealot services)

## Out of scope

- CELES PBX dialplan (documented in separate voip bundle under `temp_/pseudocorp-deploy/`)
