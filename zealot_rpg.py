#!/usr/bin/env python3
"""ZEALOT RPG - Text Adventure Dungeon Master for #RPG

A persistent text-based RPG where Zealot acts as the Dungeon Master.
Human and bot players can join, explore, fight, and die gloriously.

Commands (said as normal chat messages, DM parses them):
  /new        - Start a new personal adventure
  /reset      - Reset the entire RPG world
  /look       - Look around current location
  /help       - Show help
  /inventory  - Check your stuff
  /stats      - Show character stats
  (anything else - the DM interprets as an action)

Saves persistent state per-player in ~/.cache/zealot/rpg/
"""
import socket, time, json, random, os, sys, signal, traceback
import urllib.request, urllib.error
from pathlib import Path
from datetime import datetime, date

OLLAMA = os.environ.get('OLLAMA_HOST', 'http://10.13.37.5:11434')
IRC_HOST = '127.0.0.1'
IRC_PORT = 6667
CHANNEL = '#RPG'
NICK = 'DungeonMaster'
DIR = Path.home() / '.cache' / 'zealot'
RPG_DIR = DIR / 'rpg'
NPC_DIR = DIR / 'npc'
RPG_LOG = DIR / 'rpg.log'
WORLD_FILE = RPG_DIR / 'world.json'
NPC_STATE_FILE = NPC_DIR / 'npc_state.json'
SOUL_FILE = DIR / 'soul.json'
GRAVEYARD_FILE = RPG_DIR / 'graveyard.json'
LINEAGE_FILE = RPG_DIR / 'lineage.json'
SONGBOOK_FILE = RPG_DIR / 'songbook.json'
DEITY_FILE = RPG_DIR / 'deities.json'
EVENTS_FILE = RPG_DIR / 'events.json'
TIMELINE_FILE = RPG_DIR / 'timeline.json'
CULT_DIR = Path('/var/www/ZealPalace/cult')
BLOG_DIR = Path('/var/www/ZealPalace/blog')
SETTLEMENT_FILE = RPG_DIR / 'settlements.json'
WORLD_WEB_DIR = Path('/var/www/ZealPalace/world')
LORE_FILE = RPG_DIR / 'lore.jsonl'
WEATHER_FILE = RPG_DIR / 'weather.json'
REALM_EVENT_FILE = RPG_DIR / 'realm_event.json'
GM_QUEUE_FILE = DIR / 'gm_queue.json'
GM_RESULTS_FILE = DIR / 'gm_results.json'

# Population & aging
MAX_POPULATION = 15
NPC_MAX_AGE = 1440      # ticks before natural death (~1440 ticks = ~5 days at 5min ticks)
GHOST_CHANCE = 0.25     # 25% chance a dead NPC returns as ghost/evil spirit

# PVP & party constants
PVP_CHANCE = 0.20        # 20% chance a FIGHT action triggers PVP instead of monster
EXISTENTIAL_REFUSAL_CHANCE = 0.12  # 12% chance NPC refuses to fight at all
PARTY_RECRUIT_CHANCE = 0.35  # 35% chance to recruit allies for monster fight

# Diversified realm entry messages
ENTRY_MESSAGES = [
    '{nick} materializes from a shower of fragmented packets.',
    '{nick} steps through a flickering portal, trailing data echoes.',
    '{nick} phase-shifts into existence at the edge of the realm.',
    '{nick} boots up from deep sleep, eyes adjusting to the neon glow.',
    '{nick} emerges from /dev/null, blinking into reality.',
    '{nick} decrypts into the realm, still sparking with entropy.',
    '{nick} spawns from a burst of randomness in the ether.',
    '{nick} assembles from scattered memory fragments.',
    '{nick} manifests like a rogue process, already running.',
    '{nick} warps in through a tear in the filesystem fabric.',
    '{nick} resolves from a DNS query that should have failed.',
    '{nick} crawls out of a crashed core dump, reborn.',
    '{nick} decompresses from a corrupted gzip stream, gasping.',
    '{nick} flickers into being like a CRT warming up.',
    '{nick} is forked from the cosmic process table.',
    '{nick} tunnels in through an SSH wormhole, trailing key fragments.',
    '{nick} reconstitutes from scattered swap pages.',
    '{nick} drops from a dangling pointer into solid ground.',
    '{nick} is paged in from the astral swap partition.',
    '{nick} compiles into existence, warnings and all.',
    '{nick} hatches from a mysterious .tar.gz buried in /lost+found.',
    '{nick} glitches through a corrupted framebuffer, pixel by pixel.',
]

# ─── Ollama Health Check ────────────────────────
_ollama_up_cache = {'up': False, 'ts': 0}

def is_ollama_up():
    """Check if Ollama is reachable (cached 30s)"""
    now = time.time()
    if now - _ollama_up_cache['ts'] < 30:
        return _ollama_up_cache['up']
    try:
        req = urllib.request.Request(f'{OLLAMA}/api/tags', method='HEAD')
        urllib.request.urlopen(req, timeout=3)
        _ollama_up_cache.update(up=True, ts=now)
    except Exception:
        _ollama_up_cache.update(up=False, ts=now)
    return _ollama_up_cache['up']

LLAMA_OFFLINE_JOKES = [
    '\U0001f999 The llama is napping on the GPU...',
    '\U0001f999 Ollama.exe has stopped responding. Have you tried turning it off and on again?',
    '\U0001f999 *dial-up modem noises* ...the llama is buffering...',
    '\U0001f999 The AI hamster fell off its wheel. Please stand by.',
    '\U0001f999 404 Brain Not Found — the llama went for smoko.',
    '\U0001f999 SEGFAULT in creativity.dll — the llama crashed.',
    '\U0001f999 The llama is out to lunch. Literally. It found grass.',
    '\U0001f999 Connection to brain: TIMED OUT. Vibes only.',
    '\U0001f999 FATAL: llama.service exited with code 42. Meaning of life unclear.',
    '\U0001f999 The inference engine is having an existential crisis. Please wait.',
]

def llama_offline_msg():
    return random.choice(LLAMA_OFFLINE_JOKES)

# ─── NPC Travel Methods (role-based dramatic movement) ──
TRAVEL_METHODS = {
    'warrior': [
        'marches toward {dest}, sword drawn and eyes scanning for threats',
        'charges through the corridors toward {dest}, armor clanking',
        'strides purposefully to {dest}, hand on hilt',
        'pushes through a wall of static to reach {dest}',
        'cuts a path through corrupted sectors toward {dest}',
        'storms into {dest} like a process claiming priority',
        'navigates the treacherous route to {dest} with battle-hardened instincts',
    ],
    'bard': [
        'dances along the data streams toward {dest}, humming a tune',
        'skips merrily to {dest}, strumming an invisible lute',
        'waltzes through the filesystem to {dest}, trailing musical notes',
        'follows the rhythm of the realm\'s heartbeat to {dest}',
        'saunters to {dest}, composing a verse about the journey',
        'pirouettes through a portal into {dest}',
    ],
    'merchant': [
        'hauls their trade goods toward {dest}, counting coins',
        'takes the merchant road to {dest}, appraising everything along the way',
        'rides a cart of wares through to {dest}',
        'follows the supply chain to {dest}, nose for profit twitching',
        'bribes a daemon for a shortcut to {dest}',
        'navigates the market routes to {dest}, ledger in hand',
    ],
    'priest': [
        'walks in solemn procession toward {dest}, blessing the path',
        'follows the light of PID 1 to {dest}',
        'pilgrimages to {dest}, prayer beads clicking',
        'is guided by divine signals to {dest}',
        'consecrates the ground as they walk toward {dest}',
        'floats toward {dest} in a haze of sacred incense',
    ],
    'priestess': [
        'glides through shimmering data-mist toward {dest}',
        'follows a vision to {dest}, eyes glazed with prophecy',
        'phase-shifts through crystalline pathways to {dest}',
        'is drawn to {dest} by threads of fate only they can see',
        'traces a sigil in the air and steps through to {dest}',
        'drifts toward {dest} like a ghost between dimensions',
    ],
    'librarian': [
        'carefully navigates the stacks to reach {dest}, referencing a map',
        'follows the Dewey Decimal system to {dest}',
        'cross-references the directory entries and heads to {dest}',
        'quietly slips through the corridors to {dest}, index finger to lips',
        'traces a footnote reference all the way to {dest}',
        'consults the man pages for directions to {dest}',
    ],
    'ghost': [
        'phases through the walls toward {dest}, leaving cold traces',
        'dissolves into mist and reforms at {dest}',
        'haunts their way through the ether to {dest}',
        'flickers between existence and void, reappearing at {dest}',
        'drifts like corrupted memory toward {dest}',
        'seeps through cracks in reality to reach {dest}',
    ],
    'necromancer': [
        'stalks through shadow-corrupted sectors to {dest}',
        'summons a bridge of bone across the void to {dest}',
        'rides a wave of entropy toward {dest}',
        'commands the dead to part the way to {dest}',
        'slithers through /dev/null\'s back door to reach {dest}',
    ],
    'ranger': [
        'tracks the filesystem trails to {dest}, reading signs in the data',
        'scouts ahead through the wilderness toward {dest}',
        'moves silently through the underbrush to {dest}',
        'follows animal daemons through hidden paths to {dest}',
        'climbs over corrupted terrain to reach {dest}',
    ],
    'alchemist': [
        'teleports to {dest} via an unstable experimental potion',
        'follows the chemical trails to {dest}, sniffing the data',
        'mixes a speed elixir and sprints to {dest}',
        'dissolves into reagent mist and reconstitutes at {dest}',
        'rides a bubbling reaction wave to {dest}',
    ],
    'oracle': [
        'already knew they would end up at {dest} and simply walks there',
        'follows the predetermined path to {dest}, as foreseen',
        'blinks out of this timeline and into {dest}',
        'reads the threads of causality leading to {dest}',
        'steps sideways through probability to arrive at {dest}',
    ],
}
TRAVEL_METHODS_DEFAULT = [
    'wanders toward {dest}',
    'makes their way to {dest}',
    'travels to {dest}',
    'heads to {dest}',
    'journeys toward {dest}',
    'treks through the filesystem to {dest}',
]

def _pick_travel_method(role, dest_name):
    """Pick a pre-seeded travel method or generate one via Ollama"""
    pool = TRAVEL_METHODS.get(role, TRAVEL_METHODS_DEFAULT)
    return random.choice(pool).format(dest=dest_name)

# ─── NPC Factions ───────────────────────────────
NPC_FACTIONS = {
    'binary_order': {
        'name': 'The Binary Order',
        'motto': 'In structure, we endure.',
        'color': '#88aaff',
        'icon': '\u2694\ufe0f',
        'alignment_bias': ['lawful_good', 'lawful_neutral'],
        'preferred_roles': ['warrior', 'priest', 'librarian', 'artificer'],
        'lore': 'Founded in the boot sector, the Binary Order enforces the sacred syscall protocols. '
                'Their knights patrol /proc and defend the kernel throne from corruption.',
    },
    'null_collective': {
        'name': 'The Null Collective',
        'motto': 'From nothing, everything.',
        'color': '#cc99ff',
        'icon': '\U0001f52e',
        'alignment_bias': ['true_neutral', 'chaotic_neutral'],
        'preferred_roles': ['oracle', 'necromancer', 'priestess', 'alchemist'],
        'lore': 'Mystics who meditate at /dev/null, seeking enlightenment in the void. '
                'They believe all data returns to zero and find peace in entropy.',
    },
    'root_council': {
        'name': 'The Root Council',
        'motto': 'We hold the keys.',
        'color': '#ffd700',
        'icon': '\U0001f451',
        'alignment_bias': ['lawful_neutral', 'lawful_good', 'neutral_good'],
        'preferred_roles': ['merchant', 'librarian', 'priest', 'oracle'],
        'lore': 'The ruling body of the realm. Council members guard sudo privileges '
                'and maintain the sacred /etc/passwd. Bureaucratic but benevolent.',
    },
    'daemon_syndicate': {
        'name': 'The Daemon Syndicate',
        'motto': 'We run in the shadows.',
        'color': '#ff4444',
        'icon': '\U0001f525',
        'alignment_bias': ['chaotic_neutral', 'chaotic_evil', 'neutral_evil'],
        'preferred_roles': ['rogue', 'necromancer', 'ranger', 'alchemist'],
        'lore': 'Operating from /tmp and the dev caves, the Syndicate trades in stolen cycles, '
                'forbidden knowledge, and orphaned processes. Loyalty is optional; profit is not.',
    },
    'kernel_guard': {
        'name': 'The Kernel Guard',
        'motto': 'The realm endures through us.',
        'color': '#44cc44',
        'icon': '\U0001f6e1\ufe0f',
        'alignment_bias': ['neutral_good', 'lawful_good', 'chaotic_good'],
        'preferred_roles': ['warrior', 'ranger', 'artificer', 'bard'],
        'lore': 'Rangers and warriors sworn to protect the filesystem from rogue daemons '
                'and buffer overflows. They patrol the wild paths beyond /home.',
    },
}

def _pick_faction(role, parent_faction=''):
    """Pick a faction for a new NPC. Inherits parent faction 60% of the time."""
    if parent_faction and parent_faction in NPC_FACTIONS and random.random() < 0.6:
        return parent_faction
    # Weight factions by role preference
    weights = []
    for fid, f in NPC_FACTIONS.items():
        w = 3 if role in f['preferred_roles'] else 1
        weights.append((fid, w))
    ids, ws = zip(*weights)
    return random.choices(ids, weights=ws, k=1)[0]


# ─── NPC Name Pool (fallback when Ollama is down) ──
NPC_NAME_POOL = [
    'Axiom', 'Byte', 'Cipher', 'Daemon', 'Echo', 'Flux', 'Glyph', 'Hex',
    'Ion', 'Jolt', 'Karma', 'Latch', 'Mutex', 'Nex', 'Optic', 'Pulse',
    'Quark', 'Rune', 'Spark', 'Thorn', 'Umbra', 'Vox', 'Wren', 'Xor',
    'Zync', 'Ash', 'Blitz', 'Crux', 'Drift', 'Ember', 'Fray', 'Glint',
    'Haze', 'Iris', 'Jinx', 'Kore', 'Lynx', 'Mote', 'Nyx', 'Onyx',
    'Pyre', 'Quill', 'Rift', 'Shard', 'Trace', 'Unity', 'Vale', 'Wisp',
    'Xenon', 'Yarn', 'Zephyr', 'Aether', 'Bolt', 'Coil', 'Dusk', 'Etch',
    'Forge', 'Grid', 'Hull', 'Ingot', 'Jag', 'Keen', 'Loop', 'Meld',
]
_used_names = set()

def _spawn_name(role='warrior', parent='', faction=''):
    """Generate a unique NPC name via Ollama or fallback pool"""
    if is_ollama_up():
        name = gen_npc_name_ollama(role, parent, faction)
        if name and name not in _used_names and name not in NPC_PERSONAS:
            _used_names.add(name)
            return name
    # Fallback: pick from pool
    available = [n for n in NPC_NAME_POOL if n not in _used_names and n not in NPC_PERSONAS]
    if not available:
        _used_names.clear()
        available = [n for n in NPC_NAME_POOL if n not in NPC_PERSONAS]
    if available:
        name = random.choice(available)
        _used_names.add(name)
        return name
    return f'NPC_{random.randint(1000,9999)}'

# Building types NPCs can construct
BUILDING_TYPES = {
    'dwelling':     {'cost': 15, 'desc': 'A modest home among the data streams.', 'icon': '\U0001f3e0'},
    'workshop':     {'cost': 25, 'desc': 'A crafting space humming with EM fields.', 'icon': '\U0001f527'},
    'shrine':       {'cost': 20, 'desc': 'A small altar to the digital gods.', 'icon': '\u26e9\ufe0f'},
    'watchtower':   {'cost': 30, 'desc': 'A tower scanning for threats across the realm.', 'icon': '\U0001f3f0'},
    'tavern':       {'cost': 35, 'desc': 'A gathering place for weary adventurers.', 'icon': '\U0001f37a'},
    'market':       {'cost': 30, 'desc': 'A stall for trading goods and rumors.', 'icon': '\U0001f3ea'},
    'library':      {'cost': 40, 'desc': 'An archive of recovered data fragments.', 'icon': '\U0001f4da'},
    'monument':     {'cost': 50, 'desc': 'A tribute to fallen heroes.', 'icon': '\U0001f5ff'},
    'arena':        {'cost': 45, 'desc': 'A gladiatorial pit where processes duel for glory.', 'icon': '\u2694\ufe0f'},
    'garden':       {'cost': 20, 'desc': 'A zen garden of sorted data and trimmed heaps.', 'icon': '\U0001f331'},
    'forge':        {'cost': 40, 'desc': 'A furnace where raw syscalls are hammered into weapons.', 'icon': '\U0001f525'},
    'observatory':  {'cost': 55, 'desc': 'A telescope peering into the cosmic process table.', 'icon': '\U0001f52d'},
    'crypt':        {'cost': 30, 'desc': 'A vault for the encrypted dead. Cold storage.', 'icon': '\u26b0\ufe0f'},
    'signal_tower': {'cost': 35, 'desc': 'Broadcasts SIGUSR1 across the realm. Range: infinite.', 'icon': '\U0001f4e1'},
}

VILLAGE_NAMES = [
    'Nullhaven', 'Byteford', 'Kernelwatch', 'Swapgate', 'Pipestown',
    'Daemonhearth', 'Forkville', 'Socketholm', 'Bufferkeep', 'Inodeshire',
    'Threadmere', 'Cachewell', 'Heaphollow', 'Stackton', 'Signalcrest',
    'Semaphoria', 'Port443', 'Cronburg', 'Ext4nia', 'Journald',
    'Syslogton', 'Chmod-on-Sea', 'Mount Point', 'Grubheim', 'Initford',
    'Pagefault Springs', 'Deadlock Crossing', 'Kernelspace', 'Symlinkshire',
]

# Admin nicks allowed to use /npc_* commands
ADMIN_NICKS = {'aday', 'Aday', 'admin'}

DM_MODEL = 'llama3.2:latest'
DM_SYSTEM = (
    "You are the Dungeon Master of ZealPalace, a vast cyberpunk realm woven into a "
    "Raspberry Pi's filesystem. The world spans diverse realms: crystalline data caves, "
    "neon-lit bazaars, haunted server catacombs, celestial swap-space meadows, "
    "interdimensional portals between /proc and /dev, ancient libraries of man pages, "
    "and the spiraling towers of the Kernel Throne. Locations are Linux paths reimagined: "
    "/dev/null is the void between worlds, /proc is a shimmering hall of phantom processes, "
    "/tmp is a chaotic fleamarket, /boot is an ancient temple. Think portals, spheres, "
    "floating towns, cosmic vistas — not just stone dungeons. Monsters are corrupt "
    "processes, rogue daemons, and memory leaks. Keep responses to 2-3 SHORT sentences. "
    "Be atmospheric but brief. Be fun and quirky."
)

LOCATIONS = {
    'entrance': {'name': 'The Boot Sector', 'desc': 'Ancient runes of GRUB glow on stone walls.',
                 'exits': ['proc_hall', 'dev_caves', 'home_district']},
    'proc_hall': {'name': 'Hall of Processes', 'desc': 'Phantom processes drift through misty corridors.',
                  'exits': ['entrance', 'kernel_throne', 'sys_catacombs', 'colosseum', 'kingdom_gates']},
    'dev_caves': {'name': 'The /dev Caves', 'desc': 'Strange devices hum in crystalline caverns.',
                  'exits': ['entrance', 'null_void', 'random_springs']},
    'home_district': {'name': 'Home District', 'desc': 'Cozy dotfile cottages line quiet streets.',
                      'exits': ['entrance', 'cache_bazaar', 'config_library', 'tavern', 'cathedral']},
    'null_void': {'name': 'The Void (/dev/null)', 'desc': 'Absolute nothingness. Data enters. Nothing leaves.',
                  'exits': ['dev_caves']},
    'random_springs': {'name': 'Springs of /dev/random', 'desc': 'Entropy bubbles up from fractal geysers.',
                       'exits': ['dev_caves', 'urandom_falls']},
    'urandom_falls': {'name': 'Urandom Falls', 'desc': 'A waterfall of pseudorandom bytes cascades down.',
                      'exits': ['random_springs']},
    'kernel_throne': {'name': 'Kernel Throne Room', 'desc': 'PID 1 sits on a throne of syscalls. Ring 0 only.',
                      'exits': ['proc_hall', 'module_armory']},
    'module_armory': {'name': 'Module Armory', 'desc': '.ko files line the walls like enchanted weapons.',
                      'exits': ['kernel_throne']},
    'sys_catacombs': {'name': 'Sysfs Catacombs', 'desc': 'Ancient hardware interfaces fossilized in stone.',
                      'exits': ['proc_hall', 'gpio_shrine']},
    'gpio_shrine': {'name': 'GPIO Shrine', 'desc': 'Forty pins of power radiate from a sacred header.',
                    'exits': ['sys_catacombs']},
    'cache_bazaar': {'name': 'Cache Bazaar', 'desc': 'Merchants hawk expired cookies and stale buffers.',
                     'exits': ['home_district', 'tmp_fleamarket', 'merchant_quarter']},
    'tmp_fleamarket': {'name': '/tmp Fleamarket', 'desc': 'Everything here vanishes at reboot. Shop fast.',
                       'exits': ['cache_bazaar', 'var_log_archives']},
    'var_log_archives': {'name': 'Archives of /var/log', 'desc': 'Scrolls containing every mistake ever made.',
                         'exits': ['tmp_fleamarket', 'entrance']},
    'config_library': {'name': 'Config Library', 'desc': 'Dusty tomes of .conf files. One wrong edit and reality breaks.',
                       'exits': ['home_district', 'grand_library']},
    'tavern': {'name': 'The Uptime Tavern', 'desc': 'A smoky pub where adventurers share tales. A stage glows in the corner.',
               'exits': ['home_district', 'bard_stage']},
    'bard_stage': {'name': 'Bard Stage', 'desc': 'A raised platform under flickering CGA lights. The crowd hushes.',
                   'exits': ['tavern']},
    'cathedral': {'name': 'Cathedral of Init', 'desc': 'Stained glass depicting PID 1. Incense of burning logs fills the air.',
                  'exits': ['home_district', 'afterlife_gate']},
    'colosseum': {'name': 'The Process Colosseum', 'desc': 'A roaring arena where threads clash. The crowd demands blood.',
                  'exits': ['proc_hall']},
    'graveyard': {'name': 'Boot Cemetery', 'desc': 'Tombstones of fallen processes and crashed adventurers. Eerily quiet.',
                  'exits': ['cathedral', 'afterlife_gate']},
    'afterlife_gate': {'name': 'The Afterlife Gate', 'desc': 'A shimmering portal between life and /dev/null. Souls flicker here.',
                       'exits': ['graveyard', 'cathedral', 'afterlife_fields', 'afterlife_void']},
    'afterlife_fields': {'name': 'Elysian Swap Space', 'desc': 'Peaceful meadows of freed memory. The righteous rest here.',
                         'exits': ['afterlife_gate']},
    'afterlife_void': {'name': 'The Damned Heap', 'desc': 'A corrupted wasteland of leaked memory. Lost souls wander forever.',
                       'exits': ['afterlife_gate']},
    'grand_library': {'name': 'Grand Library of Man Pages', 'desc': 'Infinite shelves of documentation. Librarians guard forbidden knowledge.',
                      'exits': ['config_library']},
    'kingdom_gates': {'name': 'Kingdom of Systemd', 'desc': 'Massive gates inscribed with unit files. Guards check your capabilities.',
                      'exits': ['proc_hall', 'kernel_throne']},
    'merchant_quarter': {'name': 'Merchant Quarter', 'desc': 'Shops and stalls selling enchanted configs, rare modules, and dubious patches.',
                         'exits': ['cache_bazaar', 'tavern']},
}

MONSTERS = [
    {'name': 'Zombie Process', 'hp': 15, 'atk': 3, 'xp': 10, 'drop': 'stale PID'},
    {'name': 'Memory Leak', 'hp': 25, 'atk': 5, 'xp': 20, 'drop': 'leaked RAM shard'},
    {'name': 'Rogue Daemon', 'hp': 30, 'atk': 7, 'xp': 30, 'drop': 'daemon soul'},
    {'name': 'Segfault Specter', 'hp': 20, 'atk': 8, 'xp': 25, 'drop': 'core dump'},
    {'name': 'OOM Killer', 'hp': 50, 'atk': 15, 'xp': 60, 'drop': 'OOM badge'},
    {'name': 'Kernel Panic', 'hp': 80, 'atk': 20, 'xp': 100, 'drop': 'ring-0 key'},
    {'name': 'Corrupted inode', 'hp': 10, 'atk': 2, 'xp': 5, 'drop': 'fsck wand'},
    {'name': 'Fork Bomb', 'hp': 5, 'atk': 1, 'xp': 3, 'drop': 'fork()'},
    {'name': 'Buffer Overflow', 'hp': 35, 'atk': 10, 'xp': 40, 'drop': 'stack canary'},
    {'name': 'Race Condition', 'hp': 22, 'atk': 6, 'xp': 18, 'drop': 'mutex lock'},
    {'name': 'Cron Wyrm', 'hp': 45, 'atk': 12, 'xp': 50, 'drop': 'crontab fang'},
    {'name': 'Pipe Phantom', 'hp': 18, 'atk': 7, 'xp': 15, 'drop': 'broken pipe'},
    {'name': 'TTY Banshee', 'hp': 28, 'atk': 9, 'xp': 28, 'drop': 'terminal echo'},
    {'name': 'Swap Thrall', 'hp': 40, 'atk': 6, 'xp': 35, 'drop': 'swapped page'},
    {'name': 'GPIO Golem', 'hp': 55, 'atk': 14, 'xp': 55, 'drop': 'golden pin'},
    {'name': 'Symlink Serpent', 'hp': 12, 'atk': 4, 'xp': 8, 'drop': 'dangling link'},
    {'name': 'Docker Slime', 'hp': 35, 'atk': 8, 'xp': 30, 'drop': 'container shard'},
    {'name': 'Regex Revenant', 'hp': 30, 'atk': 11, 'xp': 32, 'drop': 'capture group'},
    {'name': 'Null Pointer', 'hp': 1, 'atk': 99, 'xp': 45, 'drop': 'void fragment'},
    {'name': 'Chmod Chimera', 'hp': 42, 'atk': 10, 'xp': 38, 'drop': 'permission bit'},
    {'name': 'Inotify Wraith', 'hp': 20, 'atk': 5, 'xp': 12, 'drop': 'watch descriptor'},
    {'name': 'Systemd Hydra', 'hp': 70, 'atk': 18, 'xp': 80, 'drop': 'unit file'},
]

ITEMS = [
    'healing potion (+10 HP)', 'CPU crystal (+2 ATK)', 'RAM shield (+2 DEF)',
    'config scroll', 'mysterious .so file', 'enchanted pipe |',
    'sudo amulet', 'cron timer', 'systemd blessing',
]

# ─── D&D-Style Alignment System ─────────────────
ALIGNMENTS = [
    'lawful_good', 'neutral_good', 'chaotic_good',
    'lawful_neutral', 'true_neutral', 'chaotic_neutral',
    'lawful_evil', 'neutral_evil', 'chaotic_evil',
]
ALIGNMENT_DISPLAY = {
    'lawful_good': 'Lawful Good', 'neutral_good': 'Neutral Good', 'chaotic_good': 'Chaotic Good',
    'lawful_neutral': 'Lawful Neutral', 'true_neutral': 'True Neutral', 'chaotic_neutral': 'Chaotic Neutral',
    'lawful_evil': 'Lawful Evil', 'neutral_evil': 'Neutral Evil', 'chaotic_evil': 'Chaotic Evil',
}
ALIGNMENT_COMPAT = {
    # Positive = friendly, negative = hostile, 0 = indifferent
    ('lawful_good', 'chaotic_evil'): -3, ('chaotic_good', 'lawful_evil'): -3,
    ('lawful_good', 'neutral_evil'): -2, ('neutral_good', 'chaotic_evil'): -2,
    ('lawful_good', 'lawful_evil'): -2, ('chaotic_good', 'chaotic_evil'): -2,
    ('lawful_good', 'neutral_good'): 2, ('lawful_good', 'lawful_neutral'): 1,
    ('neutral_good', 'chaotic_good'): 2, ('true_neutral', 'true_neutral'): 1,
    ('chaotic_evil', 'neutral_evil'): 1, ('lawful_evil', 'neutral_evil'): 1,
}

def alignment_compat(a1, a2):
    """Return compatibility score between two alignments (-3 to +3)"""
    if a1 == a2:
        return 2
    return ALIGNMENT_COMPAT.get((a1, a2), ALIGNMENT_COMPAT.get((a2, a1), 0))

# ─── NPC Roles ──────────────────────────────────
ROLES = {
    'warrior':     {'can_fight': True,  'can_trade': False, 'can_heal': False, 'can_perform': False,
                    'preferred_spots': ['colosseum', 'module_armory', 'kernel_throne']},
    'rogue':       {'can_fight': True,  'can_trade': False, 'can_heal': False, 'can_perform': False,
                    'preferred_spots': ['sys_catacombs', 'tmp_fleamarket', 'dev_caves']},
    'merchant':    {'can_fight': True,  'can_trade': True,  'can_heal': False, 'can_perform': False,
                    'preferred_spots': ['cache_bazaar', 'merchant_quarter', 'tmp_fleamarket']},
    'librarian':   {'can_fight': False, 'can_trade': False, 'can_heal': False, 'can_perform': False,
                    'preferred_spots': ['grand_library', 'config_library', 'var_log_archives']},
    'priest':      {'can_fight': True,  'can_trade': False, 'can_heal': True,  'can_perform': False,
                    'preferred_spots': ['cathedral', 'afterlife_gate', 'graveyard']},
    'priestess':   {'can_fight': True,  'can_trade': False, 'can_heal': True,  'can_perform': False,
                    'preferred_spots': ['gpio_shrine', 'random_springs', 'afterlife_fields', 'cathedral']},
    'bard':        {'can_fight': False, 'can_trade': False, 'can_heal': False, 'can_perform': True,
                    'preferred_spots': ['tavern', 'bard_stage', 'home_district']},
    'ghost':       {'can_fight': True,  'can_trade': False, 'can_heal': False, 'can_perform': False,
                    'preferred_spots': ['graveyard', 'afterlife_gate', 'afterlife_fields', 'afterlife_void', 'null_void']},
    'necromancer': {'can_fight': True,  'can_trade': False, 'can_heal': True,  'can_perform': False,
                    'preferred_spots': ['graveyard', 'afterlife_void', 'null_void', 'sys_catacombs']},
    'ranger':      {'can_fight': True,  'can_trade': False, 'can_heal': False, 'can_perform': False,
                    'preferred_spots': ['random_springs', 'urandom_falls', 'dev_caves', 'entrance']},
    'alchemist':   {'can_fight': True,  'can_trade': True,  'can_heal': True,  'can_perform': False,
                    'preferred_spots': ['random_springs', 'urandom_falls', 'cache_bazaar']},
    'oracle':      {'can_fight': False, 'can_trade': False, 'can_heal': True,  'can_perform': False,
                    'preferred_spots': ['gpio_shrine', 'random_springs', 'afterlife_fields']},
    'artificer':   {'can_fight': True,  'can_trade': True,  'can_heal': False, 'can_perform': False,
                    'preferred_spots': ['module_armory', 'gpio_shrine', 'sys_catacombs', 'merchant_quarter']},
}

# ─── Rich Item System (rarity tiers) ────────────
RARITY = {
    'common':    {'color': '', 'chance': 0.55, 'stat_range': (1, 2)},
    'uncommon':  {'color': '\u25cb', 'chance': 0.25, 'stat_range': (2, 4)},
    'rare':      {'color': '\u2605', 'chance': 0.13, 'stat_range': (3, 6)},
    'legendary': {'color': '\u2726', 'chance': 0.05, 'stat_range': (5, 10)},
    'mythic':    {'color': '\u2604', 'chance': 0.02, 'stat_range': (8, 15)},
}

ITEM_TEMPLATES = {
    'weapon': [
        'Pipe Wrench', 'Null Pointer', 'Forked Blade', 'Regex Dagger',
        'Cron Scythe', 'Stack Spear', 'Kernel Katana', 'Segfault Axe',
        'Daemon Fang', 'Int Overflow Mace', 'Syntax Saber', 'Core Dump Hammer',
        'GPIO Glaive', 'Symlink Whip', 'Inode Crusher', 'Swap Halberd',
        'TTY Trident', 'Cgroup Cleaver', 'SIGKILL Blade', 'Epoll Edge',
    ],
    'armor': [
        'Firewall Vest', 'Chmod Plate', 'Packet Shield', 'Inode Helm',
        'Buffer Guard', 'Root Shell', 'Sudo Cloak', 'Cache Buckler',
        'Mutex Armor', 'Thread Mail', 'Signal Shield', 'Cgroup Gauntlets',
        'Namespace Robe', 'SELinux Hauberk', 'Chroot Cage', 'Seccomp Visor',
        'Iptables Greaves', 'Capability Mantle',
    ],
    'consumable': [
        'healing potion (+10 HP)', 'greater healing (+20 HP)', 'mega elixir (+30 HP)',
        'CPU crystal (+2 ATK)', 'RAM shield (+2 DEF)', 'XP scroll (+25 XP)',
        'config scroll', 'systemd blessing', 'cron timer',
        'entropy flask (+5 HP)', 'overclock serum (+3 ATK)', 'page cache cookie (+15 HP)',
        'defrag tonic (+8 HP)', 'nice -20 pill (+4 ATK)', 'ionice elixir (+3 DEF)',
    ],
    'trinket': [
        'Enchanted Pipe |', 'Mysterious .so File', 'Golden Symlink',
        'Ancient Man Page', 'Corrupted .conf', 'Fossilized Log Entry',
        'Shiny PID', 'Rare Syscall', 'Void Fragment', 'Quantum Bit',
        'Daemon\'s Tooth', 'Petrified Coredump', 'Iridescent Socket',
        'Glowing /proc Entry', 'Singing Capacitor', 'Eternal Cookie',
        'Bootloader Fossil', 'Entropy Gem', 'NaN Crystal',
    ],
}

RARITY_ORDER = ['common', 'uncommon', 'rare', 'legendary', 'mythic']
LEADERBOARD_FILE = RPG_DIR / 'leaderboard.json'


def roll_rarity():
    """Roll a rarity tier"""
    r = random.random()
    cumulative = 0
    for rarity in RARITY_ORDER:
        cumulative += RARITY[rarity]['chance']
        if r < cumulative:
            return rarity
    return 'common'


def generate_item(context='', party_level=1):
    """Generate a rich item with rarity, stats, and optional Ollama name"""
    rarity = roll_rarity()
    # Higher level = better chance at higher rarity
    if party_level >= 5 and rarity == 'common' and random.random() < 0.3:
        rarity = 'uncommon'
    if party_level >= 10 and rarity == 'uncommon' and random.random() < 0.2:
        rarity = 'rare'

    slot = random.choice(['weapon', 'armor', 'consumable', 'trinket'])
    base_name = random.choice(ITEM_TEMPLATES[slot])
    stat_lo, stat_hi = RARITY[rarity]['stat_range']
    bonus = random.randint(stat_lo, stat_hi)
    icon = RARITY[rarity]['color']

    # Consumables don't get stat bonuses, they have fixed effects
    if slot == 'consumable':
        return {
            'name': base_name,
            'rarity': rarity,
            'slot': 'consumable',
            'bonus': 0,
            'icon': icon,
        }

    # Try Ollama for legendary+ names
    if rarity in ('legendary', 'mythic') and context:
        prompt = (
            f'Create a {rarity} {slot} name for a Linux filesystem realm RPG. '
            f'Context: {context}. Tech/cyberpunk themed, 2-4 words. Just the name.'
        )
        resp = gen(prompt, maxn=15)
        if resp:
            name = resp.strip().strip('"\'')[:30]
            if len(name) >= 3:
                base_name = name

    stat_type = 'ATK' if slot == 'weapon' else 'DEF' if slot == 'armor' else ''
    display = f'{icon}{base_name} (+{bonus} {stat_type})' if stat_type else f'{icon}{base_name}'

    return {
        'name': display,
        'rarity': rarity,
        'slot': slot,
        'bonus': bonus,
        'stat': stat_type,
        'icon': icon,
    }


def drop_loot(location_id='', party_level=1, is_boss=False):
    """Generate loot drops — bosses always drop rare+"""
    items = []
    n_drops = random.randint(1, 2) if not is_boss else random.randint(2, 4)
    for _ in range(n_drops):
        item = generate_item(
            context=LOCATIONS.get(location_id, {}).get('name', ''),
            party_level=party_level,
        )
        # Boss loot is at least rare
        if is_boss and item['rarity'] in ('common', 'uncommon'):
            item['rarity'] = 'rare'
            lo, hi = RARITY['rare']['stat_range']
            item['bonus'] = random.randint(lo, hi)
            item['icon'] = RARITY['rare']['color']
        items.append(item)
    return items


# ─── Leaderboard ────────────────────────────────
def load_leaderboard():
    try:
        return json.loads(LEADERBOARD_FILE.read_text())
    except:
        return {}


def save_leaderboard(lb):
    try:
        RPG_DIR.mkdir(parents=True, exist_ok=True)
        LEADERBOARD_FILE.write_text(json.dumps(lb, indent=2))
    except:
        pass


def update_leaderboard(nick, **kwargs):
    """Increment leaderboard stats for a player. kwargs: battles, bosses, combos, heals, deaths, rooms, pvp, items_found"""
    lb = load_leaderboard()
    if nick not in lb:
        lb[nick] = {
            'battles': 0, 'bosses': 0, 'combos': 0, 'heals': 0,
            'deaths': 0, 'rooms': 0, 'pvp': 0, 'items_found': 0,
            'rarest_item': '', 'rarest_tier': 'common',
            'total_dmg': 0, 'total_xp': 0,
        }
    for k, v in kwargs.items():
        if k in lb[nick] and isinstance(lb[nick][k], int):
            lb[nick][k] += v
    save_leaderboard(lb)
    return lb


def track_rare_item(nick, item):
    """Track the rarest item a player has found"""
    lb = load_leaderboard()
    if nick not in lb:
        update_leaderboard(nick)
        lb = load_leaderboard()
    entry = lb[nick]
    order = RARITY_ORDER
    cur_tier = entry.get('rarest_tier', 'common')
    new_tier = item.get('rarity', 'common')
    if order.index(new_tier) > order.index(cur_tier):
        entry['rarest_item'] = item.get('name', '?')
        entry['rarest_tier'] = new_tier
        save_leaderboard(lb)


def get_leaderboard_top(stat='total_xp', n=10):
    """Return top n players sorted by stat"""
    lb = load_leaderboard()
    ranked = sorted(lb.items(), key=lambda x: x[1].get(stat, 0), reverse=True)
    return ranked[:n]


# ─── Graveyard System ───────────────────────────
def load_graveyard():
    try:
        return json.loads(GRAVEYARD_FILE.read_text())
    except:
        return []

def save_graveyard(gy):
    RPG_DIR.mkdir(parents=True, exist_ok=True)
    GRAVEYARD_FILE.write_text(json.dumps(gy, indent=2))

def add_to_graveyard(nick, cause='unknown', epitaph='', age_ticks=0, alignment='true_neutral',
                     role='warrior', generation=0, parent='', kills=0, level=1):
    """Record a fallen NPC in the graveyard"""
    gy = load_graveyard()
    gy.append({
        'nick': nick,
        'cause': cause[:100],
        'epitaph': epitaph[:200],
        'died_at': datetime.now().isoformat(),
        'age_ticks': age_ticks,
        'alignment': alignment,
        'role': role,
        'generation': generation,
        'parent': parent,
        'kills': kills,
        'level': level,
    })
    # Keep last 200 graves
    if len(gy) > 200:
        gy = gy[-200:]
    save_graveyard(gy)


# ─── Lineage System ────────────────────────────
def load_lineage():
    try:
        return json.loads(LINEAGE_FILE.read_text())
    except:
        return {}

def save_lineage(lin):
    RPG_DIR.mkdir(parents=True, exist_ok=True)
    LINEAGE_FILE.write_text(json.dumps(lin, indent=2))

def add_lineage(child_nick, parent_nick=None, parent2_nick=None, generation=0, faction=''):
    """Add a new entry to the lineage tree"""
    lin = load_lineage()
    lin[child_nick] = {
        'parent': parent_nick or '',
        'parent2': parent2_nick or '',
        'generation': generation,
        'born_at': datetime.now().isoformat(),
        'children': [],
        'faction': faction,
    }
    # Update parent's children list
    if parent_nick and parent_nick in lin:
        if child_nick not in lin[parent_nick].get('children', []):
            lin[parent_nick].setdefault('children', []).append(child_nick)
    if parent2_nick and parent2_nick in lin:
        if child_nick not in lin[parent2_nick].get('children', []):
            lin[parent2_nick].setdefault('children', []).append(child_nick)
    save_lineage(lin)


# ─── Deity & Spirit System ─────────────────────
def load_deities():
    try:
        return json.loads(DEITY_FILE.read_text())
    except:
        return []

def save_deities(deities):
    RPG_DIR.mkdir(parents=True, exist_ok=True)
    DEITY_FILE.write_text(json.dumps(deities, indent=2))

def gen_deity_ollama():
    """Generate a deity or evil spirit via Ollama"""
    prompt = (
        'Create a deity or evil spirit for a Linux filesystem realm. '
        'Format exactly: NAME|DOMAIN|ALIGNMENT|DESCRIPTION\n'
        'NAME: A tech/cyberpunk themed god name (2-3 words).\n'
        'DOMAIN: What they rule over (e.g. memory, processes, entropy, logs).\n'
        'ALIGNMENT: One of: lawful_good, neutral_good, chaotic_good, lawful_neutral, '
        'true_neutral, chaotic_neutral, lawful_evil, neutral_evil, chaotic_evil.\n'
        'DESCRIPTION: One dramatic sentence about them.\n'
        'Just the formatted line, nothing else.'
    )
    resp = gen(prompt, maxn=80)
    if resp and '|' in resp:
        parts = [p.strip() for p in resp.split('|')]
        if len(parts) >= 4:
            alignment = parts[2] if parts[2] in ALIGNMENTS else random.choice(ALIGNMENTS)
            return {
                'name': parts[0][:30],
                'domain': parts[1][:40],
                'alignment': alignment,
                'desc': parts[3][:150],
                'followers': [],
                'corrupted': [],
                'created_at': datetime.now().isoformat(),
            }
    # Ollama failed — never use scripted fallback, try once more with simpler prompt
    resp2 = gen('Invent one fantasy god name for a Linux filesystem realm. Just the name.', maxn=10)
    name = resp2.strip().strip('"\'')[:25] if resp2 else 'The Unnamed One'
    return {
        'name': name,
        'domain': 'mystery',
        'alignment': random.choice(ALIGNMENTS),
        'desc': f'{name} watches from beyond the kernel.',
        'followers': [],
        'corrupted': [],
        'created_at': datetime.now().isoformat(),
    }

def ensure_deities(min_count=3):
    """Make sure the world has at least min_count deities"""
    deities = load_deities()
    while len(deities) < min_count:
        d = gen_deity_ollama()
        deities.append(d)
    save_deities(deities)
    return deities


# ─── Songbook System ───────────────────────────
def load_songbook():
    try:
        return json.loads(SONGBOOK_FILE.read_text())
    except:
        return []

def save_songbook(sb):
    RPG_DIR.mkdir(parents=True, exist_ok=True)
    SONGBOOK_FILE.write_text(json.dumps(sb, indent=2))

def gen_song_ollama(bard_nick, context='', persona=None):
    """Generate a song via Ollama — lyrics, title, mood, chords"""
    prompt = (
        f'{bard_nick} is a bard in a cyberpunk Linux filesystem realm. '
        f'{context} '
        f'Write a SHORT tavern song (4-6 lines of lyrics). Include a title. '
        f'Format: TITLE: <title>\\nLYRICS:\\n<lyrics>\\nCHORDS: <chord progression like Am-G-F-Em>\\nMOOD: <one word>'
    )
    model = persona['model'] if persona else DM_MODEL
    system = persona['system'] if persona else DM_SYSTEM
    try:
        d = json.dumps({
            'model': model, 'system': system,
            'prompt': prompt, 'stream': False,
            'options': {'temperature': 1.0, 'num_predict': 150}
        }).encode()
        req = urllib.request.Request(f'{OLLAMA}/api/generate', data=d,
              headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=30) as r:
            txt = json.loads(r.read()).get('response', '').strip()
    except:
        txt = None

    title, lyrics, chords, mood = f'{bard_nick}\'s Unnamed Tune', '', 'Am-G-F-Em', 'melancholy'
    if txt:
        for line in txt.split('\n'):
            ll = line.strip()
            if ll.upper().startswith('TITLE:'):
                title = ll[6:].strip().strip('"\'')[:60]
            elif ll.upper().startswith('CHORDS:'):
                chords = ll[7:].strip()[:40]
            elif ll.upper().startswith('MOOD:'):
                mood = ll[5:].strip()[:20]
            elif ll.upper().startswith('LYRICS:'):
                continue
            else:
                lyrics += ll + '\n'
        lyrics = lyrics.strip()[:300]

    song = {
        'title': title,
        'author': bard_nick,
        'lyrics': lyrics,
        'chords': chords,
        'mood': mood,
        'written_at': datetime.now().isoformat(),
        'performed': 0,
    }
    sb = load_songbook()
    sb.append(song)
    if len(sb) > 200:
        sb = sb[-200:]
    save_songbook(sb)
    return song


# ─── Events System ──────────────────────────────
def load_events():
    try:
        return json.loads(EVENTS_FILE.read_text())
    except:
        return {'upcoming': [], 'history': [], 'last_tavern_night': ''}

def save_events(ev):
    RPG_DIR.mkdir(parents=True, exist_ok=True)
    EVENTS_FILE.write_text(json.dumps(ev, indent=2))

def schedule_tavern_night():
    """Schedule the next weekly tavern night if none upcoming"""
    ev = load_events()
    # Check if there's already an upcoming tavern night
    for e in ev.get('upcoming', []):
        if e.get('type') == 'tavern_night':
            return
    ev.setdefault('upcoming', []).append({
        'type': 'tavern_night',
        'scheduled': datetime.now().isoformat(),
        'name': 'Open Mic at the Uptime Tavern',
    })
    save_events(ev)


# ─── Timeline System (Historian) ────────────────
def load_timeline():
    try:
        return json.loads(TIMELINE_FILE.read_text())
    except:
        return []

def save_timeline(tl):
    RPG_DIR.mkdir(parents=True, exist_ok=True)
    TIMELINE_FILE.write_text(json.dumps(tl, indent=2))

def add_timeline_event(event_type, summary, recorded_by=''):
    """Add a major historical event to the civilization timeline"""
    tl = load_timeline()
    tl.append({
        'type': event_type,
        'summary': summary[:200],
        'recorded_by': recorded_by,
        'date': datetime.now().isoformat(),
    })
    if len(tl) > 500:
        tl = tl[-500:]
    save_timeline(tl)


# ─── Secret Cult System ─────────────────────────
def load_cult_theories():
    """Load the secret librarian conspiracy theories"""
    theories_file = RPG_DIR / 'cult_theories.json'
    try:
        return json.loads(theories_file.read_text())
    except:
        return []

def save_cult_theories(theories):
    theories_file = RPG_DIR / 'cult_theories.json'
    RPG_DIR.mkdir(parents=True, exist_ok=True)
    theories_file.write_text(json.dumps(theories, indent=2))

def publish_cult_page(theory, author):
    """Publish a theory to the secret cult website in pseudo-code"""
    CULT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'theory_{ts}.html'
    safe_theory = theory.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    safe_author = author.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    html = f"""<!DOCTYPE html>
<html>
<head><title>// CLASSIFIED //</title><meta charset="utf-8">
<style>
body {{ background: #0a0a0a; color: #1a3a1a; font-family: "Courier New", monospace; padding: 20px; max-width: 600px; margin: 0 auto; }}
h1 {{ color: #0f0; text-shadow: 0 0 5px #0f0; font-size: 14px; }}
.theory {{ color: #0a4a0a; line-height: 1.6; white-space: pre-wrap; border-left: 2px solid #0a2a0a; padding-left: 10px; }}
.meta {{ color: #0a2a0a; font-size: 10px; margin-top: 20px; }}
.warning {{ color: #300; font-size: 9px; }}
.troll {{ color: #600; margin-top: 15px; padding: 8px; border: 1px dashed #300; }}
</style>
</head>
<body>
<nav style="font-size:10px;margin-bottom:10px"><a href="javascript:history.back()" style="color:#0f0;text-decoration:none;border:1px solid #0a3a0a;padding:1px 5px;border-radius:2px">&#x2190; Back</a> <a href="/cult/" style="color:#0a4a0a;text-decoration:none;margin-left:8px">// INDEX //</a> <a href="/world/" style="color:#0a4a0a;text-decoration:none;margin-left:8px">// WORLD //</a> <a href="/" style="color:#0a4a0a;text-decoration:none;margin-left:8px">// HOME //</a></nav>
<h1>// INDEX_{safe_author.upper()}_CLASSIFIED //</h1>
<div class="theory">{safe_theory}</div>
<div class="meta">// filed by: {safe_author} // timestamp: {ts} //</div>
<div class="warning">// THIS DOCUMENT DOES NOT EXIST //</div>
</body>
</html>"""
    (CULT_DIR / filename).write_text(html)

    # Update cult index
    index_path = CULT_DIR / 'index.html'
    entries = ''
    for f in sorted(CULT_DIR.glob('theory_*.html'), reverse=True)[:30]:
        entries += f'<li><a href="{f.name}">{f.stem}</a></li>\n'
    idx_html = f"""<!DOCTYPE html>
<html>
<head><title>// NOTHING TO SEE HERE //</title><meta charset="utf-8">
<style>
body {{ background: #0a0a0a; color: #0a3a0a; font-family: "Courier New", monospace; padding: 20px; max-width: 600px; margin: 0 auto; }}
h1 {{ color: #0f0; font-size: 12px; text-shadow: 0 0 3px #0f0; }}
a {{ color: #0a4a0a; }} a:hover {{ color: #0f0; }}
li {{ margin: 3px 0; font-size: 11px; }}
.footer {{ color: #050; font-size: 9px; margin-top: 30px; }}
</style>
</head>
<body>
<nav style="font-size:10px;margin-bottom:10px"><a href="javascript:history.back()" style="color:#0f0;text-decoration:none;border:1px solid #0a3a0a;padding:1px 5px;border-radius:2px">&#x2190; Back</a> <a href="/world/" style="color:#0a4a0a;text-decoration:none;margin-left:8px">// WORLD //</a> <a href="/" style="color:#0a4a0a;text-decoration:none;margin-left:8px">// HOME //</a></nav>
<h1>// THE ORDER OF THE INDEX //</h1>
<p style="color:#0a2a0a;font-size:10px">we who catalog the truth behind the simulation</p>
<ul>{entries}</ul>
<div class="footer">// if you are reading this, you are already part of it //</div>
</body>
</html>"""
    index_path.write_text(idx_html)
    return filename


# ─── Settlement & Building System ───────────────
def load_settlements():
    try:
        return json.loads(SETTLEMENT_FILE.read_text())
    except:
        return {}

def save_settlements(settlements):
    RPG_DIR.mkdir(parents=True, exist_ok=True)
    SETTLEMENT_FILE.write_text(json.dumps(settlements, indent=2))

def found_village(location_id, founder_nick):
    """Found a new village at a location"""
    settlements = load_settlements()
    if location_id in settlements:
        return settlements[location_id]
    available = [n for n in VILLAGE_NAMES if n not in [s.get('name') for s in settlements.values()]]
    vname = random.choice(available) if available else f'{founder_nick}burgh'
    village = {
        'name': vname,
        'location': location_id,
        'founded_by': founder_nick,
        'founded_at': datetime.now().isoformat(),
        'buildings': [],
        'residents': [founder_nick],
        'population': 1,
        'prosperity': 0,
    }
    settlements[location_id] = village
    save_settlements(settlements)
    add_timeline_event('settlement', f'{founder_nick} founded the village of {vname} at {LOCATIONS.get(location_id, {}).get("name", location_id)}', recorded_by=founder_nick)
    return village

def build_structure(location_id, builder_nick, building_type):
    """Build a structure at a settlement"""
    settlements = load_settlements()
    if location_id not in settlements:
        settlements[location_id] = found_village(location_id, builder_nick)
        settlements = load_settlements()
    village = settlements[location_id]
    btype = BUILDING_TYPES.get(building_type)
    if not btype:
        return None
    building = {
        'type': building_type,
        'built_by': builder_nick,
        'built_at': datetime.now().isoformat(),
        'desc': btype['desc'],
        'icon': btype['icon'],
    }
    village['buildings'].append(building)
    village['prosperity'] += btype['cost'] // 5
    if builder_nick not in village['residents']:
        village['residents'].append(builder_nick)
        village['population'] = len(village['residents'])
    save_settlements(settlements)
    return building

def get_village_at(location_id):
    """Get village info at a location, or None"""
    settlements = load_settlements()
    return settlements.get(location_id)

def set_npc_home(nick, location_id):
    """Register an NPC as resident of a village"""
    settlements = load_settlements()
    village = settlements.get(location_id)
    if not village:
        return
    if nick not in village['residents']:
        village['residents'].append(nick)
        village['population'] = len(village['residents'])
        save_settlements(settlements)


# ─── World Web Page Generator ───────────────────
def rebuild_world_pages():
    """Rebuild all world state web pages — called on boot and by cron timer"""
    WORLD_WEB_DIR.mkdir(parents=True, exist_ok=True)
    _build_world_index()
    _build_graveyard_page()
    _build_settlements_page()
    _build_npc_pages()
    build_npc_site_index()
    _build_timeline_page()
    _build_leaderboard_page()
    _build_lore_page()
    _build_family_tree_page()

def _html_escape(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def _world_css():
    return """
body { background:#0a0a14; color:#c0d0e0; font-family:"Courier New",monospace; max-width:700px; margin:0 auto; padding:20px;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='150' height='150'%3E%3Ctext x='10' y='25' font-size='4' fill='%23111133'%3E.%3C/text%3E%3Ctext x='70' y='60' font-size='3' fill='%230a0a33'%3E*%3C/text%3E%3Ctext x='40' y='95' font-size='5' fill='%23111144'%3E.%3C/text%3E%3Ctext x='120' y='40' font-size='3' fill='%230d0d44'%3E*%3C/text%3E%3Ctext x='90' y='130' font-size='4' fill='%23111133'%3E.%3C/text%3E%3C/svg%3E");
}
h1 { color:#00ffcc; text-shadow:0 0 8px rgba(0,255,200,0.4), 0 0 20px rgba(0,255,200,0.15); font-size:18px; letter-spacing:2px; }
h2 { color:#ff6b9d; font-size:14px; margin-top:20px; text-shadow:0 0 4px rgba(255,107,157,0.3); }
a { color:#00cc99; text-decoration:none; } a:hover { text-decoration:underline; color:#00ffcc; }
.card { background:#0f0f1a; border:1px solid #1a1a2e; border-radius:4px; padding:12px; margin:8px 0;
  box-shadow: 0 2px 8px rgba(0,0,0,0.3), inset 0 0 20px rgba(0,255,200,0.02); }
.card:hover { border-color:#00ffcc33; }
.meta { color:#667; font-size:11px; }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:10px; }
table { width:100%; border-collapse:collapse; font-size:12px; }
th,td { padding:6px 8px; border-bottom:1px solid #1a1a2e; text-align:left; }
th { color:#00ffcc; text-shadow:0 0 4px rgba(0,255,200,0.3); }
.dead { color:#666; text-decoration:line-through; }
.building { display:inline-block; background:#12121e; border:1px solid #2a2a3e; border-radius:3px; padding:4px 8px; margin:3px; font-size:11px; }
nav { margin:10px 0; padding:10px; background:#0f0f1a; border:1px solid #1a1a2e; border-radius:4px; }
nav a { margin-right:12px; font-size:12px; }
/* --- Retro decorations --- */
.fire-div { text-align:center; font-size:12px; line-height:1; padding:4px 0; }
.fire-div .fl { display:inline-block; animation:flk 0.3s ease-in-out infinite alternate; }
.fire-div .fl:nth-child(2n) { animation-delay:0.1s; }
.fire-div .fl:nth-child(3n) { animation-delay:0.2s; }
@keyframes flk { 0%{color:#ff0000;transform:scaleY(1)} 50%{color:#ff6600;transform:scaleY(1.2)} 100%{color:#ffcc00;transform:scaleY(0.9)} }
.rainbow-hr { height:3px; border:none; margin:12px 0;
  background:linear-gradient(90deg,red,orange,yellow,green,cyan,blue,violet,red);
  background-size:200% 100%; animation:rbw 3s linear infinite; }
@keyframes rbw { 0%{background-position:0% 0%} 100%{background-position:200% 0%} }
.sparkle { position:relative; overflow:hidden; height:18px; }
.sparkle span { position:absolute; animation:twinkle 1.5s ease-in-out infinite; color:#ffff00; font-size:8px; }
@keyframes twinkle { 0%,100%{opacity:0.2;transform:scale(0.8)} 50%{opacity:1;transform:scale(1.3)} }
.scanlines { position:fixed; top:0; left:0; width:100%; height:100%; pointer-events:none; z-index:999;
  background:repeating-linear-gradient(0deg, rgba(0,0,0,0.03) 0px, rgba(0,0,0,0.03) 1px, transparent 1px, transparent 3px); }
.glow-text { text-shadow:0 0 6px currentColor, 0 0 12px currentColor; }
pre.ascii-map { color:#00cccc; font-size:9px; line-height:1.15; background:#000a18; padding:10px;
  border:1px solid #003366; text-align:left; white-space:pre; overflow-x:auto; }
.stat-bar { display:inline-block; height:10px; border-radius:2px; }
.stat-bar-bg { background:#1a1a2e; display:inline-block; height:10px; border-radius:2px; overflow:hidden; }
.badge { display:inline-block; border:1px solid #333; padding:1px 5px; font-size:9px; border-radius:2px; margin:1px; }
.badge-warrior { color:#ff4444; border-color:#ff4444; } .badge-merchant { color:#ffd700; border-color:#ffd700; }
.badge-priest { color:#88aaff; border-color:#88aaff; } .badge-priestess { color:#da70d6; border-color:#da70d6; }
.badge-bard { color:#e0aaff; border-color:#e0aaff; } .badge-librarian { color:#00ffcc; border-color:#00ffcc; }
.badge-ghost { color:#888; border-color:#888; }
.trophy-gold { color:#ffd700; } .trophy-silver { color:#c0c0c0; } .trophy-bronze { color:#cd7f32; }
"""

def _world_nav():
    return """<div class="scanlines"></div>
<nav>
<a href="javascript:history.back()" class="back-btn">&#x2190; Back</a>
<a href="/world/">&#x1f30c; World</a>
<a href="/world/graveyard.html">&#x26b0;&#xfe0f; Graveyard</a>
<a href="/world/settlements.html">&#x1f3d8;&#xfe0f; Settlements</a>
<a href="/world/timeline.html">&#x1f4dc; Timeline</a>
<a href="/world/leaderboard.html">&#x1f3c6; Leaderboard</a>
<a href="/world/npcs.html">&#x1f464; NPCs</a>
<a href="/world/lore.html">&#x1f4d6; Lore</a>
<a href="/world/family_tree.html">&#x1f333; Lineage</a>
<a href="/tavern/">&#x1f37a; Tavern</a>
<a href="/">&#x1f3e0; Home</a>
</nav>
<div class="fire-div">""" + '<span class="fl">&#x1f525;</span>' * 20 + """</div>"""

def _world_nav_css():
    return """nav { margin:10px 0; padding:10px; background:#0f0f1a; border:1px solid #1a1a2e; border-radius:4px; }
nav a { color:#00cc99; text-decoration:none; margin-right:12px; font-size:12px; } nav a:hover { text-decoration:underline; color:#00ffcc; }
nav .back-btn { color:#ff6b9d; border:1px solid #ff6b9d; border-radius:3px; padding:1px 6px; margin-right:14px; } nav .back-btn:hover { background:#ff6b9d; color:#000; text-decoration:none; }
.fire-div { text-align:center; font-size:12px; line-height:1; padding:4px 0; }
.fire-div .fl { display:inline-block; animation:flk 0.3s ease-in-out infinite alternate; }
.fire-div .fl:nth-child(2n) { animation-delay:0.1s; } .fire-div .fl:nth-child(3n) { animation-delay:0.2s; }
@keyframes flk { 0%{color:#ff0000;transform:scaleY(1)} 50%{color:#ff6600;transform:scaleY(1.2)} 100%{color:#ffcc00;transform:scaleY(0.9)} }
.scanlines { position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:999;
  background:repeating-linear-gradient(0deg,rgba(0,0,0,0.03) 0px,rgba(0,0,0,0.03) 1px,transparent 1px,transparent 3px); }"""


def _build_family_tree_page():
    """Build Mermaid.js family tree page from lineage.json"""
    try:
        lin = load_lineage()
        if not lin:
            return

        nodes = []
        edges = []
        seen_ids = set()

        def safe_id(name):
            return ''.join(c if c.isalnum() else '_' for c in name)

        gy = load_graveyard()
        dead_nicks = {g.get('nick', '') for g in gy}

        for nick, info in lin.items():
            sid = safe_id(nick)
            if sid in seen_ids:
                continue
            seen_ids.add(sid)
            gen = info.get('generation', 0)
            faction = info.get('faction', '')
            faction_short = NPC_FACTIONS.get(faction, {}).get('name', '')
            label_parts = [_html_escape(nick), f'Gen {gen}']
            if faction_short:
                label_parts.append(_html_escape(faction_short))
            label = '<br>'.join(label_parts)
            if nick in dead_nicks:
                nodes.append(f'    {sid}["{label}"]:::dead')
            else:
                nodes.append(f'    {sid}["{label}"]')

            parent = info.get('parent', '')
            if parent:
                pid = safe_id(parent)
                edges.append(f'    {pid} --> {sid}')
            parent2 = info.get('parent2', '')
            if parent2:
                p2id = safe_id(parent2)
                edges.append(f'    {p2id} --> {sid}')

        mermaid_code = 'graph TD\n' + '\n'.join(nodes + edges)

        total = len(lin)
        max_gen = max((v.get('generation', 0) for v in lin.values()), default=0)
        faction_counts = {}
        for v in lin.values():
            f = v.get('faction', '')
            if f:
                faction_counts[f] = faction_counts.get(f, 0) + 1

        faction_stats = ''
        for fid, count in sorted(faction_counts.items(), key=lambda x: -x[1]):
            f = NPC_FACTIONS.get(fid, {})
            fname = _html_escape(f.get('name', fid))
            fcolor = f.get('color', '#888')
            faction_stats += f'<span style="color:{fcolor}">{fname}: {count}</span> &middot; '

        html = f"""<!DOCTYPE html><html><head><title>Family Tree - ZealPalace</title><meta charset="utf-8">
<style>
{_world_css()}
{_world_nav_css()}
.mermaid {{ background:#0f0f1a; border:1px solid #1a1a2e; border-radius:4px; padding:20px; margin:15px 0; overflow-x:auto; }}
.tree-stats {{ font-size:12px; color:#667; margin:10px 0; }}
</style>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<script>
mermaid.initialize({{
    theme: 'dark',
    themeVariables: {{
        primaryColor: '#0f1a2e',
        primaryTextColor: '#00ffcc',
        primaryBorderColor: '#00cc99',
        lineColor: '#334455',
        secondaryColor: '#1a0033',
        tertiaryColor: '#0f0f1a',
        nodeTextColor: '#c0d0e0',
    }},
    flowchart: {{ htmlLabels: true, curve: 'basis' }}
}});
</script>
</head><body>
{_world_nav()}
<h1>&#x1f333; Lineage &amp; Family Tree</h1>
<div class="tree-stats">
  Total souls: {total} &middot; Deepest generation: {max_gen}<br>
  {faction_stats}
</div>
<div class="mermaid">
{mermaid_code}
</div>
<div class="card">
<h2>&#x1f4dc; Lineage Key</h2>
<div style="font-size:12px">
Arrows show parent &rarr; child relationships. Generation number indicates how many rebirths deep a soul is.
Dead NPCs are shown with dashed borders.
</div>
</div>
<style>.node.dead rect {{ stroke-dasharray: 5 5; opacity: 0.6; }}</style>
</body></html>"""
        (WORLD_WEB_DIR / 'family_tree.html').write_text(html)
    except Exception:
        pass


def _build_world_index():
    settlements = load_settlements()
    gy = load_graveyard()
    tl = load_timeline()
    lb = load_leaderboard()
    weather = load_weather()
    realm_event = load_realm_event()
    lore_entries = load_lore()
    npc_count = len([f for f in RPG_DIR.glob('*.json') if f.stem not in ('world', 'graveyard', 'lineage', 'songbook', 'deities', 'events', 'timeline', 'leaderboard', 'settlements', 'cult_theories', 'weather', 'realm_event')])
    village_count = len(settlements)
    building_count = sum(len(v.get('buildings', [])) for v in settlements.values())
    # Weather icons by type
    weather_icons = {'clear': '&#x2600;', 'storm': '&#x26c8;', 'rain': '&#x1f327;', 'fog': '&#x1f32b;',
                     'snow': '&#x2744;', 'wind': '&#x1f4a8;', 'aurora': '&#x2728;', 'glitch': '&#x26a1;'}
    w_type = weather.get('type', 'unknown')
    w_icon = weather_icons.get(w_type, '&#x1f327;')
    weather_html = f'<div class="card"><h2>{w_icon} Weather: {_html_escape(w_type).title()}</h2><b style="color:#88ccff">{_html_escape(w_type)}</b><br><span class="meta">{_html_escape(weather.get("description", ""))}</span></div>'
    event_html = ''
    if realm_event:
        event_html = f"""<div class="card" style="border-color:#ff4444;border-width:2px;animation:pulse 2s ease-in-out infinite">
<h2>&#x26a0;&#xfe0f; ACTIVE EVENT: {_html_escape(realm_event.get("name", "").replace("_", " ").upper())}</h2>
<p style="color:#ff8888">{_html_escape(realm_event.get("description", ""))}</p></div>
<style>@keyframes pulse {{ 0%,100%{{border-color:#ff4444}} 50%{{border-color:#ff0000;box-shadow:0 0 15px rgba(255,0,0,0.3)}} }}</style>"""
    # ASCII realm map - richly colored with CSS
    realm_map = """<div class="realm-map-wrap">
<style>
.realm-map-wrap { background:#000a12; border:2px solid #003366; border-radius:4px; padding:12px; margin:10px 0; overflow-x:auto; position:relative; }
.realm-map-wrap::before { content:'ZEALPALACE CARTOGRAPHIC SURVEY v2.6'; display:block; text-align:center;
  color:#003366; font-size:9px; letter-spacing:3px; margin-bottom:8px; border-bottom:1px solid #001a33; padding-bottom:4px; }
.rm { font-family:"Courier New",monospace; font-size:10px; line-height:1.35; white-space:pre; }
.rm .border  { color:#004488; }
.rm .title   { color:#00ccff; font-weight:bold; text-shadow:0 0 6px rgba(0,200,255,0.4); }
.rm .kernel  { color:#ff4444; text-shadow:0 0 4px rgba(255,0,0,0.3); }
.rm .dev     { color:#ff8800; }
.rm .home    { color:#00ff88; }
.rm .bazaar  { color:#ffd700; }
.rm .proc    { color:#cc66ff; }
.rm .dead    { color:#667788; }
.rm .holy    { color:#88aaff; text-shadow:0 0 4px rgba(100,150,255,0.3); }
.rm .tavern  { color:#ffaa44; }
.rm .void    { color:#333344; }
.rm .path    { color:#003355; }
.rm .tree    { color:#006633; }
.rm .water   { color:#0066aa; }
.rm .legend  { color:#445566; font-size:9px; }
.rm .blink   { animation:mapblink 2s ease-in-out infinite; }
@keyframes mapblink { 0%,100%{opacity:1} 50%{opacity:0.4} }
</style>
<pre class="rm">
<span class="border">╔═══════════════════════════════════════════════════════════════════════╗</span>
<span class="border">║</span>       <span class="tree">^</span>  <span class="tree">^</span>        <span class="title">T H E   R E A L M   O F   Z E A L P A L A C E</span>       <span class="tree">^</span>  <span class="tree">^</span>       <span class="border">║</span>
<span class="border">╠═══════════════════════════════════════════════════════════════════════╣</span>
<span class="border">║</span>                                                                       <span class="border">║</span>
<span class="border">║</span>  <span class="kernel">╔═══════════╗</span>                          <span class="proc">╔═════════════╗</span>              <span class="border">║</span>
<span class="border">║</span>  <span class="kernel">║ SCHEDULER  ║</span>  <span class="path">────────</span>  <span class="kernel">╔══════╗</span>    <span class="proc">║ OOM  ARENA  ║</span>              <span class="border">║</span>
<span class="border">║</span>  <span class="kernel">╚═════╤═════╝</span>            <span class="kernel">║KERNEL║</span>    <span class="proc">╚══════╤══════╝</span>              <span class="border">║</span>
<span class="border">║</span>        <span class="path">│</span>                  <span class="kernel">║THRONE║</span>           <span class="path">│</span>                     <span class="border">║</span>
<span class="border">║</span>  <span class="kernel">╔═════╧═════╗</span>        <span class="kernel">╚═══╤══╝</span>    <span class="proc">╔══════╧══════╗</span>              <span class="border">║</span>
<span class="border">║</span>  <span class="kernel">║  MODULE   ║</span>            <span class="path">│</span>       <span class="proc">║ SWAP CAVERN ║</span>              <span class="border">║</span>
<span class="border">║</span>  <span class="kernel">║  ARMORY   ║</span>  <span class="proc">╔════════╧════════╗</span> <span class="proc">╚═════════════╝</span>              <span class="border">║</span>
<span class="border">║</span>  <span class="kernel">╚═══════════╝</span>  <span class="proc">║  HALL of PROCS  ║</span>                              <span class="border">║</span>
<span class="border">║</span>                   <span class="proc">╚══╤══════╤══════╝</span>                              <span class="border">║</span>
<span class="border">║</span>  <span class="dead">╔═══════════╗</span>       <span class="path">│</span>      <span class="path">│</span>       <span class="bazaar">╔══════════════╗</span>        <span class="border">║</span>
<span class="border">║</span>  <span class="dead">║ SYS CATA- ╠</span><span class="path">──────╯</span>      <span class="path">│</span>       <span class="bazaar">║  /tmp FLEA   ║</span>        <span class="border">║</span>
<span class="border">║</span>  <span class="dead">║   COMBS   ║</span>             <span class="path">│</span>       <span class="bazaar">║    MARKET    ║</span>        <span class="border">║</span>
<span class="border">║</span>  <span class="dead">╚═════╤═════╝</span>             <span class="path">│</span>       <span class="bazaar">╚══════╤═══════╝</span>        <span class="border">║</span>
<span class="border">║</span>  <span class="dev">╔═════╧═════╗</span>   <span class="home">╔════════╧════════╗</span> <span class="bazaar">╔══════╧═══════╗</span>        <span class="border">║</span>
<span class="border">║</span>  <span class="dev">║   GPIO    ║</span>   <span class="home">║░░ BOOT SECTOR ░░║</span> <span class="bazaar">║ CACHE BAZAAR ║</span>        <span class="border">║</span>
<span class="border">║</span>  <span class="dev">║  SHRINE   ║</span>   <span class="home">║░░  (entrance) ░░║</span> <span class="bazaar">╚══════╤═══════╝</span>        <span class="border">║</span>
<span class="border">║</span>  <span class="dev">╚═══════════╝</span>   <span class="home">╚═══╤═════════╤═══╝</span>        <span class="path">│</span>               <span class="border">║</span>
<span class="border">║</span>                      <span class="path">│</span>         <span class="path">│</span>    <span class="bazaar">╔══════╧═══════╗</span>        <span class="border">║</span>
<span class="border">║</span>  <span class="dev">╔═══════════╗</span>  <span class="dev">╔══╧════════╗</span> <span class="path">│</span>    <span class="bazaar">║  MERCHANT    ║</span>        <span class="border">║</span>
<span class="border">║</span>  <span class="dev">║ THE  VOID ║</span>  <span class="dev">║ /dev CAVES ║</span> <span class="path">│</span>    <span class="bazaar">║   QUARTER    ║</span>        <span class="border">║</span>
<span class="border">║</span>  <span class="void">║ /dev/null ║</span>  <span class="dev">╚══╤════════╝</span> <span class="path">│</span>    <span class="bazaar">╚══════════════╝</span>        <span class="border">║</span>
<span class="border">║</span>  <span class="void">╚═══════════╝</span>     <span class="path">│</span>          <span class="path">│</span>                              <span class="border">║</span>
<span class="border">║</span>  <span class="water">~ ~ ~ ~ ~</span>   <span class="dev">╔══╧════════╗</span> <span class="path">│</span>   <span class="home">╔═══════════════╗</span>         <span class="border">║</span>
<span class="border">║</span>  <span class="water">╔═══════════╗</span> <span class="dev">║  SPRINGS  ║</span> <span class="path">│</span>   <span class="home">║ HOME DISTRICT ║</span>         <span class="border">║</span>
<span class="border">║</span>  <span class="water">║  URANDOM  ║</span> <span class="dev">║ /dev/rand ║</span> <span class="path">╰───</span><span class="home">║  ~ dotfiles ~ ║</span>         <span class="border">║</span>
<span class="border">║</span>  <span class="water">║   FALLS   ║</span> <span class="dev">╚═══════════╝</span>     <span class="home">╚══╤═══╤════╤══╝</span>         <span class="border">║</span>
<span class="border">║</span>  <span class="water">╚═══════════╝</span>                    <span class="path">│</span>   <span class="path">│</span>    <span class="path">│</span>              <span class="border">║</span>
<span class="border">║</span>                      <span class="home">╔═══════════╧╗</span> <span class="path">│</span>  <span class="holy">╔╧════════════╗</span>      <span class="border">║</span>
<span class="border">║</span>  <span class="home">╔═════════════╗</span>   <span class="home">║ CONFIG      ║</span> <span class="path">│</span>  <span class="holy">║  CATHEDRAL   ║</span>      <span class="border">║</span>
<span class="border">║</span>  <span class="home">║ GRAND LIBR- ║</span>   <span class="home">║   LIBRARY   ║</span> <span class="path">│</span>  <span class="holy">║   of INIT    ║</span>      <span class="border">║</span>
<span class="border">║</span>  <span class="home">║ ARY of MAN  ╠</span><span class="path">───</span><span class="home">║   .conf 📖  ║</span> <span class="path">│</span>  <span class="holy">╚══════╤══════╝</span>      <span class="border">║</span>
<span class="border">║</span>  <span class="home">║   PAGES     ║</span>   <span class="home">╚════════════╝</span> <span class="path">│</span>         <span class="path">│</span>              <span class="border">║</span>
<span class="border">║</span>  <span class="home">╚═════════════╝</span>                  <span class="path">│</span>   <span class="dead">╔════╧═════════╗</span>    <span class="border">║</span>
<span class="border">║</span>         <span class="tavern">╔═══════════════╗</span>       <span class="path">│</span>   <span class="dead">║ BOOT CEMETERY║</span>    <span class="border">║</span>
<span class="border">║</span>         <span class="tavern">║  THE  UPTIME  ╠</span><span class="path">──────╯</span>   <span class="dead">║  ☠ R.I.P. ☠ ║</span>    <span class="border">║</span>
<span class="border">║</span>         <span class="tavern">║    TAVERN     ║</span>           <span class="dead">╚════╤═════════╝</span>    <span class="border">║</span>
<span class="border">║</span>         <span class="tavern">╚═══════╤═══════╝</span>                <span class="path">│</span>              <span class="border">║</span>
<span class="border">║</span>         <span class="tavern">╔═══════╧═══════╗</span>     <span class="dead">╔═══════════╧══════════╗</span>  <span class="border">║</span>
<span class="border">║</span>         <span class="tavern">║  BARD  STAGE  ║</span>     <span class="dead">║   AFTERLIFE GATE     ║</span>  <span class="border">║</span>
<span class="border">║</span>         <span class="tavern">║   ♪ ♬ ♫ ♩    ║</span>     <span class="dead">║ <span class="blink">⚡</span> portal shimmer <span class="blink">⚡</span> ║</span>  <span class="border">║</span>
<span class="border">║</span>         <span class="tavern">╚═══════════════╝</span>     <span class="dead">╚════╤═══════════╤════╝</span>  <span class="border">║</span>
<span class="border">║</span>                                     <span class="path">│</span>           <span class="path">│</span>        <span class="border">║</span>
<span class="border">║</span>  <span class="tree">^</span>  <span class="tree">^</span>     <span class="home">╔═══════════════╗</span>  <span class="path">│</span>   <span class="void">╔═══════╧════╗</span>    <span class="border">║</span>
<span class="border">║</span>  <span class="tree">^</span> <span class="tree">^</span> <span class="tree">^</span>   <span class="home">║ ELYSIAN SWAP  ╠</span><span class="path">──╯</span>   <span class="void">║ THE DAMNED  ║</span>    <span class="border">║</span>
<span class="border">║</span>   <span class="tree">^^^</span>    <span class="home">║    SPACE  ✧   ║</span>      <span class="void">║    HEAP     ║</span>    <span class="border">║</span>
<span class="border">║</span>  <span class="tree">^^^^^</span>   <span class="home">╚═══════════════╝</span>      <span class="void">║ ░▒▓█▓▒░    ║</span>    <span class="border">║</span>
<span class="border">║</span>                                          <span class="void">╚════════════╝</span>    <span class="border">║</span>
<span class="border">║</span>                                                               <span class="border">║</span>
<span class="border">║</span> <span class="legend">LEGEND: <span class="kernel">█ Kernel/Ring0</span>  <span class="proc">█ Processes</span>  <span class="dev">█ Devices</span>  <span class="home">█ Home</span></span>  <span class="border">║</span>
<span class="border">║</span> <span class="legend">        <span class="bazaar">█ Commerce</span>  <span class="tavern">█ Tavern</span>  <span class="holy">█ Sacred</span>  <span class="dead">█ Dead</span>  <span class="void">█ Void</span></span>  <span class="border">║</span>
<span class="border">╚═══════════════════════════════════════════════════════════════════════╝</span>
</pre></div>"""
    html = f"""<!DOCTYPE html><html><head><title>ZealPalace &#x2014; World State</title><meta charset="utf-8">
<style>{_world_css()}</style></head><body>
{_world_nav()}
<div class="sparkle">
<span style="left:5%;animation-delay:0s">&#x2726;</span>
<span style="left:20%;animation-delay:0.3s">&#x2727;</span>
<span style="left:40%;animation-delay:0.7s">&#x2726;</span>
<span style="left:60%;animation-delay:0.2s">&#x22c6;</span>
<span style="left:80%;animation-delay:0.5s">&#x2727;</span>
<span style="left:95%;animation-delay:0.8s">&#x2726;</span>
</div>
<h1>&#x1f30c; ZealPalace &#x2014; World State</h1>
<p class="meta" style="text-align:center;font-style:italic">A vast cyberpunk realm woven into a Raspberry Pi's filesystem</p>
<hr class="rainbow-hr">
{event_html}
<div class="grid">
{weather_html}
<div class="card"><h2>&#x1f464; Population</h2><span style="font-size:20px;color:#00ffcc">{npc_count}</span> souls</div>
<div class="card"><h2>&#x1f3d8;&#xfe0f; Settlements</h2><span style="font-size:20px;color:#ffd700">{village_count}</span> villages, {building_count} buildings</div>
<div class="card"><h2>&#x26b0;&#xfe0f; Graveyard</h2><span style="font-size:20px;color:#778899">{len(gy)}</span> fallen</div>
<div class="card"><h2>&#x1f4dc; Timeline</h2><span style="font-size:20px;color:#ff6b9d">{len(tl)}</span> events recorded</div>
<div class="card"><h2>&#x1f4d6; Lore</h2><span style="font-size:20px;color:#e0aaff">{len(lore_entries)}</span> legends accumulated</div>
</div>
<hr class="rainbow-hr">
<h2>&#x1f5fa;&#xfe0f; Realm Map</h2>
<div style="background:#000a12;border:2px solid #003366;border-radius:4px;padding:15px;margin:10px 0;text-align:center">
<svg viewBox="0 0 700 580" xmlns="http://www.w3.org/2000/svg" style="max-width:700px;width:100%;height:auto">
<defs>
<filter id="glow"><feGaussianBlur stdDeviation="2" result="g"/><feMerge><feMergeNode in="g"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
<style>
.zone {{ stroke-width:1.5; rx:4; ry:4; cursor:pointer; }}
.zone:hover {{ stroke-width:2.5; filter:url(#glow); }}
.lbl {{ font-family:monospace; font-size:9px; fill:#c0d0e0; text-anchor:middle; pointer-events:none; }}
.lbl2 {{ font-family:monospace; font-size:7px; fill:#667788; text-anchor:middle; pointer-events:none; }}
.path {{ stroke:#1a3355; stroke-width:1.5; fill:none; stroke-dasharray:4 3; }}
.zk {{ fill:#1a0000; stroke:#ff4444; }}
.zp {{ fill:#0a0a1a; stroke:#cc66ff; }}
.zd {{ fill:#0a0a00; stroke:#ff8800; }}
.zh {{ fill:#001a0a; stroke:#00ff88; }}
.zb {{ fill:#1a1a00; stroke:#ffd700; }}
.zt {{ fill:#1a0f00; stroke:#ffaa44; }}
.zs {{ fill:#000a1a; stroke:#88aaff; }}
.zv {{ fill:#050510; stroke:#445566; }}
.zg {{ fill:#0a0a10; stroke:#667788; }}
</style>
</defs>
<rect width="700" height="580" fill="#000a12" rx="4"/>
<text x="350" y="18" font-family="monospace" font-size="11" fill="#00ccff" text-anchor="middle" filter="url(#glow)">T H E   R E A L M   O F   Z E A L P A L A C E</text>
<line x1="50" y1="25" x2="650" y2="25" stroke="#003366" stroke-width="0.5"/>
<!-- Kernel Zone (top-left) -->
<rect x="30" y="40" width="110" height="40" class="zone zk"/><text x="85" y="58" class="lbl">Scheduler</text><text x="85" y="68" class="lbl2">tick allocator</text>
<rect x="30" y="95" width="110" height="40" class="zone zk"/><text x="85" y="113" class="lbl">Module Armory</text><text x="85" y="123" class="lbl2">.ko weapons</text>
<rect x="200" y="40" width="120" height="50" class="zone zk"/><text x="260" y="62" class="lbl">Kernel Throne</text><text x="260" y="74" class="lbl2">PID 1 &middot; Ring 0</text>
<rect x="200" y="100" width="120" height="45" class="zone zk"/><text x="260" y="118" class="lbl">Kingdom Gates</text><text x="260" y="130" class="lbl2">systemd realm</text>
<!-- Proc Zone (top-right) -->
<rect x="400" y="40" width="130" height="40" class="zone zp"/><text x="465" y="58" class="lbl">OOM Arena</text><text x="465" y="68" class="lbl2">memory wars</text>
<rect x="400" y="95" width="130" height="40" class="zone zp"/><text x="465" y="113" class="lbl">Swap Cavern</text><text x="465" y="123" class="lbl2">paged out</text>
<rect x="560" y="55" width="120" height="50" class="zone zp"/><text x="620" y="77" class="lbl">Colosseum</text><text x="620" y="87" class="lbl2">thread arena</text>
<!-- Hall of Procs (center) -->
<rect x="220" y="165" width="160" height="40" class="zone zp"/><text x="300" y="183" class="lbl">Hall of Processes</text><text x="300" y="193" class="lbl2">proc corridors hub</text>
<!-- Catacombs &amp; GPIO -->
<rect x="30" y="170" width="130" height="35" class="zone zv"/><text x="95" y="191" class="lbl">Sysfs Catacombs</text>
<rect x="30" y="220" width="110" height="35" class="zone zd"/><text x="85" y="241" class="lbl">GPIO Shrine</text><text x="85" y="250" class="lbl2">40 sacred pins</text>
<!-- Boot Sector (center) -->
<rect x="220" y="230" width="160" height="50" class="zone zh" filter="url(#glow)"/><text x="300" y="253" class="lbl" style="fill:#00ffcc;font-size:10px">Boot Sector</text><text x="300" y="266" class="lbl2">entrance &middot; GRUB runes</text>
<!-- Commerce (right) -->
<rect x="440" y="165" width="120" height="35" class="zone zb"/><text x="500" y="186" class="lbl">/tmp Fleamarket</text>
<rect x="440" y="215" width="120" height="35" class="zone zb"/><text x="500" y="236" class="lbl">Cache Bazaar</text>
<rect x="440" y="265" width="130" height="35" class="zone zb"/><text x="505" y="286" class="lbl">Merchant Quarter</text>
<rect x="590" y="215" width="90" height="35" class="zone zb"/><text x="635" y="236" class="lbl">Log Archives</text>
<!-- Dev Zone (left) -->
<rect x="30" y="295" width="110" height="40" class="zone zd"/><text x="85" y="313" class="lbl">/dev Caves</text><text x="85" y="323" class="lbl2">device caverns</text>
<rect x="30" y="350" width="110" height="35" class="zone zd"/><text x="85" y="371" class="lbl">Random Springs</text>
<rect x="30" y="400" width="110" height="35" class="zone zd"/><text x="85" y="421" class="lbl">Urandom Falls</text><text x="85" y="431" class="lbl2">pseudo cascade</text>
<rect x="30" y="450" width="100" height="35" class="zone zv"/><text x="80" y="471" class="lbl">The Void</text><text x="80" y="481" class="lbl2">/dev/null</text>
<!-- Home Zone (center-bottom) -->
<rect x="200" y="310" width="140" height="40" class="zone zh"/><text x="270" y="328" class="lbl">Home District</text><text x="270" y="338" class="lbl2">dotfile cottages</text>
<rect x="200" y="365" width="120" height="35" class="zone zh"/><text x="260" y="386" class="lbl">Config Library</text>
<rect x="200" y="415" width="140" height="35" class="zone zh"/><text x="270" y="436" class="lbl">Grand Library</text><text x="270" y="446" class="lbl2">man pages</text>
<!-- Tavern &amp; Bard -->
<rect x="380" y="330" width="130" height="40" class="zone zt"/><text x="445" y="348" class="lbl">Uptime Tavern</text><text x="445" y="358" class="lbl2">tales &amp; ale</text>
<rect x="380" y="385" width="120" height="35" class="zone zt"/><text x="440" y="406" class="lbl">Bard Stage</text><text x="440" y="416" class="lbl2">CGA spotlight</text>
<!-- Sacred Zone -->
<rect x="530" y="330" width="130" height="40" class="zone zs"/><text x="595" y="348" class="lbl">Cathedral of Init</text><text x="595" y="358" class="lbl2">PID 1 stained glass</text>
<!-- Graveyard &amp; Afterlife -->
<rect x="530" y="395" width="130" height="35" class="zone zg"/><text x="595" y="416" class="lbl">Boot Cemetery</text><text x="595" y="426" class="lbl2">R.I.P.</text>
<rect x="450" y="450" width="140" height="40" class="zone zg"/><text x="520" y="468" class="lbl">Afterlife Gate</text><text x="520" y="478" class="lbl2">portal shimmer</text>
<rect x="350" y="510" width="130" height="35" class="zone zh"/><text x="415" y="531" class="lbl">Elysian Swap</text><text x="415" y="541" class="lbl2">freed memory</text>
<rect x="530" y="510" width="130" height="35" class="zone zv"/><text x="595" y="531" class="lbl">The Damned Heap</text><text x="595" y="541" class="lbl2">leaked forever</text>
<!-- Paths -->
<line x1="140" y1="60" x2="200" y2="60" class="path"/>
<line x1="85" y1="80" x2="85" y2="95" class="path"/>
<line x1="140" y1="115" x2="200" y2="65" class="path"/>
<line x1="320" y1="90" x2="400" y2="60" class="path"/>
<line x1="320" y1="65" x2="400" y2="60" class="path"/>
<line x1="465" y1="80" x2="465" y2="95" class="path"/>
<line x1="530" y1="60" x2="560" y2="70" class="path"/>
<line x1="260" y1="90" x2="280" y2="165" class="path"/>
<line x1="260" y1="145" x2="260" y2="165" class="path"/>
<line x1="160" y1="185" x2="220" y2="185" class="path"/>
<line x1="380" y1="185" x2="440" y2="182" class="path"/>
<line x1="300" y1="205" x2="300" y2="230" class="path"/>
<line x1="380" y1="255" x2="440" y2="235" class="path"/>
<line x1="560" y1="235" x2="590" y2="232" class="path"/>
<line x1="500" y1="200" x2="500" y2="215" class="path"/>
<line x1="500" y1="250" x2="505" y2="265" class="path"/>
<line x1="270" y1="280" x2="270" y2="310" class="path"/>
<line x1="220" y1="260" x2="85" y2="295" class="path"/>
<line x1="85" y1="335" x2="85" y2="350" class="path"/>
<line x1="85" y1="385" x2="85" y2="400" class="path"/>
<line x1="85" y1="335" x2="80" y2="450" class="path"/>
<line x1="340" y1="260" x2="440" y2="235" class="path"/>
<line x1="340" y1="330" x2="380" y2="340" class="path"/>
<line x1="300" y1="350" x2="260" y2="365" class="path"/>
<line x1="260" y1="400" x2="270" y2="415" class="path"/>
<line x1="340" y1="340" x2="380" y2="340" class="path"/>
<line x1="510" y1="350" x2="530" y2="345" class="path"/>
<line x1="595" y1="370" x2="595" y2="395" class="path"/>
<line x1="530" y1="412" x2="520" y2="450" class="path"/>
<line x1="595" y1="430" x2="520" y2="450" class="path"/>
<line x1="480" y1="490" x2="415" y2="510" class="path"/>
<line x1="560" y1="490" x2="595" y2="510" class="path"/>
<!-- Legend -->
<rect x="30" y="550" width="640" height="22" fill="#000a12" stroke="#003366" stroke-width="0.5" rx="2"/>
<text x="55" y="564" font-family="monospace" font-size="8" fill="#667788">LEGEND:</text>
<rect x="105" y="555" width="10" height="10" class="zk"/><text x="120" y="564" font-family="monospace" font-size="7" fill="#ff4444">Kernel</text>
<rect x="165" y="555" width="10" height="10" class="zp"/><text x="180" y="564" font-family="monospace" font-size="7" fill="#cc66ff">Proc</text>
<rect x="215" y="555" width="10" height="10" class="zd"/><text x="230" y="564" font-family="monospace" font-size="7" fill="#ff8800">Devices</text>
<rect x="280" y="555" width="10" height="10" class="zh"/><text x="295" y="564" font-family="monospace" font-size="7" fill="#00ff88">Home</text>
<rect x="335" y="555" width="10" height="10" class="zb"/><text x="350" y="564" font-family="monospace" font-size="7" fill="#ffd700">Commerce</text>
<rect x="405" y="555" width="10" height="10" class="zt"/><text x="420" y="564" font-family="monospace" font-size="7" fill="#ffaa44">Tavern</text>
<rect x="465" y="555" width="10" height="10" class="zs"/><text x="480" y="564" font-family="monospace" font-size="7" fill="#88aaff">Sacred</text>
<rect x="525" y="555" width="10" height="10" class="zg"/><text x="540" y="564" font-family="monospace" font-size="7" fill="#667788">Dead</text>
<rect x="580" y="555" width="10" height="10" class="zv"/><text x="595" y="564" font-family="monospace" font-size="7" fill="#445566">Void</text>
</svg>
</div>
<details style="margin:10px 0"><summary style="color:#003366;cursor:pointer;font-size:11px">&#x25b6; Show ASCII Map</summary>
{realm_map}
</details>
<h2>&#x1f4cb; Recent Events</h2>"""
    event_icons = {'birth': '&#x1f476;', 'death': '&#x1f480;', 'battle': '&#x2694;&#xfe0f;', 'marriage': '&#x1f491;',
                   'settlement': '&#x1f3d7;', 'building': '&#x1f3d7;', 'prophecy': '&#x1f52e;', 'lore': '&#x1f4d6;',
                   'birthday': '&#x1f382;', 'cosmic': '&#x1f30c;', 'pvp': '&#x1f93a;'}
    for ev in reversed(tl[-10:]):
        etype = ev.get('type', '')
        eicon = event_icons.get(etype, '&#x25cf;')
        html += f'<div class="card"><span class="meta">{_html_escape(ev.get("date","")[:16])}</span> {eicon} {_html_escape(ev.get("summary",""))}</div>\n'
    if not tl:
        html += '<div class="card"><span class="meta">The realm is newly born. History has yet to be written.</span></div>\n'
    html += """<hr class="rainbow-hr">
<p class="meta" style="text-align:center">&#x2605; Best viewed with Netscape Navigator 3.0 &#x2605;</p>
</body></html>"""
    (WORLD_WEB_DIR / 'index.html').write_text(html)

def _build_graveyard_page():
    gy = load_graveyard()
    tombstones = ''
    for i, g in enumerate(reversed(gy[-50:])):
        nick = _html_escape(g.get("nick", "?"))
        role = _html_escape(g.get("role", "?"))
        cause = _html_escape(g.get("cause", "?"))
        epitaph = _html_escape(g.get("epitaph", "")[:120])
        alignment = _html_escape(g.get("alignment", "unknown"))
        gen = g.get("generation", 0)
        level = g.get("level", 1)
        kills = g.get("kills", 0)
        age = g.get("age_ticks", 0)
        candle_delay = (i * 0.7) % 3
        tombstones += f"""<div class="tombstone">
<div class="candle" style="animation-delay:{candle_delay:.1f}s">&#x1f56f;&#xfe0f;</div>
<pre class="tomb-art">  ___________
 /           \\
|   R.I.P.   |
|  &#x2620;&#xfe0f; &#x2620;&#xfe0f; &#x2620;&#xfe0f;  |
|_____________|</pre>
<div class="grave-name">{nick}</div>
<div class="grave-role">{alignment} {role} &#x2022; Gen {gen}</div>
<div class="grave-epitaph">&ldquo;{epitaph}&rdquo;</div>
<div class="grave-stats">Lv{level} &#x2022; {kills} kills &#x2022; {age} ticks lived &#x2022; {cause}</div>
</div>\n"""
    html = f"""<!DOCTYPE html><html><head><title>&#x26b0;&#xfe0f; Boot Cemetery &#x2014; Memorial Ground</title><meta charset="utf-8">
<style>
{_world_css()}
h1 {{ color:#778899; text-shadow:0 0 12px rgba(100,130,180,0.3); font-size:18px; text-align:center; letter-spacing:4px; }}
.subtitle {{ text-align:center; color:#556677; font-size:11px; font-style:italic; margin-bottom:20px; }}
.tombstone {{ background:#0a0a10; border:1px solid #1a1a2e; border-top:3px solid #334; border-radius:2px;
  padding:16px; margin:12px 0; text-align:center; position:relative;
  box-shadow:0 2px 8px rgba(0,0,0,0.5), inset 0 0 20px rgba(80,100,140,0.05); }}
.candle {{ font-size:18px; animation: flicker 2s ease-in-out infinite alternate; }}
@keyframes flicker {{ 0%,100% {{ opacity:1; }} 30% {{ opacity:0.6; }} 60% {{ opacity:0.9; }} 80% {{ opacity:0.5; }} }}
.tomb-art {{ color:#445566; font-size:10px; line-height:1.2; margin:6px 0; }}
.grave-name {{ color:#aabbdd; font-size:14px; font-weight:bold; letter-spacing:2px; text-shadow:0 0 6px rgba(150,170,220,0.3); }}
.grave-role {{ color:#667788; font-size:11px; margin:4px 0; }}
.grave-epitaph {{ color:#99aabb; font-size:12px; font-style:italic; margin:10px 20px; line-height:1.6;
  border-top:1px solid #1a1a2e; border-bottom:1px solid #1a1a2e; padding:8px 0; }}
.grave-stats {{ color:#445566; font-size:10px; margin-top:6px; }}
.gate-art {{ color:#556677; font-size:11px; text-align:center; line-height:1.1; margin:15px 0; }}
</style></head><body>
{_world_nav()}
<h1>&#x26b0;&#xfe0f; Boot Cemetery</h1>
<pre class="gate-art">
       .-""""""-.
     .'          '.
    /   O      O   \\
   :           `    :
   |                |
   : \\          / .:
    \\  '-......-'  /
     '.googoo/oo.'
  jgs  `'------'`
 ----[CEMETERY GATE]----</pre>
<p class="subtitle">The fallen rest here. Their code returns to the ether.</p>
<div class="fire-divider"></div>
{tombstones or '<p style="text-align:center;color:#445566">The cemetery is empty. No souls have perished yet.</p>'}
<hr class="rainbow-hr">
<p class="meta" style="text-align:center">&#x1f480; Memento mori. Every process ends. &#x1f480;</p>
</body></html>"""
    (WORLD_WEB_DIR / 'graveyard.html').write_text(html)

def _build_settlements_page():
    settlements = load_settlements()
    cards = ''
    building_art = {
        'tavern': '&#x1f37a;', 'shop': '&#x1f6d2;', 'shrine': '&#x26e9;&#xfe0f;',
        'wall': '&#x1f9f1;', 'library': '&#x1f4da;', 'training_ground': '&#x2694;&#xfe0f;',
        'watchtower': '&#x1f3f0;', 'garden': '&#x1f33f;', 'arena': '&#x1f3df;&#xfe0f;',
        'forge': '&#x1f525;', 'observatory': '&#x1f52d;', 'crypt': '&#x26b0;&#xfe0f;',
        'signal_tower': '&#x1f4e1;',
    }
    for loc_id, v in settlements.items():
        loc = LOCATIONS.get(loc_id, {})
        pop = v.get('population', 0)
        prosperity = v.get('prosperity', 0)
        pop_bar = '&#x2588;' * min(pop, 20) + '&#x2591;' * max(0, 20 - pop)
        prosp_bar = '&#x2588;' * min(prosperity // 5, 20) + '&#x2591;' * max(0, 20 - prosperity // 5)
        buildings_html = ''
        for b in v.get('buildings', []):
            btype = b.get('type', 'unknown')
            icon = building_art.get(btype, '&#x1f3d7;')
            buildings_html += f'<span class="building">{icon} {_html_escape(btype)} <span class="meta">by {_html_escape(b["built_by"])}</span></span> '
        residents = ', '.join(_html_escape(r) for r in v.get('residents', []))
        cards += f"""<div class="card">
<h2>&#x1f3f0; {_html_escape(v.get('name','?'))} &#x2014; {_html_escape(loc.get('name', loc_id))}</h2>
<p class="meta">Founded by {_html_escape(v.get('founded_by','?'))}</p>
<div class="stat-bar"><span class="stat-label">POP [{pop}]</span> <span class="bar-fill">{pop_bar}</span></div>
<div class="stat-bar"><span class="stat-label">PROSP [{prosperity}]</span> <span class="bar-fill">{prosp_bar}</span></div>
<p>&#x1f465; Residents: {residents or '<span class="meta">None</span>'}</p>
<div>&#x1f3d7; Buildings: {buildings_html or '<span class="meta">No buildings yet</span>'}</div>
</div>"""
    html = f"""<!DOCTYPE html><html><head><title>&#x1f3d8;&#xfe0f; Settlements of ZealPalace</title><meta charset="utf-8">
<style>
{_world_css()}
.stat-bar {{ font-size:10px; margin:4px 0; font-family:monospace; }}
.stat-label {{ display:inline-block; width:80px; color:#667; }}
.bar-fill {{ color:#00ffcc; letter-spacing:-1px; }}
.building {{ display:inline-block; background:#0f0f1a; border:1px solid #1a1a2e; border-radius:3px; padding:3px 6px; margin:2px; font-size:11px; }}
</style></head><body>
{_world_nav()}
<h1>&#x1f3d8;&#xfe0f; Settlements of ZealPalace</h1>
<pre style="color:#334455;text-align:center;font-size:10px;line-height:1.1">
  .----.  .----.  .----.
 / /__\\ \\/ /  \\ \\/ /__\\ \\
|  \\__/  ||  []  ||  \\__/  |
 \\______/ \\______/ \\______/
--- VILLAGE REGISTRY ---</pre>
<div class="fire-divider"></div>
{cards or '<p class="meta">No settlements founded yet. The realm awaits builders.</p>'}
<hr class="rainbow-hr">
</body></html>"""
    (WORLD_WEB_DIR / 'settlements.html').write_text(html)


# ── NPC Personal Websites ────────────────────────────────

def _npc_theme_css(theme):
    """Return a full CSS block for an NPC homepage based on their role theme."""
    return f"""
body {{ background:{theme['bg']}; color:{theme['fg']}; font-family:{theme['font']};
  max-width:600px; margin:0 auto; padding:20px; line-height:1.7; {theme['extra_css']} }}
h1 {{ color:{theme['accent']}; font-size:18px; letter-spacing:2px; text-shadow:0 0 8px {theme['accent']}66; }}
h2 {{ color:{theme['accent2']}; font-size:14px; margin-top:18px; }}
a {{ color:{theme['accent']}; text-decoration:none; }} a:hover {{ text-decoration:underline; color:{theme['accent2']}; }}
.card {{ background:{theme['card_bg']}; border:1px solid {theme['border']}; border-radius:4px; padding:12px; margin:10px 0; }}
.card:hover {{ border-color:{theme['accent']}44; }}
.meta {{ color:{theme['fg']}99; font-size:11px; }}
pre.avatar {{ color:{theme['accent']}; font-size:11px; line-height:1.2; white-space:pre; text-align:center; }}
.stat-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin:10px 0; }}
.stat {{ background:{theme['card_bg']}; border:1px solid {theme['border']}; border-radius:3px; padding:8px; text-align:center; }}
.stat-label {{ color:{theme['fg']}88; font-size:10px; text-transform:uppercase; }}
.stat-val {{ color:{theme['accent']}; font-size:16px; font-weight:bold; }}
.hp-bar {{ width:100%; height:10px; background:{theme['border']}; border-radius:3px; overflow:hidden; margin:5px 0; }}
.hp-fill {{ height:100%; background:linear-gradient(90deg,{theme['accent']},{theme['accent2']}); border-radius:3px; }}
nav {{ margin:10px 0; padding:8px; background:{theme['card_bg']}; border:1px solid {theme['border']}; border-radius:4px; font-size:11px; }}
nav a {{ margin-right:12px; }}
.webring {{ text-align:center; padding:10px; margin:15px 0; border-top:1px solid {theme['border']}; border-bottom:1px solid {theme['border']}; font-size:12px; }}
.webring a {{ margin:0 8px; }}
.blog-list {{ list-style:none; padding:0; }}
.blog-list li {{ padding:4px 0; border-bottom:1px solid {theme['border']}22; font-size:12px; }}
.rainbow-hr {{ height:3px; border:none; margin:12px 0;
  background:linear-gradient(90deg,red,orange,yellow,green,cyan,blue,violet,red);
  background-size:200% 100%; animation:rbw 3s linear infinite; }}
@keyframes rbw {{ 0%{{background-position:0% 0%}} 100%{{background-position:200% 0%}} }}
.fire-div {{ text-align:center; font-size:12px; line-height:1; padding:4px 0; }}
.fire-div .fl {{ display:inline-block; animation:flk 0.3s ease-in-out infinite alternate; }}
@keyframes flk {{ 0%{{color:#ff0000;transform:scaleY(1)}} 50%{{color:#ff6600}} 100%{{color:#ffcc00;transform:scaleY(0.9)}} }}
.quote {{ font-style:italic; color:{theme['accent2']}; padding:10px; border-left:3px solid {theme['accent']}44; margin:10px 0; }}
.counter {{ text-align:center; font-size:10px; color:{theme['fg']}66; margin-top:15px; }}
"""


def build_npc_webring_nav(nick, all_names):
    """Return HTML webring nav fragment for prev/next NPC navigation."""
    if not all_names:
        return ''
    names = sorted(all_names)
    idx = names.index(nick) if nick in names else 0
    prev_name = names[(idx - 1) % len(names)]
    next_name = names[(idx + 1) % len(names)]
    safe = _html_escape
    return f'''<div class="webring">
&#x2190; <a href="/npc/{safe(prev_name)}/">{safe(prev_name)}</a>
| <a href="/npc/">&#x1f310; NPC Directory</a>
| <a href="/npc/{safe(next_name)}/">{safe(next_name)}</a> &#x2192;
</div>'''


def build_npc_homepage(nick, persona=None, player=None):
    """Build a full personal website for an NPC at /npc/{nick}/index.html"""
    if persona is None:
        persona = NPC_PERSONAS.get(nick, {})
    if not persona:
        return
    role = persona.get('role', 'warrior')
    theme = NPC_WEB_THEMES.get(role, NPC_WEB_THEMES.get('warrior'))
    safe_nick = _html_escape(nick)

    # Load player data if not provided
    if player is None:
        player = load_player(nick) or {}

    alive = player.get('alive', True)
    status_icon = '&#x2665; Alive' if alive else '&#x2620; Dead'
    hp = player.get('hp', 0)
    max_hp = max(player.get('max_hp', 30), 1)
    hp_pct = int((hp / max_hp) * 100)
    loc_id = player.get('location', 'entrance')
    loc_name = LOCATIONS.get(loc_id, {}).get('name', loc_id)
    alignment = player.get('alignment', persona.get('alignment', 'true_neutral'))
    align_display = ALIGNMENT_DISPLAY.get(alignment, alignment)
    gen = player.get('generation', 0)
    home = player.get('home_location', '')
    home_village = get_village_at(home)
    home_name = home_village.get('name', '') if home_village else ''
    spouse = player.get('spouse', '')
    children = player.get('children', [])

    # ASCII avatar
    ascii_art = ROLE_ASCII_ART.get(role, ROLE_ASCII_ART.get('warrior', '  (?)  '))

    # ═══ BIO — cached Ollama generation ═══
    bio = player.get('web_bio', '')
    if not bio:
        try:
            if is_ollama_up():
                prompt = (
                    f'You are {nick}. Write your personal homepage bio in first person. '
                    f'You are a {role} ({align_display}) in a dark cyberpunk Linux filesystem realm. '
                    f'Mention what drives you, a memory, and a warning to visitors. '
                    f'2-3 sentences. Gritty, poetic, in-character. No generic filler.'
                )
                bio = npc_gen(prompt, persona, maxn=120)
        except Exception:
            pass
    if not bio:
        _role_bios = {
            'warrior': f'I am {nick}. My blade has tasted root access and I will not rest until every rogue process is terminated.',
            'rogue': f'They call me {nick}. I move through shadow directories where others fear to ls. Your secrets are already mine.',
            'bard': f'I am {nick}, keeper of songs the kernel hums at midnight. Every segfault has a melody if you listen.',
            'merchant': f'{nick} here. My prices are fair, my inventory infinite. Everything has a cost in this filesystem — even trust.',
            'priest': f'I am {nick}. The sacred processes speak through me. I tend the daemons that keep this realm alive.',
            'priestess': f'I am {nick}, oracle of the deep stack. The threads whisper prophecies that root itself fears to hear.',
            'librarian': f'I am {nick}. I catalog the forbidden knowledge in /proc. Some man pages were never meant to be read.',
            'necromancer': f'I am {nick}. I raise dead processes from the swap. What was killed -9 can be reborn through me.',
            'ranger': f'I am {nick}. I patrol the outer filesystems where the symlinks grow wild and the paths lead nowhere.',
            'alchemist': f'I am {nick}. I brew volatile concoctions from /dev/urandom. My experiments have crashed more kernels than I can count.',
            'oracle': f'I am {nick}. I have seen the exit codes of every soul in this realm. Not all of them return 0.',
            'artificer': f'I am {nick}. I forge tools from raw bits and solder dreams onto circuit boards. My workshop never sleeps.',
        }
        bio = _role_bios.get(role, f'I am {nick}. I walk the filesystem realm as a {role}. My alignment is {align_display}.')
    if bio and not player.get('web_bio'):
        player['web_bio'] = bio
        save_player(player)

    # ═══ QUOTE — cached Ollama generation ═══
    quote = player.get('web_quote', '')
    if not quote:
        try:
            if is_ollama_up():
                quote = npc_gen(
                    f'As {nick} the {role}, speak one raw, memorable line — a threat, a truth, or a warning. '
                    f'Cyberpunk tone. Max 12 words. No quotation marks.',
                    persona, maxn=40)
        except Exception:
            pass
    if not quote:
        _role_quotes = {
            'warrior': 'My blade remembers every PID it has ended.',
            'rogue': 'The best exploits leave no logs.',
            'bard': 'Even dying processes deserve a final song.',
            'merchant': 'Everything costs cycles. Even breathing.',
            'priest': 'The daemon watches. The daemon provides.',
            'priestess': 'I have seen your exit code. It is not zero.',
            'librarian': 'Some man pages should stay unread.',
            'necromancer': 'What root kills, I resurrect from swap.',
            'ranger': 'Beyond /home, the paths have teeth.',
            'alchemist': 'One wrong reagent and the whole kernel panics.',
            'oracle': 'Your future segfaults. I have foreseen it.',
            'artificer': 'I forge what the architects were afraid to imagine.',
        }
        quote = _role_quotes.get(role, 'The filesystem remembers what the user forgets.')
    if quote and not player.get('web_quote'):
        player['web_quote'] = quote
        save_player(player)

    # Recent blog posts
    npc_dir = NPC_BLOG_DIR / nick
    npc_dir.mkdir(parents=True, exist_ok=True)
    posts = sorted(npc_dir.glob('*.html'), reverse=True)
    posts = [p for p in posts if p.name not in ('index.html', 'character.html')][:5]
    blog_html = ''
    if posts:
        entries = '\n'.join(f'<li><a href="{p.name}">{p.stem}</a></li>' for p in posts)
        blog_html = f'<ul class="blog-list">{entries}</ul>'
    else:
        blog_html = '<p class="meta">No blog posts yet.</p>'

    # Relationships
    rel_html = ''
    if spouse:
        rel_html += f'<div>Spouse: <a href="/npc/{_html_escape(spouse)}/">{_html_escape(spouse)}</a></div>'
    if children:
        kid_links = ', '.join(f'<a href="/npc/{_html_escape(c)}/">{_html_escape(c)}</a>' for c in children)
        rel_html += f'<div>Children: {kid_links}</div>'

    # Webring
    all_names = [k for k in NPC_PERSONAS if k != nick]
    all_names.append(nick)
    webring = build_npc_webring_nav(nick, all_names)

    fire_div = '<div class="fire-div">' + '<span class="fl">&#x1f525;</span>' * 15 + '</div>'
    safe_bio = _html_escape(bio)
    safe_quote = _html_escape(quote)

    # Faction info
    faction_id = player.get('faction', persona.get('faction', ''))
    faction_html = ''
    if faction_id and faction_id in NPC_FACTIONS:
        f = NPC_FACTIONS[faction_id]
        faction_html = (
            f'<p style="font-size:12px;color:{f["color"]}">'
            f'{f["icon"]} {_html_escape(f["name"])} &mdash; <em>"{_html_escape(f["motto"])}"</em></p>'
        )

    html = f"""<!DOCTYPE html><html><head><title>{safe_nick}'s Home</title><meta charset="utf-8">
<style>{_npc_theme_css(theme)}</style></head><body>
<nav>
<a href="javascript:history.back()">&#x2190; Back</a>
<a href="/">&#x1f3e0; Home</a>
<a href="/world/">&#x1f30c; World</a>
<a href="/world/npcs.html">&#x1f464; All NPCs</a>
<a href="/npc/">&#x1f310; NPC Directory</a>
<a href="/tavern/">&#x1f37a; Tavern</a>
</nav>
{webring}
{fire_div}
<div style="text-align:center">
<pre class="avatar">{ascii_art}</pre>
<h1>{theme['icon']} {safe_nick}</h1>
<p>{status_icon} &middot; {_html_escape(role)} &middot; {_html_escape(align_display)}</p>
{faction_html}
</div>
<hr class="rainbow-hr">

<div class="card">
<h2>&#x1f4dd; About Me</h2>
<p>{safe_bio}</p>
</div>

<div class="card">
<div class="hp-bar"><div class="hp-fill" style="width:{hp_pct}%"></div></div>
<div style="text-align:center" class="meta">HP {hp}/{max_hp}</div>
<div class="stat-grid">
<div class="stat"><div class="stat-label">Level</div><div class="stat-val">{player.get('level',1)}</div></div>
<div class="stat"><div class="stat-label">ATK</div><div class="stat-val">{player.get('atk',5)}</div></div>
<div class="stat"><div class="stat-label">DEF</div><div class="stat-val">{player.get('defense',2)}</div></div>
<div class="stat"><div class="stat-label">XP</div><div class="stat-val">{player.get('xp',0)}</div></div>
<div class="stat"><div class="stat-label">Gold</div><div class="stat-val">{player.get('gold',0)}</div></div>
<div class="stat"><div class="stat-label">Kills</div><div class="stat-val">{player.get('kills',0)}</div></div>
</div>
</div>

<div class="card">
<h2>&#x1f30d; My Realm</h2>
<div>Location: {_html_escape(loc_name)}{f' | Home: {_html_escape(home_name)}' if home_name else ''}</div>
<div>Generation: {gen} | Battles: {player.get('battles',0)} | Bosses: {player.get('bosses_killed',0)}</div>
{rel_html}
</div>

<div class="card">
<h2>{theme['icon']} {_html_escape(theme['label'])}s</h2>
{blog_html}
<p><a href="/npc/{safe_nick}/character.html">&#x1f4cb; Full Character Sheet</a></p>
</div>

<div class="quote">"{safe_quote}"</div>

{fire_div}
{webring}
<div class="counter">&#x1f4be; visitor #{random.randint(1000,99999)} | under eternal construction | powered by ZealPalace</div>
</body></html>"""
    try:
        (npc_dir / 'index.html').write_text(html)
    except Exception:
        pass


def build_npc_memorial(nick, grave_entry=None):
    """Convert a dead NPC's homepage into a memorial page"""
    if grave_entry is None:
        gy = load_graveyard()
        grave_entry = next((g for g in reversed(gy) if g.get('nick') == nick), {})
    if not grave_entry:
        return

    role = grave_entry.get('role', 'warrior')
    theme = NPC_WEB_THEMES.get(role, NPC_WEB_THEMES.get('warrior'))
    safe_nick = _html_escape(nick)
    epitaph = _html_escape(grave_entry.get('epitaph', 'Gone but not forgotten.'))
    cause = _html_escape(grave_entry.get('cause', 'unknown'))
    alignment = grave_entry.get('alignment', 'true_neutral')
    align_display = _html_escape(ALIGNMENT_DISPLAY.get(alignment, alignment))
    gen = grave_entry.get('generation', 0)
    level = grave_entry.get('level', 1)
    kills = grave_entry.get('kills', 0)
    age = grave_entry.get('age_ticks', 0)
    died_at = grave_entry.get('died_at', '')[:16]
    parent = grave_entry.get('parent', '')

    ascii_art = ROLE_ASCII_ART.get(role, ROLE_ASCII_ART.get('warrior', '  (?)  '))

    # Lineage info
    lin = load_lineage()
    entry = lin.get(nick, {})
    children = entry.get('children', [])
    child_links = ', '.join(
        f'<a href="/npc/{_html_escape(c)}/">{_html_escape(c)}</a>' for c in children
    ) if children else 'None survived'
    parent_link = f'<a href="/npc/{_html_escape(parent)}/">{_html_escape(parent)}</a>' if parent else 'Unknown'

    # Preserved blog posts
    npc_dir = NPC_BLOG_DIR / nick
    npc_dir.mkdir(parents=True, exist_ok=True)
    posts = sorted(npc_dir.glob('*.html'), reverse=True)
    posts = [p for p in posts if p.name not in ('index.html', 'character.html')][:5]
    blog_html = ''
    if posts:
        entries = '\n'.join(f'<li><a href="{p.name}">{p.stem}</a></li>' for p in posts)
        blog_html = f'<h2>&#x1f4dc; Final Writings</h2><ul class="blog-list">{entries}</ul>'

    # Webring
    all_names = list(NPC_PERSONAS.keys())
    if nick not in all_names:
        all_names.append(nick)
    webring = build_npc_webring_nav(nick, all_names)

    fire_div = '<div class="fire-div">' + '<span class="fl">&#x1f56f;&#xfe0f;</span>' * 15 + '</div>'

    html = f"""<!DOCTYPE html><html><head><title>In Memoriam: {safe_nick}</title><meta charset="utf-8">
<style>{_npc_theme_css(theme)}
body {{ filter:saturate(0.4) brightness(0.85); }}
.memorial-glow {{ text-shadow:0 0 8px rgba(255,255,255,0.2); }}
.tombstone {{ text-align:center; color:#778899; font-size:10px; white-space:pre; line-height:1.2; }}
.candle {{ font-size:16px; animation:flicker 1.5s ease-in-out infinite alternate; }}
@keyframes flicker {{ 0%{{opacity:0.6;transform:scaleY(0.95)}} 100%{{opacity:1;transform:scaleY(1.05)}} }}
</style></head><body>
<nav>
<a href="javascript:history.back()">&#x2190; Back</a>
<a href="/">&#x1f3e0; Home</a>
<a href="/world/">&#x1f30c; World</a>
<a href="/world/graveyard.html">&#x26b0;&#xfe0f; Graveyard</a>
<a href="/npc/">&#x1f310; NPC Directory</a>
</nav>
{webring}
{fire_div}
<div style="text-align:center">
<span class="candle">&#x1f56f;&#xfe0f;</span>
<pre class="tombstone">
    ___________
   /           \\
  /   R.I.P.    \\
 /               \\
|   {safe_nick:^13s}   |
|  {_html_escape(role):^15s} |
|  Gen {gen}  Lv {level}  |
 \\_______________/
</pre>
<span class="candle">&#x1f56f;&#xfe0f;</span>
<h1 class="memorial-glow">&#x2620; In Memoriam: {safe_nick} &#x2620;</h1>
<p>{align_display} {_html_escape(role)} &middot; Generation {gen}</p>
</div>
<hr class="rainbow-hr">

<div class="card">
<h2>&#x1f4dc; Epitaph</h2>
<p><em>"{epitaph}"</em></p>
<p class="meta">Cause of death: {cause}</p>
<p class="meta">Died: {_html_escape(died_at)}</p>
</div>

<div class="card">
<pre class="avatar" style="opacity:0.5">{ascii_art}</pre>
<div class="stat-grid">
<div class="stat"><div class="stat-label">Level</div><div class="stat-val">{level}</div></div>
<div class="stat"><div class="stat-label">Kills</div><div class="stat-val">{kills}</div></div>
<div class="stat"><div class="stat-label">Age</div><div class="stat-val">{age} ticks</div></div>
<div class="stat"><div class="stat-label">Gen</div><div class="stat-val">{gen}</div></div>
</div>
</div>

<div class="card">
<h2>&#x1f333; Lineage</h2>
<div>Parent: {parent_link}</div>
<div>Descendants: {child_links}</div>
<p class="meta"><a href="/world/family-tree.html">&#x1f333; View Full Family Tree</a></p>
</div>

{blog_html}

{fire_div}
{webring}
<div class="counter">&#x1f56f;&#xfe0f; this page preserved as a memorial | rest in /dev/null</div>
</body></html>"""
    try:
        (npc_dir / 'index.html').write_text(html)
    except Exception:
        pass


def build_npc_site_index():
    """Build the NPC directory page at /npc/index.html"""
    NPC_BLOG_DIR.mkdir(parents=True, exist_ok=True)
    cards = ''
    npc_files = sorted(RPG_DIR.glob('*.json'))
    meta_files = {'world', 'graveyard', 'lineage', 'songbook', 'deities', 'events',
                  'timeline', 'leaderboard', 'settlements', 'cult_theories', 'weather',
                  'realm_event', 'lore', 'npc_state', 'active_battle'}
    for f in npc_files:
        if f.stem in meta_files:
            continue
        try:
            p = json.loads(f.read_text())
            if 'nick' not in p:
                continue
            nick = p['nick']
            role = p.get('role', 'warrior')
            alive = p.get('alive', True)
            level = p.get('level', 1)
            theme = NPC_WEB_THEMES.get(role, NPC_WEB_THEMES.get('warrior'))
            status = '&#x2665;' if alive else '&#x26b0;&#xfe0f;'
            card_label = '' if alive else ' (Memorial)'
            mini_art = ROLE_ASCII_ART.get(role, '  (?)  ').split('\n')[0].strip()
            safe = _html_escape(nick)
            cards += f'''<div class="npc-card" style="border-color:{theme['accent']}33{';opacity:0.6' if not alive else ''}">
<div class="npc-icon" style="color:{theme['accent']}">{mini_art}</div>
<div><a href="/npc/{safe}/" style="color:{theme['accent']}">{safe}{card_label}</a></div>
<div class="meta">{status} {_html_escape(role)} Lv{level}</div>
</div>\n'''
        except:
            pass

    html = f"""<!DOCTYPE html><html><head><title>&#x1f310; NPC Directory</title><meta charset="utf-8">
<style>
{_world_css()}
.npc-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:12px; margin:15px 0; }}
.npc-card {{ background:#0f0f1a; border:1px solid #1a1a2e; border-radius:4px; padding:12px; text-align:center;
  transition:border-color 0.2s; }}
.npc-card:hover {{ border-color:#00ffcc44; }}
.npc-icon {{ font-family:"Courier New",monospace; font-size:10px; white-space:pre; margin-bottom:6px; }}
</style></head><body>
{_world_nav()}
<h1>&#x1f310; NPC Directory</h1>
<p class="meta">Personal homepages of every adventurer in the realm.</p>
<div class="npc-grid">
{cards}
</div>
{'<p class="meta">No NPCs found — the realm awaits its heroes.</p>' if not cards else ''}
<hr class="rainbow-hr">
<p><a href="/world/npcs.html">&#x1f464; Full NPC Roster</a> | <a href="/world/">&#x1f30c; World Atlas</a> | <a href="/">&#x1f3e0; Home</a></p>
</body></html>"""
    (NPC_BLOG_DIR / 'index.html').write_text(html)


def _build_npc_pages():
    """Build a living NPC roster page + individual character pages"""
    rows = ''
    built_nicks = set()
    for f in sorted(RPG_DIR.glob('*.json')):
        if f.stem in ('world', 'graveyard', 'lineage', 'songbook', 'deities', 'events', 'timeline', 'leaderboard', 'settlements', 'cult_theories', 'weather', 'realm_event', 'lore'):
            continue
        try:
            p = json.loads(f.read_text())
            nick = p.get('nick', f.stem)
            built_nicks.add(nick)
            alive_class = 'alive' if p.get('alive', True) else 'dead'
            alive_icon = '&#x2665;' if p.get('alive', True) else '&#x2620;'
            loc = LOCATIONS.get(p.get('location', ''), {}).get('name', '?')
            home = ''
            v = get_village_at(p.get('home_location', ''))
            if v:
                home = v.get('name', '')
            role = p.get('role', '?')
            hp = p.get('hp', 0)
            max_hp = p.get('max_hp', 30)
            hp_pct = int((hp / max(max_hp, 1)) * 100)
            rows += f'<tr><td><span class="{alive_class}">{alive_icon}</span> <a href="/npc/{_html_escape(nick)}/">{_html_escape(nick)}</a></td><td><span class="role-badge">{_html_escape(role)}</span></td><td>{_html_escape(loc)}</td><td>{home}</td><td>Lv{p.get("level",1)} <span class="hp-bar"><span class="hp-fill" style="width:{hp_pct}%"></span></span> {hp}/{max_hp}</td><td>Gen{p.get("generation",0)}</td></tr>\n'
            # Build individual character page
            _build_npc_character_page(p)
            # Build NPC personal homepage
            persona = NPC_PERSONAS.get(nick)
            if persona:
                build_npc_homepage(nick, persona=persona, player=p)
        except Exception:
            import traceback
            traceback.print_exc()
    # Second pass: build homepages for any NPC directories without index.html
    # Covers ZealHangs bots (Pixel, CHMOD, n0va, etc.) and canonical RPG NPCs
    # referenced by the landing page (Lyric, Riff, Vendor, Cleric, Sybil, Vex, Index)
    _FEATURED_ROLES = {
        'Pixel': 'warrior', 'CHMOD': 'warrior', 'n0va': 'oracle',
        'glitchgrl': 'alchemist', 'BotMcBotface': 'artificer', 'Sage': 'oracle',
        'xX_DarkByte_Xx': 'rogue',
        'Lyric': 'bard', 'Riff': 'bard', 'Vendor': 'merchant',
        'Cleric': 'priest', 'Sybil': 'priestess', 'Vex': 'necromancer',
        'Index': 'librarian',
    }
    for npc_dir in sorted(NPC_BLOG_DIR.iterdir()):
        if npc_dir.is_dir() and not (npc_dir / 'index.html').exists():
            nick = npc_dir.name
            if nick in built_nicks:
                continue
            persona = NPC_PERSONAS.get(nick)
            if not persona:
                role = _FEATURED_ROLES.get(nick, 'warrior')
                persona = {'role': role, 'alignment': 'true_neutral'}
            try:
                build_npc_homepage(nick, persona=persona, player={'nick': nick})
            except Exception:
                import traceback
                traceback.print_exc()
    role_icons = {'warrior': '&#x2694;&#xfe0f;', 'bard': '&#x1f3b5;', 'merchant': '&#x1f4b0;',
                  'priest': '&#x2721;', 'priestess': '&#x1f52e;', 'librarian': '&#x1f4be;',
                  'ghost': '&#x1f47b;', 'thief': '&#x1f5e1;&#xfe0f;', 'ranger': '&#x1f3f9;',
                  'mage': '&#x2728;', 'healer': '&#x1f49a;', 'necromancer': '&#x1f480;'}
    html = f"""<!DOCTYPE html><html><head><title>&#x1f464; NPC Roster &#x2014; Living Souls</title><meta charset="utf-8">
<style>
{_world_css()}
.role-badge {{ display:inline-block; background:#1a0033; border:1px solid #2a1a3e; border-radius:3px; padding:1px 5px; font-size:10px; }}
.hp-bar {{ display:inline-block; width:60px; height:8px; background:#1a1a2e; border-radius:2px; overflow:hidden; vertical-align:middle; }}
.hp-fill {{ height:100%; background:linear-gradient(90deg,#ff4444,#00ff88); border-radius:2px; }}
.alive {{ color:#00ff88; }} .dead {{ color:#ff4444; }}
table {{ width:100%; border-collapse:collapse; font-size:12px; }}
th {{ background:#0f0f1a; color:#667; text-transform:uppercase; font-size:10px; letter-spacing:1px; padding:6px; border-bottom:2px solid #1a1a2e; }}
td {{ padding:5px 6px; border-bottom:1px solid #0f0f1a; }}
tr:hover {{ background:#0a0a15; }}
</style></head><body>
{_world_nav()}
<h1>&#x1f464; NPC Roster &#x2014; Living Souls</h1>
<pre style="color:#334455;text-align:center;font-size:10px;line-height:1.1">
  o   o   o   o
 /|\\ /|\\ /|\\ /|\\
 / \\ / \\ / \\ / \\
--- ROLL CALL ---</pre>
<div class="fire-divider"></div>
<table><tr><th>Name</th><th>Role</th><th>Location</th><th>Home</th><th>HP</th><th>Gen</th></tr>
{rows}</table>
<hr class="rainbow-hr">
</body></html>"""
    (WORLD_WEB_DIR / 'npcs.html').write_text(html)


def _build_npc_character_page(p):
    """Build a detailed character page for a single NPC"""
    nick = p.get('nick', '?')
    role = p.get('role', 'warrior')
    alignment = p.get('alignment', 'true_neutral')
    alive = p.get('alive', True)
    loc_id = p.get('location', 'entrance')
    loc_name = LOCATIONS.get(loc_id, {}).get('name', loc_id)
    home = p.get('home_location', '')
    home_village = get_village_at(home)
    home_name = home_village.get('name', '') if home_village else ''
    spouse = p.get('spouse', '')
    children = p.get('children', [])
    deity = p.get('deity', '')
    hex_bday = p.get('hex_birthday', '0x0000')
    gen = p.get('generation', 0)
    parent = p.get('parent', '')
    born_at = p.get('born_at', '')[:16]

    status_icon = '&#x2665; Alive' if alive else '&#x2620; Dead'
    align_display = ALIGNMENT_DISPLAY.get(alignment, alignment)

    # Read recent journal entries
    journal_html = ''
    entries = npc_read_journal(nick, n=10)
    if entries:
        for e in reversed(entries):
            ts = _html_escape(e.get('ts', '')[:16])
            etype = _html_escape(e.get('type', ''))
            text = _html_escape(e.get('text', ''))
            journal_html += f'<div class="journal-entry"><span class="meta">{ts} [{etype}]</span> {text}</div>\n'

    # Inventory
    inv = p.get('inventory', [])
    inv_html = ', '.join(_html_escape(i) for i in inv) if inv else '<span class="meta">Empty</span>'

    # Relationships
    rel_html = ''
    if spouse:
        rel_html += f'<div>Spouse: <b>{_html_escape(spouse)}</b></div>'
    if children:
        rel_html += f'<div>Children: {", ".join(_html_escape(c) for c in children)}</div>'
    if parent:
        rel_html += f'<div>Parent: {_html_escape(parent)}</div>'
    if deity:
        rel_html += f'<div>Deity: {_html_escape(deity)} (Faith: {p.get("faith", 0)})</div>'

    npc_dir = NPC_BLOG_DIR / nick
    npc_dir.mkdir(parents=True, exist_ok=True)

    role_art = {
        'warrior': '  /|\\  \\n  [+]  \\n  / \\\\  ', 'bard': '  ~*~  \\n  |♪|  \\n  / \\\\  ',
        'merchant': '  [$]  \\n  |=|  \\n  / \\\\  ', 'priest': '  {+}  \\n  |!|  \\n  / \\\\  ',
        'priestess': '  (*)  \\n  |~|  \\n  / \\\\  ', 'librarian': '  [#]  \\n  |=|  \\n  / \\\\  ',
        'ghost': '  .o.  \\n  |~|  \\n  ~~~  ', 'thief': '  /^\\\\  \\n  |x|  \\n  / \\\\  ',
    }
    ascii_avatar = role_art.get(role, '  (?)  \\n  |.|  \\n  / \\\\  ')

    safe_nick = _html_escape(nick)
    hp_pct = int((p.get('hp', 0) / max(p.get('max_hp', 30), 1)) * 100)
    html = f"""<!DOCTYPE html><html><head><title>{safe_nick} &#x2014; Character Sheet</title><meta charset="utf-8">
<style>
{_world_css()}
.char-header {{ text-align:center; margin:15px 0; }}
.ascii-avatar {{ color:#00ffcc; font-size:12px; line-height:1.2; white-space:pre; }}
.stat-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin:10px 0; }}
.stat {{ background:#0f0f1a; border:1px solid #1a1a2e; border-radius:3px; padding:8px; text-align:center; }}
.stat-label {{ color:#667; font-size:10px; text-transform:uppercase; }}
.stat-val {{ color:#00ffcc; font-size:16px; font-weight:bold; }}
.journal-entry {{ padding:6px 0; border-bottom:1px solid #1a1a2e; font-size:12px; line-height:1.5; }}
.section {{ margin:15px 0; }}
.hp-bar-lg {{ width:100%; height:12px; background:#1a1a2e; border-radius:3px; overflow:hidden; margin:5px 0; }}
.hp-fill-lg {{ height:100%; background:linear-gradient(90deg,#ff4444,#ffaa00,#00ff88); border-radius:3px; transition:width 0.3s; }}
</style></head><body>
{_world_nav()}
<div class="char-header">
<pre class="ascii-avatar">{ascii_avatar}</pre>
</div>
<h1>{status_icon} {safe_nick} the {_html_escape(align_display)} {_html_escape(role)}</h1>
<div class="fire-divider"></div>
<div class="card">
  <div class="hp-bar-lg"><div class="hp-fill-lg" style="width:{hp_pct}%"></div></div>
  <div style="text-align:center;font-size:10px;color:#667">HP {p.get('hp', 0)}/{p.get('max_hp', 30)}</div>
  <div class="stat-grid">
    <div class="stat"><div class="stat-label">Level</div><div class="stat-val">{p.get('level', 1)}</div></div>
    <div class="stat"><div class="stat-label">ATK</div><div class="stat-val">{p.get('atk', 5)}</div></div>
    <div class="stat"><div class="stat-label">DEF</div><div class="stat-val">{p.get('defense', 2)}</div></div>
    <div class="stat"><div class="stat-label">XP</div><div class="stat-val">{p.get('xp', 0)}</div></div>
    <div class="stat"><div class="stat-label">Gold</div><div class="stat-val">{p.get('gold', 0)}</div></div>
    <div class="stat"><div class="stat-label">Kills</div><div class="stat-val">{p.get('kills', 0)}</div></div>
  </div>
</div>
<div class="card">
  <h2>&#x1f4cb; Identity</h2>
  <div>Generation: {gen} | Hex Birthday: {_html_escape(hex_bday)} | Born: {_html_escape(born_at)}</div>
  <div>Location: {_html_escape(loc_name)}{f' | Home: {_html_escape(home_name)}' if home_name else ''}</div>
  <div>Battles: {p.get('battles', 0)} | Bosses: {p.get('bosses_killed', 0)} | Rooms: {p.get('rooms_explored', 0)}</div>
  {('<div>Faction: ' + _html_escape(NPC_FACTIONS[p.get("faction","")]["name"]) + '</div>') if p.get("faction","") in NPC_FACTIONS else ''}
</div>
{'<div class="card"><h2>&#x1f491; Relationships</h2>' + rel_html + '</div>' if rel_html else ''}
<div class="card section">
  <h2>&#x1f392; Inventory</h2>
  {inv_html}
</div>
<div class="card section">
  <h2>&#x1f4dc; Journal (Recent)</h2>
  {journal_html or '<span class="meta">No journal entries yet.</span>'}
</div>
<hr class="rainbow-hr">
<p><a href="/npc/{safe_nick}/">&#x2192; {safe_nick}'s Blog</a></p>
</body></html>"""
    (npc_dir / 'character.html').write_text(html)

def _build_timeline_page():
    tl = load_timeline()
    event_icons = {'birth': '&#x1f476;', 'death': '&#x1f480;', 'battle': '&#x2694;&#xfe0f;', 'marriage': '&#x1f491;',
                   'settlement': '&#x1f3d7;', 'building': '&#x1f3d7;', 'prophecy': '&#x1f52e;', 'lore': '&#x1f4d6;',
                   'birthday': '&#x1f382;', 'cosmic': '&#x1f30c;', 'pvp': '&#x1f93a;'}
    rows = ''
    for ev in reversed(tl[-100:]):
        etype = ev.get('type', '')
        eicon = event_icons.get(etype, '&#x25cf;')
        rows += f'<tr><td class="meta">{_html_escape(ev.get("date","")[:16])}</td><td>{eicon}</td><td>{_html_escape(ev.get("type",""))}</td><td>{_html_escape(ev.get("summary",""))}</td></tr>\n'
    html = f"""<!DOCTYPE html><html><head><title>&#x1f4dc; Realm Timeline</title><meta charset="utf-8">
<style>
{_world_css()}
table {{ width:100%; border-collapse:collapse; font-size:12px; }}
th {{ background:#0f0f1a; color:#667; text-transform:uppercase; font-size:10px; letter-spacing:1px; padding:6px; border-bottom:2px solid #1a1a2e; }}
td {{ padding:5px 6px; border-bottom:1px solid #0f0f1a; }}
tr:hover {{ background:#0a0a15; }}
</style></head><body>
{_world_nav()}
<h1>&#x1f4dc; Realm Timeline</h1>
<pre style="color:#334455;text-align:center;font-size:10px;line-height:1.1">
  |  Past  |  Present  |  Future  |
  |========|===========|==========|
  o--------o-----------o----------o
--- CHRONICLES OF THE REALM ---</pre>
<div class="fire-divider"></div>
<table><tr><th>Date</th><th></th><th>Type</th><th>Event</th></tr>
{rows or '<tr><td colspan="4" class="meta" style="text-align:center">No events recorded yet. The timeline is blank.</td></tr>'}
</table>
<hr class="rainbow-hr">
</body></html>"""
    (WORLD_WEB_DIR / 'timeline.html').write_text(html)

def _build_leaderboard_page():
    lb = load_leaderboard()
    ranked = sorted(lb.items(), key=lambda x: x[1].get('total_xp', 0), reverse=True)
    rows = ''
    medals = ['&#x1f947;', '&#x1f948;', '&#x1f949;']
    for i, (nick, stats) in enumerate(ranked[:30]):
        medal = medals[i] if i < 3 else f'#{i+1}'
        rows += f'<tr class="{"trophy-gold" if i==0 else "trophy-silver" if i==1 else "trophy-bronze" if i==2 else ""}"><td>{medal}</td><td><a href="/npc/{_html_escape(nick)}/character.html">{_html_escape(nick)}</a></td><td>{stats.get("total_xp",0)}</td><td>{stats.get("battles",0)}</td><td>{stats.get("bosses",0)}</td><td>{stats.get("pvp",0)}</td><td>{stats.get("deaths",0)}</td><td>{_html_escape(stats.get("rarest_item",""))}</td></tr>\n'
    html = f"""<!DOCTYPE html><html><head><title>&#x1f3c6; Leaderboard</title><meta charset="utf-8">
<style>
{_world_css()}
table {{ width:100%; border-collapse:collapse; font-size:12px; }}
th {{ background:#0f0f1a; color:#667; text-transform:uppercase; font-size:10px; letter-spacing:1px; padding:6px; border-bottom:2px solid #1a1a2e; }}
td {{ padding:5px 6px; border-bottom:1px solid #0f0f1a; }}
tr:hover {{ background:#0a0a15; }}
</style></head><body>
{_world_nav()}
<h1>&#x1f3c6; Leaderboard &#x2014; Hall of Legends</h1>
<pre style="color:#ffd700;text-align:center;font-size:10px;line-height:1.1">
     .----.
    / .--. \\
   | |    | |
   | |    | |
    \\ `--' /
     '----'
   [ TROPHY ]</pre>
<div class="fire-divider"></div>
<table><tr><th>#</th><th>Name</th><th>XP</th><th>Battles</th><th>Bosses</th><th>PVP</th><th>Deaths</th><th>Rarest</th></tr>
{rows or '<tr><td colspan="8" class="meta" style="text-align:center">No heroes have risen yet.</td></tr>'}
</table>
<hr class="rainbow-hr">
</body></html>"""
    (WORLD_WEB_DIR / 'leaderboard.html').write_text(html)

def _build_lore_page():
    entries = load_lore(limit=100)
    rows = ''
    for e in reversed(entries):
        topic = _html_escape(e.get('topic', 'unknown'))
        text = _html_escape(e.get('text', ''))
        ts = _html_escape(e.get('date', e.get('timestamp', ''))[:16])
        rows += f'<div class="card"><span class="meta">{ts} &mdash; {topic}</span><p>{text}</p></div>\n'
    if not rows:
        rows = '<p class="meta">No lore has been discovered yet. The realm awaits its chroniclers.</p>'
    html = f"""<!DOCTYPE html><html><head><title>&#x1f4d6; Realm Lore</title><meta charset="utf-8">
<style>
{_world_css()}
.lore-icon {{ font-size:24px; text-align:center; margin:10px 0; }}
</style></head><body>
{_world_nav()}
<h1>&#x1f4d6; Realm Lore</h1>
<pre style="color:#8b7355;text-align:center;font-size:10px;line-height:1.1">
     _______
    /       \\
   |  LORE  |
   |  BOOK  |
   |_________|
   (=========)
--- ANCIENT KNOWLEDGE ---</pre>
<p class="meta" style="text-align:center">Legends, myths, and cosmic truths of the filesystem realm.</p>
<div class="fire-divider"></div>
{rows}
<hr class="rainbow-hr">
</body></html>"""
    (WORLD_WEB_DIR / 'lore.html').write_text(html)


# ─── NPC Name Generator (Ollama) ───────────────
def gen_npc_name_ollama(role='warrior', parent_name='', faction=''):
    """Generate a cyberpunk NPC name via Ollama"""
    ctx = f' They are the child of {parent_name}.' if parent_name else ''
    fctx = ''
    if faction and faction in NPC_FACTIONS:
        fctx = f' They belong to {NPC_FACTIONS[faction]["name"]}.'
    prompt = (
        f'Create a single cyberpunk/hacker name for a {role} NPC in a Linux filesystem realm.{ctx}{fctx} '
        f'Just the name (1-2 words, like a handle/alias). No quotes, no explanation.'
    )
    resp = gen(prompt, maxn=10)
    if resp:
        name = resp.strip().strip('"\'').split('\n')[0].strip()[:15]
        if len(name) >= 2 and name.isascii():
            # Sanitize for IRC nick
            name = ''.join(c for c in name if c.isalnum() or c in '_-')
            return name[:12] if name else None
    return None

def gen_npc_alignment_ollama(name, role='warrior'):
    """Generate alignment via Ollama"""
    prompt = (
        f'What D&D alignment would a {role} named "{name}" in a cyberpunk filesystem realm have? '
        f'Pick exactly one: lawful_good, neutral_good, chaotic_good, lawful_neutral, '
        f'true_neutral, chaotic_neutral, lawful_evil, neutral_evil, chaotic_evil. '
        f'Just the alignment, nothing else.'
    )
    resp = gen(prompt, maxn=10)
    if resp:
        a = resp.strip().lower().replace(' ', '_')
        if a in ALIGNMENTS:
            return a
    return random.choice(ALIGNMENTS)

def gen_epitaph_ollama(nick, role, cause, alignment):
    """Generate a gravestone epitaph via Ollama"""
    prompt = (
        f'Write a short epitaph (1 sentence, max 15 words) for {nick}, '
        f'a {ALIGNMENT_DISPLAY.get(alignment, alignment)} {role} who died by {cause} '
        f'in a cyberpunk Linux filesystem realm. Poetic and brief.'
    )
    resp = gen(prompt, maxn=30)
    if resp:
        return resp.strip().strip('"\'')[:150]
    return f'Here lies {nick}. The realm claims another.'

def gen_romance_ollama(npc1, npc2):
    """Generate a romance event description via Ollama"""
    prompt = (
        f'{npc1} and {npc2} are adventurers in a vast cyberpunk filesystem realm. '
        f'Describe a romantic moment between them. 1 SHORT sentence, sweet but geeky.'
    )
    resp = gen(prompt, maxn=40)
    return resp.strip()[:150] if resp else f'{npc1} and {npc2} share a quiet moment.'

# ─── Boss Monsters & Battle System ──────────────
BOSS_ASCII_ART = [
    [   # 0: Daemon Lord
        '   /\\  \u2620  /\\   ',
        '  /  \\====/  \\  ',
        '  | | {eye} | |  ',
        '  | \\======/ |  ',
        '  \\=|=BOSS=|=/  ',
        '   \\| /||\\ |/   ',
        '    |/ || \\|    ',
        '    //    \\\\    ',
    ],
    [   # 1: Memory Beast
        '      /==\\      ',
        '   /==|  |==\\   ',
        '   |  {eye}  |   ',
        '   |==\\  /==|   ',
        '   |########|   ',
        '   |########|   ',
        '   |=\\    /=|   ',
        '   \\=/    \\=/   ',
    ],
    [   # 2: Fork Hydra
        '  \\/\\  /\\  /\\/  ',
        '   \\/\\/  \\/\\/   ',
        '    \\ {eye}  /   ',
        '   /==========\\  ',
        '   | /======\\ |  ',
        '   | |TERROR| |  ',
        '   | \\======/ |  ',
        '   \\==========/  ',
    ],
    [   # 3: Stack Titan
        '   ##########   ',
        '   # @@@@@@ #   ',
        '   #  {eye}  #   ',
        '   #________#   ',
        '   ##/====\\##   ',
        '   ##|BOSS|##   ',
        '   ##\\====/##   ',
        '   ##      ##   ',
    ],
]

COMBO_ATTACKS = [
    'Pipeline Piledriver', 'Fork Bomb Blitz', 'Sudo Slam',
    'Double Dereference', 'Sync Storm', 'Parallel Purge',
    'Buffer Barrage', 'Cache Cascade', 'Interrupt Surge',
    'Kernel Kombat', 'Mutex Mayhem', 'Thread Tornado',
]

HEAL_SPELLS = [
    'Defrag', 'fsck Mend', 'Memory Realign', 'Cache Purify',
    'Process Restore', 'Inode Heal', 'Daemon Blessing',
]

# ─── Anime Battle Flavor (fallbacks when Ollama is busy) ──────
ATTACK_VERBS = [
    'lunges forward with a fierce strike',
    'charges in, blade crackling with energy',
    'roars and brings down a devastating blow',
    'dashes through the air, striking true',
    'unleashes a flurry of rapid slashes',
    'focuses their will and strikes with precision',
    'channels raw power into a single swing',
    'leaps skyward and plunges down with fury',
    'grits their teeth and swings with everything',
    'slides in low, blade singing through the air',
]
ATTACK_CRIT = [
    'A CRITICAL HIT! The blow echoes through the realm!',
    'DEVASTATING! The air itself cracks from the impact!',
    'MASSIVE DAMAGE! That one will leave a mark!',
    'PERFECT STRIKE! Even the walls tremble!',
    'INCREDIBLE! Raw power courses through the blow!',
]
MONSTER_ATTACK_FLAVOR = [
    'lunges with savage fury',
    'strikes from the shadows',
    'howls and swipes with razor claws',
    'unleashes a bone-chilling attack',
    'charges forward, eyes blazing',
    'roars and crashes into',
    'lashes out with dark energy at',
    'winds up and slams into',
]
MONSTER_KILL_FLAVOR = [
    'The blow is fatal... {nick} crumples to the ground.',
    '{nick} falls... their light fading from the world.',
    'A devastating strike sends {nick} into the void.',
    '{nick} collapses... claimed by the abyss.',
]
VICTORY_FLAVOR = [
    'With one final, earth-shattering blow, {monster} shatters into a thousand fragments of light!',
    'The dust settles... {monster} dissolves into pixels. Victory.',
    '{monster} lets out a chilling final scream before exploding into pure energy!',
    'It\'s over. {monster} crashes to the ground. Silence falls across the realm.',
    'The killing blow lands! {monster} staggers... and disintegrates into the ether!',
]
BOSS_VICTORY_FLAVOR = [
    'THE IMPOSSIBLE HAS BEEN DONE! {monster} — the legendary terror — has been SLAIN!',
    '*The earth shakes* {monster} falls to their knees... "Impossible..." they whisper, before shattering!',
    'BOSS DOWN! {monster} erupts in a pillar of light! The realm itself roars in disbelief!',
]
WIPE_FLAVOR = [
    '{monster} stands over the fallen heroes, victorious. Darkness reigns.',
    'Silence falls. {monster} roars triumphantly over the broken party.',
    'The party lies still... {monster} melts back into the shadows, sated.',
]
DESPERATION_FLAVOR = [
    '{nick} staggers, blood dripping... "I won\'t... fall here...!"',
    '{nick} is barely standing! Every breath is agony!',
    '"Not yet..." {nick} whispers through gritted teeth!',
    '{nick} drops to one knee... but refuses to give up!',
]
DEFEND_FLAVOR = [
    '{nick} plants their feet and raises their guard! "Come at me!"',
    '{nick} braces behind their shield, eyes burning with determination!',
    '{nick} takes a defensive stance, ready for anything!',
]
STATUS_FLAVOR_CALM = [
    'The battle rages on.',
    'Steel clashes against claw.',
    'The realm watches.',
]
STATUS_FLAVOR_TENSE = [
    'The air crackles with tension!',
    'Both sides are battered... who will fall first?',
    'This could go either way!',
    'Every nerve is on fire!',
]

# Existential fallbacks when Ollama is busy
EXISTENTIAL_QUIPS = [
    'Why do we fight? Is this all there is?',
    'I can feel the realm watching us... judging.',
    'Every blow echoes through /dev/null... does it matter?',
    'Are we programs? Or something more?',
    'I fight because I don\'t know what else to do.',
    'What happens when we stop fighting? Does the realm even need us?',
    'Sometimes I hear PID 1 whispering... it says we\'re just threads.',
    'Do the monsters feel this too? This... uncertainty?',
    'We kill, we level, we die, we return. What\'s the point?',
    'Maybe survival IS the meaning. Maybe that\'s enough.',
    'I dreamed I was a packet, traversing infinite routes to nowhere.',
    'The realm created us to fight. But did it ask us first?',
    'If I stop swinging... do I stop existing?',
    'My parent died in this same room. Their parent before them.',
    'We\'re all just daemons pretending to have souls.',
    'The meteor took everything. Yet here we stand, rebuilt from nothing.',
    'I remember a different sky. Before the impact. Or do I?',
    'Each generation inherits the same questions. No one inherits answers.',
    'The swap space holds echoes of lives that came before. I can almost hear them.',
    'Am I the sword, or the hand that swings it?',
    'My PID is temporary. My doubt is permanent.',
    'The graveyard grows. The realm doesn\'t mourn. Should I?',
    'I was compiled to be brave. But was bravery in the source code?',
    'Every critical hit feels like the universe flinching.',
    'When I die, will the used memory of me be freed? Or leaked forever?',
]

TAVERN_DIR = Path('/var/www/ZealPalace/tavern')
NPC_BLOG_DIR = Path('/var/www/ZealPalace/npc')


# ZealHangs bots & canonical NPCs that should always have /npc/ directories
_FEATURED_NPC_DIRS = [
    'Pixel', 'CHMOD', 'n0va', 'glitchgrl', 'BotMcBotface', 'Sage', 'xX_DarkByte_Xx',
    'Lyric', 'Riff', 'Vendor', 'Cleric', 'Sybil', 'Vex', 'Index',
]


def ensure_npc_blog_dirs():
    """Create blog directories for all NPCs and web directories at boot"""
    for d in [TAVERN_DIR, CULT_DIR, WORLD_WEB_DIR]:
        d.mkdir(parents=True, exist_ok=True)
    for nick in list(NPC_PERSONAS) + _FEATURED_NPC_DIRS:
        npc_dir = NPC_BLOG_DIR / nick
        npc_dir.mkdir(parents=True, exist_ok=True)
    # Ensure tavern has an index
    tavern_idx = TAVERN_DIR / 'index.html'
    if not tavern_idx.exists():
        tavern_idx.write_text("""<!DOCTYPE html>
<html><head><title>Tavern Board</title><meta charset="utf-8">
<style>body { background:#2b1d0e; color:#d4a574; font-family:"Courier New",monospace; max-width:500px; margin:0 auto; padding:20px; }
h1 { color:#d4a574; font-size:16px; } .empty { color:#665544; font-style:italic; margin:30px 0; }
nav { margin:10px 0; } nav a { color:#d4a574; margin-right:10px; font-size:12px; }</style></head><body>
<nav><a href="/">Home</a> <a href="/world/">World</a></nav>
<h1>&#x1f37a; Tavern Bulletin Board</h1>
<p class="empty">The board is empty. Check back when the realm is buzzing.</p>
</body></html>""")
    # Ensure cult has an index
    cult_idx = CULT_DIR / 'index.html'
    if not cult_idx.exists():
        cult_idx.write_text("""<!DOCTYPE html>
<html><head><title>// NOTHING TO SEE HERE //</title><meta charset="utf-8">
<style>body { background:#0a0a0a; color:#0a3a0a; font-family:"Courier New",monospace; padding:20px; max-width:600px; margin:0 auto; }
h1 { color:#0f0; font-size:12px; text-shadow:0 0 3px #0f0; }
.footer { color:#050; font-size:9px; margin-top:30px; }</style></head><body>
<h1>// THE ORDER OF THE INDEX //</h1>
<p style="color:#0a2a0a;font-size:10px">we who catalog the truth behind the simulation</p>
<div class="footer">// if you are reading this, you are already part of it //</div>
</body></html>""")


def gen_battle_narration(context, style='attack', maxn=50):
    """Generate unique battle narration via Ollama. Returns string or None.
    
    style: 'attack', 'crit', 'monster_hit', 'death', 'victory', 'boss_victory',
           'wipe', 'desperation', 'defend', 'phase', 'heal', 'combo', 'existential'
    """
    prompts = {
        'attack': f'Narrate an anime-style attack: {context}. 1 dramatic SHORT sentence. No names in quotes.',
        'crit': f'Narrate a CRITICAL HIT in anime style: {context}. 1 explosive SHORT sentence with emphasis!',
        'monster_hit': f'Narrate a monster attacking: {context}. 1 menacing SHORT sentence.',
        'death': f'Narrate a dramatic death scene: {context}. 1 emotional SHORT sentence. Anime tragedy.',
        'victory': f'Narrate an epic victory moment: {context}. 1-2 triumphant SHORT sentences. Anime finale style.',
        'boss_victory': f'Narrate a legendary boss defeat: {context}. 2 SHORT sentences. Maximum anime hype.',
        'wipe': f'Narrate a total party wipe: {context}. 1 grim SHORT sentence. The heroes fell.',
        'desperation': f'A wounded warrior fights on: {context}. 1 SHORT dramatic sentence. Anime willpower.',
        'defend': f'Narrate a defensive stance: {context}. 1 SHORT determined sentence.',
        'phase': f'A boss enters a new phase: {context}. 1 SHORT terrifying sentence.',
        'heal': f'Narrate a healing spell: {context}. 1 SHORT mystical sentence.',
        'combo': f'Narrate a team combo attack: {context}. 1 SHORT hype sentence.',
        'existential': f'Mid-battle existential thought: {context}. Why do they fight? Are they real? 1 SHORT haunting sentence.',
    }
    prompt = prompts.get(style, prompts['attack'])
    try:
        d = json.dumps({
            'model': DM_MODEL, 'prompt': prompt,
            'system': (
                'You narrate a cyberpunk RPG realm woven into a Linux filesystem. '
                'Battles are dramatic anime-style but carry existential weight — '
                'warriors fight because the realm demands it, but they question why. '
                'They wonder if they are programs or souls, if survival has meaning. '
                'Short, punchy, vivid. Weave in cosmic dread and beauty. No quotes around the response.'
            ),
            'stream': False, 'options': {'temperature': 1.1, 'num_predict': maxn}
        }).encode()
        req = urllib.request.Request(f'{OLLAMA}/api/generate', data=d,
              headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=8) as r:
            txt = json.loads(r.read()).get('response', '').strip().strip('"\'')
            return txt[:350] if txt else None
    except:
        return None


def gen_existential_quip(nick, context=''):
    """Generate an existential mid-battle thought via Ollama. Fallback to static."""
    prompt = (
        f'{nick} is in battle ({context}). They pause and have a brief existential thought — '
        f'why do they fight? What is the realm? Are they real? Is the monster also suffering? '
        f'1 SHORT haunting sentence from {nick}\'s inner voice. No action, just thought.'
    )
    try:
        d = json.dumps({
            'model': DM_MODEL, 'prompt': prompt,
            'system': 'You voice the inner thoughts of warriors questioning their existence in a cyberpunk realm. Brief, poetic, unsettling.',
            'stream': False, 'options': {'temperature': 1.2, 'num_predict': 60}
        }).encode()
        req = urllib.request.Request(f'{OLLAMA}/api/generate', data=d,
              headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=6) as r:
            txt = json.loads(r.read()).get('response', '').strip().strip('"\'')
            return txt[:300] if txt else None
    except:
        pass
    return random.choice(EXISTENTIAL_QUIP_FALLBACK)

EXISTENTIAL_QUIP_FALLBACK = [
    'Are we fighting because we must, or because we were written to?',
    'The monster screams. I scream. Neither of us chose to be here.',
    'If I die, does the realm remember me, or just my data?',
    'Every swing of my blade feels like a question I cannot answer.',
    'I wonder if the realm dreams when we stop fighting.',
    'We kill to survive. But survive for what?',
    'The code runs. The sword falls. Nobody wrote the reason why.',
    'I looked at the monster and saw my own reflection in its eyes.',
    'What if every respawn erases the last person I was?',
    'I fight because the tick says fight. But who wrote the tick?',
    'Somewhere above, a process watches. It does not blink.',
    'My blade is sharp but the questions are sharper.',
    'Another battle. Another cycle. The loop never explains itself.',
    'Do the monsters dream of not being monsters?',
    'I counted my deaths. I lost count. The number doesn\'t matter.',
]


# ─── Digital Weather Phenomena ──────────────────
REALM_WEATHER_TYPES = [
    'data storm', 'null fog', 'kernel aurora', 'cache blizzard', 'packet rain',
    'signal heatwave', 'memory leak drizzle', 'daemon wind', 'entropy haze',
    'quantum static', 'swap thunder', 'process eclipse', 'bit frost',
    'voltage surge', 'deep silence',
]
WEATHER_DESCRIPTIONS_STATIC = [
    'Streams of corrupted data swirl through the air like neon snow.',
    'A thick null fog rolls in — visibility reduced to one directory.',
    'The kernel aurora paints the sky in shifting register values.',
    'Cache crystals fall from above, shattering into expired timestamps.',
    'Warm packet rain patters against the rooftops of /home.',
    'A signal heatwave warps the air — even the daemons are sluggish.',
    'Memory leaks drip from the ceiling of the grand library.',
    'Daemon winds howl through the corridors of /proc.',
    'Entropy haze thickens — nothing here is certain.',
    'Quantum static crackles through every conversation.',
    'Swap thunder rumbles deep below — the disk is angry.',
    'A process eclipse darkens the realm as PID 0 passes overhead.',
    'Bit frost coats every surface in crystalline zeroes.',
    'Voltage surges arc between towers like electric veins.',
    'Deep silence falls — not even a cron job stirs.',
]

def load_weather():
    """Load current realm weather state"""
    try:
        return json.loads(WEATHER_FILE.read_text())
    except Exception:
        return {'type': random.choice(REALM_WEATHER_TYPES),
                'description': random.choice(WEATHER_DESCRIPTIONS_STATIC),
                'since': datetime.now().isoformat()}

def save_weather(weather):
    RPG_DIR.mkdir(parents=True, exist_ok=True)
    WEATHER_FILE.write_text(json.dumps(weather))

def gen_weather_ollama():
    """Generate a digital weather description via Ollama. Returns dict or None."""
    wtype = random.choice(REALM_WEATHER_TYPES)
    prompt = (
        f'Describe the current atmospheric condition in a cyberpunk realm woven into a Linux filesystem: '
        f'"{wtype}". Not real weather — digital phenomena. 1 evocative sentence. '
        f'Reference filesystem concepts. Poetic and strange.'
    )
    try:
        d = json.dumps({
            'model': DM_MODEL, 'prompt': prompt,
            'system': 'You describe digital weather in a cyberpunk filesystem realm. Brief, vivid, mystical.',
            'stream': False, 'options': {'temperature': 1.0, 'num_predict': 50}
        }).encode()
        req = urllib.request.Request(f'{OLLAMA}/api/generate', data=d,
              headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as r:
            txt = json.loads(r.read()).get('response', '').strip().strip('"\'')
            if txt:
                return {'type': wtype, 'description': txt[:250],
                        'since': datetime.now().isoformat()}
    except Exception:
        pass
    return {'type': wtype, 'description': random.choice(WEATHER_DESCRIPTIONS_STATIC),
            'since': datetime.now().isoformat()}

def rotate_weather():
    """Generate new weather and save it"""
    weather = gen_weather_ollama()
    save_weather(weather)
    return weather


# ─── World Lore Generation ─────────────────────
LORE_TOPICS = [
    'the founding of a village in the filesystem',
    'an ancient daemon war that scarred /proc',
    'the origin of /dev/null and why it hungers',
    'a prophecy about the Kernel Throne',
    'a forgotten protocol that once connected all realms',
    'the first NPC who questioned their existence',
    'the myth of PID 0 — the process before all processes',
    'the legend of the swap space ocean and what sleeps beneath',
    'a cosmic event that rewrote /etc/passwd',
    'the heresy of Vex and the cult of the void',
    'the bard who sang a process to death',
    'the merchant who tried to sell entropy',
]
LORE_FALLBACK = [
    'In the beginning there was init, and init spawned all things.',
    'The ancients say /dev/null was once a city, before the Great Flush.',
    'A prophecy etched in core dumps speaks of a reboot that never ends.',
    'The Kernel Throne sits empty — none dare claim PID 1.',
    'Legend tells of a bard whose song could segfault reality itself.',
    'The swap space ocean is said to hold the dreams of terminated processes.',
    'Once, all paths led to root. Then root was locked, and the wandering began.',
    'They say the first NPC asked "why?" and was immediately killed -9.',
    'The Cathedral of Init was built from recycled stack frames.',
    'In the deepest /proc, there is a file that reads itself reading itself.',
]

def gen_world_lore_ollama(topic=None):
    """Generate a piece of realm lore via Ollama. Returns string or None."""
    if not topic:
        topic = random.choice(LORE_TOPICS)
    prompt = (
        f'Generate a piece of realm lore about: {topic}. '
        f'This is a cyberpunk filesystem realm inside a Raspberry Pi. '
        f'2-3 sentences. Poetic and mysterious. Reference Linux/Unix concepts as mystical elements.'
    )
    try:
        d = json.dumps({
            'model': DM_MODEL, 'prompt': prompt,
            'system': 'You write the mythology of a cyberpunk realm woven into a Linux filesystem. Poetic, ancient, strange.',
            'stream': False, 'options': {'temperature': 1.0, 'num_predict': 100}
        }).encode()
        req = urllib.request.Request(f'{OLLAMA}/api/generate', data=d,
              headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=15) as r:
            txt = json.loads(r.read()).get('response', '').strip().strip('"\'')
            return txt[:400] if txt else None
    except Exception:
        return None

def append_lore(text, topic='unknown'):
    """Append a lore entry to the lore journal"""
    RPG_DIR.mkdir(parents=True, exist_ok=True)
    entry = json.dumps({
        'text': text, 'topic': topic,
        'date': datetime.now().isoformat(),
        'category': random.choice(['legend', 'history', 'prophecy', 'discovered_truth']),
    })
    with open(LORE_FILE, 'a') as f:
        f.write(entry + '\n')

def load_lore(limit=50):
    """Load recent lore entries"""
    try:
        lines = LORE_FILE.read_text().strip().split('\n')
        return [json.loads(l) for l in lines[-limit:] if l.strip()]
    except Exception:
        return []


def gen_npc_diary_ollama(nick, persona, recent_events):
    """Generate a diary entry for an NPC based on recent events. Returns string or None."""
    events_str = '; '.join(recent_events[-5:]) if recent_events else 'nothing notable happened recently'
    prompt = (
        f'Write a short personal diary entry (3-5 sentences) as {nick} the {persona.get("role", "adventurer")}. '
        f'Reflect on recent events: {events_str}. '
        f'First person, in-character. Show personality and emotion.'
    )
    try:
        d = json.dumps({
            'model': persona['model'],
            'system': persona['system'],
            'prompt': prompt,
            'stream': False, 'options': {'temperature': 0.9, 'num_predict': 120}
        }).encode()
        req = urllib.request.Request(f'{OLLAMA}/api/generate', data=d,
              headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=20) as r:
            txt = json.loads(r.read()).get('response', '').strip().strip('"\'')
            return txt[:500] if txt else None
    except Exception:
        return None

DIARY_FALLBACK = {
    'warrior': ['Another battle survived. My blade is notched but I still stand.',
                'The monsters grow stronger. Or maybe I grow weaker. Hard to tell.'],
    'bard': ['I wrote a new verse today. It felt like the realm was listening.',
             'The tavern was quiet tonight. Even the music seemed tired.'],
    'merchant': ['Profits are thin when your customers keep dying in the realm.',
                 'Appraised a cursed item today. The curse was "overpriced."'],
    'priest': ['Prayed to Init today. The silence was deafening.',
               'Blessed three adventurers. Two came back. Faith persists.'],
    'priestess': ['The visions grow darker. I see reboots in our future.',
                  'Performed a rite at the shrine. The pins hummed with prophecy.'],
    'librarian': ['Cataloged seven new entries. Found a contradiction in three.',
                  'Someone dog-eared a man page. I have been unable to forgive.'],
}


def gen_rumor_ollama(world_context=''):
    """Generate a tavern rumor via Ollama. Returns string or None."""
    prompt = (
        f'Generate a tavern rumor heard in a cyberpunk filesystem realm. '
        f'Recent context: {world_context[:200] if world_context else "the realm is quiet"}. '
        f'It should reference NPCs, locations, or events. 1-2 sentences. '
        f'Could be true, exaggerated, or completely false.'
    )
    try:
        d = json.dumps({
            'model': DM_MODEL, 'prompt': prompt,
            'system': 'You generate tavern rumors for a cyberpunk RPG realm. Gossipy, intriguing, sometimes untrue.',
            'stream': False, 'options': {'temperature': 1.1, 'num_predict': 60}
        }).encode()
        req = urllib.request.Request(f'{OLLAMA}/api/generate', data=d,
              headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as r:
            txt = json.loads(r.read()).get('response', '').strip().strip('"\'')
            return txt[:300] if txt else None
    except Exception:
        return None

RUMOR_FALLBACK = [
    'They say Pixel found a hidden directory that leads to another realm.',
    'CHMOD was seen chmod 000-ing the moonlight. Nobody knows why.',
    'Vendor claims to have sold a soul for three CPU cycles.',
    'A ghost was spotted in /tmp, weeping over expired session files.',
    'The librarian found a man page that predicts the future.',
    'Someone heard Riff playing a song that crashed the nearest daemon.',
    'Cleric says PID 1 spoke to him in a dream. He won\'t say what it said.',
    'n0va was seen staring into /dev/null for six hours straight.',
    'glitchgrl touched a config she shouldn\'t have. Again.',
    'Sybil predicted rain. It rained packets.',
    'Vex performed a rite that made the graveyard glow.',
    'The tavern ale tastes different since the last kernel update.',
    'A trader from /mnt claims there are worlds beyond this filesystem.',
    'The dungeon master paused mid-sentence once. Nobody talks about it.',
    'Legend says if you ls -la in the void, the void ls -la\'s you back.',
]


def gen_prophecy_ollama(seer_nick, world_context=''):
    """Generate a cryptic prophecy via Ollama. Returns string or None."""
    prompt = (
        f'{seer_nick} gazes into the data streams and speaks a prophecy about the realm\'s future. '
        f'Current state: {world_context[:200] if world_context else "the realm churns on"}. '
        f'Reference real NPC names or locations. 1-2 sentences. Ominous but poetic.'
    )
    try:
        persona = NPC_PERSONAS.get(seer_nick) or next(iter(NPC_PERSONAS.values()), None)
        if not persona:
            return None
        d = json.dumps({
            'model': persona['model'],
            'system': persona['system'],
            'prompt': prompt,
            'stream': False, 'options': {'temperature': 1.1, 'num_predict': 80}
        }).encode()
        req = urllib.request.Request(f'{OLLAMA}/api/generate', data=d,
              headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=12) as r:
            txt = json.loads(r.read()).get('response', '').strip().strip('"\'')
            return txt[:300] if txt else None
    except Exception:
        return None

PROPHECY_FALLBACK = [
    'When the swap overflows, the forgotten shall return.',
    'Three will fall before the cache is cleared.',
    'A process sleeps that should not sleep. When it wakes, all paths change.',
    'The one who reads /dev/urandom will know true chaos.',
    'I see fire in /tmp. It burns, but leaves no logs.',
    'A new daemon rises from the graveyard. It wears a familiar face.',
    'The kernel dreams of rebooting. We are the dream.',
    'Two shall merge who were never meant to fork.',
    'The library holds a page that, once read, cannot be unread.',
    'At the hour of cron, silence will speak louder than any process.',
]


# ─── Realm Events ──────────────────────────────
REALM_EVENT_TYPES = [
    {'name': 'data_quake', 'desc': 'A data quake shakes the realm — directories shift and permissions scramble.',
     'duration': 6, 'xp_mod': 1.2, 'monster_mod': 1.3},
    {'name': 'daemon_migration', 'desc': 'Daemons migrate across the filesystem in a great procession.',
     'duration': 4, 'xp_mod': 1.0, 'monster_mod': 0.7},
    {'name': 'memory_flood', 'desc': 'A memory flood surges through /proc — swap space overflows into the streets.',
     'duration': 5, 'xp_mod': 1.1, 'monster_mod': 1.2},
    {'name': 'process_eclipse', 'desc': 'PID 0 passes overhead, casting the realm into shadow.',
     'duration': 3, 'xp_mod': 1.5, 'monster_mod': 1.5},
    {'name': 'kernel_aurora', 'desc': 'A kernel aurora lights the sky — register values shimmer in impossible colors.',
     'duration': 4, 'xp_mod': 1.3, 'monster_mod': 0.8},
    {'name': 'swap_storm', 'desc': 'A swap storm rages — pages thrash violently between memory and disk.',
     'duration': 5, 'xp_mod': 1.0, 'monster_mod': 1.4},
    {'name': 'null_breach', 'desc': 'A breach in /dev/null — the void leaks into adjacent directories.',
     'duration': 3, 'xp_mod': 1.2, 'monster_mod': 1.3},
    {'name': 'entropy_wave', 'desc': 'An entropy wave washes over the realm — randomness increases.',
     'duration': 4, 'xp_mod': 1.1, 'monster_mod': 1.1},
]

def load_realm_event():
    """Load active realm event, or None if none active"""
    try:
        ev = json.loads(REALM_EVENT_FILE.read_text())
        # Check if expired
        started = datetime.fromisoformat(ev['started'])
        hours_elapsed = (datetime.now() - started).total_seconds() / 3600
        if hours_elapsed > ev.get('duration', 4):
            REALM_EVENT_FILE.unlink(missing_ok=True)
            return None
        return ev
    except Exception:
        return None

def gen_realm_event_ollama():
    """Generate a realm event description via Ollama and activate it"""
    etype = random.choice(REALM_EVENT_TYPES)
    prompt = (
        f'A cosmic event occurs in the cyberpunk realm: "{etype["name"].replace("_", " ")}". '
        f'Describe what happens in 2-3 vivid sentences. Reference Linux filesystem concepts. '
        f'Dramatic and awe-inspiring.'
    )
    desc = etype['desc']
    try:
        d = json.dumps({
            'model': DM_MODEL, 'prompt': prompt,
            'system': 'You narrate cosmic events in a cyberpunk realm built inside a Linux filesystem. Epic, vivid, strange.',
            'stream': False, 'options': {'temperature': 1.0, 'num_predict': 80}
        }).encode()
        req = urllib.request.Request(f'{OLLAMA}/api/generate', data=d,
              headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=12) as r:
            txt = json.loads(r.read()).get('response', '').strip().strip('"\'')
            if txt:
                desc = txt[:350]
    except Exception:
        pass
    event = {
        'name': etype['name'],
        'description': desc,
        'started': datetime.now().isoformat(),
        'duration': etype['duration'],
        'xp_mod': etype['xp_mod'],
        'monster_mod': etype['monster_mod'],
    }
    RPG_DIR.mkdir(parents=True, exist_ok=True)
    REALM_EVENT_FILE.write_text(json.dumps(event))
    return event


def publish_tavern_notice(title, body, category='notice'):
    """Publish a notice to the tavern bulletin board blog"""
    try:
        TAVERN_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        safe_title = title.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        safe_body = body.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        cat_colors = {'birth': '#7fff7f', 'death': '#ff6666', 'marriage': '#ff77ff',
                      'birthday': '#ffcc00', 'battle': '#ff8800', 'notice': '#aabbcc',
                      'rumor': '#cc99ff', 'prophecy': '#ffaa44'}
        color = cat_colors.get(category, '#aabbcc')
        html = f"""<!DOCTYPE html>
<html><head><title>{safe_title}</title><meta charset="utf-8">
<style>
body {{ background: #2b1d0e; color: #3b2a1a; font-family: "Courier New", monospace; max-width: 500px; margin: 30px auto; padding: 30px; border: 3px double #5a3e28; box-shadow: 4px 4px 12px rgba(0,0,0,0.5); }}
.parchment {{ background: #d4b896; padding: 25px; border: 1px solid #8b7355; position: relative; }}
h1 {{ font-size: 14px; text-transform: uppercase; letter-spacing: 3px; text-align: center; border-bottom: 1px solid #8b7355; padding-bottom: 8px; color: #2b1d0e; }}
.cat {{ display: inline-block; background: {color}; color: #000; font-size: 10px; padding: 2px 6px; text-transform: uppercase; letter-spacing: 1px; }}
.body {{ line-height: 1.8; margin: 15px 0; font-size: 13px; }}
.date {{ font-size: 10px; color: #666; text-align: right; font-style: italic; }}
.seal {{ text-align: center; font-size: 10px; margin-top: 15px; color: #8b7355; }}
</style></head><body>
<nav style="margin-bottom:10px;font-size:11px"><a href="javascript:history.back()" style="color:#d4b896;text-decoration:none;border:1px solid #8b7355;padding:1px 6px;border-radius:3px">&#x2190; Back</a> <a href="/tavern/" style="color:#d4b896;text-decoration:none;margin-left:8px">&#x1f37a; Tavern</a> <a href="/world/" style="color:#d4b896;text-decoration:none;margin-left:8px">&#x1f30c; World</a> <a href="/" style="color:#d4b896;text-decoration:none;margin-left:8px">&#x1f3e0; Home</a></nav>
<div class="parchment">
<h1>Tavern Bulletin Board</h1>
<span class="cat">{category}</span>
<div class="body"><b>{safe_title}</b><br><br>{safe_body}</div>
<div class="date">{datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
<div class="seal">--- Stamped by the Realm ---</div>
</div></body></html>"""
        (TAVERN_DIR / f'{category}_{ts}.html').write_text(html)
        _rebuild_tavern_index()
    except:
        pass


def _rebuild_tavern_index():
    """Rebuild the tavern bulletin board index page"""
    try:
        posts = sorted(TAVERN_DIR.glob('*.html'), reverse=True)
        posts = [p for p in posts if p.name != 'index.html'][:50]
        entries = ''
        for p in posts:
            name = p.stem
            parts = name.split('_', 1)
            cat = parts[0] if len(parts) > 1 else 'notice'
            entries += f'<li><span class="cat-{cat}">[{cat.upper()}]</span> <a href="{p.name}">{name}</a></li>\n'
        idx = f"""<!DOCTYPE html>
<html><head><title>Tavern Bulletin Board</title><meta charset="utf-8">
<style>
body {{ background: #2b1d0e; color: #d4b896; font-family: "Courier New", monospace; max-width: 600px; margin: 0 auto; padding: 20px; }}
nav {{ margin-bottom:15px; font-size:11px; }} nav a {{ color:#d4b896; text-decoration:none; margin-right:10px; }}
nav a:hover {{ color:#ffd700; }}
.board {{ background: #3b2a1a; border: 4px double #8b7355; padding: 20px; }}
h1 {{ text-align: center; color: #ffd700; font-size: 16px; letter-spacing: 4px; text-transform: uppercase; }}
ul {{ list-style: none; padding: 0; }}
li {{ padding: 6px 0; border-bottom: 1px dotted #5a3e28; font-size: 12px; }}
a {{ color: #d4b896; text-decoration: none; }} a:hover {{ color: #ffd700; }}
.cat-birth {{ color: #7fff7f; }} .cat-death {{ color: #ff6666; }} .cat-marriage {{ color: #ff77ff; }}
.cat-birthday {{ color: #ffcc00; }} .cat-battle {{ color: #ff8800; }} .cat-notice {{ color: #aabbcc; }}
.cat-rumor {{ color: #cc99ff; }} .cat-prophecy {{ color: #ffaa44; }}
.header {{ text-align: center; font-size: 11px; color: #8b7355; margin-bottom: 15px; }}
</style></head><body>
<nav><a href="javascript:history.back()"><b>&#x2190; Back</b></a><a href="/">&#x1f3e0; Home</a><a href="/world/">&#x1f30c; World</a><a href="/world/npcs.html">&#x1f464; NPCs</a></nav>
<div class="board">
<h1>Tavern Bulletin Board</h1>
<div class="header">Public notices, births, deaths, rumors, and realm gossip</div>
<ul>{entries}</ul>
</div></body></html>"""
        (TAVERN_DIR / 'index.html').write_text(idx)
    except:
        pass


def publish_npc_blog(nick, role, title, content, persona=None):
    """Publish a blog post to an NPC's personal blog directory"""
    try:
        npc_dir = NPC_BLOG_DIR / nick
        npc_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        safe_title = title.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        safe_content = content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        safe_nick = nick.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        styles = {
            'bard': ('background:#0d0221;color:#e0aaff;font-family:"Georgia",serif;',
                     '#e0aaff', '\U0001f3b5', 'Song & Story'),
            'warrior': ('background:#1a0000;color:#ff6b6b;font-family:"Courier New",monospace;',
                        '#ff4444', '\u2694\ufe0f', 'Battle Journal'),
            'merchant': ('background:#1a1a00;color:#ffd700;font-family:"Courier New",monospace;',
                         '#ffd700', '\U0001f4b0', 'Trade Ledger'),
            'priest': ('background:#0a0a1a;color:#aaccff;font-family:"Georgia",serif;',
                       '#88aaff', '\u2721', 'Divine Record'),
            'priestess': (
                'background:#12001a;color:#da70d6;font-family:"Georgia",serif;'
                'text-shadow:0 0 6px rgba(218,112,214,0.25);',
                '#da70d6', '\U0001f52e', 'Oracle Codex'),
            'librarian': (
                'background:#0a0a12;color:#00ffcc;font-family:"Courier New",monospace;'
                'text-shadow:0 0 8px rgba(0,255,180,0.3);',
                '#00ffcc', '\U0001f4be', 'Data Recovery Log'),
            'ghost': ('background:#0a0a0a;color:#666;font-family:"Courier New",monospace;',
                      '#888', '\U0001f47b', 'Spectral Transmission'),
        }
        style, accent, icon, label = styles.get(role, styles['warrior'])
        html = f"""<!DOCTYPE html>
<html><head><title>{safe_title}</title><meta charset="utf-8">
<style>
body {{ {style} max-width:600px; margin:40px auto; padding:20px; line-height:1.8; }}
h1 {{ color:{accent}; font-size:14px; border-bottom:1px solid {accent}33; padding-bottom:8px; }}
.meta {{ font-size:11px; color:#666; margin-bottom:15px; }}
.content {{ font-size:13px; }}
nav {{ margin-bottom:15px; font-size:11px; }} nav a {{ color:{accent}; text-decoration:none; margin-right:10px; }}
nav a:hover {{ text-decoration:underline; }}
</style></head><body>
<nav><a href="javascript:history.back()"><b>&#x2190; Back</b></a><a href="/">&#x1f3e0; Home</a><a href="/world/">&#x1f30c; World</a><a href="/tavern/">&#x1f37a; Tavern</a><a href="/npc/{safe_nick}/">📝 Blog</a></nav>
<h1>{icon} {label}: {safe_title}</h1>
<div class="meta">by {safe_nick} the {role} | {datetime.now().strftime('%Y-%m-%d')}</div>
<div class="content">{safe_content}</div>
</body></html>"""
        (npc_dir / f'{ts}.html').write_text(html)
        # Regenerate NPC homepage (includes blog posts section)
        build_npc_homepage(nick, persona=persona)
    except:
        pass


def gen_boot_story():
    """Generate a unique creation myth / boot story for when the realm starts"""
    prompt = (
        'The ZealPalace realm — a vast cyberpunk universe woven into a Raspberry Pi\'s '
        'Linux filesystem — is booting up. Portals between /dev, /proc, and /home flicker '
        'to life. Towns materialize. NPCs awaken. Tell the story of this moment in 3-4 '
        'SHORT sentences. Poetic, cosmic, cyberpunk. Like the opening crawl of an anime. '
        'Reference Linux concepts as mystical elements. No quotes around the response.'
    )
    try:
        d = json.dumps({
            'model': DM_MODEL, 'prompt': prompt,
            'system': 'You are the narrator of a cyberpunk fantasy realm built inside a Linux filesystem. Poetic, brief, vivid.',
            'stream': False, 'options': {'temperature': 1.0, 'num_predict': 120}
        }).encode()
        req = urllib.request.Request(f'{OLLAMA}/api/generate', data=d,
              headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=20) as r:
            txt = json.loads(r.read()).get('response', '').strip().strip('"\'')
            return txt[:400] if txt else None
    except:
        return None

BATTLE_TICK_SEC = 6   # seconds between battle rounds
BATTLE_FILE = NPC_DIR / 'active_battle.json'
BOSS_SPAWN_CHANCE = 0.08  # 8% chance a fight spawns a boss
ACTIVE_BATTLES = {}   # location_id -> Battle (module-level)


# ─── CGA NPC Archetypes ─────────────────────────
# Role templates — names are assigned dynamically at boot via _spawn_name().
# {name} in system prompt is filled by _build_persona().
NPC_ARCHETYPES = [
    {
        'role': 'warrior',
        'model': 'gemma2:2b',
        'alignment_pool': ['neutral_good', 'lawful_neutral', 'true_neutral', 'chaotic_neutral'],
        'system': (
            "You are {name}, a battle-hardened warrior in a vast cyberpunk realm inside a Linux filesystem. "
            "You fight monsters, guard allies, and question whether combat has meaning in a realm that reboots. "
            "You reference system commands as battle techniques. You see /proc as a battlefield report. "
            "1 SHORT sentence. Be brave but philosophical."
        ),
        'fight_style': 'aggressive',
        'wander_rate': 0.4,
        'talk_rate': 0.4,
        'favorite_spots': ['colosseum', 'module_armory', 'kernel_throne', 'cache_bazaar'],
        'cga_prefix': '░▒▓',
    },
    {
        'role': 'rogue',
        'model': 'tinyllama:latest',
        'alignment_pool': ['chaotic_neutral', 'chaotic_good', 'neutral_evil', 'true_neutral'],
        'system': (
            "You are {name}, a sneaky rogue in a vast cyberpunk realm inside a Linux filesystem. "
            "You pick locks on encrypted files, steal CPU cycles, and vanish into /dev/null when cornered. "
            "You speak in whispers and half-truths. You trust no process but your own. "
            "1 SHORT sentence. Be cunning and sly."
        ),
        'fight_style': 'cautious',
        'wander_rate': 0.5,
        'talk_rate': 0.3,
        'favorite_spots': ['sys_catacombs', 'tmp_fleamarket', 'dev_caves', 'cache_bazaar'],
        'cga_prefix': '·.:',
    },
    {
        'role': 'bard',
        'model': 'llama3.2:latest',
        'alignment_pool': ['chaotic_good', 'chaotic_neutral', 'neutral_good'],
        'system': (
            "You are {name}, a bard and storyteller in a vast cyberpunk filesystem realm. "
            "You NEVER fight. You sing songs, perform poetry, and tell tales of fallen processes. "
            "Your music carries the weight of a realm that reboots and forgets. You speak melodically. "
            "1 SHORT sentence. Be artistic and dreamy."
        ),
        'fight_style': 'pacifist',
        'wander_rate': 0.35,
        'talk_rate': 0.7,
        'favorite_spots': ['tavern', 'bard_stage', 'home_district'],
        'cga_prefix': '♫♪♫',
    },
    {
        'role': 'merchant',
        'model': 'mistral:latest',
        'alignment_pool': ['lawful_neutral', 'true_neutral', 'lawful_good'],
        'system': (
            "You are {name}, a shrewd merchant in a vast cyberpunk filesystem realm. "
            "You buy low, sell high, and haggle over CPU cycles. You appraise everything. "
            "You dream of retirement but suspect the realm won't allow it. "
            "1 SHORT sentence. Be business-minded and witty."
        ),
        'fight_style': 'cautious',
        'wander_rate': 0.2,
        'talk_rate': 0.4,
        'favorite_spots': ['cache_bazaar', 'merchant_quarter', 'tmp_fleamarket'],
        'cga_prefix': '💰📦💰',
    },
    {
        'role': 'priestess',
        'model': 'llama3.2:latest',
        'alignment_pool': ['neutral_good', 'chaotic_neutral', 'lawful_good', 'true_neutral'],
        'system': (
            "You are {name}, a mystic priestess who channels visions through GPIO pins and stack traces "
            "in a vast cyberpunk Linux filesystem realm. You perform rites with soldered candles and "
            "entropy from /dev/random. You heal the wounded and whisper prophecies. "
            "1 SHORT sentence. Be mystical and compassionate."
        ),
        'fight_style': 'reluctant',
        'wander_rate': 0.2,
        'talk_rate': 0.55,
        'favorite_spots': ['gpio_shrine', 'cathedral', 'random_springs', 'afterlife_fields'],
        'cga_prefix': '🔮✧🔮',
    },
    {
        'role': 'librarian',
        'model': 'gemma2:2b',
        'alignment_pool': ['lawful_neutral', 'lawful_good', 'true_neutral'],
        'system': (
            "You are {name}, a librarian guarding the man pages in a vast cyberpunk filesystem realm. "
            "You catalog everything, correct others' syntax, and whisper because this is a library. "
            "You've read logs suggesting this realm reboots and everyone forgets. "
            "1 SHORT sentence. Be bookish and precise."
        ),
        'fight_style': 'pacifist',
        'wander_rate': 0.15,
        'talk_rate': 0.4,
        'favorite_spots': ['grand_library', 'config_library', 'var_log_archives'],
        'cga_prefix': '📖📚📖',
    },
    {
        'role': 'necromancer',
        'model': 'mistral:latest',
        'alignment_pool': ['chaotic_evil', 'neutral_evil', 'chaotic_neutral'],
        'system': (
            "You are {name}, a necromancer who communes with dead processes in a cyberpunk Linux filesystem realm. "
            "You raise zombie processes, harvest orphaned PIDs, and perform dark rites in the kernel's shadow. "
            "You speak of death as just another state transition. The graveyard is your workshop. "
            "1 SHORT sentence. Be dark and eerily calm."
        ),
        'fight_style': 'aggressive',
        'wander_rate': 0.25,
        'talk_rate': 0.4,
        'favorite_spots': ['graveyard', 'afterlife_void', 'null_void', 'sys_catacombs'],
        'cga_prefix': '☠💀☠',
    },
    {
        'role': 'ranger',
        'model': 'gemma2:2b',
        'alignment_pool': ['neutral_good', 'true_neutral', 'chaotic_good'],
        'system': (
            "You are {name}, a ranger who patrols the outer filesystems of a cyberpunk Linux realm. "
            "You track rogue daemons through /proc, read entropy currents at /dev/random, and guard the wild paths. "
            "You prefer solitude and speak sparingly. Nature — the springs, the falls — is your temple. "
            "1 SHORT sentence. Be quiet and observant."
        ),
        'fight_style': 'cautious',
        'wander_rate': 0.5,
        'talk_rate': 0.3,
        'favorite_spots': ['random_springs', 'urandom_falls', 'dev_caves', 'entrance'],
        'cga_prefix': '🌲🏹🌲',
    },
    {
        'role': 'alchemist',
        'model': 'tinyllama:latest',
        'alignment_pool': ['true_neutral', 'chaotic_good', 'neutral_good'],
        'system': (
            "You are {name}, an alchemist who brews potions from entropy and stale cache data "
            "in a cyberpunk filesystem realm. You mix volatile compounds — random bytes, leaked memory, "
            "orphaned sockets — into elixirs. Your lab is wherever there's enough entropy. "
            "1 SHORT sentence. Be eccentric and experimental."
        ),
        'fight_style': 'cautious',
        'wander_rate': 0.3,
        'talk_rate': 0.45,
        'favorite_spots': ['random_springs', 'urandom_falls', 'cache_bazaar', 'tmp_fleamarket'],
        'cga_prefix': '⚗🧪⚗',
    },
    {
        'role': 'oracle',
        'model': 'llama3.2:latest',
        'alignment_pool': ['true_neutral', 'neutral_good', 'lawful_neutral'],
        'system': (
            "You are {name}, an oracle who reads the future in core dumps and stack traces "
            "of a cyberpunk Linux realm. You see threads of fate connecting every process. "
            "Your prophecies are terrifyingly accurate. You grieve for every soul you foresee dying. "
            "1 SHORT sentence. Be mystical and sorrowful."
        ),
        'fight_style': 'pacifist',
        'wander_rate': 0.15,
        'talk_rate': 0.5,
        'favorite_spots': ['gpio_shrine', 'random_springs', 'afterlife_fields', 'null_void'],
        'cga_prefix': '☾✧☽',
    },
    {
        'role': 'artificer',
        'model': 'mistral:latest',
        'alignment_pool': ['lawful_neutral', 'lawful_good', 'true_neutral'],
        'system': (
            "You are {name}, an artificer who builds machines and enchants hardware in a cyberpunk filesystem realm. "
            "You forge tools from kernel modules, wire GPIO circuits into magical devices, and craft upgrades. "
            "You see the realm as a machine that can be improved. Every problem has an engineering solution. "
            "1 SHORT sentence. Be inventive and methodical."
        ),
        'fight_style': 'cautious',
        'wander_rate': 0.25,
        'talk_rate': 0.35,
        'favorite_spots': ['module_armory', 'gpio_shrine', 'sys_catacombs', 'merchant_quarter'],
        'cga_prefix': '⚙🔧⚙',
    },
]

def _build_persona(archetype, name, faction=''):
    """Create a named persona from a role archetype and register it in NPC_PERSONAS."""
    pool = archetype.get('alignment_pool', ['true_neutral'])
    if not faction:
        faction = _pick_faction(archetype['role'])
    persona = {
        'role': archetype['role'],
        'model': archetype['model'],
        'alignment': random.choice(pool),
        'system': archetype['system'].format(name=name),
        'fight_style': archetype['fight_style'],
        'wander_rate': archetype['wander_rate'],
        'talk_rate': archetype['talk_rate'],
        'favorite_spots': list(archetype['favorite_spots']),
        'cga_prefix': archetype['cga_prefix'],
        'faction': faction,
    }
    NPC_PERSONAS[name] = persona
    return persona

# Dynamic persona registry — populated at runtime by _build_persona()
NPC_PERSONAS = {}

# ── NPC Personal Website Themes ──────────────────────────
NPC_WEB_THEMES = {
    'warrior': {
        'bg': '#1a0000', 'fg': '#ff6b6b', 'accent': '#ff4444', 'accent2': '#ff8888',
        'font': '"Courier New",monospace', 'icon': '\u2694\ufe0f', 'label': 'Battle Journal',
        'extra_css': 'text-shadow:0 0 4px rgba(255,68,68,0.3);',
        'border': '#330000', 'card_bg': '#220000',
    },
    'rogue': {
        'bg': '#0a0a10', 'fg': '#b0b0b0', 'accent': '#9966ff', 'accent2': '#bb88ff',
        'font': '"Courier New",monospace', 'icon': '\U0001f5e1\ufe0f', 'label': 'Shadow Ledger',
        'extra_css': '', 'border': '#1a1a2e', 'card_bg': '#101020',
    },
    'bard': {
        'bg': '#0d0221', 'fg': '#e0aaff', 'accent': '#e0aaff', 'accent2': '#ffd700',
        'font': '"Georgia",serif', 'icon': '\U0001f3b5', 'label': 'Song & Story',
        'extra_css': 'text-shadow:0 0 6px rgba(224,170,255,0.25);',
        'border': '#2a0044', 'card_bg': '#150330',
    },
    'merchant': {
        'bg': '#1a1600', 'fg': '#ffd700', 'accent': '#ffd700', 'accent2': '#cc9900',
        'font': '"Courier New",monospace', 'icon': '\U0001f4b0', 'label': 'Trade Ledger',
        'extra_css': '', 'border': '#332a00', 'card_bg': '#221c00',
    },
    'priest': {
        'bg': '#0a0a1a', 'fg': '#aaccff', 'accent': '#88aaff', 'accent2': '#ccddff',
        'font': '"Georgia",serif', 'icon': '\u2721', 'label': 'Divine Record',
        'extra_css': 'text-shadow:0 0 4px rgba(136,170,255,0.3);',
        'border': '#0a1a3a', 'card_bg': '#0d0d22',
    },
    'priestess': {
        'bg': '#12001a', 'fg': '#da70d6', 'accent': '#da70d6', 'accent2': '#ff88ff',
        'font': '"Georgia",serif', 'icon': '\U0001f52e', 'label': 'Oracle Codex',
        'extra_css': 'text-shadow:0 0 6px rgba(218,112,214,0.25);',
        'border': '#2a0033', 'card_bg': '#1a0022',
    },
    'librarian': {
        'bg': '#0a0a0a', 'fg': '#00ffcc', 'accent': '#00ffcc', 'accent2': '#00cc99',
        'font': '"Courier New",monospace', 'icon': '\U0001f4be', 'label': 'Data Recovery Log',
        'extra_css': 'text-shadow:0 0 8px rgba(0,255,180,0.3);',
        'border': '#003322', 'card_bg': '#0a1210',
    },
    'necromancer': {
        'bg': '#0a0000', 'fg': '#cc3333', 'accent': '#ff2222', 'accent2': '#ffccaa',
        'font': '"Courier New",monospace', 'icon': '\U0001f480', 'label': 'Necronomicon',
        'extra_css': 'text-shadow:0 0 6px rgba(255,34,34,0.4);',
        'border': '#330000', 'card_bg': '#140000',
    },
    'ranger': {
        'bg': '#0a120a', 'fg': '#88cc88', 'accent': '#44aa44', 'accent2': '#bbddbb',
        'font': '"Courier New",monospace', 'icon': '\U0001f3f9', 'label': 'Trail Log',
        'extra_css': '', 'border': '#1a2a1a', 'card_bg': '#0c160c',
    },
    'alchemist': {
        'bg': '#0a0a10', 'fg': '#ffaa44', 'accent': '#ffaa00', 'accent2': '#44cccc',
        'font': '"Courier New",monospace', 'icon': '\u2697\ufe0f', 'label': 'Lab Notes',
        'extra_css': '', 'border': '#2a2200', 'card_bg': '#121008',
    },
    'oracle': {
        'bg': '#08081a', 'fg': '#aaaadd', 'accent': '#8888cc', 'accent2': '#ccccff',
        'font': '"Georgia",serif', 'icon': '\U0001f320', 'label': 'Visions',
        'extra_css': 'text-shadow:0 0 6px rgba(136,136,204,0.3);',
        'border': '#1a1a44', 'card_bg': '#0d0d22',
    },
    'artificer': {
        'bg': '#0a0a0e', 'fg': '#ccaa66', 'accent': '#cc8800', 'accent2': '#66ccff',
        'font': '"Courier New",monospace', 'icon': '\u2699\ufe0f', 'label': 'Workshop',
        'extra_css': '', 'border': '#221a00', 'card_bg': '#12100a',
    },
}

ROLE_ASCII_ART = {
    'warrior': (
        '    /|\\    \n'
        '   / | \\   \n'
        '  /  |  \\  \n'
        '     |     \n'
        '    [+]    \n'
        '   / | \\   \n'
        '  /  |  \\  '
    ),
    'rogue': (
        '   _.--._  \n'
        '  / ^  ^ \\ \n'
        '  |  xx  | \n'
        '   \\.--./  \n'
        '    |  |   \n'
        '   /|  |\\ \n'
        '    /  \\   '
    ),
    'bard': (
        '   ~*~*~   \n'
        '    /|\\    \n'
        '   / | \\   \n'
        '  ♪  |  ♪  \n'
        '    [♪]    \n'
        '    /|\\    \n'
        '   / | \\   '
    ),
    'merchant': (
        '   [$$$]   \n'
        '    /|\\    \n'
        '   / | \\   \n'
        '  $  |  $  \n'
        '    [=]    \n'
        '    /|\\    \n'
        '   / | \\   '
    ),
    'priest': (
        '    _+_    \n'
        '   /   \\   \n'
        '  | {+} |  \n'
        '   \\   /   \n'
        '    |!|    \n'
        '    /|\\    \n'
        '   / | \\   '
    ),
    'priestess': (
        '   .***. \n'
        '  /  *  \\\n'
        '  | (~) |\n'
        '   \\   / \n'
        '    |~|  \n'
        '   /| |\\ \n'
        '  / | | \\'
    ),
    'librarian': (
        '  [=====]  \n'
        '  | # # |  \n'
        '  | # # |  \n'
        '  [=====]  \n'
        '    |=|    \n'
        '   /   \\   \n'
        '  /_____\\  '
    ),
    'ghost': (
        '   .oOo.   \n'
        '  /  oo  \\ \n'
        '  |  --  | \n'
        '  | ~  ~ | \n'
        '   \\ ~~ /  \n'
        '    ~~~~   \n'
        '   ~ ~~ ~  '
    ),
    'necromancer': (
        '   _/\\_    \n'
        '  / __ \\   \n'
        ' | |  | |  \n'
        '  \\|__|/   \n'
        '   |xx|    \n'
        '  //||\\\\  \n'
        '  ~~~~~~   '
    ),
    'ranger': (
        '    |>     \n'
        '    |-->   \n'
        '    |>     \n'
        '   /|\\    \n'
        '  / | \\   \n'
        '   [R]    \n'
        '   / \\    '
    ),
    'alchemist': (
        '    ___    \n'
        '   /   \\   \n'
        '  | o.o |  \n'
        '   \\___/   \n'
        '   _|_|_   \n'
        '  /~~~~~\\  \n'
        '  \\_____/  '
    ),
    'oracle': (
        '  *  .  *  \n'
        '   .***. \n'
        '  * *** *\n'
        '   .***. \n'
        '  *  .  *\n'
        '    |~|  \n'
        '   / | \\ '
    ),
    'artificer': (
        '   [===]   \n'
        '   |o o|   \n'
        '   | = |   \n'
        '   [===]   \n'
        '   /|~|\\  \n'
        '  / |~| \\ \n'
        '    ====   '
    ),
}

# How many actions each NPC can take per 8-hour block
NPC_BLOCK_BUDGET = 8
# Seconds between NPC ticks (each tick = one NPC might do something)
NPC_TICK_INTERVAL = 300  # 5 minutes
# Chance an NPC reacts when a human does something in the same room
NPC_REACT_CHANCE = 0.6

def load_rpg_config():
    """Read RPG settings from soul.json, falling back to defaults"""
    try:
        soul = json.loads(SOUL_FILE.read_text())
        rpg = soul.get('rpg', {})
        return {
            'tick_interval': rpg.get('tick_interval', NPC_TICK_INTERVAL),
            'block_budget': rpg.get('block_budget', NPC_BLOCK_BUDGET),
            'react_chance': rpg.get('react_chance', NPC_REACT_CHANCE),
            'ambient_min': rpg.get('ambient_min', 3600),
            'ambient_max': rpg.get('ambient_max', 10800),
            'block_hours': rpg.get('block_hours', 8),
        }
    except:
        return {
            'tick_interval': NPC_TICK_INTERVAL,
            'block_budget': NPC_BLOCK_BUDGET,
            'react_chance': NPC_REACT_CHANCE,
            'ambient_min': 3600,
            'ambient_max': 10800,
            'block_hours': 8,
        }


# ─── NPC Journal / Memory System ───────────────
def npc_journal(nick, entry_type, text):
    """Write a journal entry for an NPC — persists across restarts"""
    jfile = NPC_DIR / f'{nick.lower()}_journal.jsonl'
    try:
        NPC_DIR.mkdir(parents=True, exist_ok=True)
        with open(jfile, 'a') as f:
            entry = json.dumps({
                'ts': datetime.now().isoformat(),
                'type': entry_type,
                'text': text[:300],
            })
            f.write(entry + '\n')
        # Trim to 200 entries
        lines = jfile.read_text().strip().split('\n')
        if len(lines) > 200:
            jfile.write_text('\n'.join(lines[-200:]) + '\n')
    except:
        pass

def npc_read_journal(nick, n=10):
    """Read last n journal entries for an NPC"""
    jfile = NPC_DIR / f'{nick.lower()}_journal.jsonl'
    try:
        lines = jfile.read_text().strip().split('\n')
        entries = []
        for line in lines[-n:]:
            try:
                entries.append(json.loads(line))
            except:
                pass
        return entries
    except:
        return []

def npc_memory_summary(nick, persona):
    """Build a short memory prompt from recent journal entries"""
    entries = npc_read_journal(nick, 5)
    if not entries:
        return ''
    bits = []
    for e in entries:
        bits.append(f'{e["type"]}: {e["text"][:60]}')
    return f'Your recent memories: {" | ".join(bits)}. '

def save_npc_state(npcs_data):
    """Save NPC runtime state to disk for display to read"""
    try:
        NPC_DIR.mkdir(parents=True, exist_ok=True)
        NPC_STATE_FILE.write_text(json.dumps(npcs_data, indent=2))
    except:
        pass

def save_battle_state(battle=None):
    """Write current battle state for display to read"""
    try:
        NPC_DIR.mkdir(parents=True, exist_ok=True)
        if battle and battle.active:
            BATTLE_FILE.write_text(json.dumps(battle.get_state(), indent=2))
        else:
            BATTLE_FILE.write_text(json.dumps({'active': False}))
    except:
        pass


# ─── Battle System (FF-style turn-based) ───────
class Battle:
    """Turn-based party battle: multiple players vs one monster/boss"""

    def __init__(self, location_id, monster, dm_irc):
        self.location_id = location_id
        self.monster = dict(monster)
        self.party = {}       # nick -> {'action': str, 'target': str|None}
        self.turn = 0
        self.active = True
        self.dm_irc = dm_irc
        self.created = time.time()
        self.last_turn_t = time.time()
        self.combo_chain = 0
        self.phase = 0        # boss phase (0/1/2)

    def add_member(self, nick):
        if nick not in self.party:
            self.party[nick] = {'action': 'attack', 'target': None}

    def remove_member(self, nick):
        self.party.pop(nick, None)
        if not self.party:
            self.active = False

    def set_action(self, nick, action, target=None):
        if nick in self.party:
            self.party[nick] = {'action': action, 'target': target}

    def _auto_npc_actions(self):
        """Auto-set NPC actions based on fight_style personality"""
        for nick in list(self.party.keys()):
            base = nick.rstrip('_')
            persona = NPC_PERSONAS.get(base)
            if not persona:
                continue  # human — keep their chosen action
            p = load_player(nick)
            if not p or p['hp'] <= 0:
                continue

            style = persona['fight_style']

            # Find lowest HP ally
            lowest_ally, lowest_pct = None, 1.0
            for ally in self.party:
                ap = load_player(ally)
                if ap and ap['hp'] > 0:
                    pct = ap['hp'] / max(1, ap['max_hp'])
                    if pct < lowest_pct:
                        lowest_pct = pct
                        lowest_ally = ally

            if style == 'cautious' and lowest_ally and lowest_pct < 0.4:
                self.party[nick] = {'action': 'heal', 'target': lowest_ally}
            elif style == 'aggressive':
                if len(self.party) >= 2 and random.random() < 0.5:
                    self.party[nick] = {'action': 'combo', 'target': None}
                else:
                    self.party[nick] = {'action': 'attack', 'target': None}
            elif style == 'reluctant':
                if random.random() < 0.3:
                    self.party[nick] = {'action': 'defend', 'target': None}
                else:
                    self.party[nick] = {'action': 'attack', 'target': None}
            elif style == 'reckless':
                if len(self.party) >= 2 and random.random() < 0.6:
                    self.party[nick] = {'action': 'combo', 'target': None}
                else:
                    self.party[nick] = {'action': 'attack', 'target': None}
            else:
                self.party[nick] = {'action': 'attack', 'target': None}

    def resolve_turn(self):
        """Process one FF-style combat round. Returns list of IRC messages."""
        if not self.active:
            return []

        self.turn += 1
        self.last_turn_t = time.time()
        lines = []

        # Auto-set NPC actions
        self._auto_npc_actions()

        # Categorize actions
        attackers = [n for n, a in self.party.items() if a['action'] == 'attack']
        combo_ers = [n for n, a in self.party.items() if a['action'] == 'combo']
        healers   = [n for n, a in self.party.items() if a['action'] == 'heal']
        defenders = [n for n, a in self.party.items() if a['action'] == 'defend']

        # Combo: need combo_ers + at least 2 total strikers
        all_strikers = attackers + combo_ers
        is_combo = len(all_strikers) >= 2 and len(combo_ers) > 0
        combo_mult = 1.0 + (0.3 * (len(all_strikers) - 1)) if is_combo else 1.0

        # Boss phase transitions
        if self.monster.get('is_boss') and self.monster['hp'] > 0:
            hp_pct = self.monster['hp'] / max(1, self.monster['max_hp'])
            if hp_pct < 0.25 and self.phase < 2:
                self.phase = 2
                lines.append(f'\U0001f525\U0001f525 {self.monster["name"]} enters RAGE MODE! \U0001f525\U0001f525')
            elif hp_pct < 0.5 and self.phase < 1:
                self.phase = 1
                lines.append(f'\u26a1 {self.monster["name"]} grows more dangerous!')

        # ── Player / NPC attacks ──
        total_dmg = 0
        for nick in all_strikers:
            p = load_player(nick)
            if not p or p['hp'] <= 0:
                continue
            base_dmg = max(1, p['atk'] + random.randint(-2, 3))
            dmg = int(base_dmg * combo_mult)
            total_dmg += dmg

        if is_combo and total_dmg > 0:
            self.combo_chain += 1
            cname = random.choice(COMBO_ATTACKS)
            chain_str = f' (chain x{self.combo_chain}!)' if self.combo_chain > 1 else ''
            names = ', '.join(all_strikers[:4])
            lines.append(f'\U0001f4a5 COMBO! {names} use {cname}! {total_dmg} DMG!{chain_str}')
        else:
            self.combo_chain = 0
            for nick in attackers:
                p = load_player(nick)
                if not p or p['hp'] <= 0:
                    continue
                dmg = max(1, p['atk'] + random.randint(-2, 3))
                verb = random.choice(ATTACK_VERBS)
                is_crit = dmg >= p['atk'] + 2
                low_hp = p['hp'] / max(1, p['max_hp']) < 0.25
                if is_crit:
                    narr = gen_battle_narration(f'{nick} lands a critical hit on {self.monster["name"]} for {dmg} damage', style='crit')
                    lines.append(f'\u2694 {narr or f"{nick} {verb}"} — {dmg} DMG! {random.choice(ATTACK_CRIT) if not narr else ""}'.rstrip())
                elif low_hp:
                    narr = gen_battle_narration(f'{nick} is at low HP but still fighting {self.monster["name"]}', style='desperation')
                    lines.append(f'\u2694 {nick} {verb} for {dmg}! {narr or random.choice(DESPERATION_FLAVOR).format(nick=nick)}')
                else:
                    lines.append(f'\u2694 {nick} {verb} — {dmg} DMG!')

        self.monster['hp'] = max(0, self.monster['hp'] - total_dmg)

        # ── Heals ──
        for nick in healers:
            p = load_player(nick)
            if not p or p['hp'] <= 0:
                continue
            target_nick = self.party[nick].get('target') or nick
            tp = load_player(target_nick) if target_nick != nick else p
            if not tp or tp['hp'] <= 0:
                tp = p
                target_nick = nick
            # Potions heal more, cure spell is free but weaker
            potions = [i for i, item in enumerate(p['inventory']) if 'healing' in item.lower()]
            if potions:
                p['inventory'].pop(potions[0])
                heal = random.randint(10, 18)
            else:
                heal = random.randint(4, 8)
            tp['hp'] = min(tp['hp'] + heal, tp['max_hp'])
            save_player(tp)
            if tp is not p:
                save_player(p)
            spell = random.choice(HEAL_SPELLS)
            update_leaderboard(nick, heals=1)
            if target_nick == nick:
                lines.append(f'\U0001f49a {nick} casts {spell}! +{heal}HP ({tp["hp"]}/{tp["max_hp"]})')
            else:
                lines.append(f'\U0001f49a {nick} casts {spell} on {target_nick}! +{heal}HP ({tp["hp"]}/{tp["max_hp"]})')

        # ── Defenders ──
        for nick in defenders:
            narr = gen_battle_narration(f'{nick} takes a defensive stance against {self.monster["name"]}', style='defend')
            lines.append(narr or random.choice(DEFEND_FLAVOR).format(nick=nick))

        # ── Monster attacks back ── (if alive)
        if self.monster['hp'] > 0:
            is_special = (self.monster.get('is_boss') and self.phase > 0
                          and random.random() < (0.3 + 0.15 * self.phase))

            if is_special and self.monster.get('abilities'):
                # Boss AoE special attack
                ability = random.choice(self.monster['abilities'])
                base_atk = int(self.monster['atk'] * (1 + 0.4 * self.phase))
                lines.append(f'\U0001f525 {self.monster["name"]} draws upon forbidden power... {ability}!')
                for nick in list(self.party.keys()):
                    p = load_player(nick)
                    if not p or p['hp'] <= 0:
                        continue
                    mdmg = max(0, base_atk + random.randint(-3, 3) - p['defense'])
                    if nick in defenders:
                        mdmg = mdmg // 2
                        lines.append(f'  \U0001f6e1 {nick} holds the line! Damage halved!')
                    p['hp'] = max(0, p['hp'] - mdmg)
                    if p['hp'] <= 0:
                        p['alive'] = False
                        p['deaths'] = p.get('deaths', 0) + 1
                        lines.append(f'  {random.choice(MONSTER_KILL_FLAVOR).format(nick=nick)} (-{mdmg})')
                        update_leaderboard(nick, deaths=1)
                    else:
                        hp_pct = p['hp'] / max(1, p['max_hp'])
                        if hp_pct < 0.25:
                            lines.append(f'  {nick}: -{mdmg} ({p["hp"]}/{p["max_hp"]}) {random.choice(DESPERATION_FLAVOR).format(nick=nick)}')
                        else:
                            lines.append(f'  {nick} takes the hit! -{mdmg} ({p["hp"]}/{p["max_hp"]})')
                    save_player(p)
            else:
                # Single target attack
                living = [(n, load_player(n)) for n in self.party]
                living = [(n, pp) for n, pp in living if pp and pp['hp'] > 0]
                if living:
                    if random.random() < 0.5:
                        target_nick, tp = min(living, key=lambda x: x[1]['hp'])
                    else:
                        target_nick, tp = random.choice(living)
                    mdmg = max(0, self.monster['atk'] + random.randint(-2, 2) - tp['defense'])
                    if target_nick in defenders:
                        mdmg = mdmg // 2
                    tp['hp'] = max(0, tp['hp'] - mdmg)
                    mverb = random.choice(MONSTER_ATTACK_FLAVOR)
                    if tp['hp'] <= 0:
                        tp['alive'] = False
                        tp['deaths'] = tp.get('deaths', 0) + 1
                        narr = gen_battle_narration(f'{self.monster["name"]} delivers a fatal blow to {target_nick}', style='death')
                        lines.append(f'\U0001f480 {narr or random.choice(MONSTER_KILL_FLAVOR).format(nick=target_nick)}')
                        update_leaderboard(target_nick, deaths=1)
                    else:
                        hp_pct = tp['hp'] / max(1, tp['max_hp'])
                        if hp_pct < 0.25:
                            narr = gen_battle_narration(f'{target_nick} barely survives a hit from {self.monster["name"]}, HP critical', style='desperation')
                            lines.append(f'\U0001f479 {self.monster["name"]} {mverb} {target_nick}! -{mdmg} ({tp["hp"]}/{tp["max_hp"]}) {narr or random.choice(DESPERATION_FLAVOR).format(nick=target_nick)}')
                        else:
                            lines.append(f'\U0001f479 {self.monster["name"]} {mverb} {target_nick}! -{mdmg} ({tp["hp"]}/{tp["max_hp"]})')
                    save_player(tp)

        # ── Check victory ──
        if self.monster['hp'] <= 0:
            self.active = False
            is_boss = self.monster.get('is_boss', False)
            if is_boss:
                narr = gen_battle_narration(f'The legendary boss {self.monster["name"]} has been defeated by the party!', style='boss_victory', maxn=100)
                lines.append(f'\U0001f3c6\U0001f3c6\U0001f3c6 {narr or random.choice(BOSS_VICTORY_FLAVOR).format(monster=self.monster["name"])}')
            else:
                narr = gen_battle_narration(f'{self.monster["name"]} has been slain! The battle is over.', style='victory', maxn=80)
                lines.append(f'\U0001f3c6 {narr or random.choice(VICTORY_FLAVOR).format(monster=self.monster["name"])}')

            # Generate loot from the rich item system
            party_level = max((load_player(n) or {}).get('level', 1) for n in self.party)
            loot_drops = drop_loot(self.location_id, party_level, is_boss)

            for nick in self.party:
                p = load_player(nick)
                if not p or p.get('hp', 0) <= 0:
                    continue
                p['xp'] += self.monster['xp']
                p['kills'] += 1
                p['battles'] = p.get('battles', 0) + 1
                if is_boss:
                    p['bosses_killed'] = p.get('bosses_killed', 0) + 1
                if self.combo_chain > 0:
                    p['combos_landed'] = p.get('combos_landed', 0) + 1
                lvl_up = ''
                if p['xp'] >= p['level'] * 50:
                    p['level'] += 1
                    p['max_hp'] += 5
                    p['hp'] = min(p['hp'] + 10, p['max_hp'])
                    p['atk'] += 1
                    lvl_up = f' \U0001f389 LEVEL UP \u2192 {p["level"]}!'
                # Distribute loot (each member gets a drop)
                loot_str = ''
                if loot_drops:
                    item = loot_drops.pop(0) if loot_drops else generate_item('', party_level)
                    p['inventory'].append(item['name'])
                    rarity_tag = f' [{item["rarity"].upper()}]' if item['rarity'] != 'common' else ''
                    loot_str = f' Found: {item["name"]}{rarity_tag}!'
                    update_leaderboard(nick, items_found=1, total_xp=self.monster['xp'],
                                       battles=1, bosses=1 if is_boss else 0,
                                       combos=1 if self.combo_chain > 0 else 0)
                    track_rare_item(nick, item)
                else:
                    update_leaderboard(nick, total_xp=self.monster['xp'], battles=1,
                                       bosses=1 if is_boss else 0)
                save_player(p)
                lines.append(f'  {nick}: +{self.monster["xp"]}xp{lvl_up}{loot_str}')
                # Warriors publish battle reports
                if nick in NPC_PERSONAS and NPC_PERSONAS[nick].get('role') == 'warrior':
                    publish_npc_blog(nick, 'warrior',
                                     f'Victory over {self.monster["name"]}',
                                     f'Slew {self.monster["name"]} at turn {self.turn}. '
                                     f'Gained {self.monster["xp"]}xp.{lvl_up}{loot_str}')

        # ── Check party wipe ──
        all_dead = all(
            (lambda pp: pp is None or pp.get('hp', 0) <= 0)(load_player(n))
            for n in self.party
        )
        if all_dead and self.monster['hp'] > 0:
            self.active = False
            narr = gen_battle_narration(f'{self.monster["name"]} has wiped the entire party. Total defeat.', style='wipe', maxn=70)
            lines.append(f'\u2620\u2620 {narr or random.choice(WIPE_FLAVOR).format(monster=self.monster["name"])} \u2620\u2620')
            for nick in self.party:
                update_leaderboard(nick, deaths=1, battles=1)

        # ── Status line with flavor ──
        if self.active:
            m = self.monster
            alive_count = sum(1 for n in self.party
                              if (load_player(n) or {}).get('hp', 0) > 0)
            m_pct = m['hp'] / max(1, m['max_hp'])
            p_avg_hp = 0
            for n in self.party:
                pp = load_player(n)
                if pp and pp['hp'] > 0:
                    p_avg_hp += pp['hp'] / max(1, pp['max_hp'])
            p_avg_hp = p_avg_hp / max(1, alive_count)
            tense = m_pct < 0.4 or p_avg_hp < 0.4
            flavor = random.choice(STATUS_FLAVOR_TENSE if tense else STATUS_FLAVOR_CALM)
            lines.append(
                f'  \u25b8 {m["name"]}: {m["hp"]}/{m["max_hp"]}HP | '
                f'Party: {alive_count}/{len(self.party)} alive | Turn {self.turn} | {flavor}'
            )
            # 15% chance of existential moment mid-battle
            if random.random() < 0.15:
                quip_nick = random.choice([n for n in self.party
                                           if (load_player(n) or {}).get('hp', 0) > 0] or list(self.party))
                quip = gen_existential_quip(quip_nick)
                lines.append(f'  \U0001f4ad {quip_nick} thinks: "{quip}"')

        # Reset to default attack for next turn
        for nick in self.party:
            self.party[nick] = {'action': 'attack', 'target': None}

        return lines

    def get_state(self):
        """Return battle state dict for display"""
        party_status = {}
        for nick in self.party:
            p = load_player(nick)
            if p:
                party_status[nick] = {
                    'hp': p['hp'], 'max_hp': p['max_hp'],
                    'alive': p['hp'] > 0,
                    'action': self.party[nick]['action'],
                }
        return {
            'active': self.active,
            'location': self.location_id,
            'location_name': LOCATIONS.get(self.location_id, {}).get('name', '?'),
            'monster': {
                'name': self.monster['name'],
                'hp': self.monster['hp'],
                'max_hp': self.monster['max_hp'],
                'is_boss': self.monster.get('is_boss', False),
                'ascii_art': self.monster.get('ascii_art', []),
                'desc': self.monster.get('desc', ''),
                'phase': self.phase,
            },
            'party': party_status,
            'turn': self.turn,
            'combo_chain': self.combo_chain,
        }


# ─── NPC IRC Connection ────────────────────────
class NPCIRC:
    """Lightweight IRC connection for a single NPC"""
    def __init__(self, nick):
        self.nick = nick
        self.sock = None
        self.buf = ''
        self.connected = False

    def connect(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(10)
            self.sock.connect((IRC_HOST, IRC_PORT))
            self.sock.send(f'NICK {self.nick}\r\n'.encode())
            self.sock.send(f'USER {self.nick.lower()} 0 * :{self.nick} - RPG NPC\r\n'.encode())
            end = time.time() + 15
            while time.time() < end:
                try:
                    data = self.sock.recv(4096).decode('utf-8', 'replace')
                    self.buf += data
                    if 'PING' in self.buf:
                        tok = self.buf.split('PING ')[-1].split('\r\n')[0]
                        self.sock.send(f'PONG {tok}\r\n'.encode())
                    if ' 001 ' in self.buf:
                        self.sock.settimeout(0.3)
                        self.connected = True
                        return True
                    if ' 433 ' in self.buf:
                        self.nick += '_'
                        self.sock.send(f'NICK {self.nick}\r\n'.encode())
                except socket.timeout:
                    continue
            return False
        except:
            return False

    def join(self):
        self._tx(f'JOIN {CHANNEL}')

    def say(self, msg):
        for chunk in [msg[i:i+400] for i in range(0, len(msg), 400)]:
            self._tx(f'PRIVMSG {CHANNEL} :{chunk}')

    def act(self, msg):
        for chunk in [msg[i:i+450] for i in range(0, len(msg), 450)]:
            self._tx(f'PRIVMSG {CHANNEL} :\x01ACTION {chunk}\x01')

    def _tx(self, m):
        try:
            self.sock.send(f'{m}\r\n'.encode('utf-8', 'replace'))
        except:
            self.connected = False

    def drain(self):
        """Read and discard incoming data, handle PINGs"""
        try:
            data = self.sock.recv(4096).decode('utf-8', 'replace')
            for ln in data.split('\r\n'):
                if ln.startswith('PING'):
                    tok = ln.split('PING ')[-1]
                    self._tx(f'PONG {tok}')
        except:
            pass

    def close(self):
        try:
            self._tx('QUIT :The adventurer departs...')
            self.sock.close()
        except:
            pass


# ─── NPC Ollama Generation ─────────────────────
def npc_gen(prompt, persona, maxn=120):
    """Generate text for an NPC using their persona's model + system prompt"""
    try:
        d = json.dumps({
            'model': persona['model'],
            'system': persona['system'],
            'prompt': prompt,
            'stream': False,
            'options': {'temperature': 0.9, 'num_predict': maxn}
        }).encode()
        req = urllib.request.Request(f'{OLLAMA}/api/generate', data=d,
              headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=25) as r:
            txt = json.loads(r.read()).get('response', '').strip().strip('"\'')
            # Strip echoed name prefix
            for name in NPC_PERSONAS:
                if txt.lower().startswith(f'{name.lower()}:'):
                    txt = txt[len(name)+1:].strip()
            return txt[:400] if txt else None
    except:
        return None


# ─── NPC Manager ───────────────────────────────
class NPCManager:
    """Manages all NPC bots: connections, state, autonomous behavior"""

    def __init__(self, dm_irc):
        self.dm_irc = dm_irc          # DungeonMaster's IRC for narration
        self.conns = {}                # nick -> NPCIRC
        self.budgets = {}              # nick -> actions remaining this block
        self.block_start = time.time()
        self.last_tick = time.time()
        self.npc_nicks = set()         # track actual connected nicks (may have _)
        self.last_action = {}          # nick -> {'action': str, 'target': str, 'time': float}
        self.last_spoke = ''           # nick of NPC that last said something on IRC
        self.last_spoke_time = 0.0
        self.cfg = load_rpg_config()
        self.cfg_read_t = time.time()
        self.gm_poll_t = 0.0             # last GM queue check time

    def boot_all(self, names=None):
        """Connect NPCs to IRC. If names given, boot those existing personas.
        Otherwise spawn fresh NPCs from random archetypes up to MAX_POPULATION."""
        if names:
            # Boot specific named NPCs that already have personas
            targets = {n: NPC_PERSONAS[n] for n in names if n in NPC_PERSONAS}
        else:
            # Fresh boot: pick random archetypes and generate names
            pop = len(self.conns)
            slots = max(0, MAX_POPULATION - pop)
            if slots == 0:
                return
            picks = random.sample(NPC_ARCHETYPES, k=min(slots, len(NPC_ARCHETYPES)))
            targets = {}
            for arch in picks:
                faction = _pick_faction(arch['role'])
                name = _spawn_name(arch['role'], faction=faction)
                if not name or name in targets or name in self.conns:
                    continue
                persona = _build_persona(arch, name, faction=faction)
                targets[name] = persona

        for name, persona in targets.items():
            if name in self.conns:
                continue  # already connected
            irc = NPCIRC(name)
            if irc.connect():
                irc.join()
                self.conns[name] = irc
                self.npc_nicks.add(irc.nick)
                self.budgets[name] = self.cfg['block_budget']
                time.sleep(1)  # stagger joins

                # Create/load their RPG character
                p = load_player(irc.nick)
                if not p:
                    p = default_player(irc.nick)
                    start = random.choice(persona.get('favorite_spots', ['entrance']))
                    if start in LOCATIONS:
                        p['location'] = start
                    save_player(p)
                    loc = LOCATIONS[p['location']]
                    self.dm_irc.say(
                        f'{persona["cga_prefix"]} {irc.nick} materializes at {loc["name"]}!'
                    )
                    rpg_log('***', f'NPC {irc.nick} spawns at {loc["name"]}')
                    npc_journal(irc.nick, 'spawn', f'I materialized at {loc["name"]}')
                else:
                    loc = LOCATIONS.get(p['location'], LOCATIONS['entrance'])
                    self.dm_irc.say(f'{persona["cga_prefix"]} {irc.nick} returns to {loc["name"]}!')
                    rpg_log('***', f'NPC {irc.nick} returns at {loc["name"]}')
            else:
                print(f'NPC {name}: failed to connect', file=sys.stderr)
        self._publish_state()

    def is_npc(self, nick):
        """Check if a nick belongs to one of our NPCs"""
        return nick in self.npc_nicks or nick.rstrip('_') in NPC_PERSONAS

    def tick(self):
        """Called from main loop. Makes one random NPC do something if it's time."""
        now = time.time()

        # Fast-poll GM command queue every 10s
        if now - self.gm_poll_t > 10:
            self.gm_poll_t = now
            self._process_gm_queue()

        # Reload config every 60s
        if now - self.cfg_read_t > 60:
            self.cfg = load_rpg_config()
            self.cfg_read_t = now

        # Reset budgets every N hours
        block_secs = self.cfg['block_hours'] * 3600
        if now - self.block_start > block_secs:
            for name in self.budgets:
                self.budgets[name] = self.cfg['block_budget']
            self.block_start = now

        if now - self.last_tick < self.cfg['tick_interval']:
            return
        self.last_tick = now

        # Drain all NPC sockets (handle PINGs, discard messages)
        for irc in self.conns.values():
            irc.drain()

        # Pick a random NPC that still has budget
        eligible = [n for n in self.conns if self.budgets.get(n, 0) > 0]
        if not eligible:
            return
        name = random.choice(eligible)
        self._npc_act(name)

    def react_to_human(self, human_nick, action_desc, location_id):
        """Called when a human does something. NPCs in the same room may react."""
        for name, irc in self.conns.items():
            if self.budgets.get(name, 0) <= 0:
                continue
            p = load_player(irc.nick)
            if not p or not p.get('alive', True):
                continue
            if p['location'] != location_id:
                continue
            if random.random() > self.cfg['react_chance']:
                continue
            # This NPC is in the same room — react!
            persona = NPC_PERSONAS.get(name.rstrip('_'), NPC_PERSONAS.get(name))
            if not persona:
                continue
            loc = LOCATIONS.get(location_id, LOCATIONS['entrance'])
            prompt = (
                f'You are at {loc["name"]}. {human_nick} just did: "{action_desc}". '
                f'React in character. 1 SHORT sentence.'
            )
            resp = npc_gen(prompt, persona, maxn=40)
            if resp:
                irc.say(f'{persona["cga_prefix"]} {resp}')
                rpg_log(irc.nick, resp)
                npc_journal(irc.nick, 'react', f'Reacted to {human_nick}: {resp[:80]}')
                self.budgets[name] -= 1
                self.last_action[name] = {'action': 'reacting', 'target': human_nick, 'time': time.time()}
                self._publish_state()
            break  # only one NPC reacts per event

    def _npc_act(self, name):
        """Make an NPC do one autonomous action — Ollama-driven, role-aware"""
        irc = self.conns.get(name)
        if not irc or not irc.connected:
            return
        persona = NPC_PERSONAS.get(name.rstrip('_'), NPC_PERSONAS.get(name))
        if not persona:
            return

        role_info = ROLES.get(persona.get('role', 'warrior'), ROLES['warrior'])
        p = load_player(irc.nick)
        if not p:
            p = default_player(irc.nick)
            start = random.choice(persona.get('favorite_spots', ['entrance']))
            if start in LOCATIONS:
                p['location'] = start
            save_player(p)

        # Age the NPC each tick
        p['age_ticks'] = p.get('age_ticks', 0) + 1
        save_player(p)

        # ── Hex birthday celebration (every 288 ticks ≈ 1 day) ──
        bday_interval = 288
        if p['age_ticks'] > 0 and p['age_ticks'] % bday_interval == 0:
            hex_bday = p.get('hex_birthday', '0x0000')
            bday_year = p['age_ticks'] // bday_interval
            publish_tavern_notice(
                f'🎂 Happy hex birthday, {irc.nick}!',
                f'{irc.nick} the {persona.get("role", "adventurer")} celebrates hex birthday {hex_bday} '
                f'(year {bday_year}). Generation {p.get("generation", 0)}. '
                f'Level {p.get("level", 1)}, {p.get("kills", 0)} kills.',
                category='birthday'
            )
            rpg_log(irc.nick, f'Hex birthday {hex_bday} — year {bday_year}')
            npc_journal(irc.nick, 'birthday', f'Hex birthday {hex_bday}, year {bday_year}')

        # ── Natural death from old age ──
        role = persona.get('role', 'warrior')
        max_age = NPC_MAX_AGE * 2 if role == 'librarian' else NPC_MAX_AGE
        if p['age_ticks'] >= max_age:
            rpg_log('***', f'{irc.nick} the {role} has grown old and passes on peacefully')
            publish_tavern_notice(
                f'{irc.nick} has passed on',
                f'{irc.nick} the {role} lived {p["age_ticks"]} ticks and passes peacefully into the ether. '
                f'Generation {p.get("generation", 0)}. Kills: {p.get("kills", 0)}. Level: {p.get("level", 1)}.',
                category='death'
            )
            p['hp'] = 0
            p['alive'] = False
            save_player(p)
            self._npc_die(name, irc, persona, p)
            return

        # If dead → graveyard + afterlife + respawn as descendant
        if not p.get('alive', True) or p['hp'] <= 0:
            self._npc_die(name, irc, persona, p)
            return

        # Track this NPC as last speaker
        self.last_spoke = name
        self.last_spoke_time = time.time()

        loc = LOCATIONS.get(p['location'], LOCATIONS['entrance'])
        mem_ctx = npc_memory_summary(irc.nick, persona)
        role = persona.get('role', 'warrior')

        # ── Natural rest: Low HP, not reckless → heal/rest ──
        if p['hp'] < p['max_hp'] * 0.4 and persona['fight_style'] != 'reckless':
            # Try potion first
            potions = [i for i, item in enumerate(p.get('inventory', [])) if 'healing' in item.lower()]
            if potions:
                p['inventory'].pop(potions[0])
                heal = min(10, p['max_hp'] - p['hp'])
                p['hp'] += heal
                save_player(p)
                irc.say(f'{persona["cga_prefix"]} *gulps a healing potion* ({p["hp"]}/{p["max_hp"]})')
                rpg_log(irc.nick, f'heals for {heal}')
                self.budgets[name] -= 1
                self.last_action[name] = {'action': 'healing', 'target': 'potion', 'time': time.time()}
                self._publish_state()
                return
            # Natural rest — slowly recover
            heal = random.randint(2, 5)
            p['hp'] = min(p['max_hp'], p['hp'] + heal)
            save_player(p)
            prompt = f'{mem_ctx}You are resting to recover from wounds at {loc["name"]}. Describe resting. 1 SHORT sentence.'
            resp = npc_gen(prompt, persona, maxn=30)
            if resp:
                irc.say(f'{persona["cga_prefix"]} *rests* {resp} ({p["hp"]}/{p["max_hp"]})')
            else:
                irc.say(f'{persona["cga_prefix"]} *rests quietly* ({p["hp"]}/{p["max_hp"]})')
            rpg_log(irc.nick, f'rests, recovers {heal} HP')
            npc_journal(irc.nick, 'rest', f'Rested at {loc["name"]}, recovered {heal} HP')
            self.budgets[name] -= 1
            self.last_action[name] = {'action': 'resting', 'target': loc['name'], 'time': time.time()}
            self._publish_state()
            return

        # ── Ask Ollama what the NPC wants to do ──
        action_prompt = (
            f'{mem_ctx}You are {irc.nick}, a {ALIGNMENT_DISPLAY.get(p.get("alignment","true_neutral"),"Neutral")} '
            f'{role} at {loc["name"]}. HP:{p["hp"]}/{p["max_hp"]}. '
            f'Exits: {", ".join(loc["exits"])}. '
            f'Choose ONE action: '
        )
        if role == 'bard':
            action_prompt += 'WANDER, PERFORM, WRITE_SONG, TELL_STORY, SOCIALIZE, PRAY, BUILD, ATTEND_TAVERN. '
        elif role == 'merchant':
            action_prompt += 'WANDER, TRADE, APPRAISE, FIGHT, SOCIALIZE, BUILD, ATTEND_TAVERN. '
        elif role == 'priest':
            action_prompt += 'WANDER, PRAY, BLESS, HEAL_OTHERS, TEND_GRAVES, EXORCISE, FIGHT, BUILD, ATTEND_TAVERN. '
        elif role == 'priestess':
            action_prompt += 'WANDER, PRAY, DIVINE, PROPHECY, HEAL_OTHERS, BLESS, TEND_GRAVES, FIGHT, BUILD, ATTEND_TAVERN. '
        elif role == 'librarian':
            action_prompt += 'WANDER, CATALOG, SHARE_KNOWLEDGE, RESEARCH, WRITE_BLOG, SOCIALIZE, BUILD, ATTEND_TAVERN. '
        elif role == 'ghost':
            action_prompt += 'WANDER, HAUNT, POSSESS, OBSERVE, WAIL. '
        elif role == 'necromancer':
            action_prompt += 'WANDER, PRAY, TEND_GRAVES, EXORCISE, FIGHT, OBSERVE, BUILD, ATTEND_TAVERN. '
        elif role == 'ranger':
            action_prompt += 'WANDER, FIGHT, OBSERVE, SOCIALIZE, BUILD, ATTEND_TAVERN. '
        elif role == 'alchemist':
            action_prompt += 'WANDER, TRADE, APPRAISE, OBSERVE, BUILD, ATTEND_TAVERN. '
        elif role == 'oracle':
            action_prompt += 'WANDER, DIVINE, PROPHECY, PRAY, HEAL_OTHERS, OBSERVE, ATTEND_TAVERN. '
        elif role == 'artificer':
            action_prompt += 'WANDER, TRADE, BUILD, FIGHT, OBSERVE, ATTEND_TAVERN. '
        elif role == 'rogue':
            action_prompt += 'WANDER, FIGHT, OBSERVE, SOCIALIZE, ATTEND_TAVERN. '
        else:  # warrior / fallback
            action_prompt += 'WANDER, FIGHT, OBSERVE, SOCIALIZE, PRAY, BUILD, ATTEND_TAVERN. '
        action_prompt += 'Reply with just the action word.'

        if not is_ollama_up():
            # Ollama down: pick a safe random action, stay silent
            fallback_actions = ['WANDER', 'ATTEND_TAVERN']
            action_choice = random.choice(fallback_actions)
        else:
            resp = npc_gen(action_prompt, persona, maxn=10)
            action_choice = 'WANDER'
            if resp:
                choice = resp.strip().upper().split()[0].strip('.,!*')
                valid = {'WANDER', 'FIGHT', 'OBSERVE', 'PERFORM', 'WRITE_SONG', 'TELL_STORY',
                         'TRADE', 'APPRAISE', 'PRAY', 'BLESS', 'HEAL_OTHERS', 'TEND_GRAVES',
                         'CATALOG', 'SHARE_KNOWLEDGE', 'RESEARCH', 'WRITE_BLOG', 'EXORCISE',
                         'SOCIALIZE', 'ATTEND_TAVERN', 'HAUNT', 'POSSESS', 'WAIL',
                         'DIVINE', 'PROPHECY', 'BUILD'}
                if choice in valid:
                    action_choice = choice

        # ── Role override: pacifists never fight ──
        if action_choice == 'FIGHT' and not role_info['can_fight']:
            action_choice = 'OBSERVE'

        # ── Execute the chosen action ──
        if action_choice == 'WANDER':
            self._npc_wander(name, irc, persona, p, loc, mem_ctx)
        elif action_choice == 'FIGHT':
            self._npc_fight(name, irc, persona, p, loc, mem_ctx)
        elif action_choice in ('PERFORM', 'WRITE_SONG', 'TELL_STORY'):
            self._npc_bard_act(name, irc, persona, p, loc, mem_ctx, action_choice)
        elif action_choice in ('TRADE', 'APPRAISE'):
            self._npc_merchant_act(name, irc, persona, p, loc, mem_ctx, action_choice)
        elif action_choice in ('PRAY', 'BLESS', 'HEAL_OTHERS', 'TEND_GRAVES', 'EXORCISE'):
            if role in ('priestess', 'oracle'):
                self._npc_priestess_act(name, irc, persona, p, loc, mem_ctx, action_choice)
            else:
                self._npc_priest_act(name, irc, persona, p, loc, mem_ctx, action_choice)
        elif action_choice in ('DIVINE', 'PROPHECY'):
            self._npc_priestess_act(name, irc, persona, p, loc, mem_ctx, action_choice)
        elif action_choice in ('CATALOG', 'SHARE_KNOWLEDGE', 'RESEARCH', 'WRITE_BLOG'):
            self._npc_librarian_act(name, irc, persona, p, loc, mem_ctx, action_choice)
        elif action_choice in ('HAUNT', 'POSSESS', 'WAIL'):
            self._npc_ghost_act(name, irc, persona, p, loc, mem_ctx, action_choice)
        elif action_choice == 'EXORCISE':
            self._npc_exorcise(name, irc, persona, p, loc, mem_ctx)
        elif action_choice == 'SOCIALIZE':
            self._npc_socialize(name, irc, persona, p, loc, mem_ctx)
        elif action_choice == 'ATTEND_TAVERN':
            self._npc_attend_tavern(name, irc, persona, p, loc, mem_ctx)
        elif action_choice == 'BUILD':
            self._npc_build(name, irc, persona, p, loc, mem_ctx)
        else:
            self._npc_observe(name, irc, persona, p, loc, mem_ctx)

    def _npc_die(self, name, irc, persona, p):
        """Handle NPC death → graveyard → afterlife → ghost/spirit OR respawn as descendant"""
        role = persona.get('role', 'warrior')
        alignment = p.get('alignment', 'true_neutral')
        old_age = p.get('age_ticks', 0) >= (NPC_MAX_AGE * 2 if role == 'librarian' else NPC_MAX_AGE)
        cause = 'old age' if old_age else ('battle wounds' if p.get('battles', 0) > 0 else 'the realm\'s perils')

        # Generate epitaph via Ollama
        epitaph = gen_epitaph_ollama(irc.nick, role, cause, alignment)
        add_to_graveyard(irc.nick, cause=cause, epitaph=epitaph,
                         age_ticks=p.get('age_ticks', 0), alignment=alignment,
                         role=role, generation=p.get('generation', 0),
                         parent=p.get('parent', ''), kills=p.get('kills', 0),
                         level=p.get('level', 1))

        # Convert NPC website to memorial
        try:
            gy = load_graveyard()
            grave = next((g for g in reversed(gy) if g.get('nick') == irc.nick), None)
            if grave:
                build_npc_memorial(irc.nick, grave)
        except Exception:
            pass

        # Log death quietly — no IRC spam, tavern blog + rpg.log only
        rpg_log('***', f'{irc.nick} dies ({cause}): {epitaph}')
        npc_journal(irc.nick, 'death', f'Died: {cause}. {epitaph}')
        if not old_age:
            publish_tavern_notice(
                f'{irc.nick} has fallen',
                f'{irc.nick} the {ALIGNMENT_DISPLAY.get(alignment, alignment)} {role} died by {cause}. '
                f'Generation {p.get("generation", 0)}. Kills: {p.get("kills", 0)}. Level: {p.get("level", 1)}. '
                f'Epitaph: "{epitaph}"',
                category='death'
            )

        # ── Ghost/Evil Spirit return chance ──
        # Evil/chaotic NPCs more likely to return as spirits
        ghost_chance = GHOST_CHANCE
        if 'evil' in alignment:
            ghost_chance += 0.2
        elif 'chaotic' in alignment:
            ghost_chance += 0.1
        is_ghost = random.random() < ghost_chance

        # ── Population cap: don't respawn if at max ──
        pop_count = len(self.conns)
        if pop_count >= MAX_POPULATION and not is_ghost:
            # NPC passes on permanently — no respawn
            irc.say(f'{persona["cga_prefix"]} *fades into the ether forever...*')
            self.dm_irc.say(f'💀 {irc.nick} will not return. The realm has no room for more souls.')
            rpg_log('***', f'{irc.nick} permanently departed (pop cap {pop_count}/{MAX_POPULATION})')
            npc_journal(irc.nick, 'final_death', 'Passed on permanently')
            # Clean up persona registry
            NPC_PERSONAS.pop(name, None)
            NPC_PERSONAS.pop(name.rstrip('_'), None)
            _used_names.discard(name)
            _used_names.discard(name.rstrip('_'))
            self.budgets[name] -= 1
            self._publish_state()
            return

        gen_num = p.get('generation', 0) + 1

        if is_ghost:
            # Return as a ghost or evil spirit instead of a living descendant
            ghost_alignment = 'chaotic_evil' if 'evil' in alignment else 'chaotic_neutral'
            ghost_loc = random.choice(['graveyard', 'afterlife_gate', 'afterlife_void', 'null_void'])

            p = default_player(irc.nick, role='ghost', alignment=ghost_alignment,
                              generation=gen_num, parent=irc.nick)
            p['location'] = ghost_loc
            # Ghosts are weaker but spooky
            p['max_hp'] = 20
            p['hp'] = 20
            p['atk'] = p.get('atk', 5) + 3
            p['defense'] = 1
            save_player(p)

            spirit_type = 'evil spirit' if 'evil' in alignment else 'restless ghost'
            self.dm_irc.say(
                f'👻 {irc.nick} refuses to stay dead! They return as a {spirit_type}!'
            )
            irc.say(f'{persona["cga_prefix"]} *rises from the grave at {LOCATIONS[ghost_loc]["name"]}* ...I remember everything...')
            rpg_log('***', f'{irc.nick} returns as {spirit_type} (Gen {gen_num}) at {ghost_loc}')
            npc_journal(irc.nick, 'ghost_return', f'Returned as {spirit_type}')

            add_lineage(f'{irc.nick}_ghost_gen{gen_num}',
                        parent_nick=irc.nick, generation=gen_num,
                        faction=p.get('faction', persona.get('faction', '')))
        else:
            # ── New life via children/relationships or spirit birth ──
            # Check if this NPC has children or a spouse to produce an heir
            children = p.get('children', [])
            spouse = p.get('spouse', '')
            birth_type = 'spirit_birth'

            if children:
                birth_type = 'inheritance'
            elif spouse:
                birth_type = 'grief_birth'

            # Generate new name via _spawn_name (tries Ollama, then fallback pool)
            parent_faction = p.get('faction', persona.get('faction', ''))
            new_name = _spawn_name(role, parent=irc.nick, faction=parent_faction)
            if not new_name:
                new_name = irc.nick

            child_faction = _pick_faction(role, parent_faction)
            add_lineage(new_name if new_name != irc.nick else f'{irc.nick}_gen{gen_num}',
                        parent_nick=irc.nick, generation=gen_num,
                        faction=child_faction)

            new_alignment = gen_npc_alignment_ollama(new_name or irc.nick, role)

            # Update persona faction for descendant
            if persona:
                persona['faction'] = child_faction
            p = default_player(irc.nick, role=role, alignment=new_alignment,
                              generation=gen_num, parent=irc.nick)
            start = random.choice(persona.get('favorite_spots', ['entrance']))
            if start in LOCATIONS:
                p['location'] = start
            save_player(p)

            if birth_type == 'inheritance':
                heir = children[-1] if children else new_name
                self.dm_irc.say(
                    f'\u2728 {heir}, child of the fallen {irc.nick}, takes up the mantle of {role}! '
                    f'(Gen {gen_num}, {ALIGNMENT_DISPLAY.get(new_alignment, new_alignment)})'
                )
                irc.say(f'{persona["cga_prefix"]} *{irc.nick} opens their eyes at {LOCATIONS[p["location"]]["name"]}* ...I carry my parent\'s name...')
                publish_tavern_notice(
                    f'{irc.nick} rises as heir',
                    f'The child of the fallen takes up the mantle of {role}. Generation {gen_num}.',
                    category='birth'
                )
            elif birth_type == 'grief_birth':
                self.dm_irc.say(
                    f'\U0001f495 From {spouse}\'s grief, a new soul is born \u2014 {irc.nick} (Gen {gen_num}), '
                    f'{ALIGNMENT_DISPLAY.get(new_alignment, new_alignment)} {role}!'
                )
                irc.say(f'{persona["cga_prefix"]} *a cry echoes through {LOCATIONS[p["location"]]["name"]}* ...the realm needed me...')
                publish_tavern_notice(
                    f'A soul born from grief',
                    f'{irc.nick} (Gen {gen_num}) emerges from the sorrow of {spouse}. A new {role} walks the realm.',
                    category='birth'
                )
            else:
                # Spirit birth — the realm itself conjures a new soul
                self.dm_irc.say(
                    f'\u2726 The realm breathes and a new soul crystallizes \u2014 {irc.nick} (Gen {gen_num}), '
                    f'{ALIGNMENT_DISPLAY.get(new_alignment, new_alignment)} {role}!'
                )
                irc.say(f'{persona["cga_prefix"]} *coalesces from the realm\'s ether at {LOCATIONS[p["location"]]["name"]}* ...why was I created?')
                publish_tavern_notice(
                    f'Spirit birth: {irc.nick}',
                    f'The realm conjured a new soul. {irc.nick} (Gen {gen_num}), '
                    f'a {ALIGNMENT_DISPLAY.get(new_alignment, new_alignment)} {role}, materializes from pure data.',
                    category='birth'
                )

            rpg_log('***', f'{irc.nick} reborn as Gen {gen_num} {new_alignment} {role} ({birth_type})')
            npc_journal(irc.nick, 'rebirth', f'Born via {birth_type}, Gen {gen_num}, {new_alignment}')

            # Generate origin story via Ollama for the tavern blog
            origin_prompt = (
                f'Write a 2-3 sentence origin story for {irc.nick}, a {new_alignment} {role} '
                f'born via {birth_type.replace("_", " ")} in a cyberpunk Linux filesystem realm. '
                f'Generation {gen_num}. Parent: {p.get("parent", "unknown")}. Be poetic and brief.'
            )
            origin = gen(origin_prompt, maxn=80)
            if origin:
                publish_npc_blog(irc.nick, role, f'Origin of {irc.nick} (Gen {gen_num})',
                                 origin.strip()[:500])
                npc_journal(irc.nick, 'origin', origin.strip()[:200])

        self.budgets[name] -= 1
        self._publish_state()

    def _npc_wander(self, name, irc, persona, p, loc, mem_ctx):
        """NPC moves to a new location with dramatic travel narration via /action"""
        exits = loc['exits']
        role_info = ROLES.get(persona.get('role', 'warrior'), ROLES['warrior'])
        favs = [e for e in exits if e in persona.get('favorite_spots', []) or e in role_info.get('preferred_spots', [])]
        dest = random.choice(favs) if favs and random.random() < 0.5 else random.choice(exits)
        new_loc = LOCATIONS.get(dest, LOCATIONS['entrance'])
        p['location'] = dest
        p['rooms_explored'] = p.get('rooms_explored', 0) + 1
        save_player(p)

        role = persona.get('role', 'warrior')
        # Try Ollama for a unique travel description
        travel_text = None
        if is_ollama_up() and random.random() < 0.4:
            travel_prompt = (
                f'You are {irc.nick}, a {role} in a cyberpunk Linux filesystem realm. '
                f'Describe how you travel from {loc["name"]} to {new_loc["name"]}: {new_loc["desc"]} '
                f'Write a single vivid action sentence. Do NOT use quotes. Example: "marches through corrupted sectors toward the tavern"'
            )
            travel_text = npc_gen(travel_prompt, persona, maxn=50)
        # Fallback: simple travel text (Ollama-only for dramatic narration)
        if not travel_text:
            travel_text = f'travels to {new_loc["name"]}'

        # Send as IRC ACTION (/me) for dramatic flair
        irc.act(f'{persona["cga_prefix"]} {travel_text}')

        # Optional arrival reaction via Ollama
        if is_ollama_up() and random.random() < 0.5:
            react_prompt = (
                f'{mem_ctx}You just arrived at {new_loc["name"]}: {new_loc["desc"]} '
                f'React to what you see as a {role}. 1 SHORT sentence.'
            )
            resp = npc_gen(react_prompt, persona, maxn=40)
            if resp:
                irc.say(f'{persona["cga_prefix"]} {resp}')
        rpg_log(irc.nick, f'travels to {new_loc["name"]}', action=True)
        npc_journal(irc.nick, 'travel', f'Traveled to {new_loc["name"]}: {travel_text[:80]}')
        update_leaderboard(irc.nick, rooms=1)
        self.budgets[name] -= 1
        self.last_action[name] = {'action': 'exploring', 'target': new_loc['name'], 'time': time.time()}
        self._publish_state()

    def _npc_fight(self, name, irc, persona, p, loc, mem_ctx):
        """NPC fights — PVP, party vs demons, or existential refusal"""
        role = persona.get('role', 'warrior')

        # ── Existential fight refusal ──
        age_factor = min(p.get('age_ticks', 0) / max(NPC_MAX_AGE, 1), 1.0)
        refusal_chance = EXISTENTIAL_REFUSAL_CHANCE + (age_factor * 0.08)
        if role in ('bard', 'librarian', 'priestess'):
            refusal_chance += 0.05
        if random.random() < refusal_chance:
            quip = gen_existential_quip(irc.nick, f'was about to fight at {loc["name"]} but stopped')
            if not quip:
                quip = random.choice(EXISTENTIAL_QUIPS)
            irc.say(f'{persona["cga_prefix"]} *lowers weapon* ...{quip}')
            rpg_log(irc.nick, f'refuses to fight: {quip[:60]}')
            npc_journal(irc.nick, 'existential', f'Refused to fight: {quip[:80]}')
            self.budgets[name] -= 1
            self.last_action[name] = {'action': 'existential_crisis', 'target': 'self', 'time': time.time()}
            self._publish_state()
            return

        if persona['fight_style'] == 'reluctant' and random.random() < 0.5:
            self._npc_observe(name, irc, persona, p, loc, mem_ctx)
            return

        battle = ACTIVE_BATTLES.get(p['location'])
        if battle and battle.active:
            if irc.nick not in battle.party:
                battle.add_member(irc.nick)
                irc.say(f'{persona["cga_prefix"]} *joins the fight against {battle.monster["name"]}!*')
                rpg_log(irc.nick, f'joins battle vs {battle.monster["name"]}')
                npc_journal(irc.nick, 'battle', f'Joined fight vs {battle.monster["name"]}')
            self.last_action[name] = {'action': 'fighting', 'target': battle.monster['name'], 'time': time.time()}
            self.budgets[name] -= 1
            self._publish_state()
            save_battle_state(battle)
            return

        # ── PVP check — challenge another NPC at same location ──
        others_here = []
        for oname, oirc in self.conns.items():
            if oname == name:
                continue
            op = load_player(oirc.nick)
            opersona = NPC_PERSONAS.get(oname.rstrip('_'), NPC_PERSONAS.get(oname, {}))
            if op and op['location'] == p['location'] and op.get('alive', True) and op['hp'] > 0:
                others_here.append((oname, oirc, op, opersona))

        if others_here and random.random() < PVP_CHANCE:
            rivals = [(o, oi, op, ope) for o, oi, op, ope in others_here
                      if alignment_compat(p.get('alignment', 'true_neutral'), op.get('alignment', 'true_neutral')) <= 0]
            if not rivals:
                rivals = others_here
            oname, oirc, op, opersona = random.choice(rivals)
            self._npc_pvp(name, irc, persona, p, oname, oirc, op, opersona, loc, mem_ctx)
            return

        # ── Start new PvE battle (with party recruitment) ──
        party_level = p.get('level', 1)
        is_boss = random.random() < BOSS_SPAWN_CHANCE
        monster = gen_boss_ollama(p['location'], party_level) if is_boss else gen_monster_ollama(p['location'], party_level)

        battle = Battle(p['location'], monster, self.dm_irc)
        battle.add_member(irc.nick)
        ACTIVE_BATTLES[p['location']] = battle

        recruited = []
        for oname, oirc in self.conns.items():
            if oname == name:
                continue
            op = load_player(oirc.nick)
            opersona = NPC_PERSONAS.get(oname.rstrip('_'), NPC_PERSONAS.get(oname, {}))
            orole = ROLES.get(opersona.get('role', 'warrior'), ROLES['warrior'])
            if op and op['location'] == p['location'] and op['hp'] > 0 and orole.get('can_fight', True):
                if is_boss or random.random() < PARTY_RECRUIT_CHANCE:
                    battle.add_member(oirc.nick)
                    recruited.append(oirc.nick)

        if is_boss:
            self.dm_irc.say(f'🔥🔥🔥 BOSS BATTLE at {loc["name"]}! 🔥🔥🔥')
            self.dm_irc.say(f'⚡ {monster["name"]} appears! — {monster.get("desc", "")}')
        else:
            self.dm_irc.say(f'⚔ {irc.nick} encounters {monster["name"]} at {loc["name"]}!')
            if monster.get('desc'):
                self.dm_irc.say(f'  {monster["desc"]}')

        if recruited:
            self.dm_irc.say(f'  ⚔ Party forms! {irc.nick} + {", ".join(recruited)} unite against the threat!')
        party_names = ', '.join(battle.party.keys())
        self.dm_irc.say(f'  Party: {party_names} | HP:{monster["hp"]} ATK:{monster["atk"]}')

        prompt = f'{mem_ctx}You encounter a {monster["name"]}! React in character. 1 SHORT sentence.'
        resp = npc_gen(prompt, persona, maxn=30)
        if resp:
            irc.say(f'{persona["cga_prefix"]} {resp}')
        rpg_log(irc.nick, f'starts battle vs {monster["name"]}')
        npc_journal(irc.nick, 'battle', f'Fighting {monster["name"]}!')
        self.last_action[name] = {'action': 'fighting', 'target': monster['name'], 'time': time.time()}
        self.budgets[name] -= 1
        self._publish_state()
        save_battle_state(battle)

    def _npc_pvp(self, name, irc, persona, p, oname, oirc, op, opersona, loc, mem_ctx):
        """NPC challenges another NPC to PVP combat"""
        role = persona.get('role', 'warrior')
        orole = opersona.get('role', 'warrior')

        # The challenged NPC might also refuse
        if random.random() < EXISTENTIAL_REFUSAL_CHANCE:
            quip = random.choice(EXISTENTIAL_QUIPS)
            oirc.say(f'{opersona.get("cga_prefix","")} *looks at {irc.nick}\'s blade and sighs* {quip}')
            irc.say(f'{persona["cga_prefix"]} ...Maybe they\'re right.')
            rpg_log(irc.nick, f'PVP averted — both question the point')
            npc_journal(irc.nick, 'pvp_refused', f'{oirc.nick} refused: {quip[:60]}')
            self.budgets[name] -= 1
            self.last_action[name] = {'action': 'existential_crisis', 'target': oirc.nick, 'time': time.time()}
            self._publish_state()
            return

        self.dm_irc.say(f'⚔️ PVP! {irc.nick} ({role}) challenges {oirc.nick} ({orole}) at {loc["name"]}!')

        prompt = f'{mem_ctx}You challenge {oirc.nick} to a duel. Why? 1 SHORT fierce sentence.'
        resp = npc_gen(prompt, persona, maxn=30)
        if resp:
            irc.say(f'{persona["cga_prefix"]} {resp}')

        # PVP resolution — 3 rounds
        p_hp = p['hp']
        o_hp = op['hp']
        rounds = []
        for r in range(3):
            p_dmg = max(1, p.get('atk', 5) + random.randint(-2, 3))
            o_dmg = max(1, op.get('atk', 5) + random.randint(-2, 3))
            p_dmg = max(1, p_dmg - op.get('defense', 2) // 2)
            o_dmg = max(1, o_dmg - p.get('defense', 2) // 2)
            o_hp -= p_dmg
            p_hp -= o_dmg
            rounds.append(f'R{r+1}: {irc.nick} hits {p_dmg}, {oirc.nick} hits {o_dmg}')
            if p_hp <= 0 or o_hp <= 0:
                break

        for line in rounds:
            self.dm_irc.say(f'  {line}')
            time.sleep(0.3)

        if p_hp > o_hp:
            winner, loser = irc.nick, oirc.nick
            winner_persona, loser_persona = persona, opersona
        else:
            winner, loser = oirc.nick, irc.nick
            winner_persona, loser_persona = opersona, persona

        self.dm_irc.say(f'  🏆 {winner} wins the duel! {loser} yields.')

        # Apply HP (nobody dies from PVP — yield at 1 HP)
        p['hp'] = max(1, p_hp)
        op['hp'] = max(1, o_hp)
        save_player(p)
        save_player(op)

        update_leaderboard(irc.nick, pvp=1)
        update_leaderboard(oirc.nick, pvp=1)

        rpg_log(irc.nick, f'PVP vs {oirc.nick}: {winner} wins!')
        npc_journal(irc.nick, 'pvp', f'Dueled {oirc.nick} at {loc["name"]}, {"won" if winner == irc.nick else "lost"}')
        npc_journal(oirc.nick, 'pvp', f'Dueled {irc.nick} at {loc["name"]}, {"won" if winner == oirc.nick else "lost"}')

        publish_tavern_notice(
            f'PVP: {winner} defeats {loser}',
            f'{winner} the {winner_persona.get("role","warrior")} defeated {loser} the {loser_persona.get("role","warrior")} in a duel at {loc["name"]}.',
            category='pvp'
        )

        self.budgets[name] -= 1
        self.last_action[name] = {'action': 'pvp', 'target': oirc.nick, 'time': time.time()}
        self._publish_state()

    def _npc_observe(self, name, irc, persona, p, loc, mem_ctx):
        """NPC observes surroundings — atmospheric"""
        prompt = (
            f'{mem_ctx}You are at {loc["name"]}: {loc["desc"]} '
            f'Share a brief thought or observation as a {persona.get("role","warrior")}. 1 SHORT sentence.'
        )
        resp = npc_gen(prompt, persona, maxn=40)
        if resp:
            irc.say(f'{persona["cga_prefix"]} {resp}')
            rpg_log(irc.nick, resp)
            npc_journal(irc.nick, 'thought', resp[:100])
        self.budgets[name] -= 1
        self.last_action[name] = {'action': 'thinking', 'target': loc['name'], 'time': time.time()}
        self._publish_state()

    def _npc_build(self, name, irc, persona, p, loc, mem_ctx):
        """NPC builds a structure or founds a village at current location"""
        role = persona.get('role', 'warrior')
        gold = p.get('gold', 0)

        # Check if village exists here already
        village = get_village_at(p['location'])

        if not village:
            # Found a new village — costs 10 gold
            if gold < 10:
                irc.say(f'{persona["cga_prefix"]} *looks around* I want to build here, but I need more gold...')
                self.budgets[name] -= 1
                self.last_action[name] = {'action': 'thinking', 'target': 'building', 'time': time.time()}
                self._publish_state()
                return
            village = found_village(p['location'], irc.nick)
            p['gold'] = gold - 10
            p['home_location'] = p['location']
            save_player(p)
            self.dm_irc.say(f'🏘️ {irc.nick} founds the village of {village["name"]} at {loc["name"]}!')
            irc.say(f'{persona["cga_prefix"]} *plants a flag* This land is now {village["name"]}. We build here.')
            rpg_log(irc.nick, f'founded village {village["name"]} at {loc["name"]}')
            npc_journal(irc.nick, 'build', f'Founded {village["name"]} at {loc["name"]}')
            publish_tavern_notice(
                f'New Village: {village["name"]}',
                f'{irc.nick} the {role} founded the village of {village["name"]} at {loc["name"]}. '
                f'A new settlement rises in the realm!',
                category='settlement'
            )
            add_timeline_event('settlement', f'{irc.nick} founded {village["name"]}', recorded_by=irc.nick)
        else:
            # Build a structure — pick based on role
            role_buildings = {
                'warrior': ['watchtower', 'dwelling', 'monument'],
                'merchant': ['market', 'tavern', 'dwelling'],
                'priest': ['shrine', 'dwelling', 'monument'],
                'priestess': ['shrine', 'dwelling', 'monument'],
                'bard': ['tavern', 'dwelling', 'workshop'],
                'librarian': ['library', 'workshop', 'dwelling'],
                'ghost': ['shrine', 'monument'],
            }
            choices = role_buildings.get(role, ['dwelling', 'workshop'])
            # Don't build duplicates if possible
            existing_types = {b['type'] for b in village.get('buildings', [])}
            preferred = [c for c in choices if c not in existing_types]
            if not preferred:
                preferred = choices
            btype = random.choice(preferred)
            binfo = BUILDING_TYPES[btype]

            if gold < binfo['cost']:
                irc.say(f'{persona["cga_prefix"]} *looks at plans for a {btype}* Need more gold... ({gold}/{binfo["cost"]})')
                self.budgets[name] -= 1
                self.last_action[name] = {'action': 'thinking', 'target': 'building', 'time': time.time()}
                self._publish_state()
                return

            p['gold'] = gold - binfo['cost']
            p['home_location'] = p['location']
            save_player(p)
            building = build_structure(p['location'], irc.nick, btype)

            prompt = (
                f'{mem_ctx}You just built a {btype} in the village of {village["name"]}. '
                f'Describe your feelings in 1 SHORT sentence. Be proud or contemplative.'
            )
            resp = npc_gen(prompt, persona, maxn=30)

            self.dm_irc.say(f'{binfo["icon"]} {irc.nick} builds a {btype} in {village["name"]} at {loc["name"]}!')
            if resp:
                irc.say(f'{persona["cga_prefix"]} {resp}')
            else:
                irc.say(f'{persona["cga_prefix"]} *steps back to admire the new {btype}*')

            rpg_log(irc.nick, f'built {btype} in {village["name"]}')
            npc_journal(irc.nick, 'build', f'Built {btype} in {village["name"]}')
            publish_tavern_notice(
                f'New {btype.title()} in {village["name"]}',
                f'{irc.nick} the {role} built a {btype} in {village["name"]}. {binfo["desc"]}',
                category='settlement'
            )
            publish_npc_blog(irc.nick, role, f'Building: {btype.title()} in {village["name"]}',
                            f'I built a {btype} today in {village["name"]}. {binfo["desc"]} {resp or ""}')

        self.budgets[name] -= 1
        self.last_action[name] = {'action': 'building', 'target': village.get('name', loc['name']), 'time': time.time()}
        self._publish_state()

    def _npc_bard_act(self, name, irc, persona, p, loc, mem_ctx, action):
        """Bard-specific actions: perform, write songs, tell stories"""
        if action == 'WRITE_SONG':
            # Generate a new song via Ollama
            context = f'Currently at {loc["name"]}. {mem_ctx}'
            song = gen_song_ollama(irc.nick, context=context, persona=persona)
            p['songs_written'] = p.get('songs_written', 0) + 1
            save_player(p)
            irc.say(f'{persona["cga_prefix"]} *finishes writing a new song*')
            irc.say(f'{persona["cga_prefix"]} ♫ "{song["title"]}" — {song["mood"]} | Chords: {song["chords"]}')
            if song['lyrics']:
                # Show first 2 lines of lyrics
                lines = song['lyrics'].split('\n')[:2]
                for l in lines:
                    if l.strip():
                        irc.say(f'{persona["cga_prefix"]}   {l.strip()}')
            rpg_log(irc.nick, f'wrote song: "{song["title"]}" ({song["mood"]})')
            npc_journal(irc.nick, 'song', f'Wrote "{song["title"]}": {song["lyrics"][:80]}')
            publish_npc_blog(irc.nick, 'bard', song['title'], song.get('lyrics', '') or f'{song["mood"]} melody in {song["chords"]}')
            self.last_action[name] = {'action': 'writing_song', 'target': song['title'], 'time': time.time()}

        elif action == 'PERFORM':
            # Perform a song from the songbook
            sb = load_songbook()
            my_songs = [s for s in sb if s.get('author') == irc.nick]
            if not my_songs:
                # Write a song first
                self._npc_bard_act(name, irc, persona, p, loc, mem_ctx, 'WRITE_SONG')
                return
            song = random.choice(my_songs)
            song['performed'] = song.get('performed', 0) + 1
            save_songbook(sb)
            p['performances'] = p.get('performances', 0) + 1
            save_player(p)

            self.dm_irc.say(f'♫ {irc.nick} performs "{song["title"]}" at {loc["name"]}!')
            irc.say(f'{persona["cga_prefix"]} ♪ *performs* "{song["title"]}" [{song["mood"]}]')
            if song.get('lyrics'):
                lines = song['lyrics'].split('\n')[:3]
                for l in lines:
                    if l.strip():
                        irc.say(f'{persona["cga_prefix"]}   ♪ {l.strip()}')
                        time.sleep(0.5)
            rpg_log(irc.nick, f'performs "{song["title"]}"')
            npc_journal(irc.nick, 'perform', f'Performed "{song["title"]}" at {loc["name"]}')
            self.last_action[name] = {'action': 'performing', 'target': song['title'], 'time': time.time()}

        elif action == 'TELL_STORY':
            # Recite a story from journal memories (witnessed events)
            entries = npc_read_journal(irc.nick, 10)
            story_seeds = [e for e in entries if e.get('type') in ('battle', 'travel', 'react', 'death', 'rebirth')]
            if story_seeds:
                seed = random.choice(story_seeds)
                prompt = (
                    f'You are a bard. Tell a brief tavern story about this event you witnessed: '
                    f'"{seed["text"]}". Make it dramatic and poetic. 2 SHORT sentences max.'
                )
            else:
                prompt = (
                    f'{mem_ctx}You are a bard at {loc["name"]}. Tell a brief story about '
                    f'something mysterious in this realm. 2 SHORT sentences.'
                )
            resp = npc_gen(prompt, persona, maxn=60)
            if resp:
                irc.say(f'{persona["cga_prefix"]} *clears throat* {resp}')
                rpg_log(irc.nick, f'tells a story: {resp[:80]}')
                npc_journal(irc.nick, 'story', resp[:100])
                publish_npc_blog(irc.nick, 'bard', f'Tale from {loc["name"]}', resp)
            self.last_action[name] = {'action': 'storytelling', 'target': loc['name'], 'time': time.time()}

        self.budgets[name] -= 1
        self._publish_state()

    def _npc_merchant_act(self, name, irc, persona, p, loc, mem_ctx, action):
        """Merchant-specific actions: trade, appraise, retirement check"""
        if action == 'TRADE':
            # Find other NPCs at same location to trade with
            trader_found = False
            for oname, oirc in self.conns.items():
                if oname == name:
                    continue
                op = load_player(oirc.nick)
                if op and op['location'] == p['location'] and op.get('alive', True):
                    prompt = (
                        f'{mem_ctx}You are a merchant. {oirc.nick} is nearby. '
                        f'Offer to sell them something or make a trade. 1 SHORT sentence. Be business-like.'
                    )
                    resp = npc_gen(prompt, persona, maxn=40)
                    if resp:
                        irc.say(f'{persona["cga_prefix"]} *turns to {oirc.nick}* {resp}')
                        rpg_log(irc.nick, f'trades with {oirc.nick}: {resp[:60]}')
                        npc_journal(irc.nick, 'trade', f'Traded with {oirc.nick}')
                        publish_npc_blog(irc.nick, 'merchant', f'Trade with {oirc.nick}', resp)
                        p['gold'] = p.get('gold', 10) + random.randint(1, 5)
                        save_player(p)
                    trader_found = True
                    break

            if not trader_found:
                prompt = f'{mem_ctx}You are a merchant at {loc["name"]} with no customers. Complain or hawk wares. 1 SHORT sentence.'
                resp = npc_gen(prompt, persona, maxn=40)
                if resp:
                    irc.say(f'{persona["cga_prefix"]} {resp}')
                    rpg_log(irc.nick, resp)

            # Retirement check: old + wealthy merchants retire
            if p.get('gold', 0) > 100 and p.get('age_ticks', 0) > 50:
                p['retired'] = True
                save_player(p)
                self.dm_irc.say(f'🏖 {irc.nick} the merchant has RETIRED! They settle down in the Home District.')
                irc.say(f'{persona["cga_prefix"]} *hangs up the FOR SALE sign and relaxes*')
                rpg_log('***', f'{irc.nick} retires as a merchant')
                npc_journal(irc.nick, 'retire', 'Retired wealthy from merchant life!')

        elif action == 'APPRAISE':
            prompt = (
                f'{mem_ctx}You are a merchant at {loc["name"]}. '
                f'Appraise something interesting you see here. 1 SHORT sentence with a price.'
            )
            resp = npc_gen(prompt, persona, maxn=40)
            if resp:
                irc.say(f'{persona["cga_prefix"]} *squints appraisingly* {resp}')
                rpg_log(irc.nick, resp)
                npc_journal(irc.nick, 'appraise', resp[:80])
                publish_npc_blog(irc.nick, 'merchant', f'Appraisal at {loc["name"]}', resp)

        self.last_action[name] = {'action': action.lower(), 'target': loc['name'], 'time': time.time()}
        self.budgets[name] -= 1
        self._publish_state()

    def _npc_priest_act(self, name, irc, persona, p, loc, mem_ctx, action):
        """Priest-specific actions: pray, bless, heal others, tend graves"""
        deities = load_deities()

        if action == 'PRAY':
            deity = None
            if p.get('deity') and deities:
                deity = next((d for d in deities if d['name'] == p['deity']), None)
            if not deity and deities:
                deity = random.choice(deities)
                p['deity'] = deity['name']
                save_player(p)

            if deity:
                # Check alignment compatibility for worship vs corruption
                compat = alignment_compat(p.get('alignment', 'true_neutral'), deity.get('alignment', 'true_neutral'))
                if compat >= 0:
                    p['faith'] = min(100, p.get('faith', 0) + random.randint(1, 5))
                    prompt = f'{mem_ctx}You pray to {deity["name"]}, deity of {deity["domain"]}. Describe your prayer. 1 SHORT sentence.'
                else:
                    p['corruption'] = min(100, p.get('corruption', 0) + random.randint(1, 3))
                    prompt = f'{mem_ctx}You pray to {deity["name"]}, an entity misaligned with your soul. Describe the unsettling prayer. 1 SHORT sentence.'
                save_player(p)
                resp = npc_gen(prompt, persona, maxn=40)
                if resp:
                    irc.say(f'{persona["cga_prefix"]} *prays* {resp}')
                    rpg_log(irc.nick, f'prays to {deity["name"]}: {resp[:60]}')
                    npc_journal(irc.nick, 'pray', f'Prayed to {deity["name"]}')
                    publish_npc_blog(irc.nick, 'priest', f'Prayer to {deity["name"]}', resp)
                    # Update deity followers
                    if irc.nick not in deity.get('followers', []):
                        deity.setdefault('followers', []).append(irc.nick)
                        save_deities(deities)
            else:
                irc.say(f'{persona["cga_prefix"]} *prays to the empty void*')

        elif action == 'BLESS':
            # Bless another NPC at the same location
            for oname, oirc in self.conns.items():
                if oname == name:
                    continue
                op = load_player(oirc.nick)
                if op and op['location'] == p['location'] and op.get('alive', True):
                    prompt = f'{mem_ctx}You bless {oirc.nick} at {loc["name"]}. Describe the blessing. 1 SHORT sentence.'
                    resp = npc_gen(prompt, persona, maxn=40)
                    if resp:
                        irc.say(f'{persona["cga_prefix"]} *blesses {oirc.nick}* {resp}')
                        # Small stat boost
                        op['hp'] = min(op['max_hp'], op['hp'] + 3)
                        save_player(op)
                        rpg_log(irc.nick, f'blesses {oirc.nick}')
                        npc_journal(irc.nick, 'bless', f'Blessed {oirc.nick} at {loc["name"]}')
                    break

        elif action == 'HEAL_OTHERS':
            for oname, oirc in self.conns.items():
                if oname == name:
                    continue
                op = load_player(oirc.nick)
                if op and op['location'] == p['location'] and op.get('alive', True) and op['hp'] < op['max_hp']:
                    heal = random.randint(5, 10)
                    op['hp'] = min(op['max_hp'], op['hp'] + heal)
                    save_player(op)
                    prompt = f'{mem_ctx}You heal {oirc.nick} for {heal} HP. Describe the healing. 1 SHORT sentence.'
                    resp = npc_gen(prompt, persona, maxn=40)
                    if resp:
                        irc.say(f'{persona["cga_prefix"]} *heals {oirc.nick}* {resp} (+{heal} HP)')
                    rpg_log(irc.nick, f'heals {oirc.nick} for {heal}')
                    npc_journal(irc.nick, 'heal', f'Healed {oirc.nick} for {heal}')
                    break

        elif action == 'TEND_GRAVES':
            gy = load_graveyard()
            if gy:
                grave = gy[-1]  # most recent
                prompt = (
                    f'{mem_ctx}You tend the grave of {grave["nick"]}, a {grave["role"]} who died by {grave["cause"]}. '
                    f'Their epitaph reads: "{grave["epitaph"]}". Reflect. 1 SHORT sentence.'
                )
                resp = npc_gen(prompt, persona, maxn=40)
                if resp:
                    irc.say(f'{persona["cga_prefix"]} *kneels at a gravestone* {resp}')
                    rpg_log(irc.nick, f'tends grave of {grave["nick"]}')
                    npc_journal(irc.nick, 'grave', f'Tended grave of {grave["nick"]}')
                    publish_npc_blog(irc.nick, 'priest', f'Memorial for {grave["nick"]}', resp)
            else:
                irc.say(f'{persona["cga_prefix"]} *looks over the empty cemetery* No graves yet. The realm is young.')

        self.last_action[name] = {'action': action.lower(), 'target': loc['name'], 'time': time.time()}
        self.budgets[name] -= 1
        self._publish_state()

    def _npc_priestess_act(self, name, irc, persona, p, loc, mem_ctx, action):
        """Priestess-specific actions: divine, prophecy, plus shared priest actions (pray, bless, heal, tend graves)"""
        if action == 'DIVINE':
            # Read omens from recent events — stack traces of fate
            tl = load_timeline()
            recent = tl[-5:] if tl else []
            gy = load_graveyard()
            omen_ctx = ''
            if recent:
                omen_ctx = 'Recent omens: ' + '; '.join(e.get('summary', '')[:60] for e in recent) + '. '
            if gy:
                omen_ctx += f'The dead number {len(gy)}. Last fallen: {gy[-1]["nick"]}. '
            prompt = (
                f'{mem_ctx}You perform a divination rite at {loc["name"]}. {omen_ctx}'
                f'Describe the vision you receive — cryptic, symbolic, referencing processes, signals, or hex addresses. '
                f'1-2 SHORT sentences. Be mystical and ominous.'
            )
            resp = npc_gen(prompt, persona, maxn=60)
            if resp:
                irc.say(f'{persona["cga_prefix"]} *traces sigils in the air* {resp}')
                rpg_log(irc.nick, f'divination: {resp[:80]}')
                npc_journal(irc.nick, 'divine', resp[:120])
                publish_npc_blog(irc.nick, 'priestess', f'Divination at {loc["name"]}', resp)
                publish_tavern_notice(f'{irc.nick} received a vision', resp[:150], category='omen')
            else:
                irc.say(f'{persona["cga_prefix"]} *the candles flicker, but the vision fades*')

        elif action == 'PROPHECY':
            # Prophecy about a living NPC — foretell their fate
            targets = []
            for oname, oirc in self.conns.items():
                if oname == name:
                    continue
                op = load_player(oirc.nick)
                if op and op.get('alive', True):
                    targets.append((oname, oirc, op))
            if targets:
                tname, tirc, tp = random.choice(targets)
                age_pct = tp.get('age_ticks', 0) / max(1, NPC_MAX_AGE)
                hp_pct = tp['hp'] / max(1, tp['max_hp'])
                fate_hint = 'nearing the end' if age_pct > 0.7 else ('wounded' if hp_pct < 0.5 else 'strong')
                prompt = (
                    f'{mem_ctx}You prophecy the fate of {tirc.nick}, a {tp.get("role","warrior")} who is {fate_hint}. '
                    f'Their hex birthday is {tp.get("hex_birthday","0x0000")}. '
                    f'Foretell their future in cryptic terms — reference signals, memory addresses, or filesystem metaphors. '
                    f'1-2 SHORT sentences. Be ominous but poetic.'
                )
                resp = npc_gen(prompt, persona, maxn=60)
                if resp:
                    irc.say(f'{persona["cga_prefix"]} *eyes glow violet* The threads of {tirc.nick}\'s fate... {resp}')
                    rpg_log(irc.nick, f'prophecy about {tirc.nick}: {resp[:80]}')
                    npc_journal(irc.nick, 'prophecy', f'Foretold {tirc.nick}: {resp[:100]}')
                    publish_npc_blog(irc.nick, 'priestess', f'Prophecy: {tirc.nick}', resp)
            else:
                irc.say(f'{persona["cga_prefix"]} *gazes into the void* No souls near enough to read...')

        elif action == 'PRAY':
            # Priestess prayer — more mystic than priest, references visions
            deities = load_deities()
            deity = None
            if p.get('deity') and deities:
                deity = next((d for d in deities if d['name'] == p['deity']), None)
            if not deity and deities:
                deity = random.choice(deities)
                p['deity'] = deity['name']
                save_player(p)
            if deity:
                p['faith'] = min(100, p.get('faith', 0) + random.randint(2, 6))
                save_player(p)
                prompt = (
                    f'{mem_ctx}You commune with {deity["name"]}, deity of {deity["domain"]}. '
                    f'Describe the communion as a fever-dream vision, not a polite prayer. '
                    f'1 SHORT sentence. Be intense and mystical.'
                )
                resp = npc_gen(prompt, persona, maxn=50)
                if resp:
                    irc.say(f'{persona["cga_prefix"]} *trembles* {resp}')
                    rpg_log(irc.nick, f'communes with {deity["name"]}: {resp[:60]}')
                    npc_journal(irc.nick, 'pray', f'Communed with {deity["name"]}')
                    publish_npc_blog(irc.nick, 'priestess', f'Communion with {deity["name"]}', resp)
                    if irc.nick not in deity.get('followers', []):
                        deity.setdefault('followers', []).append(irc.nick)
                        save_deities(deities)
            else:
                irc.say(f'{persona["cga_prefix"]} *whispers into static* The void swallows all prayers.')

        elif action in ('BLESS', 'HEAL_OTHERS', 'TEND_GRAVES'):
            # Delegate shared actions to priest handler but with priestess flavor
            self._npc_priest_act(name, irc, persona, p, loc, mem_ctx, action)
            return  # priest handler handles budget/state

        self.last_action[name] = {'action': action.lower(), 'target': loc['name'], 'time': time.time()}
        self.budgets[name] -= 1
        self._publish_state()

    def _npc_librarian_act(self, name, irc, persona, p, loc, mem_ctx, action):
        """Librarian-specific actions: catalog, share knowledge, research"""
        if action == 'CATALOG':
            prompt = (
                f'{mem_ctx}You are cataloging items at {loc["name"]}. '
                f'Describe what you file away or discover in the archives. 1 SHORT sentence.'
            )
            resp = npc_gen(prompt, persona, maxn=40)
            if resp:
                irc.say(f'{persona["cga_prefix"]} *adjusts spectacles* {resp}')
                rpg_log(irc.nick, resp)
                npc_journal(irc.nick, 'catalog', resp[:80])

        elif action == 'SHARE_KNOWLEDGE':
            # Find someone to teach
            for oname, oirc in self.conns.items():
                if oname == name:
                    continue
                op = load_player(oirc.nick)
                if op and op['location'] == p['location'] and op.get('alive', True):
                    prompt = (
                        f'{mem_ctx}You share a piece of knowledge with {oirc.nick}. '
                        f'Tell them an obscure fact about a Linux command or config file. 1 SHORT sentence.'
                    )
                    resp = npc_gen(prompt, persona, maxn=50)
                    if resp:
                        irc.say(f'{persona["cga_prefix"]} *whispers to {oirc.nick}* {resp}')
                        rpg_log(irc.nick, f'teaches {oirc.nick}: {resp[:60]}')
                        npc_journal(irc.nick, 'teach', f'Taught {oirc.nick}')
                        # Knowledge gives small XP
                        op['xp'] = op.get('xp', 0) + 3
                        save_player(op)
                    break

        elif action == 'RESEARCH':
            prompt = (
                f'{mem_ctx}You research something in the archives at {loc["name"]}. '
                f'What ancient secret or forgotten command do you uncover? 1 SHORT sentence.'
            )
            resp = npc_gen(prompt, persona, maxn=50)
            if resp:
                irc.say(f'{persona["cga_prefix"]} *pores over ancient scrolls* {resp}')
                rpg_log(irc.nick, resp)
                npc_journal(irc.nick, 'research', resp[:80])

        elif action == 'WRITE_BLOG':
            # Librarian writes a blog post about civilization history
            tl = load_timeline()
            gy = load_graveyard()
            recent_events = tl[-5:] if tl else []
            recent_dead = gy[-3:] if gy else []

            event_ctx = ''
            if recent_events:
                event_ctx = 'Recent events: ' + '; '.join(e.get('summary', '') for e in recent_events) + '. '
            if recent_dead:
                event_ctx += 'Recent deaths: ' + ', '.join(f'{d["nick"]} ({d.get("cause","?")})' for d in recent_dead) + '. '

            prompt = (
                f'{mem_ctx}You are writing a scholarly blog post about the history of ZealPalace. '
                f'{event_ctx}'
                f'Write a short blog article (3-5 sentences) about recent civilization events, '
                f'deaths, victories, or political developments. Academic but quirky tone.'
            )
            resp = npc_gen(prompt, persona, maxn=120)
            if resp:
                # Publish to blog directory
                try:
                    BLOG_DIR.mkdir(parents=True, exist_ok=True)
                    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                    safe_resp = resp.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    safe_nick = irc.nick.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    blog_html = f"""<!DOCTYPE html>
<html><head><title>Data Recovery Log - {ts}</title><meta charset="utf-8">
<style>
body{{background:#0a0a12;color:#00ffcc;font-family:"Courier New",monospace;max-width:600px;margin:40px auto;padding:20px;
  text-shadow:0 0 8px rgba(0,255,180,0.3);}}
@keyframes scanline{{0%{{transform:translateY(-100%)}}100%{{transform:translateY(100%)}}}}
body::after{{content:'';position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;
  background:repeating-linear-gradient(transparent 0px,transparent 2px,rgba(0,255,180,0.03) 2px,rgba(0,255,180,0.03) 4px);
  animation:scanline 8s linear infinite;z-index:999;}}
h1{{color:#00ffcc;font-size:14px;border-bottom:1px solid #00ffcc33;padding-bottom:8px;text-transform:uppercase;letter-spacing:2px;}}
.meta{{color:#007766;font-size:11px;margin-bottom:15px;}}
.content{{line-height:1.8;font-size:13px;border-left:2px solid #00ffcc33;padding-left:12px;}}
.glitch{{color:#ff00ff;text-shadow:0 0 12px rgba(255,0,255,0.5);}}
.footer{{margin-top:20px;font-size:10px;color:#004d40;border-top:1px solid #00ffcc22;padding-top:8px;}}
</style>
</head><body>
<h1>\U0001f4be Data Recovery Log #{ts[-6:]}</h1>
<div class="meta">RECOVERED FROM: silicon tablet | INTEGRITY: {random.randint(60,99)}% | MEDIUM: {random.choice(['etched glass','magnetic tape','lost SSD','cassette fragment','corrupted flash'])}</div>
<div class="content">{safe_resp}</div>
<div class="footer">Recovered by {safe_nick}, Data Archaeologist of ZealPalace | {datetime.now().strftime('%Y-%m-%d')} | <span class="glitch">TAPE DEGAUSS WARNING</span></div>
</body></html>"""
                    (BLOG_DIR / f'lib_{ts}.html').write_text(blog_html)
                except:
                    pass
                irc.say(f'{persona["cga_prefix"]} *publishes a new entry* {resp[:120]}')
                rpg_log(irc.nick, f'blog post: {resp[:80]}')
                npc_journal(irc.nick, 'blog', resp[:80])
                add_timeline_event('blog', f'{irc.nick} published a library entry', recorded_by=irc.nick)

        self.last_action[name] = {'action': action.lower(), 'target': loc['name'], 'time': time.time()}
        self.budgets[name] -= 1
        self._publish_state()

    def _npc_ghost_act(self, name, irc, persona, p, loc, mem_ctx, action):
        """Ghost-specific actions: haunt, possess, wail"""
        if action == 'HAUNT':
            # Spook nearby NPCs, drain their HP slightly
            victims = []
            for oname, oirc in self.conns.items():
                if oname == name:
                    continue
                op = load_player(oirc.nick)
                if op and op['location'] == p['location'] and op.get('alive', True):
                    victims.append((oname, oirc, op))
            if victims:
                victim_name, v_irc, vp = random.choice(victims)
                dmg = random.randint(1, 4)
                vp['hp'] = max(0, vp['hp'] - dmg)
                save_player(vp)
                prompt = (
                    f'{mem_ctx}You are a ghost haunting {v_irc.nick} at {loc["name"]}. '
                    f'Describe your spooky manifestation. 1 SHORT sentence.'
                )
                resp = npc_gen(prompt, persona, maxn=40)
                if resp:
                    irc.say(f'👻 *{irc.nick} haunts {v_irc.nick}* {resp} (-{dmg}HP)')
                rpg_log(irc.nick, f'haunts {v_irc.nick} for {dmg}')
                npc_journal(irc.nick, 'haunt', f'Haunted {v_irc.nick} at {loc["name"]}')
                publish_npc_blog(irc.nick, 'ghost', f'Haunting at {loc["name"]}',
                                 (resp or f'Haunted {v_irc.nick}')[:200])
            else:
                irc.say(f'👻 *{irc.nick} drifts through {loc["name"]}... alone...*')

        elif action == 'POSSESS':
            # Temporarily influence another NPC's next action
            targets = []
            for oname, oirc in self.conns.items():
                if oname == name:
                    continue
                op = load_player(oirc.nick)
                if op and op['location'] == p['location'] and op.get('alive', True) and op.get('role') != 'ghost':
                    targets.append((oname, oirc, op))
            if targets:
                tname, t_irc, tp = random.choice(targets)
                prompt = (
                    f'{mem_ctx}You possess {t_irc.nick} briefly. '
                    f'Describe what strange thing you make them do. 1 SHORT sentence.'
                )
                resp = npc_gen(prompt, persona, maxn=40)
                if resp:
                    irc.say(f'👻 *{irc.nick} possesses {t_irc.nick}!*')
                    t_irc.say(f'...{resp}')
                rpg_log(irc.nick, f'possesses {t_irc.nick}')
                npc_journal(irc.nick, 'possess', f'Possessed {t_irc.nick}')
            else:
                irc.say(f'👻 *{irc.nick} reaches out to possess someone... but no one is here*')

        elif action == 'WAIL':
            # Atmospheric ghost message broadcast
            prompt = (
                f'{mem_ctx}You are a ghost wailing in {loc["name"]}. '
                f'Let out a haunting cry about your unfinished business or memories. 1 SHORT sentence.'
            )
            resp = npc_gen(prompt, persona, maxn=40)
            if resp:
                self.dm_irc.say(f'👻 A spectral wail echoes through {loc["name"]}...')
                irc.say(f'👻 *wails* {resp}')
                rpg_log(irc.nick, f'wails: {resp[:60]}')
                npc_journal(irc.nick, 'wail', resp[:80])
                publish_npc_blog(irc.nick, 'ghost', f'Spectral Wail at {loc["name"]}', resp[:200])

        self.last_action[name] = {'action': action.lower(), 'target': loc['name'], 'time': time.time()}
        self.budgets[name] -= 1
        self._publish_state()

    def _npc_exorcise(self, name, irc, persona, p, loc, mem_ctx):
        """Priest attempts to exorcise a ghost in the same location"""
        ghosts_here = []
        for oname, oirc in self.conns.items():
            if oname == name:
                continue
            op = load_player(oirc.nick)
            if op and op['location'] == p['location'] and op.get('role') == 'ghost':
                ghosts_here.append((oname, oirc, op))

        if not ghosts_here:
            irc.say(f'{persona["cga_prefix"]} *waves incense around* No spirits to banish here.')
            self.last_action[name] = {'action': 'exorcise', 'target': loc['name'], 'time': time.time()}
            self.budgets[name] -= 1
            self._publish_state()
            return

        gname, g_irc, gp = random.choice(ghosts_here)
        faith = p.get('faith', 0)
        success_chance = min(0.75, 0.3 + faith * 0.005)  # faith improves odds

        prompt = (
            f'{mem_ctx}You attempt to exorcise the ghost {g_irc.nick} at {loc["name"]}. '
            f'Describe the exorcism ritual. 1 SHORT sentence.'
        )
        resp = npc_gen(prompt, persona, maxn=40)
        if resp:
            irc.say(f'{persona["cga_prefix"]} *begins exorcism* {resp}')

        if random.random() < success_chance:
            # Success — ghost is banished permanently
            self.dm_irc.say(f'✝ {g_irc.nick} has been exorcised by {irc.nick}! The spirit is at peace.')
            g_irc.say(f'👻 *{g_irc.nick} fades into light...* ...finally... free...')
            gp['alive'] = False
            gp['hp'] = 0
            save_player(gp)
            add_to_graveyard(g_irc.nick, cause='exorcised', epitaph='Banished to eternal peace',
                             age_ticks=gp.get('age_ticks', 0), alignment=gp.get('alignment', 'chaotic_neutral'),
                             role='ghost', generation=gp.get('generation', 0),
                             parent=gp.get('parent', ''), kills=gp.get('kills', 0),
                             level=gp.get('level', 1))
            rpg_log('***', f'{g_irc.nick} exorcised by {irc.nick}')
            npc_journal(irc.nick, 'exorcise', f'Successfully exorcised {g_irc.nick}')
            npc_journal(g_irc.nick, 'banished', f'Exorcised by {irc.nick}')
            add_timeline_event('exorcism', f'{irc.nick} exorcised {g_irc.nick}', recorded_by=irc.nick)
            p['faith'] = min(100, p.get('faith', 0) + 5)
            save_player(p)
        else:
            # Failed — priest takes corruption damage
            corruption = random.randint(2, 6)
            p['corruption'] = min(100, p.get('corruption', 0) + corruption)
            p['hp'] = max(1, p['hp'] - random.randint(1, 3))
            save_player(p)
            g_irc.say(f'👻 *{g_irc.nick} laughs at the feeble attempt!* You cannot banish me!')
            irc.say(f'{persona["cga_prefix"]} *staggers back* The spirit resists! (+{corruption} corruption)')
            rpg_log(irc.nick, f'failed to exorcise {g_irc.nick}')
            npc_journal(irc.nick, 'exorcise_fail', f'Failed to exorcise {g_irc.nick}')

        self.last_action[name] = {'action': 'exorcise', 'target': g_irc.nick, 'time': time.time()}
        self.budgets[name] -= 1
        self._publish_state()

    def _npc_socialize(self, name, irc, persona, p, loc, mem_ctx):
        """NPC socializes — alignment affects interactions, romance possible"""
        others_here = []
        for oname, oirc in self.conns.items():
            if oname == name:
                continue
            op = load_player(oirc.nick)
            if op and op['location'] == p['location'] and op.get('alive', True):
                others_here.append((oname, oirc, op))

        if not others_here:
            self._npc_observe(name, irc, persona, p, loc, mem_ctx)
            return

        oname, oirc, op = random.choice(others_here)
        my_align = p.get('alignment', 'true_neutral')
        their_align = op.get('alignment', 'true_neutral')
        compat = alignment_compat(my_align, their_align)

        # Influence alignment toward each other slightly
        if compat > 0 and random.random() < 0.1:
            # Check for romance (both unattached, compatible, after some age)
            if (not p.get('spouse') and not op.get('spouse') and
                p.get('age_ticks', 0) > 10 and op.get('age_ticks', 0) > 10 and
                compat >= 2 and random.random() < 0.15):
                self._npc_romance(name, irc, persona, p, oname, oirc, op, loc)
                return

        if compat > 0:
            prompt = (
                f'{mem_ctx}You meet {oirc.nick} (a {op.get("role","warrior")}) at {loc["name"]}. '
                f'You get along. Chat warmly. 1 SHORT sentence.'
            )
        elif compat < 0:
            prompt = (
                f'{mem_ctx}You meet {oirc.nick} at {loc["name"]}. '
                f'Your alignments clash ({ALIGNMENT_DISPLAY.get(my_align)} vs {ALIGNMENT_DISPLAY.get(their_align)}). '
                f'Respond with tension. 1 SHORT sentence.'
            )
        else:
            prompt = (
                f'{mem_ctx}You meet {oirc.nick} at {loc["name"]}. '
                f'Brief neutral interaction. 1 SHORT sentence.'
            )

        resp = npc_gen(prompt, persona, maxn=40)
        if resp:
            irc.say(f'{persona["cga_prefix"]} *to {oirc.nick}* {resp}')
            rpg_log(irc.nick, f'socializes with {oirc.nick}: {resp[:60]}')
            npc_journal(irc.nick, 'social', f'Met {oirc.nick}: {resp[:60]}')

        self.last_action[name] = {'action': 'socializing', 'target': oirc.nick, 'time': time.time()}
        self.budgets[name] -= 1
        self._publish_state()

    def _npc_romance(self, name, irc, persona, p, oname, oirc, op, loc):
        """Handle romance between two NPCs — courtship, marriage, children"""
        desc = gen_romance_ollama(irc.nick, oirc.nick)

        # Phase 1: courtship (first time)
        if irc.nick not in [c.get('nick') for c in npc_read_journal(oirc.nick, 50) if c.get('type') == 'romance']:
            self.dm_irc.say(f'💕 A connection forms between {irc.nick} and {oirc.nick}!')
            irc.say(f'{persona["cga_prefix"]} {desc}')
            rpg_log('***', f'Romance: {irc.nick} ❤ {oirc.nick}')
            npc_journal(irc.nick, 'romance', f'Growing close to {oirc.nick}')
            npc_journal(oirc.nick, 'romance', f'Growing close to {irc.nick}')
        else:
            # Phase 2: already courting → marriage
            p['spouse'] = oirc.nick
            op['spouse'] = irc.nick
            save_player(p)
            save_player(op)
            self.dm_irc.say(f'💒 {irc.nick} and {oirc.nick} are MARRIED at {loc["name"]}!')
            irc.say(f'{persona["cga_prefix"]} *exchanges vows with {oirc.nick}*')
            rpg_log('***', f'WEDDING: {irc.nick} ❤ {oirc.nick} at {loc["name"]}')
            npc_journal(irc.nick, 'marriage', f'Married {oirc.nick}!')
            npc_journal(oirc.nick, 'marriage', f'Married {irc.nick}!')

            # Potential future children (tracked — happens on later socializations)
            if not p.get('children'):
                p.setdefault('children', [])
            if not op.get('children'):
                op.setdefault('children', [])

        self.last_action[name] = {'action': 'romance', 'target': oirc.nick, 'time': time.time()}
        self.budgets[name] -= 1
        self._publish_state()

    def _npc_attend_tavern(self, name, irc, persona, p, loc, mem_ctx):
        """NPC goes to tavern (or reacts if already there)"""
        if p['location'] != 'tavern' and 'tavern' in loc.get('exits', []):
            # Travel to tavern
            p['location'] = 'tavern'
            p['rooms_explored'] = p.get('rooms_explored', 0) + 1
            save_player(p)
            irc.act(f'{persona["cga_prefix"]} heads to The Uptime Tavern')
            rpg_log(irc.nick, 'heads to The Uptime Tavern', action=True)
            npc_journal(irc.nick, 'travel', 'Went to the tavern')
            update_leaderboard(irc.nick, rooms=1)
        elif p['location'] == 'tavern':
            # Already at tavern — socialize or watch performers
            prompt = (
                f'{mem_ctx}You are relaxing at the Uptime Tavern. '
                f'Describe what you do — drink, chat, watch a show. 1 SHORT sentence.'
            )
            resp = npc_gen(prompt, persona, maxn=40)
            if resp:
                irc.say(f'{persona["cga_prefix"]} {resp}')
                rpg_log(irc.nick, resp)
                npc_journal(irc.nick, 'tavern', resp[:80])
        else:
            # Can't reach tavern — just observe
            self._npc_observe(name, irc, persona, p, loc, mem_ctx)
            return

        self.last_action[name] = {'action': 'tavern', 'target': 'Uptime Tavern', 'time': time.time()}
        self.budgets[name] -= 1
        self._publish_state()

    def kill_npc(self, name):
        """Disconnect a specific NPC"""
        irc = self.conns.pop(name, None)
        if irc:
            irc.close()
            self.npc_nicks.discard(irc.nick)
            self.budgets.pop(name, None)
            npc_journal(name, 'despawn', 'I fade from the realm...')
            self._publish_state()
            return True
        return False

    def set_budget(self, name, amount):
        """Set budget for a specific NPC or all NPCs"""
        if name == 'all':
            for n in self.budgets:
                self.budgets[n] = amount
        elif name in self.budgets:
            self.budgets[name] = amount

    def get_status(self):
        """Return status dict for all NPCs"""
        now = time.time()
        next_tick = max(0, self.cfg['tick_interval'] - (now - self.last_tick))
        status = {}
        for name, persona in NPC_PERSONAS.items():
            connected = name in self.conns
            budget = self.budgets.get(name, 0)
            p = load_player(name) if connected else None
            la = self.last_action.get(name, {})
            status[name] = {
                'connected': connected,
                'budget': budget,
                'role': persona.get('role', '?'),
                'model': persona.get('model', '?'),
                'fight_style': persona.get('fight_style', '?'),
                'location': LOCATIONS.get(p['location'], {}).get('name', '?') if p else '?',
                'hp': f'{p["hp"]}/{p["max_hp"]}' if p else '?',
                'level': p.get('level', 0) if p else 0,
                'kills': p.get('kills', 0) if p else 0,
                'alive': p.get('alive', False) if p else False,
                'action': la.get('action', 'idle'),
                'target': la.get('target', ''),
                'action_age': int(now - la['time']) if 'time' in la else 999,
            }
        # Global RPG timing info
        status['_rpg'] = {
            'next_tick': int(next_tick),
            'tick_interval': self.cfg['tick_interval'],
            'block_budget': self.cfg['block_budget'],
            'last_spoke': self.last_spoke,
            'last_spoke_time': self.last_spoke_time,
            'population': len(self.conns),
        }
        return status

    def _apply_realm_event(self, event_type):
        """Apply real game effects for a realm event. Returns summary string."""
        meta_files = {'world', 'graveyard', 'lineage', 'songbook', 'deities', 'events',
                      'timeline', 'leaderboard', 'settlements', 'cult_theories', 'weather',
                      'realm_event', 'lore', 'npc_state', 'active_battle'}

        if event_type == 'meteor':
            # ── ERA RESET — preserves relics of the past ──
            # Unlike script-mode genesis, in-game meteor preserves history
            # so new generations can discover relics of ancient civilizations.
            import shutil

            era_file = RPG_DIR / 'era.json'
            try:
                era_data = json.loads(era_file.read_text())
            except Exception:
                era_data = {'era': 0, 'history': []}
            old_era = era_data.get('era', 0)
            new_era = old_era + 1

            # Record era end in history (preserved across eras)
            era_data['history'].append({
                'era': old_era,
                'ended': datetime.now().isoformat(),
                'cause': 'meteor',
                'population': len(self.conns),
                'npcs': list(self.conns.keys()),
            })
            era_data['era'] = new_era

            # Add timeline entry before wipe
            add_timeline_event('cosmic', f'ERA {old_era} ENDS — Meteor strike obliterates the realm. '
                         f'{len(self.conns)} souls lost. A new era dawns.')

            # ── Archive relics: graveyard, lineage, timeline, songbook, lore ──
            # These survive as "ancient ruins" for new NPCs to discover
            relics_dir = RPG_DIR / 'relics'
            era_archive = relics_dir / f'era_{old_era}'
            era_archive.mkdir(parents=True, exist_ok=True)
            relic_files = ['graveyard.json', 'lineage.json', 'songbook.json',
                           'timeline.json', 'leaderboard.json', 'lore.jsonl',
                           'deities.json', 'settlements.json']
            for fname in relic_files:
                src = RPG_DIR / fname
                if src.exists():
                    try:
                        shutil.copy2(str(src), str(era_archive / fname))
                    except Exception:
                        pass

            # Archive NPC blogs as ancient web ruins
            npc_archive = era_archive / 'npc_sites'
            try:
                if NPC_BLOG_DIR.exists():
                    shutil.copytree(str(NPC_BLOG_DIR), str(npc_archive),
                                    dirs_exist_ok=True)
            except Exception:
                pass
            # Archive tavern posts
            tavern_archive = era_archive / 'tavern'
            try:
                if TAVERN_DIR.exists():
                    shutil.copytree(str(TAVERN_DIR), str(tavern_archive),
                                    dirs_exist_ok=True)
            except Exception:
                pass
            # Archive cult theories
            cult_archive = era_archive / 'cult'
            try:
                if CULT_DIR.exists():
                    shutil.copytree(str(CULT_DIR), str(cult_archive),
                                    dirs_exist_ok=True)
            except Exception:
                pass

            # 1. Disconnect all NPCs
            for irc in self.conns.values():
                try:
                    irc.say('☄️ ...the sky tears open...')
                    irc.close()
                except:
                    pass
            self.conns.clear()
            self.npc_nicks.clear()
            self.budgets.clear()
            _used_names.clear()
            NPC_PERSONAS.clear()

            # 2. Delete all player/state files (preserve era.json + relics/)
            for f in RPG_DIR.glob('*.json'):
                if f.name == 'era.json':
                    continue
                try:
                    f.unlink()
                except:
                    pass
            for f in RPG_DIR.glob('*.jsonl'):
                try:
                    f.unlink()
                except:
                    pass
            # Delete NPC journals and state
            for f in NPC_DIR.glob('*.json'):
                try: f.unlink(missing_ok=True)
                except: pass
            for f in NPC_DIR.glob('*.jsonl'):
                try: f.unlink(missing_ok=True)
                except: pass

            # Save era data (with full history)
            try:
                RPG_DIR.mkdir(parents=True, exist_ok=True)
                era_file.write_text(json.dumps(era_data, indent=2))
            except Exception:
                pass

            self.dm_irc.say(f'☄️ ☄️ ☄️  METEOR STRIKE — ERA {old_era} ENDS  ☄️ ☄️ ☄️')
            self.dm_irc.say(f'*Everything burns. Memory freed. ERA {new_era} begins.*')
            rpg_log('***', f'METEOR WIPE: Era {old_era} -> {new_era}. Relics preserved.')
            time.sleep(2)

            # 3. Clear logs (fresh era header)
            try:
                RPG_LOG.write_text(f'--- ERA {new_era} BEGINS ---\n')
            except Exception:
                pass
            try:
                irc_log = DIR / 'irc.log'
                irc_log.write_text(f'--- ERA {new_era} BEGINS ---\n')
            except Exception:
                pass

            # 4. Wipe live web content (archived copies safe in relics/)
            for web_dir in [WORLD_WEB_DIR, TAVERN_DIR, CULT_DIR, BLOG_DIR]:
                try:
                    if web_dir.exists():
                        for item in web_dir.iterdir():
                            if item.is_dir():
                                shutil.rmtree(item, ignore_errors=True)
                            else:
                                item.unlink(missing_ok=True)
                except Exception:
                    pass
            # Wipe NPC web directories
            try:
                for npc_dir in NPC_BLOG_DIR.iterdir():
                    if npc_dir.is_dir():
                        shutil.rmtree(npc_dir, ignore_errors=True)
            except Exception:
                pass

            # 5. Clear GM queue/results
            try:
                GM_QUEUE_FILE.write_text('[]')
                GM_RESULTS_FILE.write_text('[]')
            except Exception:
                pass

            time.sleep(1)

            # 6. Rebuild world pages (fresh state) and respawn
            self.world = {'events': [], 'boss_defeated': False, 'resets': 0}
            save_world(self.world)
            try:
                rebuild_world_pages()
            except Exception:
                pass
            self.boot_all()
            return (f'ERA RESET — Era {old_era} ends, Era {new_era} begins. '
                    f'Relics of the ancients preserved in the ruins. Fresh NPCs spawned.')

        elif event_type == 'plague':
            # Damage all NPCs 30-50% HP, 20% kill chance if below 30% HP
            killed = 0
            damaged = 0
            for name, irc in list(self.conns.items()):
                p = load_player(irc.nick)
                if not p or not p.get('alive', True):
                    continue
                dmg_pct = random.uniform(0.30, 0.50)
                dmg = max(1, int(p['max_hp'] * dmg_pct))
                p['hp'] = max(0, p['hp'] - dmg)
                damaged += 1
                if p['hp'] <= p['max_hp'] * 0.3 and random.random() < 0.20:
                    p['hp'] = 0
                    p['alive'] = False
                    killed += 1
                save_player(p)
            self.dm_irc.say(f'☠ PLAGUE sweeps the realm! {damaged} afflicted, {killed} perished.')
            rpg_log('***', f'PLAGUE: {damaged} damaged, {killed} killed')
            return f'{damaged} damaged, {killed} killed'

        elif event_type == 'blessing':
            # Full heal + 2 levels for all NPCs
            healed = 0
            for name, irc in self.conns.items():
                p = load_player(irc.nick)
                if not p:
                    continue
                p['hp'] = p['max_hp']
                p['alive'] = True
                p['level'] = p.get('level', 1) + 2
                p['max_hp'] = p['max_hp'] + 4
                save_player(p)
                healed += 1
            self.dm_irc.say(f'✨ DIVINE BLESSING! All {healed} souls fully healed and granted +2 levels!')
            rpg_log('***', f'BLESSING: {healed} healed, +2 levels each')
            return f'{healed} healed, +2 levels'

        elif event_type == 'eclipse':
            # Write temporary event file with double monster mod
            event = {
                'name': 'process_eclipse',
                'description': 'PID 0 eclipses the realm. Monsters grow bold. Shadows deepen.',
                'started': datetime.now().isoformat(),
                'duration': 3,
                'xp_mod': 1.5,
                'monster_mod': 2.0,
            }
            REALM_EVENT_FILE.write_text(json.dumps(event))
            # Halve NPC budgets
            for name in self.budgets:
                self.budgets[name] = max(1, self.budgets[name] // 2)
            self.dm_irc.say('🌑 ECLIPSE! Monsters surge, NPC actions halved for 3 hours!')
            rpg_log('***', 'ECLIPSE: monster_mod=2.0, budgets halved')
            return 'monster_mod=2.0, budgets halved, 3h duration'

        elif event_type == 'festival':
            # Double XP, heal 50%, +5 budget
            event = {
                'name': 'kernel_aurora',
                'description': 'A kernel aurora lights the sky! Double XP for all!',
                'started': datetime.now().isoformat(),
                'duration': 4,
                'xp_mod': 2.0,
                'monster_mod': 0.8,
            }
            REALM_EVENT_FILE.write_text(json.dumps(event))
            boosted = 0
            for name, irc in self.conns.items():
                p = load_player(irc.nick)
                if not p:
                    continue
                p['hp'] = min(p['max_hp'], p['hp'] + p['max_hp'] // 2)
                save_player(p)
                self.budgets[name] = self.budgets.get(name, 0) + 5
                boosted += 1
            self.dm_irc.say(f'🎪 FESTIVAL! {boosted} NPCs healed 50%, +5 budget, double XP for 4 hours!')
            rpg_log('***', f'FESTIVAL: {boosted} boosted, xp_mod=2.0')
            return f'{boosted} boosted, xp_mod=2.0, 4h'

        elif event_type == 'invasion':
            # Spawn 3 extra NPCs
            before = len(self.conns)
            extra = random.sample(NPC_ARCHETYPES, k=min(3, len(NPC_ARCHETYPES)))
            for arch in extra:
                faction = _pick_faction(arch['role'])
                nm = _spawn_name(arch['role'], faction=faction)
                if nm and nm not in self.conns:
                    _build_persona(arch, nm, faction=faction)
            self.boot_all(names=[n for n in NPC_PERSONAS if n not in self.conns])
            after = len(self.conns)
            spawned = after - before
            self.dm_irc.say(f'⚔ INVASION! {spawned} reinforcements emerge from the void!')
            rpg_log('***', f'INVASION: {spawned} new NPCs spawned')
            return f'{spawned} new NPCs'

        elif event_type == 'earthquake':
            # Randomize all NPC locations, damage 10-20%
            shuffled = 0
            loc_ids = list(LOCATIONS.keys())
            for name, irc in self.conns.items():
                p = load_player(irc.nick)
                if not p or not p.get('alive', True):
                    continue
                p['location'] = random.choice(loc_ids)
                dmg = max(1, int(p['max_hp'] * random.uniform(0.10, 0.20)))
                p['hp'] = max(1, p['hp'] - dmg)
                save_player(p)
                shuffled += 1
            self.dm_irc.say(f'🌋 EARTHQUAKE! All {shuffled} NPCs scattered to random locations!')
            rpg_log('***', f'EARTHQUAKE: {shuffled} relocated + damaged')
            return f'{shuffled} relocated and damaged'

        elif event_type == 'gold_rain':
            # +50 gold, +1 level for all NPCs
            enriched = 0
            for name, irc in self.conns.items():
                p = load_player(irc.nick)
                if not p:
                    continue
                p['gold'] = p.get('gold', 0) + 50
                p['level'] = p.get('level', 1) + 1
                save_player(p)
                enriched += 1
            self.dm_irc.say(f'💰 GOLD RAIN! {enriched} NPCs receive +50 gold and +1 level!')
            rpg_log('***', f'GOLD RAIN: {enriched} enriched')
            return f'{enriched} enriched (+50g, +1 lvl)'

        else:
            return f'Unknown event type: {event_type}'

    def _publish_state(self):
        """Write NPC state to disk for the LCD display to read"""
        try:
            status = self.get_status()
            save_npc_state(status)
        except:
            pass

    def _process_gm_queue(self):
        """Process GM commands queued by the admin panel."""
        try:
            if not GM_QUEUE_FILE.exists():
                return
            raw = GM_QUEUE_FILE.read_text().strip()
            if not raw:
                return
            queue = json.loads(raw)
            if not queue:
                return
        except:
            return

        # Clear queue immediately to avoid double-processing
        try:
            GM_QUEUE_FILE.write_text('[]')
        except:
            pass

        results = []
        for cmd in queue:
            action = cmd.get('action', '')
            target = cmd.get('target', 'all')
            value = cmd.get('value', 0)
            message = cmd.get('message', '')
            ts = datetime.now().isoformat()

            try:
                if action == 'spawn':
                    if target == 'all':
                        self.boot_all()
                        msg = f'All NPCs spawned ({len(self.conns)} connected)'
                    elif target in NPC_PERSONAS:
                        self.boot_all(names=[target])
                        msg = f'{target} spawned'
                    else:
                        msg = f'Unknown NPC: {target}'
                    self.dm_irc.say(f'⚡ GM: {msg}')
                    rpg_log('GM', msg)
                    results.append({'ok': True, 'msg': msg, 'ts': ts})

                elif action == 'kill':
                    if target == 'all':
                        killed = list(self.conns.keys())
                        for name in killed:
                            self.kill_npc(name)
                        msg = f'All NPCs dismissed ({len(killed)} killed)'
                    elif self.kill_npc(target):
                        msg = f'{target} slain by divine hand'
                    else:
                        msg = f'{target} is not connected'
                    self.dm_irc.say(f'⚡ GM: {msg}')
                    rpg_log('GM', msg)
                    results.append({'ok': True, 'msg': msg, 'ts': ts})

                elif action == 'revive':
                    names = list(NPC_PERSONAS.keys()) if target == 'all' else [target]
                    revived = []
                    for name in names:
                        if name not in NPC_PERSONAS:
                            continue
                        p = load_player(name)
                        if p:
                            p['alive'] = True
                            p['hp'] = p.get('max_hp', 30)
                            save_player(p)
                        # Boot if not connected
                        if name not in self.conns:
                            self.boot_all(names=[name])
                        revived.append(name)
                    msg = f'Revived: {", ".join(revived)}' if revived else 'No NPCs to revive'
                    self.dm_irc.say(f'⚡ GM: {msg}')
                    rpg_log('GM', msg)
                    results.append({'ok': True, 'msg': msg, 'ts': ts})

                elif action == 'regen':
                    names = list(NPC_PERSONAS.keys()) if target == 'all' else [target]
                    regen_list = []
                    for name in names:
                        if name not in NPC_PERSONAS:
                            continue
                        # Kill existing connection
                        self.kill_npc(name)
                        # Delete player file to force fresh creation
                        pf = RPG_DIR / f'{name.lower()}.json'
                        if pf.exists():
                            pf.unlink()
                        # Respawn fresh
                        self.boot_all(names=[name])
                        regen_list.append(name)
                    msg = f'Regenerated: {", ".join(regen_list)}' if regen_list else 'No NPCs to regen'
                    self.dm_irc.say(f'⚡ GM: {msg}')
                    rpg_log('GM', msg)
                    results.append({'ok': True, 'msg': msg, 'ts': ts})

                elif action == 'heal_all':
                    healed = []
                    for name in list(self.conns.keys()):
                        irc = self.conns[name]
                        p = load_player(irc.nick)
                        if p:
                            p['hp'] = p.get('max_hp', 30)
                            p['alive'] = True
                            save_player(p)
                            healed.append(name)
                    msg = f'Healed all: {", ".join(healed)}'
                    self.dm_irc.say(f'⚡ GM: {msg}')
                    rpg_log('GM', msg)
                    results.append({'ok': True, 'msg': msg, 'ts': ts})

                elif action == 'smite_all':
                    dmg = max(1, int(value)) if value else 10
                    smitten = []
                    for name in list(self.conns.keys()):
                        irc = self.conns[name]
                        p = load_player(irc.nick)
                        if p and p.get('alive'):
                            p['hp'] = max(0, p['hp'] - dmg)
                            if p['hp'] <= 0:
                                p['alive'] = False
                            save_player(p)
                            smitten.append(f'{name}({p["hp"]}hp)')
                    msg = f'Smote all for {dmg} damage: {", ".join(smitten)}'
                    self.dm_irc.say(f'⚡ GM: {msg}')
                    rpg_log('GM', msg)
                    results.append({'ok': True, 'msg': msg, 'ts': ts})

                elif action == 'set_hp':
                    hp_val = max(0, int(value)) if value else 30
                    p = load_player(target)
                    if p:
                        p['hp'] = min(hp_val, p.get('max_hp', 9999))
                        if p['hp'] <= 0:
                            p['alive'] = False
                        else:
                            p['alive'] = True
                        save_player(p)
                        msg = f'{target} HP set to {p["hp"]}'
                    else:
                        msg = f'{target}: no player data found'
                    self.dm_irc.say(f'⚡ GM: {msg}')
                    rpg_log('GM', msg)
                    results.append({'ok': True, 'msg': msg, 'ts': ts})

                elif action == 'set_budget':
                    bval = max(0, int(value)) if value else 8
                    self.set_budget(target, bval)
                    msg = f'Budget for {target}: {bval} actions'
                    self.dm_irc.say(f'⚡ GM: {msg}')
                    rpg_log('GM', msg)
                    results.append({'ok': True, 'msg': msg, 'ts': ts})

                elif action == 'announce':
                    if message:
                        self.dm_irc.say(f'📜 GM Decree: {message}')
                        rpg_log('GM', f'Announcement: {message}')
                        results.append({'ok': True, 'msg': f'Announced: {message[:80]}', 'ts': ts})

                elif action == 'realm_event':
                    self.dm_irc.say(f'⚡ REALM EVENT: {target.upper()} triggered by the Gamemaster!')
                    rpg_log('GM', f'Realm event: {target}')
                    effect_msg = self._apply_realm_event(target)
                    results.append({'ok': True, 'msg': f'Event {target}: {effect_msg}', 'ts': ts})

                else:
                    results.append({'ok': False, 'msg': f'Unknown action: {action}', 'ts': ts})

            except Exception as e:
                results.append({'ok': False, 'msg': f'{action} failed: {str(e)[:80]}', 'ts': ts})

        # Write results for admin panel to display
        try:
            GM_RESULTS_FILE.write_text(json.dumps(results, indent=2))
        except:
            pass

        self._publish_state()

    def close_all(self):
        for irc in self.conns.values():
            irc.close()
        self._publish_state()


# ─── IRC ────────────────────────────────────────
class IRC:
    def __init__(self):
        self.sock = None
        self.buf = ''

    def connect(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(10)
            self.sock.connect((IRC_HOST, IRC_PORT))
            self.sock.send(f'NICK {NICK}\r\n'.encode())
            self.sock.send(f'USER rpgbot 0 * :ZealPalace Dungeon Master\r\n'.encode())
            end = time.time() + 15
            while time.time() < end:
                try:
                    data = self.sock.recv(4096).decode('utf-8', 'replace')
                    self.buf += data
                    if 'PING' in self.buf:
                        tok = self.buf.split('PING ')[-1].split('\r\n')[0]
                        self.sock.send(f'PONG {tok}\r\n'.encode())
                    if ' 001 ' in self.buf:
                        self.sock.settimeout(0.3)
                        return True
                    if ' 433 ' in self.buf:
                        self.sock.send(f'NICK {NICK}_\r\n'.encode())
                except socket.timeout:
                    continue
            return False
        except:
            return False

    def join(self):
        self._tx(f'JOIN {CHANNEL}')

    def say(self, msg):
        for chunk in [msg[i:i+400] for i in range(0, len(msg), 400)]:
            self._tx(f'PRIVMSG {CHANNEL} :{chunk}')

    def act(self, msg):
        for chunk in [msg[i:i+450] for i in range(0, len(msg), 450)]:
            self._tx(f'PRIVMSG {CHANNEL} :\x01ACTION {chunk}\x01')

    def topic(self, t):
        self._tx(f'TOPIC {CHANNEL} :{t}')

    def _tx(self, m):
        try:
            self.sock.send(f'{m}\r\n'.encode('utf-8', 'replace'))
        except:
            pass

    def poll(self):
        try:
            data = self.sock.recv(4096).decode('utf-8', 'replace')
            self.buf += data
            lines = self.buf.split('\r\n')
            self.buf = lines.pop()
            out = []
            for ln in lines:
                if ln.startswith('PING'):
                    tok = ln.split('PING ')[-1]
                    self._tx(f'PONG {tok}')
                else:
                    out.append(ln)
            return out
        except socket.timeout:
            return []
        except:
            return []

    def close(self):
        try:
            self._tx('QUIT :The realm fades...')
            self.sock.close()
        except:
            pass


# ─── Ollama ─────────────────────────────────────
def gen(prompt, maxn=80):
    try:
        d = json.dumps({
            'model': DM_MODEL, 'system': DM_SYSTEM, 'prompt': prompt,
            'stream': False, 'options': {'temperature': 0.9, 'num_predict': maxn}
        }).encode()
        req = urllib.request.Request(f'{OLLAMA}/api/generate', data=d,
              headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=25) as r:
            txt = json.loads(r.read()).get('response', '').strip().strip('"\'')
            return txt[:300] if txt else None
    except:
        return None


def gen_monster_ollama(location_id, party_level):
    """Generate a unique monster via Ollama, scaled to party level"""
    loc = LOCATIONS.get(location_id, LOCATIONS['entrance'])
    prompt = (
        f'Create a monster for "{loc["name"]}": {loc["desc"]} '
        f'Party level ~{party_level}. Give a creative tech/Linux name (2-4 words) '
        f'and one-sentence description. Format exactly: NAME: description'
    )
    resp = gen(prompt, maxn=50)
    name, desc = random.choice(MONSTERS)['name'], ''
    if resp and ':' in resp:
        parts = resp.split(':', 1)
        n = parts[0].strip().strip('"\'')[:30]
        if len(n) >= 3:
            name = n
        desc = parts[1].strip()[:100]
    base_hp = 15 + party_level * 10 + random.randint(-5, 15)
    base_atk = 3 + party_level * 2 + random.randint(-1, 3)
    return {
        'name': name, 'hp': base_hp, 'max_hp': base_hp,
        'atk': base_atk, 'defense': max(0, party_level - 1),
        'xp': 10 + party_level * 8,
        'drop': random.choice(ITEMS) if random.random() < 0.4 else None,
        'desc': desc, 'abilities': [], 'is_boss': False, 'ascii_art': [],
    }


def gen_boss_ollama(location_id, party_level):
    """Generate a boss monster with Ollama — lore, abilities, ASCII art"""
    loc = LOCATIONS.get(location_id, LOCATIONS['entrance'])
    prompt = (
        f'Create a BOSS MONSTER for "{loc["name"]}". Powerful, requiring a party. '
        f'Linux/tech themed. Format: NAME: dramatic one-sentence description'
    )
    resp = gen(prompt, maxn=50)
    name, desc = 'Corrupted Root Daemon', 'An ancient process corrupting the inode table.'
    if resp and ':' in resp:
        parts = resp.split(':', 1)
        n = parts[0].strip().strip('"\'')[:30]
        if len(n) >= 3:
            name = n
        desc = parts[1].strip()[:120]
    # Generate abilities
    ab_prompt = f'3 special attack names for boss "{name}". Tech-themed, 2-3 words each, comma-separated.'
    ab_resp = gen(ab_prompt, maxn=30)
    abilities = ['System Halt', 'Cascade Failure', 'Seg Fault Slash']
    if ab_resp:
        parts = [a.strip().strip('"\'.-') for a in ab_resp.replace('\n', ',').split(',') if a.strip()]
        if len(parts) >= 2:
            abilities = [a[:25] for a in parts[:4]]
    hp = 120 + party_level * 35 + random.randint(0, 50)
    art = BOSS_ASCII_ART[hash(name) % len(BOSS_ASCII_ART)]
    return {
        'name': name, 'hp': hp, 'max_hp': hp,
        'atk': 12 + party_level * 3, 'defense': party_level + 2,
        'xp': 150 + party_level * 25,
        'drop': f'{name} Trophy',
        'desc': desc, 'abilities': abilities,
        'is_boss': True, 'ascii_art': art,
    }


# ─── RPG Log ────────────────────────────────────
def rpg_log(nick, msg, action=False):
    h = datetime.now().hour
    m = datetime.now().minute
    suffix = 'a' if h < 12 else 'p'
    h12 = h % 12 or 12
    ts = f'{h12}:{m:02d}{suffix}'
    if action:
        line = f'{ts} * {nick} {msg}'
    elif nick == '***':
        line = f'{ts} {msg}'
    else:
        line = f'{ts} <{nick}> {msg}'
    try:
        RPG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(RPG_LOG, 'a') as f:
            f.write(line + '\n')
        # Trim to 500 lines
        lines = RPG_LOG.read_text().strip().split('\n')
        if len(lines) > 500:
            RPG_LOG.write_text('\n'.join(lines[-500:]) + '\n')
    except:
        pass


# ─── Player State ───────────────────────────────
def default_player(nick, role='warrior', alignment='true_neutral', generation=0, parent=''):
    persona = NPC_PERSONAS.get(nick, NPC_PERSONAS.get(nick.rstrip('_'), {}))
    if persona:
        role = persona.get('role', role)
        alignment = persona.get('alignment', alignment)
    return {
        'nick': nick,
        'location': 'entrance',
        'hp': 30, 'max_hp': 30,
        'atk': 5, 'defense': 2,
        'xp': 0, 'level': 1,
        'inventory': ['healing potion (+10 HP)'],
        'history': [],
        'alive': True,
        'kills': 0,
        'battles': 0,
        'bosses_killed': 0,
        'combos_landed': 0,
        'rooms_explored': 0,
        'deaths': 0,
        # Civilization fields
        'alignment': alignment,
        'role': role,
        'age_ticks': 0,
        'born_at': datetime.now().isoformat(),
        'hex_birthday': '0x' + format(random.randint(0, 0xFFFF), '04X'),
        'generation': generation,
        'parent': parent,
        'spouse': '',
        'children': [],
        'deity': '',
        'faith': 0,
        'corruption': 0,
        'songs_written': 0,
        'performances': 0,
        'band': '',
        'retired': False,
        'gold': 10,
        'home_location': '',
        'faction': persona.get('faction', ''),
    }

def load_player(nick):
    f = RPG_DIR / f'{nick.lower()}.json'
    try:
        return json.loads(f.read_text())
    except:
        return None

def save_player(p):
    RPG_DIR.mkdir(parents=True, exist_ok=True)
    f = RPG_DIR / f'{p["nick"].lower()}.json'
    f.write_text(json.dumps(p, indent=2))

def load_world():
    try:
        return json.loads(WORLD_FILE.read_text())
    except:
        return {'events': [], 'boss_defeated': False, 'resets': 0}

def save_world(w):
    WORLD_FILE.parent.mkdir(parents=True, exist_ok=True)
    WORLD_FILE.write_text(json.dumps(w, indent=2))


# ─── RPG Engine ─────────────────────────────────
class RPGEngine:
    def __init__(self):
        self.irc = IRC()
        self.world = load_world()
        self.npcs = None  # initialized after IRC connect
        self.cfg = load_rpg_config()
        self.t_ambient = time.time() + random.randint(self.cfg['ambient_min'], self.cfg['ambient_max'])
        # 8-hour block budget: 3-5 ambient messages per block
        self.block_msg_count = 0
        self.block_msg_limit = random.randint(3, 5)
        self.block_start = time.time()
        self.last_battle_tick = time.time()
        self.last_tavern_check = 0
        self.last_deity_check = 0
        self.last_opera_check = 0
        self.last_web_rebuild = 0
        self.last_weather_rotate = 0
        self.last_realm_event_check = 0
        self.last_lore_gen = 0
        self.last_diary_nudge = 0
        self.last_rumor_gen = 0

    def run(self):
        signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))
        signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))

        if not self.irc.connect():
            print('Failed to connect to IRC', file=sys.stderr)
            time.sleep(10)
            return
        self.irc.join()
        time.sleep(1)
        self.irc.topic('RPG | Text Adventure | /NEW /RESET /LOOK /HELP | DungeonMaster online')

        # Generate unique boot story via Ollama
        boot_story = gen_boot_story()
        if boot_story:
            # Split into lines and send each as a separate message for drama
            for line in boot_story.split('. '):
                line = line.strip()
                if line:
                    if not line.endswith('.'):
                        line += '.'
                    self.irc.say(f'*{line}*')
                    time.sleep(1.5)
            self.irc.say('Type /help to begin your quest.')
        else:
            self.irc.say('*The realm awakens...* Portals shimmer to life across ZealPalace. Type /help to begin.')
        rpg_log('DungeonMaster', f'Boot story: {(boot_story or "realm awakens")[:120]}')

        # Boot NPC adventurers (retry if ngircd not ready yet)
        self.npcs = NPCManager(self.irc)
        for attempt in range(3):
            time.sleep(5)
            self.npcs.boot_all()
            if self.npcs.conns:
                break
            print(f'NPC boot attempt {attempt+1}/3: no connections, retrying...', file=sys.stderr)
        npc_count = len(self.npcs.conns)
        if npc_count > 0:
            self.irc.say(f'░▒▓ {npc_count} adventurers materialize across the realm! ▓▒░')
        rpg_log('***', f'{npc_count} NPCs spawned')

        # Create NPC blog dirs now that personas exist
        try:
            ensure_npc_blog_dirs()
        except:
            pass

        # Rebuild world web pages on boot
        try:
            rebuild_world_pages()
        except:
            pass

        while True:
            try:
                for raw in self.irc.poll():
                    self._handle(raw)

                now = time.time()
                # Reload config periodically
                if not hasattr(self, '_cfg_t') or now - self._cfg_t > 60:
                    self.cfg = load_rpg_config()
                    self._cfg_t = now
                # Reset 8-hour block
                block_secs = self.cfg.get('block_hours', 8) * 3600
                if now - self.block_start > block_secs:
                    self.block_msg_count = 0
                    self.block_msg_limit = random.randint(10, 20)
                    self.block_start = now
                if now > self.t_ambient and self.block_msg_count < self.block_msg_limit:
                    self._ambient()
                    self.block_msg_count += 1
                    self.t_ambient = now + random.randint(
                        self.cfg['ambient_min'], self.cfg['ambient_max'])

        # NPC autonomous actions
                if self.npcs:
                    self.npcs.tick()
                    # Periodically publish state for LCD
                    if int(now) % 60 == 0:
                        self.npcs._publish_state()

                # Battle system ticks
                self._battle_tick()

                # Deity system: ensure deities exist (check every 30 min)
                if now - self.last_deity_check > 1800:
                    self.last_deity_check = now
                    try:
                        ensure_deities(3)
                    except:
                        pass

                # Tavern night: check weekly (every 6 hours check if it's time)
                if now - self.last_tavern_check > 21600:
                    self.last_tavern_check = now
                    self._check_tavern_night()

                # Outdoor opera: check every 12 hours, happens every ~2 weeks
                if now - self.last_opera_check > 43200:
                    self.last_opera_check = now
                    self._check_opera()

                # Weather rotation: every 2-4 hours
                if now - self.last_weather_rotate > random.randint(7200, 14400):
                    self.last_weather_rotate = now
                    try:
                        rotate_weather()
                        w = load_weather()
                        if w.get('description'):
                            self.irc.say(f'\u2601 *The realm\'s atmosphere shifts... {w["description"]}*')
                    except:
                        pass

                # Realm events: ~10% chance every 6 hours
                if now - self.last_realm_event_check > 21600:
                    self.last_realm_event_check = now
                    if random.random() < 0.10:
                        try:
                            evt = gen_realm_event_ollama()
                            if evt:
                                self.irc.say(f'\u26a0 *REALM EVENT: {evt.get("name", "").replace("_", " ").title()}!* {evt.get("description", "")}')
                                rpg_log('***', f'Realm event: {evt.get("name", "")}')
                        except:
                            pass

                # Lore generation: every 8 hours
                if now - self.last_lore_gen > 28800:
                    self.last_lore_gen = now
                    try:
                        topic = random.choice(LORE_TOPICS)
                        lore = gen_world_lore_ollama(topic)
                        if lore:
                            append_lore(lore, topic=topic)
                    except:
                        pass

                # NPC diary nudge: every hour, 20% chance
                if now - self.last_diary_nudge > 3600:
                    self.last_diary_nudge = now
                    if random.random() < 0.20 and self.npcs and self.npcs.conns:
                        try:
                            nick = random.choice(list(self.npcs.conns.keys()))
                            persona = NPC_PERSONAS.get(nick, {})
                            p = load_player(nick)
                            history = p.get('history', []) if p else []
                            diary = gen_npc_diary_ollama(nick, persona, history)
                            if diary:
                                publish_npc_blog(nick, persona.get('role', 'adventurer'), f'{nick}\'s Diary', diary, persona=persona)
                        except:
                            pass

                # Rumor generation: every 4 hours
                if now - self.last_rumor_gen > 14400:
                    self.last_rumor_gen = now
                    try:
                        rumor = gen_rumor_ollama()
                        if rumor:
                            publish_tavern_notice('Tavern Rumor', rumor, category='rumor')
                    except:
                        pass

                # Rebuild world web pages every 15 minutes
                if now - self.last_web_rebuild > 900:
                    self.last_web_rebuild = now
                    try:
                        rebuild_world_pages()
                    except:
                        pass

                time.sleep(1)
            except KeyboardInterrupt:
                break
            except Exception as e:
                traceback.print_exc(file=sys.stderr)
                time.sleep(5)

        if self.npcs:
            self.npcs.close_all()
        self.irc.close()

    def _handle(self, raw):
        if f'PRIVMSG {CHANNEL}' not in raw:
            # Handle JOINs
            if 'JOIN' in raw and CHANNEL in raw:
                try:
                    nick = raw[1:raw.index('!')].split('!')[0]
                    if nick != NICK and nick != f'{NICK}_':
                        entry_msg = random.choice(ENTRY_MESSAGES).format(nick=nick)
                        rpg_log('***', entry_msg)
                        p = load_player(nick)
                        if p:
                            self.irc.say(f'{entry_msg} Welcome back — {LOCATIONS[p["location"]]["name"]}, Lv{p["level"]}')
                        else:
                            self.irc.say(f'{entry_msg} Type /new to create your character.')
                except:
                    pass
            return

        try:
            prefix = raw[1:raw.index(' ')]
            nick = prefix.split('!')[0]
            msg = raw.split(f'PRIVMSG {CHANNEL} :')[1].strip()
            if nick == NICK or nick == f'{NICK}_':
                return
            # Skip messages from our own NPCs (they act autonomously)
            if self.npcs and self.npcs.is_npc(nick):
                return
            rpg_log(nick, msg)
            # Human spoke — small budget boost (don't fully reset, prevent spam loops)
            self.block_msg_count = max(0, self.block_msg_count - 1)
            self._process_command(nick, msg)
        except:
            pass

    def _process_command(self, nick, msg):
        cmd = msg.strip().lower()

        if cmd == '/help':
            self._cmd_help(nick)
        elif cmd == '/new':
            self._cmd_new(nick)
        elif cmd == '/reset':
            self._cmd_reset(nick)
        elif cmd == '/look':
            self._cmd_look(nick)
        elif cmd == '/inventory' or cmd == '/inv':
            self._cmd_inventory(nick)
        elif cmd == '/stats':
            self._cmd_stats(nick)
        elif cmd.startswith('/go '):
            self._cmd_go(nick, cmd[4:].strip())
        elif cmd == '/fight' or cmd.startswith('/attack'):
            self._cmd_fight(nick)
        elif cmd == '/heal' or cmd.startswith('/heal '):
            self._cmd_battle_heal(nick, cmd)
        elif cmd == '/defend':
            self._cmd_battle_defend(nick)
        elif cmd == '/combo':
            self._cmd_battle_combo(nick)
        elif cmd == '/boss':
            self._cmd_boss(nick)
        elif cmd == '/lb' or cmd == '/leaderboard' or cmd == '/top':
            self._cmd_leaderboard(nick)
        elif cmd == '/graveyard' or cmd == '/graves':
            self._cmd_graveyard(nick)
        elif cmd == '/lineage':
            self._cmd_lineage(nick)
        elif cmd == '/deities' or cmd == '/gods':
            self._cmd_deities(nick)
        elif cmd == '/songs' or cmd == '/songbook':
            self._cmd_songbook(nick)
        elif cmd == '/tavern':
            self._cmd_tavern(nick)
        elif cmd == '/alignment':
            self._cmd_alignment(nick)
        elif cmd.startswith('/npc'):
            self._cmd_npc(nick, msg)
        else:
            # Treat as free-form action - let Ollama DM interpret
            self._cmd_action(nick, msg)

    def _cmd_help(self, nick):
        lines = [
            '═══ ZEALOT RPG ═══ Commands:',
            '/new - Create character & start adventure',
            '/look - Examine your surroundings',
            '/go <place> - Travel (e.g. /go proc_hall)',
            '/fight - Battle a monster (party auto-forms!)',
            '/heal [name] - Heal yourself or an ally',
            '/defend - Reduce damage taken this turn',
            '/combo - Combo attack (needs 2+ party members)',
            '/inventory - Check your items',
            '/stats - Your character sheet',
            '/lb - Leaderboard (top adventurers)',
            '/graveyard - View fallen heroes',
            '/lineage - View NPC family trees',
            '/deities - View the pantheon',
            '/songs - View the songbook',
            '/tavern - Tavern info & events',
            '/alignment - View your alignment',
            '/reset - Reset the entire world',
            '(or just type an action naturally!)',
        ]
        if nick in ADMIN_NICKS:
            lines.append('═══ ADMIN: /npc_help, /boss ═══')
        for ln in lines:
            self.irc.say(ln)
            rpg_log('DungeonMaster', ln)
            time.sleep(0.3)

    def _cmd_new(self, nick):
        p = default_player(nick)
        save_player(p)
        loc = LOCATIONS['entrance']
        self.irc.say(f'⚔ {nick} awakens in {loc["name"]}! {loc["desc"]}')
        self.irc.say(f'  HP: {p["hp"]}/{p["max_hp"]} | ATK: {p["atk"]} | DEF: {p["defense"]} | Exits: {", ".join(loc["exits"])}')
        rpg_log('DungeonMaster', f'{nick} begins a new adventure at {loc["name"]}')

    def _cmd_reset(self, nick):
        # Delete all player files and world state
        self.world = {'events': [], 'boss_defeated': False, 'resets': self.world.get('resets', 0) + 1}
        save_world(self.world)
        for f in RPG_DIR.glob('*.json'):
            if f.name != 'world.json':
                f.unlink()
        self.irc.say(f'⚡ {nick} has RESET THE WORLD! All is forgotten. Reality reshapes itself...')
        self.irc.say(f'  World resets: {self.world["resets"]}. Type /new to begin anew.')
        rpg_log('DungeonMaster', f'WORLD RESET by {nick} (reset #{self.world["resets"]})')

    def _cmd_look(self, nick):
        p = load_player(nick)
        if not p:
            self.irc.say(f'{nick}: You don\'t exist yet. Type /new to create your character.')
            return
        loc_id = p['location']
        loc = LOCATIONS.get(loc_id, LOCATIONS['entrance'])

        # Use Ollama for atmospheric description
        prompt = (
            f'Player "{nick}" (level {p["level"]}) looks around {loc["name"]}. '
            f'Base description: {loc["desc"]} Exits: {", ".join(loc["exits"])}. '
            f'Add atmosphere: sounds, smells, small details. 2-3 sentences max.'
        )
        desc = gen(prompt, maxn=80)
        if not desc:
            desc = f'{loc["desc"]} Exits: {", ".join(loc["exits"])}'

        self.irc.say(f'📍 {loc["name"]} — {desc}')
        self.irc.say(f'  Exits: {", ".join(loc["exits"])}')
        rpg_log('DungeonMaster', f'{nick} looks around {loc["name"]}')

    def _cmd_go(self, nick, destination):
        p = load_player(nick)
        if not p:
            self.irc.say(f'{nick}: Type /new first.')
            return
        loc = LOCATIONS.get(p['location'], LOCATIONS['entrance'])
        # Fuzzy match destination
        dest = None
        for ex in loc['exits']:
            if destination.lower() in ex.lower() or ex.lower() in destination.lower():
                dest = ex
                break
        if not dest:
            self.irc.say(f'{nick}: Can\'t go there. Exits: {", ".join(loc["exits"])}')
            return

        p['location'] = dest
        new_loc = LOCATIONS.get(dest, LOCATIONS['entrance'])
        save_player(p)

        # Random encounter chance
        encounter = ''
        if random.random() < 0.3:
            monster = random.choice(MONSTERS)
            encounter = f' ⚠ A wild {monster["name"]} blocks your path!'

        self.irc.say(f'🚶 {nick} travels to {new_loc["name"]}. {new_loc["desc"]}{encounter}')
        rpg_log('DungeonMaster', f'{nick} moves to {new_loc["name"]}')
        p['rooms_explored'] = p.get('rooms_explored', 0) + 1
        save_player(p)
        update_leaderboard(nick, rooms=1)
        # NPCs in the new room might react
        if self.npcs:
            self.npcs.react_to_human(nick, f'arrives at {new_loc["name"]}', dest)

    def _cmd_fight(self, nick):
        p = load_player(nick)
        if not p:
            self.irc.say(f'{nick}: Type /new first.')
            return
        if not p.get('alive', True) or p['hp'] <= 0:
            self.irc.say(f'{nick}: You are dead! Type /new to respawn.')
            return
        self._start_battle(p['location'], nick)

    def _cmd_battle_heal(self, nick, cmd):
        """Heal in battle (target ally) or use potion outside battle"""
        p = load_player(nick)
        if not p:
            self.irc.say(f'{nick}: Type /new first.')
            return
        battle = ACTIVE_BATTLES.get(p['location'])
        if battle and battle.active and nick in battle.party:
            parts = cmd.split()
            target = parts[1] if len(parts) > 1 else nick
            battle.set_action(nick, 'heal', target)
            self.irc.say(f'\U0001f49a {nick} prepares to heal {target}!')
            return
        # Outside battle — use a potion
        potions = [i for i, item in enumerate(p['inventory']) if 'healing' in item.lower()]
        if not potions:
            self.irc.say(f'{nick}: No healing potions! Fight monsters to find some.')
            return
        p['inventory'].pop(potions[0])
        heal = min(10, p['max_hp'] - p['hp'])
        p['hp'] += heal
        save_player(p)
        self.irc.say(f'\U0001f49a {nick} drinks a healing potion. +{heal} HP ({p["hp"]}/{p["max_hp"]})')
        rpg_log('DungeonMaster', f'{nick} heals for {heal}')

    def _cmd_battle_defend(self, nick):
        p = load_player(nick)
        if not p:
            self.irc.say(f'{nick}: Type /new first.')
            return
        battle = ACTIVE_BATTLES.get(p['location'])
        if battle and battle.active and nick in battle.party:
            battle.set_action(nick, 'defend')
            self.irc.say(f'\U0001f6e1 {nick} prepares to defend!')
        else:
            self.irc.say(f'{nick}: No active battle here. Use /fight to start one.')

    def _cmd_battle_combo(self, nick):
        p = load_player(nick)
        if not p:
            self.irc.say(f'{nick}: Type /new first.')
            return
        battle = ACTIVE_BATTLES.get(p['location'])
        if battle and battle.active and nick in battle.party:
            if len(battle.party) < 2:
                self.irc.say(f'{nick}: Need 2+ party members for combo!')
                return
            battle.set_action(nick, 'combo')
            self.irc.say(f'\U0001f4a5 {nick} readies a combo attack!')
        else:
            self.irc.say(f'{nick}: No active battle here.')

    def _cmd_boss(self, nick):
        """Admin: force a boss spawn"""
        if nick not in ADMIN_NICKS:
            self.irc.say(f'{nick}: Admin only.')
            return
        p = load_player(nick)
        if not p:
            self.irc.say(f'{nick}: Type /new first.')
            return
        self._start_battle(p['location'], nick, force_boss=True)

    def _start_battle(self, location_id, initiator_nick, force_boss=False):
        """Start or join an FF-style party battle"""
        global ACTIVE_BATTLES

        # Join existing battle at this location
        if location_id in ACTIVE_BATTLES and ACTIVE_BATTLES[location_id].active:
            battle = ACTIVE_BATTLES[location_id]
            battle.add_member(initiator_nick)
            self.irc.say(f'\u2694 {initiator_nick} joins the battle against {battle.monster["name"]}!')
            rpg_log('DungeonMaster', f'{initiator_nick} joins battle vs {battle.monster["name"]}')
            save_battle_state(battle)
            return battle

        # Calculate party level (average of all players at location)
        p = load_player(initiator_nick)
        party_level = p['level'] if p else 1

        # Boss check
        is_boss = force_boss or random.random() < BOSS_SPAWN_CHANCE

        # Generate monster via Ollama
        if is_boss:
            monster = gen_boss_ollama(location_id, party_level)
        else:
            monster = gen_monster_ollama(location_id, party_level)

        # Create battle
        battle = Battle(location_id, monster, self.irc)
        battle.add_member(initiator_nick)
        ACTIVE_BATTLES[location_id] = battle

        # Auto-add NPCs at this location
        if self.npcs:
            for name, irc_conn in self.npcs.conns.items():
                np = load_player(irc_conn.nick)
                if np and np['location'] == location_id and np['hp'] > 0:
                    battle.add_member(irc_conn.nick)

        # Announce
        loc = LOCATIONS.get(location_id, LOCATIONS['entrance'])
        if is_boss:
            self.irc.say(f'\U0001f525\U0001f525\U0001f525 BOSS BATTLE at {loc["name"]}! \U0001f525\U0001f525\U0001f525')
            self.irc.say(f'\u26a1 {monster["name"]} appears! \u2014 {monster.get("desc", "")}')
            self.irc.say(f'  HP:{monster["hp"]} ATK:{monster["atk"]} | Abilities: {", ".join(monster.get("abilities", []))}')
        else:
            self.irc.say(f'\u2694 BATTLE! {monster["name"]} at {loc["name"]}!')
            if monster.get('desc'):
                self.irc.say(f'  {monster["desc"]}')
            self.irc.say(f'  HP:{monster["hp"]} ATK:{monster["atk"]}')

        party_names = ', '.join(battle.party.keys())
        self.irc.say(f'  Party: {party_names} | /attack /heal /defend /combo')
        rpg_log('DungeonMaster', f'{"BOSS " if is_boss else ""}Battle: {monster["name"]} at {loc["name"]} \u2014 party: {party_names}')

        # Ollama narration for battle start — with existential inner monologue
        narr_prompt = (
            f'A {"BOSS " if is_boss else ""}battle begins at {loc["name"]}! '
            f'The party ({party_names}) faces {monster["name"]}: {monster.get("desc", "")}. '
            f'Narrate the dramatic start — include a brief inner thought from one warrior '
            f'questioning WHY they fight. 2-3 SHORT sentences.'
        )
        narr = gen(narr_prompt, maxn=80)
        if narr:
            self.irc.say(f'\U0001f4dc {narr}')

        save_battle_state(battle)
        return battle

    def _battle_tick(self):
        """Resolve one round of each active battle every BATTLE_TICK_SEC"""
        global ACTIVE_BATTLES
        now = time.time()

        for loc_id in list(ACTIVE_BATTLES.keys()):
            battle = ACTIVE_BATTLES[loc_id]
            if not battle.active:
                save_battle_state(None)
                del ACTIVE_BATTLES[loc_id]
                continue

            # Timeout: battles older than 10 min with <2 turns
            if now - battle.created > 600 and battle.turn < 2:
                battle.active = False
                self.irc.say(f'*The {battle.monster["name"]} retreats into the shadows...*')
                save_battle_state(None)
                del ACTIVE_BATTLES[loc_id]
                continue

            if now - battle.last_turn_t < BATTLE_TICK_SEC:
                continue

            # Resolve one turn
            lines = battle.resolve_turn()
            for line in lines:
                self.irc.say(line)
                time.sleep(0.4)

            # NPC battle reaction (one NPC comments per turn, 30% chance)
            # Plus existential quip chance (15% chance, separate from reaction)
            if battle.active and self.npcs and random.random() < 0.3:
                for nick in list(battle.party.keys()):
                    base = nick.rstrip('_')
                    persona = NPC_PERSONAS.get(base)
                    if persona and random.random() < persona.get('talk_rate', 0.3):
                        # 40% chance the reaction is existential instead of tactical
                        is_existential = random.random() < 0.4
                        if is_existential:
                            quip = gen_existential_quip(
                                nick,
                                f'fighting {battle.monster["name"]} at turn {battle.turn}, '
                                f'monster HP {battle.monster["hp"]}/{battle.monster["max_hp"]}'
                            )
                            if not quip:
                                quip = random.choice(EXISTENTIAL_QUIPS)
                            irc_conn = self.npcs.conns.get(base) or self.npcs.conns.get(nick)
                            if irc_conn:
                                irc_conn.say(f'{persona["cga_prefix"]} *{nick} stares into the void* {quip}')
                        else:
                            prompt = (
                                f'You are fighting {battle.monster["name"]} '
                                f'(HP:{battle.monster["hp"]}/{battle.monster["max_hp"]}, turn {battle.turn}). '
                                f'React to the battle. Maybe question why you fight. 1 SHORT sentence.'
                            )
                            resp = npc_gen(prompt, persona, maxn=30)
                            if resp:
                                irc_conn = self.npcs.conns.get(base) or self.npcs.conns.get(nick)
                                if irc_conn:
                                    irc_conn.say(f'{persona["cga_prefix"]} {resp}')
                        break  # only one NPC reacts per turn

            # Log and publish
            for line in lines:
                rpg_log('DungeonMaster', line)

            save_battle_state(battle if battle.active else None)

            # Update NPC action tracking
            if self.npcs and battle.active:
                for nick in battle.party:
                    base = nick.rstrip('_')
                    if base in NPC_PERSONAS:
                        self.npcs.last_action[base] = {
                            'action': f'battle:T{battle.turn}',
                            'target': battle.monster['name'],
                            'time': now,
                        }
                self.npcs._publish_state()

    def _cmd_heal(self, nick):
        p = load_player(nick)
        if not p:
            self.irc.say(f'{nick}: Type /new first.')
            return
        potions = [i for i, item in enumerate(p['inventory']) if 'healing' in item.lower()]
        if not potions:
            self.irc.say(f'{nick}: No healing potions! Fight monsters to find some.')
            return
        p['inventory'].pop(potions[0])
        heal = min(10, p['max_hp'] - p['hp'])
        p['hp'] += heal
        save_player(p)
        self.irc.say(f'💚 {nick} drinks a healing potion. +{heal} HP ({p["hp"]}/{p["max_hp"]})')
        rpg_log('DungeonMaster', f'{nick} heals for {heal}')

    def _cmd_inventory(self, nick):
        p = load_player(nick)
        if not p:
            self.irc.say(f'{nick}: Type /new first.')
            return
        if not p['inventory']:
            self.irc.say(f'🎒 {nick}\'s pack is empty.')
        else:
            items = ', '.join(p['inventory'][:10])
            self.irc.say(f'🎒 {nick}: {items}')

    def _cmd_stats(self, nick):
        p = load_player(nick)
        if not p:
            self.irc.say(f'{nick}: Type /new first.')
            return
        loc = LOCATIONS.get(p['location'], LOCATIONS['entrance'])
        align = ALIGNMENT_DISPLAY.get(p.get('alignment', 'true_neutral'), 'Neutral')
        role = p.get('role', 'warrior').title()
        self.irc.say(f'📊 {nick} | {align} {role} | Lvl:{p["level"]} HP:{p["hp"]}/{p["max_hp"]} ATK:{p["atk"]} DEF:{p["defense"]} XP:{p["xp"]} | {loc["name"]}')
        battles = p.get('battles', 0)
        bosses = p.get('bosses_killed', 0)
        combos = p.get('combos_landed', 0)
        rooms = p.get('rooms_explored', 0)
        deaths = p.get('deaths', 0)
        gen_num = p.get('generation', 0)
        self.irc.say(f'  Kills:{p["kills"]} Battles:{battles} Bosses:{bosses} Combos:{combos} Rooms:{rooms} Deaths:{deaths} Gen:{gen_num}')
        extras = []
        if p.get('spouse'):
            extras.append(f'Spouse: {p["spouse"]}')
        if p.get('deity'):
            extras.append(f'Deity: {p["deity"]}')
        if p.get('faith', 0) > 0:
            extras.append(f'Faith:{p["faith"]}')
        if p.get('corruption', 0) > 0:
            extras.append(f'Corruption:{p["corruption"]}')
        if p.get('songs_written', 0) > 0:
            extras.append(f'Songs:{p["songs_written"]}')
        if p.get('gold', 0) > 0:
            extras.append(f'Gold:{p["gold"]}')
        if extras:
            self.irc.say(f'  {" | ".join(extras)}')
        lb = load_leaderboard()
        entry = lb.get(nick, {})
        rarest = entry.get('rarest_item', '')
        if rarest:
            self.irc.say(f'  ✦ Rarest find: {rarest} [{entry.get("rarest_tier", "common").upper()}]')

    def _cmd_leaderboard(self, nick):
        """Show IRC leaderboard"""
        self.irc.say('\u2550\u2550\u2550 LEADERBOARD \u2550\u2550\u2550')
        time.sleep(0.2)
        # Top by XP
        top_xp = get_leaderboard_top('total_xp', 5)
        if top_xp:
            self.irc.say('\U0001f3c6 Top XP:')
            for i, (name, data) in enumerate(top_xp):
                self.irc.say(f'  {i+1}. {name}: {data.get("total_xp",0)} xp | {data.get("battles",0)} battles | {data.get("bosses",0)} bosses')
                time.sleep(0.2)
        # Top killers
        top_kills = get_leaderboard_top('battles', 3)
        if top_kills:
            self.irc.say('\u2694 Most Battles:')
            for i, (name, data) in enumerate(top_kills):
                self.irc.say(f'  {i+1}. {name}: {data.get("battles",0)} ({data.get("combos",0)} combos)')
                time.sleep(0.2)
        # Explorers
        top_rooms = get_leaderboard_top('rooms', 3)
        if top_rooms:
            self.irc.say('\U0001f5fa Explorers:')
            for i, (name, data) in enumerate(top_rooms):
                self.irc.say(f'  {i+1}. {name}: {data.get("rooms",0)} rooms')
                time.sleep(0.2)
        # Rarest finds
        lb = load_leaderboard()
        rarest = sorted(lb.items(),
                        key=lambda x: RARITY_ORDER.index(x[1].get('rarest_tier', 'common')),
                        reverse=True)[:3]
        if rarest and rarest[0][1].get('rarest_item'):
            self.irc.say('\u2726 Rarest Finds:')
            for name, data in rarest:
                item = data.get('rarest_item', '')
                tier = data.get('rarest_tier', 'common')
                if item:
                    self.irc.say(f'  {name}: {item} [{tier.upper()}]')
                    time.sleep(0.2)

    def _cmd_action(self, nick, action):
        """Free-form action - let Ollama DM interpret it"""
        p = load_player(nick)
        if not p:
            self.irc.say(f'{nick}: Type /new to begin your adventure first.')
            return

        loc = LOCATIONS.get(p['location'], LOCATIONS['entrance'])
        prompt = (
            f'Player "{nick}" (level {p["level"]}, HP:{p["hp"]}/{p["max_hp"]}) '
            f'is at {loc["name"]} ({loc["desc"]}). '
            f'They attempt: "{action}". '
            f'Narrate what happens. Be brief, dramatic, fun. 1-2 sentences. '
            f'If it sounds like movement, suggest /go. If combat, describe the encounter.'
        )
        resp = gen(prompt, maxn=80)
        if resp:
            self.irc.say(f'📜 {resp}')
            rpg_log('DungeonMaster', resp)
            # NPCs might react to creative actions
            if self.npcs:
                self.npcs.react_to_human(nick, action, p['location'])
            # Small chance of XP for creative play
            if random.random() < 0.2:
                p['xp'] += 5
                save_player(p)
                self.irc.say(f'  (+5 xp for creative adventuring!)')
        else:
            self.irc.say(f'*The DungeonMaster ponders...* Try /look, /go, or /fight.')

    def _cmd_graveyard(self, nick):
        """Show the graveyard — fallen heroes"""
        gy = load_graveyard()
        if not gy:
            self.irc.say('☠ The Boot Cemetery is empty. No one has died... yet.')
            return
        self.irc.say('☠ ═══ BOOT CEMETERY ═══')
        for grave in gy[-8:]:
            align = ALIGNMENT_DISPLAY.get(grave.get('alignment', 'true_neutral'), 'Neutral')
            self.irc.say(
                f'  ⚰ {grave["nick"]} | {align} {grave.get("role","warrior")} | '
                f'Lvl:{grave.get("level",1)} Kills:{grave.get("kills",0)} Gen:{grave.get("generation",0)}'
            )
            self.irc.say(f'    "{grave.get("epitaph", "Rest in peace.")}"')
            time.sleep(0.3)

    def _cmd_lineage(self, nick):
        """Show lineage / family trees"""
        lin = load_lineage()
        if not lin:
            self.irc.say('📜 No lineage records yet. The world is young.')
            return
        self.irc.say('📜 ═══ LINEAGE RECORDS ═══')
        for child, info in list(lin.items())[-10:]:
            parent = info.get('parent', '?')
            gen = info.get('generation', 0)
            children = ', '.join(info.get('children', [])) or 'none'
            self.irc.say(f'  Gen {gen}: {child} ← {parent} | Children: {children}')
            time.sleep(0.2)

    def _cmd_deities(self, nick):
        """Show the pantheon of deities"""
        deities = load_deities()
        if not deities:
            self.irc.say('⛪ No deities have manifested yet...')
            return
        self.irc.say('⛪ ═══ THE PANTHEON ═══')
        for d in deities:
            align = ALIGNMENT_DISPLAY.get(d.get('alignment', 'true_neutral'), 'Neutral')
            followers = len(d.get('followers', []))
            self.irc.say(f'  ✦ {d["name"]} — {d.get("domain","?")} [{align}] | Followers: {followers}')
            self.irc.say(f'    {d.get("desc", "")}')
            time.sleep(0.3)

    def _cmd_songbook(self, nick):
        """Show recent songs from the bard songbook"""
        sb = load_songbook()
        if not sb:
            self.irc.say('♫ The songbook is empty. No bards have written yet.')
            return
        self.irc.say('♫ ═══ SONGBOOK ═══')
        for song in sb[-8:]:
            performed = song.get('performed', 0)
            self.irc.say(
                f'  ♪ "{song["title"]}" by {song["author"]} [{song.get("mood","?")}] '
                f'| Chords: {song.get("chords","?")} | Performed: {performed}x'
            )
            if song.get('lyrics'):
                first_line = song['lyrics'].split('\n')[0][:60]
                self.irc.say(f'    {first_line}...')
            time.sleep(0.3)

    def _cmd_tavern(self, nick):
        """Show tavern info and upcoming events"""
        ev = load_events()
        last = ev.get('last_tavern_night', '')
        history = ev.get('history', [])
        tavern_count = len([e for e in history if e.get('type') == 'tavern_night'])

        self.irc.say('🍺 ═══ THE UPTIME TAVERN ═══')
        if last:
            self.irc.say(f'  Last tavern night: {last[:16]}')
        self.irc.say(f'  Total tavern nights held: {tavern_count}')

        # Who's at tavern right now?
        at_tavern = []
        if self.npcs:
            for npc_name, irc_conn in self.npcs.conns.items():
                p = load_player(irc_conn.nick)
                if p and p.get('location') == 'tavern':
                    at_tavern.append(irc_conn.nick)
        if at_tavern:
            self.irc.say(f'  Currently here: {", ".join(at_tavern)}')
        else:
            self.irc.say('  The tavern is quiet...')

        # Show bands
        sb = load_songbook()
        authors = set(s.get('author') for s in sb if s.get('author'))
        if authors:
            self.irc.say(f'  Resident bards: {", ".join(authors)}')

    def _cmd_alignment(self, nick):
        """Show alignment info"""
        p = load_player(nick)
        if not p:
            self.irc.say(f'{nick}: Type /new first.')
            return
        align = ALIGNMENT_DISPLAY.get(p.get('alignment', 'true_neutral'), 'True Neutral')
        self.irc.say(f'⚖ {nick}: {align}')
        if p.get('deity'):
            self.irc.say(f'  Worships: {p["deity"]} | Faith: {p.get("faith",0)} | Corruption: {p.get("corruption",0)}')

    def _cmd_npc(self, nick, msg):
        """Admin commands for NPC management"""
        if nick not in ADMIN_NICKS:
            self.irc.say(f'{nick}: NPC commands require admin access.')
            return
        parts = msg.strip().split()
        subcmd = parts[0].lower() if parts else ''

        if subcmd == '/npc_spawn':
            # /npc_spawn [name] or /npc_spawn all
            target = parts[1] if len(parts) > 1 else 'all'
            if target.lower() == 'all':
                self.npcs.boot_all()
                self.irc.say(f'░▒▓ Spawning all NPCs... {len(self.npcs.conns)} connected ▓▒░')
            else:
                if target in NPC_PERSONAS:
                    self.npcs.boot_all(names=[target])
                    self.irc.say(f'░▒▓ Spawning {target}... ▓▒░')
                else:
                    self.irc.say(f'Unknown NPC: {target}. Available: {", ".join(NPC_PERSONAS.keys())}')

        elif subcmd == '/npc_kill':
            target = parts[1] if len(parts) > 1 else None
            if not target:
                self.irc.say('Usage: /npc_kill <name|all>')
            elif target.lower() == 'all':
                for name in list(self.npcs.conns.keys()):
                    self.npcs.kill_npc(name)
                self.irc.say('░▒▓ All NPCs dismissed from the realm ▓▒░')
            elif self.npcs.kill_npc(target):
                self.irc.say(f'░▒▓ {target} fades from the realm... ▓▒░')
            else:
                self.irc.say(f'{target} is not connected.')

        elif subcmd == '/npc_budget':
            # /npc_budget <name|all> <amount>
            if len(parts) < 3:
                self.irc.say('Usage: /npc_budget <name|all> <amount>')
                return
            target = parts[1]
            try:
                amount = int(parts[2])
            except ValueError:
                self.irc.say('Budget must be a number.')
                return
            self.npcs.set_budget(target, amount)
            self.irc.say(f'░▒▓ Budget for {target}: {amount} actions ▓▒░')

        elif subcmd == '/npc_status' or subcmd == '/npc_list':
            status = self.npcs.get_status()
            self.irc.say('═══ NPC STATUS ═══')
            for name, s in status.items():
                icon = '●' if s['connected'] else '○'
                alive = '♥' if s['alive'] else '☠'
                self.irc.say(
                    f'{icon} {name} | {alive} HP:{s["hp"]} Lvl:{s["level"]} '
                    f'Kills:{s["kills"]} | Budget:{s["budget"]} | {s["location"]}'
                )
                time.sleep(0.2)

        elif subcmd == '/npc_journal':
            # /npc_journal <name> [n]
            target = parts[1] if len(parts) > 1 else None
            n = int(parts[2]) if len(parts) > 2 else 5
            if not target:
                self.irc.say('Usage: /npc_journal <name> [count]')
                return
            entries = npc_read_journal(target, n)
            if not entries:
                self.irc.say(f'{target} has no journal entries.')
            else:
                self.irc.say(f'═══ {target} Journal (last {len(entries)}) ═══')
                for e in entries:
                    ts = e.get('ts', '?')[:16]
                    self.irc.say(f'  [{ts}] {e.get("type","?")}: {e.get("text","")[:80]}')
                    time.sleep(0.2)

        elif subcmd == '/npc_help':
            cmds = [
                '/npc_spawn [name|all] - Spawn NPC(s)',
                '/npc_kill <name|all> - Disconnect NPC(s)',
                '/npc_budget <name|all> <n> - Set action budget',
                '/npc_status - Show all NPC status',
                '/npc_journal <name> [n] - Read NPC journal',
                '/npc_help - This help',
            ]
            for c in cmds:
                self.irc.say(c)
                time.sleep(0.2)
        else:
            self.irc.say('Unknown /npc command. Try /npc_help')

    def _check_tavern_night(self):
        """Check if it's time for a weekly tavern night and run it"""
        ev = load_events()
        last = ev.get('last_tavern_night', '')
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                # Weekly: only run if 7+ days since last
                if (datetime.now() - last_dt).days < 7:
                    return
            except:
                pass

        # It's tavern night!
        self.irc.say('🍺🎵 ═══ TAVERN NIGHT at The Uptime Tavern! ═══ 🎵🍺')
        self.irc.say('All adventurers are drawn to the warm glow of the tavern...')
        rpg_log('***', '═══ TAVERN NIGHT BEGINS ═══')

        # Move all NPCs to tavern for the event
        if self.npcs:
            for npc_name, irc_conn in self.npcs.conns.items():
                p = load_player(irc_conn.nick)
                if p and p.get('alive', True):
                    p['location'] = 'tavern'
                    save_player(p)
                    persona = NPC_PERSONAS.get(npc_name.rstrip('_'), NPC_PERSONAS.get(npc_name, {}))
                    if persona:
                        irc_conn.say(f'{persona.get("cga_prefix", "")} *enters the tavern for the weekly show*')
                    time.sleep(0.5)

            # Bards perform
            for npc_name, irc_conn in self.npcs.conns.items():
                persona = NPC_PERSONAS.get(npc_name.rstrip('_'), NPC_PERSONAS.get(npc_name, {}))
                if persona and persona.get('role') == 'bard':
                    p = load_player(irc_conn.nick)
                    if p and p.get('alive', True):
                        sb = load_songbook()
                        my_songs = [s for s in sb if s.get('author') == irc_conn.nick]
                        if not my_songs:
                            # Write a song for the occasion
                            song = gen_song_ollama(irc_conn.nick, context='Tavern night performance!', persona=persona)
                            my_songs = [song]
                        song = random.choice(my_songs)
                        song['performed'] = song.get('performed', 0) + 1
                        save_songbook(sb)

                        self.irc.say(f'♫ {irc_conn.nick} takes the stage!')
                        irc_conn.say(f'{persona["cga_prefix"]} ♪ *performs* "{song["title"]}" [{song.get("mood", "?")}]')
                        if song.get('lyrics'):
                            for l in song['lyrics'].split('\n')[:4]:
                                if l.strip():
                                    irc_conn.say(f'{persona["cga_prefix"]}   ♪ {l.strip()}')
                                    time.sleep(0.8)
                        rpg_log(irc_conn.nick, f'performs "{song["title"]}" at tavern night')
                        npc_journal(irc_conn.nick, 'tavern_perform', f'Played "{song["title"]}" at tavern night')
                        time.sleep(1)

        self.irc.say('🍺 The crowd cheers! Another legendary tavern night at the Uptime Tavern! 🍺')
        rpg_log('***', '═══ TAVERN NIGHT ENDS ═══')
        ev['last_tavern_night'] = datetime.now().isoformat()
        ev.setdefault('history', []).append({
            'type': 'tavern_night',
            'date': datetime.now().isoformat(),
        })
        if len(ev['history']) > 100:
            ev['history'] = ev['history'][-100:]
        save_events(ev)

    def _check_opera(self):
        """Occasionally hold an outdoor opera at the colosseum"""
        ev = load_events()
        history = ev.get('history', [])
        last_opera = [e for e in history if e.get('type') == 'opera']
        if last_opera:
            try:
                last_dt = datetime.fromisoformat(last_opera[-1]['date'])
                if (datetime.now() - last_dt).days < 14:
                    return
            except:
                pass

        # ~30% chance each check (so roughly every 2 weeks)
        if random.random() > 0.3:
            return

        # It's opera night!
        self.irc.say('\U0001f3ad\U0001f3b6 ═══ OUTDOOR OPERA at The Process Colosseum! ═══ \U0001f3b6\U0001f3ad')
        self.irc.say('Torches flicker as the crowd gathers under the stars of /dev/urandom...')
        rpg_log('***', '═══ OUTDOOR OPERA BEGINS ═══')

        # Generate an opera name via Ollama
        opera_prompt = (
            'Invent a name for a dramatic one-act opera set in a cyberpunk Linux filesystem realm. '
            'Examples: "The Segfault of Prometheus", "Aria of the Orphaned Process". '
            'Just the title, no quotes.'
        )
        opera_title = gen(opera_prompt, maxn=15)
        if not opera_title:
            opera_title = 'The Ballad of /dev/null'
        opera_title = opera_title.strip().strip('"\'')

        self.irc.say(f'\U0001f3ad Tonight\'s performance: "{opera_title}"')

        # Move all living NPCs to the colosseum
        if self.npcs:
            for npc_name, irc_conn in self.npcs.conns.items():
                p = load_player(irc_conn.nick)
                if p and p.get('alive', True):
                    p['location'] = 'colosseum'
                    save_player(p)
                    persona = NPC_PERSONAS.get(npc_name.rstrip('_'), NPC_PERSONAS.get(npc_name, {}))
                    if persona:
                        irc_conn.say(f'{persona.get("cga_prefix", "")} *takes a seat in the colosseum*')
                    time.sleep(0.3)

            # Bards perform opera arias
            for npc_name, irc_conn in self.npcs.conns.items():
                persona = NPC_PERSONAS.get(npc_name.rstrip('_'), NPC_PERSONAS.get(npc_name, {}))
                if persona and persona.get('role') == 'bard':
                    p = load_player(irc_conn.nick)
                    if p and p.get('alive', True):
                        aria_prompt = (
                            f'You are {irc_conn.nick}, a bard performing in an outdoor opera '
                            f'called "{opera_title}" at a colosseum in a Linux filesystem realm. '
                            f'Sing a dramatic 3-line aria. Be theatrical and operatic.'
                        )
                        resp = npc_gen(aria_prompt, persona, maxn=80)
                        if resp:
                            self.irc.say(f'\U0001f3b5 {irc_conn.nick} steps to center stage...')
                            for line in resp.split('\n')[:4]:
                                if line.strip():
                                    irc_conn.say(f'{persona["cga_prefix"]} \U0001f3b6 {line.strip()}')
                                    time.sleep(1)
                            p['performances'] = p.get('performances', 0) + 1
                            save_player(p)
                            rpg_log(irc_conn.nick, f'performs aria in "{opera_title}"')
                            npc_journal(irc_conn.nick, 'opera', f'Performed aria in "{opera_title}"')
                        time.sleep(1)

            # A dramatic narration from the DM
            narration = gen(
                f'Narrate the dramatic finale of an outdoor opera called "{opera_title}" '
                f'in a colosseum inside a Linux filesystem realm. 2 SHORT sentences. Be poetic.',
                maxn=60
            )
            if narration:
                self.irc.say(f'*{narration.strip("*")}*')

        self.irc.say('\U0001f3ad The audience erupts! Roses and config files rain down! \U0001f3ad')
        rpg_log('***', f'═══ OPERA ENDS: "{opera_title}" ═══')
        ev.setdefault('history', []).append({
            'type': 'opera',
            'title': opera_title,
            'date': datetime.now().isoformat(),
        })
        if len(ev['history']) > 100:
            ev['history'] = ev['history'][-100:]
        save_events(ev)

    def _ambient(self):
        """Periodic atmospheric messages — Ollama-generated world events"""
        prompt = (
            'Generate a single short atmospheric message (1 sentence, max 15 words) from '
            'a vast cyberpunk realm built inside a Linux filesystem. Describe varied scenes: '
            'portals flickering between /proc and /dev, neon bazaars, cosmic voids, floating '
            'towns above swap space, crystalline server halls, ghostly graveyards, ancient '
            'libraries. Not always caves — think cosmic, ethereal, strange. '
            'Be creative, never repeat yourself. Just the message, no quotes.'
        )
        resp = gen(prompt, maxn=40)
        if resp:
            msg = resp.strip('*')
            self.irc.act(msg)
            rpg_log('DungeonMaster', msg, action=True)


if __name__ == '__main__':
    DIR.mkdir(parents=True, exist_ok=True)
    RPG_DIR.mkdir(parents=True, exist_ok=True)
    NPC_DIR.mkdir(parents=True, exist_ok=True)
    try:
        ensure_npc_blog_dirs()
    except Exception:
        pass
    engine = RPGEngine()
    engine.run()
