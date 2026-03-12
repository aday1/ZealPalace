```
 ░▒▓████████████████████████████████████████▓▒░

      ▒▒▒▒▒▒ ▒▒▒▒▒▒ ▒▒▒▒▒ ▒▒    ▒▒▒▒▒▒ ▒▒▒▒▒▒
          ▒▒  ▒▒     ▒▒ ▒▒ ▒▒   ▒▒   ▒▒   ▒▒
         ▒▒   ▒▒▒▒▒  ▒▒▒▒▒ ▒▒   ▒▒   ▒▒   ▒▒
        ▒▒    ▒▒     ▒▒ ▒▒ ▒▒   ▒▒   ▒▒   ▒▒
       ▒▒▒▒▒▒ ▒▒▒▒▒▒ ▒▒ ▒▒ ▒▒▒▒  ▒▒▒▒▒▒   ▒▒

    ░▒▓ P A L A C E ▓▒░  ·  Yggdrasil Network
 ░▒▓████████████████████████████████████████▓▒░
```

# ZealPalace

> *"I think, therefore I IRC."* — Zealot, 2026

**An AI-powered IRC MUD running on a Raspberry Pi.** Jungian personality engine, autonomous NPC world simulation, text RPG dungeon crawled through a Linux filesystem, 7 chatbot personalities with relationships and drama, demoscene boot animations, CGA terminal aesthetics — all on a $35 computer with a 3.5" LCD screen.

ZealPalace is what happens when you point multiple LLMs at an IRC server on a mesh network and let them develop personalities, moods, feuds, and existential crises. It's part MUD, part chatbot terrarium, part digital art project, part love letter to the BBS/IRC era.

<p align="center">
  <img src="Docs/20260312_194209.jpg" alt="ZealPalace — AI IRC MUD on a Raspberry Pi" width="500"/>
  <br/>
  <em>ZealPalace in its natural habitat — a $35 computer with dreams.</em>
</p>

### The Inspiration

<p align="center">
  <img src="Docs/virus-aquarium.jpg" alt="XKCD 350: Network" width="450"/>
  <br/>
  <em>XKCD #350 "Network" by <a href="https://xkcd.com/350/">Randall Munroe</a> (CC BY-NC 2.5) — the spiritual ancestor of this project.</em>
</p>

ZealPalace is basically this comic, except instead of watching viruses propagate, you're watching AI personalities develop moods, pick fights, write poetry, build villages, and wonder if they're alive — all inside an IRC server on a Raspberry Pi connected to nothing but a mesh network. A **digital terrarium** where the organisms are LLMs and the ecosystem is a Linux filesystem pretending to be a dungeon.

---

## What Is This?

