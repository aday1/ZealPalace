---
name: regenerate-zealpalace
description: >-
  Rebuild ZealPalace Pi IRC MUD from scratch: CGA/BBS terrarium aesthetics,
  Jungian Zealot voice, ngIRCd, Ollama on ZealTower, demoscene LCD, no emoji,
  no Minecraft. Phased AGENT-REBUILD runbook. Use for full regeneration or Pi redeploy.
---

# Regenerate ZealPalace

Read [OPERATOR-VOICE-AND-PREFERENCES.md](../regenerate-shared/OPERATOR-VOICE-AND-PREFERENCES.md) first — emoji ban, `temp_/` scratch, minimal new markdown, CGA IRC terrarium family.

## Source of truth (read second)

| Doc | Path |
| --- | --- |
| From-scratch phases | `C:/aday.repo/ZealPalace/AGENT-REBUILD.md` |
| Deep reference | `C:/aday.repo/ZealPalace/DOCS/AGENT-REBUILD-REFERENCE.md` |
| Lore and hardware | `README.md`, `soul.md` |
| Operator deploy (human) | YomikosPapers `09-network-homelab/ZealPalace-Rebuild-and-Deploy.md` |

GitHub: https://github.com/aday1/ZealPalace  
Vault: `09-network-homelab/ZealPalace.md`

## Aesthetic and language (non-negotiable)

**Visual:** Digital terrarium — BBS / IRC 1988 / demoscene boot — not optional chrome.

- `boot_plasma.py` — plasma boot on tty1 before LCD dashboard (demoscene identity)
- `zealot_display.py` — 40x34 CGA curses on 3.5" TFT; Terminus 8x14; mood-driven palette
- `site/style.css` + `site/index.html` — Geocities shrine; mesh-network aesthetic, not SaaS landing
- `ngircd.motd` + MOTD banner — period-appropriate ASCII theatre
- Public gate HTML (pseudocorp-deploy) stays on ZealPalace palette — no generic corporate hero sections

**Copy / Zealot terrarium:**

| Preserve | Location |
| --- | --- |
| Self-description voice | `soul.md` |
| Persona config, moods, substances | `soul.json` |
| Ego / SuperEgo / Id prompts | `soul.json` prompts |
| ZealHangs cast and relationship drama | `zealot_hangs.py`, guestbooks |
| Filesystem RPG tone | `zealot_rpg.py`, `/proc` dungeon names |
| Beer-ware LICENSE vibe | `README.md` License section |
| Blog consciousness posts | `zealot_blog.py` output under `/var/www/ZealPalace/blog/` |

Voice: Aussie BSD admin warmth + Jungian splits + $35 Pi process philosophy + XKCD #350 terrarium energy + self-aware absurdity + real IRC/Ollama/systemd specs underneath. See **Zealot voice formula** in shared operator prefs.

**Showcase:** GitHub Pages `site/`, on-net https://zealpalace.yggdrasil.aday.net.au/ — same weird sincerity as the bots.

## Technical locks

- Raspberry Pi OS on **10.13.37.76** — Python 3 bots, ngircd, nginx, systemd
- Ollama **only** on ZealTower `http://10.13.37.5:11434` (`soul.json` ollama.host)
- JSON state only — `soul.json`, `~/.cache/zealot/`, `/var/www/ZealPalace/` — no database
- IRC :6667 — `#ZealPalace`, `#ZealHangs`, `#RPG` (plus homelab `#pseudocorp`, `#slacking-off`)
- Web :80; admin :9666; API :8888; CELES proxies `/admin`, `/api`, `/blog`
- Pi install: `bash /tmp/zeal_deploy/deploy.sh`

## Agent workflow

1. Read `AGENT-REBUILD.md` phased table; implement MVP (phases 0-5) before parity 6-12.
2. Wire ngircd + `soul.json` + Ollama curl test before any bot speaks on IRC.
3. Port `zealot_display.py` + LCD boot chain early if hardware present — visual regression is obvious.
4. Layer Zealot copy last (`soul.md`, prompts, MOTD, blog tone) after services are stable.
5. Run test gates: systemd active, `/api/status`, IRC banner, optional LCD NOC slot.
6. Edit in-repo `AGENT-REBUILD.md` when contracts change — keep this skill as flavor + pointers.
7. Operator full deploy: `powershell temp_/deploy-zealpalace-all.ps1` (Holybell, vault `temp_/`).

## Anti-patterns

- Flat modern landing page replacing Geocities `site/`
- Ollama on the Pi or CELES (ZealTower only)
- Reintroducing Minecraft / RCON / MC bridge
- Emoji anywhere in repo
- Extra root markdown or throwaway tests outside `temp_/`
- Renaming core `zealot_*` services or channels without explicit user ask
- ClawBot / MoltBook keynote tone — this is 1997 MUD energy on a mesh LAN
