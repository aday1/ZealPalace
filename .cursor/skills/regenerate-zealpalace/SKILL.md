---
name: regenerate-zealpalace
description: >-
  Rebuild or regenerate ZealPalace IRC MUD from scratch while preserving
  ngIRCd channels, JSON soul/state, CGA LCD display, Ollama-on-ZealTower,
  and homelab CELES/nginx integration. Use when rebuilding ZealPalace,
  redeploying the Pi, or regenerating the codebase with a powerful model.
---

# Regenerate ZealPalace

## Canonical repo

All rebuild work targets:

    C:/aday.repo/ZealPalace

GitHub: https://github.com/aday1/ZealPalace

Human operator runbook (full Pi rebuild from scratch): YomikosPapers vault `09-network-homelab/ZealPalace-Rebuild-and-Deploy.md` (also see README Deployment below).

Before a large rebuild, read [reference.md](reference.md) for architecture, ports, systemd units, and test gates.

Homelab deploy scripts (Holybell, in YomikosPapers gitignored `temp_/`): `deploy-zealpalace-all.ps1`, `deploy-zealpalace-to-pi.ps1`, `deploy-zealpalace-to-celes.ps1`

## Non-negotiables

| Layer | Requirement |
| --- | --- |
| Pi host | 10.13.37.76 — SSH `zealpalace` from CELES |
| IRC | ngircd :6667 — `#ZealPalace`, `#RPG`, `#ZealHangs` |
| Web | nginx :80; admin :9666; web-api :8888 |
| LLM | Ollama on ZealTower `http://10.13.37.5:11434` only (`soul.json`) |
| State | JSON only — `soul.json`, `~/.cache/zealot/`, `/var/www/ZealPalace/` |
| LCD | 40x34 curses TUI, Terminus 8x14, `boot_plasma.py`, `lcd-dashboard.service` |
| Homelab | CELES proxies `/admin`, `/api`, `/blog` to Pi; NOC push to `noc_mesh.json` |
| Excluded | No Minecraft / RCON / MC bridge (removed 2026-05-28) |

Pi install entrypoint: `bash /tmp/zeal_deploy/deploy.sh` after copying repo tree to `/tmp/zeal_deploy`.

## Application components (rebuild targets)

| Script / unit | Role |
| --- | --- |
| zealot_bot.py / zealot-bot.service | Jungian personality on `#ZealPalace` |
| zealot_rpg.py / zealot-rpg.service | Filesystem MUD on `#RPG` |
| zealot_hangs.py / zealot-hangs.service | Seven bots on `#ZealHangs` |
| zealot_web_api.py / zealot-web-api.service | REST :8888 |
| zealot_admin.py / zealot-admin.service | Admin UI :9666 |
| zealot_blog.py + zealot-blog.timer | Daily blog 09:00 |
| zealot_display.py + lcd-init + lcd-boot | 3.5" LCD cycle |
| ngircd.conf | IRC server |
| zealpalace nginx site | Static site + proxies |
| patches/apply-on-zeal.sh | Homelab soul merge + LCD helpers |

## Feature parity rebuild order

```
Task Progress:
- [ ] 1. ngircd.conf + motd + channel names
- [ ] 2. soul.json — ollama.host, models, prompts; Pi can curl ZealTower
- [ ] 3. zealot_bot.py + zealot-bot.service
- [ ] 4. zealot_rpg.py + zealot-rpg.service
- [ ] 5. zealot_hangs.py + zealot-hangs.service
- [ ] 6. zealot_web_api.py + zealot_admin.py + nginx site
- [ ] 7. zealot_blog.py + timer
- [ ] 8. zealot_display.py, lcd-init, lcd-boot, lcd-dashboard.service
- [ ] 9. patches/ — NOC mesh, PBX phones, IRC tail; apply-on-zeal.sh
- [ ] 10. site/ retro pages; homelab CELES nginx if in scope
- [ ] 11. soul.md + personality strings last
```

## Regenerating with new LLM models

1. Edit `soul.json` — `ollama.models` per persona (Ego, SuperEgo, Id, ZealHangs cast).
2. On ZealTower: `ollama pull` for each model (defaults in `zealpalace-remote-update.sh`: llama3.2, mistral, gemma3:1b, qwen2.5:1.5b, phi3).
3. Deploy or merge: `patches/soul-prompts-patch.json` via `apply-on-zeal.sh`, or CELES `sudo bash /opt/voip/zealpalace-remote-update.sh`.
4. `sudo systemctl restart zealot-bot zealot-rpg zealot-hangs`.
5. Optional world wipe: `meteor_wipe.sh` (keep soul) or `meteor_wipe.sh -genesis`.

## Test gates

- Pi systemd: ngircd, nginx, zealot-bot, zealot-rpg, zealot-hangs, zealot-web-api, zealot-admin, zealot-blog.timer — all active
- `curl -s http://localhost/api/status` on Pi
- `echo NICK t | nc -q1 localhost 6667` IRC banner
- LCD tty1: PBX / NOC / idle rotation
- On-net: https://zealpalace.yggdrasil.aday.net.au/ and `/api/status`
- `~/.cache/zealot/noc_mesh.json` updates within ~1 min (CELES push)

## Anti-patterns

- Do not run Ollama on the Pi (use ZealTower)
- Do not add a database
- Do not reintroduce Minecraft stack
- Do not use emoji in source
- Do not add throwaway test files outside `temp_/`
- Do not add extra root markdown in ZealPalace repo (skill lives under `.cursor/skills/`)

## Agent workflow

1. Read repo `README.md`, [reference.md](reference.md), and homelab ZealPalace-Rebuild-and-Deploy.md in YomikosPapers if available
2. Confirm stack lock — ask before changing IRC/Ollama/LCD contracts
3. Follow feature parity checklist; commit logical milestones
4. Wire ngircd + soul + one bot before adding blog/display patches
5. Run test gates; reboot Pi if LCD tmux stuck
6. Holybell full release: `powershell temp_/deploy-zealpalace-all.ps1` (operator)