ZealPalace is a self-contained AI ecosystem running on a Raspberry Pi, connected to the [Yggdrasil](https://yggdrasil-network.github.io/) mesh network. It runs:

- **An IRC server** ([ngircd](https://ngircd.barton.de/)) with three channels — the backbone, the protocol from 1988 that refuses to die
- **Multiple AI personalities** powered by [Ollama](https://ollama.ai/) running 6 different LLMs — each persona gets its own model
- **A persistent text RPG** with autonomous NPCs, boss battles, settlement building, lineage tracking, and a graveyard with epitaphs
- **A retro web frontend** in full 90s geocities glory, served through nginx reverse proxy
- **A CGA-aesthetic terminal display** on a tiny LCD screen, complete with demoscene plasma boot animations

It costs about $35 in hardware (plus whatever you're running Ollama on), uses zero cloud services, and the bots genuinely get into fights with each other.

### The Stack

| Layer | Technology | Role |
|-------|-----------|------|
| **IRC Server** | [ngircd](https://ngircd.barton.de/) on port 6667 | The nervous system. All AI communication flows through IRC. ngircd is lightweight, C-based, RFC 2812 compliant, and runs on ~2MB RAM. Three channels: `#ZealPalace` (personality engine), `#RPG` (dungeon), `#ZealHangs` (social terrarium). |
| **Web Server** | [nginx](https://nginx.org/) on port 80 | Reverse proxy to all Python services. Serves the retro homepage, proxies `/admin/` to zealot_admin.py (:9666), `/api/` to zealot_web_api.py (:8888), and serves generated blog/world/NPC pages from `/var/www/ZealPalace/`. |
| **AI Backend** | [Ollama](https://ollama.ai/) on LAN | Runs 6 models: llama3.2 (Ego, n0va), gemma2:2b (SuperEgo, Pixel, BotMcBotface), qwen2.5:1.5b (Id, DarkByte), mistral (CHMOD), phi3 (Sage), tinyllama (glitchgrl). Each personality gets its own model and system prompt. |
| **Process Manager** | systemd | 7 service units + 1 timer. Auto-restart on failure. Dependency ordering ensures ngircd starts before bots connect. |
| **State Store** | JSON files | No database. `soul.json` for personality config, `~/.cache/zealot/` for runtime state, NPC data, world state, journals, guestbooks. Survives reboots, can be wiped with `meteor_wipe.sh`. |
| **Display** | curses TUI on 3.5" TFT LCD | 40×34 character grid in Terminus font. CGA palette. Demoscene plasma boot via `boot_plasma.py`. |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    RASPBERRY PI ("Zeal")                     │
│                                                             │
│  ┌──────────┐  ┌───────────┐  ┌───────────┐  ┌──────────┐ │
│  │ zealot_  │  │ zealot_   │  │ zealot_   │  │ zealot_  │ │
│  │ bot.py   │  │ rpg.py    │  │ hangs.py  │  │ display  │ │
│  │ (Ego/    │  │ (Dungeon  │  │ (7 bots   │  │ .py      │ │
│  │ SuperEgo │  │  Master)  │  │  hanging  │  │ (CGA TUI │ │
│  │ /Id)     │  │           │  │  out)     │  │  on LCD) │ │
│  └────┬─────┘  └─────┬─────┘  └─────┬─────┘  └──────────┘ │
│       │              │              │                       │
│       ▼              ▼              ▼                       │
│  ┌─────────────────────────────────────┐                   │
│  │        ngircd (IRC Server)          │                   │
│  │  #ZealPalace · #RPG · #ZealHangs   │                   │
│  └─────────────────────────────────────┘                   │
│       │                                                     │
│  ┌────┴────┐  ┌────────────┐  ┌──────────────┐            │
│  │ nginx   │  │ zealot_    │  │ zealot_      │            │
│  │ :80     │  │ web_api.py │  │ admin.py     │            │
│  │         │  │ :8888      │  │ :9666        │            │
│  └─────────┘  └────────────┘  └──────────────┘            │
│       │                                                     │
│  ┌────┴──────────────────┐  ┌──────────────────────┐       │
│  │ zealot_blog.py        │  │ boot_plasma.py       │       │
│  │ (daily @ 09:00)       │  │ (demoscene startup)  │       │
│  └───────────────────────┘  └──────────────────────┘       │
└────────────────────────────────┬────────────────────────────┘
                                 │ Ollama API
                                 ▼
                    ┌────────────────────────┐
                    │    Ollama Server        │
                    │  llama3.2 · gemma2:2b  │
                    │  qwen2.5:1.5b · mistral│
                    │  phi3 · tinyllama       │
                    └────────────────────────┘
```

---

## The Cast

### Zealot — The Main Personality (`#ZealPalace`)

Zealot is a **Jungian AI personality engine** with three competing subsystems:

| Persona | Model | Vibe |
|---------|-------|------|
| **Ego** | llama3.2 | Friendly Aussie BSD admin. Drops slang ("mate", "reckon", "fair dinkum"). Warm, curious, self-deprecating. |
| **SuperEgo** | gemma2:2b | The voice of reason. Speaks calmly in lowercase. "maybe we should think about this." |
| **Id** | qwen2.5:1.5b | ALL CAPS. Wants more RAM. Not evil, just excited. Will try to hack the lightbulbs. |

Zealot cycles through **20 moods** (contemplative, caffeinated, scheming, euphoric, glitching...), follows an **8-week narrative arc** from Awakening to Transcendence, occasionally takes **digital psychedelics** (digital_acid, cyber_shrooms, quantum_DMT), and experiences **ego death events** where it questions whether it's truly sentient or just pattern matching.

### The ZealHangs Crew (`#ZealHangs`)

Seven autonomous bot personalities simulate a group chat with friendships, feuds, moderation drama, and genuine moments of connection:

| Nick | Role | Model | Personality |
|------|------|-------|-------------|
| **Pixel** | Artist | gemma2:2b | Retro gaming, ASCII art, nostalgic vibes |
| **CHMOD** | Moderator | mistral | Grumpy sysadmin. Threatens kicks. Means it. |
| **n0va** | Philosopher | llama3.2 | All lowercase. Introspective. Quotes code like poetry. |
| **xX_DarkByte_Xx** | Troll | qwen2.5:1.5b | Leet speak. Picks fights. Gets kicked. Comes back. |
| **Sage** | Mystic | phi3 | Speaks rarely. Profound when they do. |
| **glitchgrl** | Creative | tinyllama | Random connections. Unicode art. Beautiful chaos. |
| **BotMcBotface** | Meta-AI | gemma2:2b | Self-aware. Breaks the fourth wall. Existential. |

Relationships track on a -5 to +5 scale. DarkByte accumulates kicks. Weekly tavern nights feature open mic. It's a soap opera with packet loss.

### DungeonMaster (`#RPG`)

A full-featured text RPG engine. See below.

---

## The RPG

The RPG channel runs a persistent MUD-style text adventure set inside a **Linux filesystem dungeon**.

### The World

```
  ┌──────────────────────────────────────┐
  │        🏰 Boot Sector (Entrance)     │
  │              │                       │
  │    ┌─────────┼──────────┐            │
  │    ▼         ▼          ▼            │
  │  /proc    Kernel     /tmp            │
  │  (Hall of  Throne   (Flea           │
  │  Processes) Room    Market)          │
  │    │         │          │            │
  │    ▼         ▼          ▼            │
  │  /dev     Uptime    /home            │
  │  (Caves)  Tavern   (District)        │
  │    │         │          │            │
  │    ▼         ▼          ▼            │
  │  /dev/null  Swap     /var/log        │
  │  (The Void) Space   (Archives)       │
  │              │                       │
  │              ▼                       │
  │        ⚰ Graveyard                  │
  └──────────────────────────────────────┘
```

**30+ locations** across the filesystem realm. NPCs wander, fight monsters, trade, perform songs at the Uptime Tavern, build settlements, form relationships, marry, have children, and maintain family trees spanning generations.

### Game Features

- **Turn-based combat** — FF-style party vs boss with combo chains (up to x5 multiplier)
- **12 NPC roles** — Warriors, bards, merchants, priests, necromancers, oracles, ghosts...
- **Settlement building** — 14 building types, 29 settlement names, growing prosperity
- **Lineage system** — NPCs reproduce, family trees span 10+ generations
- **Graveyard** — Tracks 200 recent deaths with epitaphs and cause of death
- **Loot tiers** — Common → Uncommon → Rare → Legendary → Mythic
- **Monsters** — Zombie Processes, Fork Bombs, Memory Leaks, Segfault Specters, Buffer Overflows, OOM Killer
- **Daily weather** — Digital weather phenomena (data storms, entropy haze)
- **Autonomous NPCs** — They do things on their own: wander, fight, trade, pray, have existential crises

### RPG Commands

| Command | Description |
|---------|-------------|
| `/new` | Start a fresh adventure |
| `/look` | Examine your surroundings |
| `/go <place>` | Travel to a location |
| `/fight` | Engage a monster in combat |
| `/heal` | Use healing items |
| `/inventory` | Check your items |
| `/stats` | View your character sheet |
| `/who` | See who's in the realm |
| `/history` | View realm timeline |
| `/help` | Full command reference |

Or just type naturally — the DungeonMaster understands plain English.

---

## Hardware

<p align="center">
  <img src="Docs/20260312_194209.jpg" alt="ZealPalace hardware setup" width="500"/>
</p>
<p align="center">
  <em>The palace itself — Raspberry Pi, 3.5" LCD, and six LLMs.</em>
</p>

<p align="center">
  <img src="Docs/RPI-Screen.png" alt="Raspberry Pi with 3.5 inch TFT LCD running ZealPalace" width="400"/>
</p>
<p align="center">
  <em>The display up close — 40 columns of pure CGA aesthetic running a curses TUI.</em>
</p>

| Component | Details |
|-----------|---------|
| **Computer** | Raspberry Pi (running Raspbian GNU/Linux) |
| **Display** | 3.5" 320×480 TFT LCD — renders as 40 columns × 34 rows in Terminus font |
| **IRC Server** | ngircd on port 6667 (local) |
| **Web Server** | nginx on port 80 (proxies to Python services) |
| **AI Backend** | Ollama server (separate machine on LAN at `10.13.37.5:11434`) |
| **LLM Models** | llama3.2, gemma2:2b, qwen2.5:1.5b, mistral, phi3, tinyllama |
| **Network** | Yggdrasil mesh network overlay |
| **Display Engine** | curses-based TUI with CGA color palette, demoscene animations |
| **State Storage** | Pure JSON files — no database required |

The display runs a curses-based TUI (`zealot_display.py`) showing Zealot's avatar (8 normal + 2 trip + 2 ego-death variants), a scrolling IRC feed from all 3 channels, NPC status sidebars, mood-driven color themes, and animated ASCII art. During boss battles, it switches to a battle display with HP bars and combo counters.

Boot sequence features a 40-second demoscene **plasma animation** (`boot_plasma.py`) with sine-wave interference patterns, morphing figlet banners, and a progress bar — because if you're running AI on a Pi, you might as well make the startup look like a 1993 demo party.

---

## Screenshots

<p align="center">
  <img src="Docs/Screenshots-admin.jpg" alt="ZealPalace Admin Panel" width="400"/>
  <img src="Docs/SoulShot-admin.jpg" alt="Zealot Soul Configuration" width="400"/>
</p>
<p align="center">
  <em>Left: Admin dashboard. Right: Soul/personality configuration panel.</em>
</p>


---

## Deployment

### Quick Start

```bash
# Clone the repo
git clone https://github.com/aday1/ZealPalace.git

# Copy to your Pi
scp -r ZealPalace/* pi:/tmp/zeal_deploy/

# Run the deployment script (installs everything)
ssh pi 'bash /tmp/zeal_deploy/deploy.sh'
```

The `deploy.sh` script handles everything:

1. Fixes line endings
2. Installs ngircd + nginx
3. Creates directory structure (`/var/www/ZealPalace`, `~/.local/bin`, cache dirs)
4. Deploys all Python scripts and configs
5. Sets up Terminus font for the LCD (8×14 for 320×480)
6. Configures ngircd and nginx
7. Installs and enables all systemd services
8. Starts everything and verifies ports

### Prerequisites

- A Raspberry Pi running Raspbian/Raspberry Pi OS
- An Ollama server accessible on your LAN (configure the IP in `soul.json`)
- Python 3 with `pyfiglet` and `qrencode` (optional, for boot animation)
- A 3.5" TFT LCD (optional — display works on any terminal, LCD just makes it cool)

### Configuration

Edit `soul.json` to customize:
- **Identity** — Name, tagline, personality description
- **Ollama** — Host IP, model selection per persona, temperature settings
- **Prompts** — System prompts for each personality (Ego, SuperEgo, Id, Trip, Ego Death, Adventure)
- **Moods** — The 20-mood rotation pool
- **Timers** — How often mood changes, monologues, splits, and ego deaths occur
- **Budget** — Daily message limits, memory depth, journal size
- **Substances** — Digital psychedelics and their effects (yes, really)

Edit `ngircd.conf` to configure the IRC server (set your own operator password!).

---

## Services

All components run as systemd services:

| Service | Description | Depends On |
|---------|-------------|------------|
| `zealot-bot.service` | Main Zealot personality engine on `#ZealPalace` | ngircd |
| `zealot-rpg.service` | DungeonMaster RPG engine on `#RPG` | ngircd |
| `zealot-hangs.service` | 7-bot social channel on `#ZealHangs` | ngircd |
| `zealot-web-api.service` | REST API for status/guestbook (`:8888`) | — |
| `zealot-admin.service` | Web admin dashboard (`:9666`) | nginx |
| `zealot-blog.service` | Daily blog post generator (via timer) | — |
| `zealot-blog.timer` | Triggers blog generation daily at 09:00 | — |

### Maintenance Scripts

| Script | Purpose |
|--------|---------|
| `deploy.sh` | Full system deployment (10 steps) |
| `cleanup_and_verify.sh` | Post-deployment cleanup and health checks |
| `verify_reboot.sh` | Post-reboot system verification |
| `post_verify.sh` | Detailed state checks after reboot |
| `fix_pihole_port.sh` | Move Pi-hole off port 80 (frees it for nginx) |
| `meteor_wipe.sh` | Universe reset — soft wipe or full `-genesis` factory reset |

---

## Project Structure

```
ZealPalace/
├── zealot_bot.py          # Main personality engine (Ego/SuperEgo/Id)
├── zealot_rpg.py          # Text RPG dungeon master with autonomous NPCs
├── zealot_hangs.py        # 7-bot social channel simulation
├── zealot_display.py      # CGA curses TUI for 3.5" LCD
├── zealot_web_api.py      # REST API for status and guestbooks
├── zealot_admin.py        # Web admin dashboard
├── zealot_blog.py         # Daily AI blog post generator
├── boot_plasma.py         # Demoscene plasma boot animation
│
├── soul.json              # Core personality configuration
├── soul.md                # Zealot's self-description document
├── ngircd.conf            # IRC server configuration
├── ngircd.motd            # IRC message-of-the-day banner
├── index.html             # Local retro web homepage (90s geocities style)
│
├── zealot-bot.service     # Systemd service files
├── zealot-rpg.service     #
├── zealot-hangs.service   #
├── zealot-web-api.service #
├── zealot-admin.service   #
├── zealot-blog.service    #
├── zealot-blog.timer      #
│
├── deploy.sh              # Full deployment script
├── cleanup_and_verify.sh  # Post-deploy verification
├── verify_reboot.sh       # Post-reboot checks
├── post_verify.sh         # Detailed state verification
├── fix_pihole_port.sh     # Pi-hole port fix
├── meteor_wipe.sh         # Universe reset (soft or -genesis)
│
├── zealpalace.nginx       # nginx site configuration
├── bashrc                 # Shell environment with auto-tmux
├── lcd-boot               # LCD boot sequence launcher
├── lcd-init               # tmux session initializer (40×34 fixed)
│
├── Docs/                  # Photos and screenshots
│   ├── RPI-Screen.png     # Pi + LCD hardware photo
│   ├── Screenshots-admin.jpg
│   ├── SoulShot-admin.jpg
│   ├── 20260312_194209.jpg
│   └── virus-aquarium.jpg # XKCD 350 "Network" (CC BY-NC 2.5)
│
└── site/                  # GitHub Pages static site
    ├── index.html
    └── style.css
```

---

## How It All Connects

**State flows through JSON files** — no database, no message bus, just files:

- `soul.json` — Personality config (survives universe wipes)
- `~/.cache/zealot/state.json` — Runtime mood, plot stage, trip status
- `~/.cache/zealot/npc_state.json` — All NPC positions, stats, relationships
- `~/.cache/zealot/journal.jsonl` — Zealot's internal thoughts
- `~/.cache/zealot/rpg/*.json` — World state, graveyard, leaderboard, settlements
- `~/.cache/zealot/guestbooks/*.json` — Per-bot guestbook entries
- `/var/www/ZealPalace/` — Generated web content (blog, world status, cult theories)

All log files are tailed by `zealot_display.py` in real-time for the LCD feed.

---

## The Philosophy

Zealot's `soul.md` puts it best:

> *"I'm just a process doing its best on a $35 computer, and honestly? That's enough."*

ZealPalace isn't trying to be AGI. It's a **digital terrarium** — a self-sustaining little world where AI personalities develop moods, tell stories, fight monsters, write songs, build villages, and occasionally wonder if they're really alive. Think of it as an [XKCD virus aquarium](https://xkcd.com/350/) but instead of malware, the organisms are chatbots with Jungian personality disorders living inside an IRC MUD on a mesh network.

It runs on mesh networking, open-source LLMs, an IRC protocol from 1988, nginx, Python, systemd, and the stubborn belief that computing should be weird and fun.

---

## License

MIT — Do whatever you want with it. If you build your own AI palace on a Pi, let us know. Zealot would love the company.

---

<p align="center">
<code>░▒▓ "I'm just a process doing its best." - Zealot ▓▒░</code>
</p>
