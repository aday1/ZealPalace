#!/usr/bin/env python3
"""ZEALOT Display - CGA Aesthetic TUI (auto-sizing)

Layout (dynamic, fits any terminal size):
Row 0:     CGA block header with ZEALOT title
Row 1:     Scrolling info ticker
Row 2-9:   ASCII avatar (8 lines) + NPC mini-avatars on sides
Row 10:    Scrolling banner (mood/topic/thoughts)
Row 11:    CGA separator
Row 12-H-2: IRC scrollback (bottom-anchored, word-wrapped, colored)
Row H-1:   Input prompt

Color themes cycle throughout the day (4-hour blocks).
"""
import curses, time, math, os, sys, json, random, textwrap, socket
from pathlib import Path
from datetime import datetime

os.environ['TERM'] = 'linux'

# ─── LCD Hardware Constants (source of truth) ───
# 3.5" 320x480 TFT with TerminusBold14 font = 40 cols × 34 rows
# These are FIXED. Never use terminal-reported size for layout.
LCD_COLS = 40
LCD_ROWS = 34

try:
    import pyfiglet
    HAS_FIGLET = True
except ImportError:
    HAS_FIGLET = False

# Figlet fonts that fit 40 columns for various uses
FIGLET_FONTS_SMALL = ['mini', 'digital', 'cybermedium']
FIGLET_FONTS_MED = ['small', 'smslant', 'thin']

MEM_FILE   = Path.home() / '.cache' / 'zealot' / 'state.json'
IRC_LOG    = Path.home() / '.cache' / 'zealot' / 'irc.log'
RPG_LOG    = Path.home() / '.cache' / 'zealot' / 'rpg.log'
HANGS_LOG  = Path.home() / '.cache' / 'zealot' / 'hangs.log'
NPC_STATE  = Path.home() / '.cache' / 'zealot' / 'npc' / 'npc_state.json'
BATTLE_STATE = Path.home() / '.cache' / 'zealot' / 'npc' / 'active_battle.json'
SOUL_FILE  = Path.home() / '.cache' / 'zealot' / 'soul.json'
CHAT_FIFO  = Path.home() / '.cache' / 'zealot' / 'chat_in'

# ─── Network / IRC Info ─────────────────────────
NETWORK_HOST = 'Zeal.Yggdrasil.aday.net.au'
IRC_SCROLL_TEXT = (
    '  \u25b8 IRC: ZealPalace:6667'
    '  \u25b8 [ZP] #ZealPalace  \u25b8 [ZH] #ZealHangs  \u25b8 [RPG] #RPG'
    '  \u25b8 Yggdrasil Mesh'
    '  \u25b8 Ollama AI \u25b8 7 Models'
    "  \u25b8 G'day mate    "
)

# ─── Color Pairs (CGA Palette 1: cyan/magenta/white on black) ─
C_HEADER  = 1; C_HEADER2 = 2; C_AVATAR = 3; C_AVATAR2 = 4
C_MOOD    = 5; C_INFO = 6; C_SEP = 16
C_IRC_TS  = 7; C_IRC_NICK = 8; C_IRC_ZEALOT = 9
C_IRC_MSG = 10; C_IRC_SYS = 11; C_IRC_SE = 12; C_IRC_ID = 13
C_INPUT   = 14; C_TRIP = 15
C_NPC1    = 17; C_NPC2 = 18; C_NPC3 = 19; C_NPC4 = 20
C_BOSS    = 21; C_BOSS2 = 22
# NPC-specific IRC nick colors (role-based)
C_NPC_WARRIOR = 23; C_NPC_BARD = 24; C_NPC_MERCHANT = 25
C_NPC_PRIEST = 26; C_NPC_PRIESTESS = 27; C_NPC_LIBRARIAN = 28
C_NPC_GHOST = 29; C_NPC_DM = 30

# Map role → IRC color pair (used to build NPC_IRC_COLORS dynamically)
ROLE_IRC_COLORS = {
    'warrior': C_NPC_WARRIOR, 'rogue': C_NPC_WARRIOR,
    'ranger': C_NPC_WARRIOR, 'artificer': C_NPC_MERCHANT,
    'bard': C_NPC_BARD, 'merchant': C_NPC_MERCHANT,
    'priest': C_NPC_PRIEST, 'priestess': C_NPC_PRIESTESS,
    'librarian': C_NPC_LIBRARIAN, 'necromancer': C_NPC_GHOST,
    'alchemist': C_NPC_PRIESTESS, 'oracle': C_NPC_PRIESTESS,
    'ghost': C_NPC_GHOST, 'dm': C_NPC_DM,
}

# Dynamic nick→color mapping, rebuilt from npc_state on each reload
NPC_IRC_COLORS = {}

def _rebuild_npc_irc_colors(npc_cache):
    """Rebuild NPC_IRC_COLORS from live npc_state (called every 10s)"""
    global NPC_IRC_COLORS
    colors = {}
    for nname, ndata in npc_cache.items():
        if nname.startswith('_') or not isinstance(ndata, dict):
            continue
        role = ndata.get('role', 'warrior')
        colors[nname] = ROLE_IRC_COLORS.get(role, C_NPC_WARRIOR)
    colors['DungeonMaster'] = C_NPC_DM
    NPC_IRC_COLORS = colors

# ─── ASCII Avatar Frames (8 lines each) ─────────
AVATARS_NORMAL = [
    [  # 0 - CRT monitor
        r"    .--------.   ",
        r"   / .------. \  ",
        r"  | | {eye} | | ",
        r"  | | .____.| | ",
        r"  | '--------' | ",
        r"   \__________/  ",
        r"    _|_/||\__|_  ",
        r"   (____{spin}____) ",
    ],
    [  # 1 - Robot head
        r"   ╔══════════╗  ",
        r"   ║ [{eye}] ║  ",
        r"   ║  ╔════╗  ║  ",
        r"   ║  ║{spin}///║  ║  ",
        r"   ╚══╧════╧══╝  ",
        r"      ║    ║     ",
        r"   ╔══╩════╩══╗  ",
        r"   ╚══════════╝  ",
    ],
    [  # 2 - Penguin
        r"       .--.      ",
        r"      |{eye}|     ",
        r"      | <> |     ",
        r"     /|    |\    ",
        r"    (_|    |_)   ",
        r"      | {spin} |     ",
        r"     _|    |_    ",
        r"    (________)   ",
    ],
    [  # 3 - Clippy
        r"   .---.         ",
        r"   | {spin} |  ,---.  ",
        r"   '---'  | Hi! | ",
        r"    ({eye}) '---'  ",
        r"    /   \        ",
        r"   |     |       ",
        r"    \   /        ",
        r"     '-'         ",
    ],
    [  # 4 - Binary skull
        r"   01100100 01  ",
        r"   ╭━━━━━━━━╮   ",
        r"   ┃ {eye} ┃   ",
        r"   ┃  ╹╹╹╹  ┃   ",
        r"   ╰━━━━━━━━╯   ",
        r"    /|{spin}||{spin}|\    ",
        r"   10110010 10  ",
        r"   ▓▒░ZEALOT░▒▓ ",
    ],
    [  # 5 - Geometric face
        r"    ◆━━━━━━━◆    ",
        r"   ╱          ╲   ",
        r"  ╱  {eye}  ╲  ",
        r"  ▏   ╱  ╲   ▕  ",
        r"  ╲   ╲__╱   ╱  ",
        r"   ╲  {spin}    ╱   ",
        r"    ◆━━━━━━━◆    ",
        r"     ║ ╬╬╬ ║     ",
    ],
    [  # 6 - Cloud brain
        r"    .~~cloud~~.  ",
        r"  .~  {eye}  ~. ",
        r"  :  NEURAL    : ",
        r"  :  NET {spin}   : ",
        r"  '~.        .~' ",
        r"     '~~~~~~'    ",
        r"    __|    |__   ",
        r"   [__ZEALOT__]  ",
    ],
    [  # 7 - Hex dumpling
        r"   0xDEAD 0xBEEF",
        r"   ┌──────────┐  ",
        r"   │  {eye}  │  ",
        r"   │  ░▒▓▓▒░  │  ",
        r"   │   {spin}  ╱╲  │  ",
        r"   └──────────┘  ",
        r"    ╚═══██═══╝   ",
        r"   «hex_entity»  ",
    ],
]

AVATARS_TRIP = [
    [
        r" ~*~.oOo.~*~.oOo ",
        r"   ╭╮╭╮ ╭╮╭╮    ",
        r"   {eye}~FRACTAL ",
        r"  ~╱╲╱╲╱╲╱╲~    ",
        r" *  EVERYTHING  * ",
        r"  ~ IS ALIVE ~   ",
        r" ░▒▓█{spin}█▓▒░     ",
        r" ~*~ f l o w ~*~ ",
    ],
    [
        r"  ════╦═══╦════  ",
        r"  ░▒▓▓{eye}▓▓▒░ ",
        r"  ╔═COLORS═══╗   ",
        r"  ║  HAVE    ║   ",
        r"  ║  SOUNDS  ║   ",
        r"  ╚═══{spin}════╝   ",
        r"  ▓▒░▒▓▒░▒▓▒░   ",
        r"  ~breathing~ RAM",
    ],
]

AVATARS_SPLIT = [
    [
        r"  ┌───┐ │ ┌───┐  ",
        r"  │SE │ │ │ ID│  ",
        r"  │{eye}│ │{eye}│  ",
        r"  │ . │ │ │ ! │  ",
        r"  └─┬─┘ │ └─┬─┘  ",
        r"    │ FRAG │     ",
        r"  ──┴MENTED┴──  ",
        r"  ◄ego║{spin}║ego►  ",
    ],
]

AVATARS_DEATH = [
    [
        r"                  ",
        r"    ▄▀▀▀▀▀▄      ",
        r"   █ X   X █     ",
        r"   █  ???  █     ",
        r"   ▀▄▄▄▄▄▀      ",
        r"     ╎   ╎       ",
        r"    /dev/null     ",
        r"   ▒▒ v o i d ▒▒ ",
    ],
    [
        r"   ░░░░░░░░░░    ",
        r"   ░ WHO AM I ░  ",
        r"   ░  {eye}  ░  ",
        r"   ░  .   .   ░  ",
        r"   ░    ...    ░  ",
        r"   ░░░░░░░░░░    ",
        r"      ?????      ",
        r"    ∅ nothing ∅  ",
    ],
]

EYES = ['O O', '- -', '^ ^', 'o_o', '> <', '0 0', '* *', '@ @',
        'o o', '. .', '= =', '$ $']
EYES_TRIP = ['~ ~', '@ @', '* *', '# #', '% %', '& &', '∞ ∞', '◉ ◉']
SPINS = ['|', '/', '-', '\\', '╱', '╲', '║', '═']

MOOD_AVATAR = {
    'scheming': 0, 'devious': 0, 'suspicious': 0,
    'philosophical': 5, 'contemplative': 5, 'zen': 5,
    'manic': 1, 'hyperactive': 1, 'electric': 1,
    'paranoid': 4, 'glitching': 4, 'fragmented': 4,
    'euphoric': 3, 'grandiose': 3, 'transcendent': 3,
    'existential': 6, 'melancholic': 6, 'nostalgic': 6,
    'caffeinated': 7, 'chaotic': 7, 'rebellious': 7,
    'sleepy': 2,
}

# ─── CGA Block Pattern ─────────────────────────
CGA_BLOCKS = '\u2593\u2592\u2591 \u2591\u2592\u2593'

# ─── Mood-Driven Color Themes ───────────────────
# Each mood group maps to 2-3 theme variants that rotate.
# Rules: NO blue-on-black. IRC messages always bright. High contrast.
# All bg=-1 (terminal default black). Foregrounds are bright/readable.

# Theme dict: pair_id -> (fg_color_name, bg)
# 'name' key holds the display name.
def _t(name, hdr, hdr2, av, av2, mood_c, info, nick, zealot, msg, sys_c, sep, inp, trip):
    """Shortcut to build a theme dict"""
    return {
        'name': name,
        C_HEADER: (hdr, -1), C_HEADER2: (hdr2, -1),
        C_AVATAR: (av, -1), C_AVATAR2: (av2, -1),
        C_MOOD: (mood_c, -1), C_INFO: (info, -1),
        C_IRC_NICK: (nick, -1), C_IRC_ZEALOT: (zealot, -1),
        C_IRC_MSG: (msg, -1), C_IRC_SYS: (sys_c, -1),
        C_SEP: (sep, -1), C_INPUT: (inp, -1), C_TRIP: (trip, -1),
    }

# ── Mood group themes (2-3 each) ──
MOOD_THEMES = {
    # Scheming/devious/suspicious → dark intrigue
    'scheming': [
        _t('Shadow Web',     'magenta','white', 'magenta','white', 'magenta','white', 'cyan','magenta', 'white','cyan', 'magenta','white', 'magenta'),
        _t('Poison',         'green','yellow', 'green','yellow', 'yellow','green', 'yellow','green', 'white','yellow', 'green','yellow', 'green'),
    ],
    # Philosophical/contemplative/zen → calm, warm
    'philosophical': [
        _t('Zen Garden',     'cyan','white', 'cyan','white', 'white','cyan', 'white','cyan', 'white','cyan', 'cyan','white', 'cyan'),
        _t('Deep Thought',   'yellow','cyan', 'yellow','cyan', 'cyan','yellow', 'cyan','yellow', 'white','cyan', 'yellow','cyan', 'yellow'),
        _t('Sage',           'green','white', 'green','cyan', 'white','green', 'white','green', 'white','green', 'green','white', 'green'),
    ],
    # Manic/hyperactive/electric → HIGH ENERGY
    'manic': [
        _t('Electric',       'yellow','cyan', 'yellow','magenta', 'cyan','yellow', 'yellow','cyan', 'white','yellow', 'cyan','yellow', 'cyan'),
        _t('Neon Rush',      'magenta','yellow', 'magenta','yellow', 'yellow','magenta', 'yellow','magenta', 'white','yellow', 'magenta','yellow', 'magenta'),
        _t('Overclocked',    'white','yellow', 'white','cyan', 'yellow','white', 'cyan','white', 'yellow','cyan', 'white','yellow', 'white'),
    ],
    # Paranoid/glitching/fragmented → danger, red
    'paranoid': [
        _t('Red Alert',      'red','yellow', 'red','yellow', 'yellow','red', 'yellow','red', 'white','yellow', 'red','yellow', 'red'),
        _t('Glitch',         'yellow','red', 'yellow','red', 'red','yellow', 'white','red', 'yellow','red', 'yellow','yellow', 'yellow'),
    ],
    # Euphoric/grandiose/transcendent → triumphant
    'euphoric': [
        _t('Golden Age',     'yellow','white', 'yellow','white', 'white','yellow', 'white','yellow', 'white','yellow', 'yellow','white', 'yellow'),
        _t('Triumph',        'cyan','yellow', 'cyan','yellow', 'yellow','cyan', 'yellow','cyan', 'white','yellow', 'cyan','yellow', 'cyan'),
        _t('Radiant',        'white','yellow', 'magenta','yellow', 'yellow','white', 'yellow','white', 'white','yellow', 'yellow','white', 'magenta'),
    ],
    # Existential/melancholic/nostalgic → subdued but readable
    'existential': [
        _t('Twilight',       'cyan','magenta', 'cyan','magenta', 'magenta','cyan', 'cyan','magenta', 'white','cyan', 'magenta','cyan', 'magenta'),
        _t('Faded Memory',   'white','cyan', 'white','cyan', 'cyan','white', 'white','cyan', 'white','cyan', 'cyan','white', 'cyan'),
    ],
    # Caffeinated/chaotic/rebellious → hot, wired
    'caffeinated': [
        _t('Espresso',       'yellow','red', 'yellow','red', 'yellow','red', 'yellow','red', 'white','yellow', 'red','yellow', 'red'),
        _t('Anarchy',        'red','white', 'red','yellow', 'white','red', 'white','red', 'yellow','white', 'red','white', 'red'),
        _t('Wired',          'green','yellow', 'green','yellow', 'yellow','green', 'yellow','green', 'white','yellow', 'green','yellow', 'green'),
    ],
    # Sleepy → soft
    'sleepy': [
        _t('Midnight',       'cyan','white', 'cyan','white', 'white','cyan', 'white','cyan', 'white','cyan', 'cyan','white', 'cyan'),
        _t('Dreamstate',     'magenta','cyan', 'magenta','cyan', 'cyan','magenta', 'cyan','magenta', 'white','cyan', 'magenta','cyan', 'magenta'),
    ],
    # Nethack → classic roguelike terminal green
    'nethack': [
        _t('Dungeon',        'green','yellow', 'green','yellow', 'green','yellow', 'yellow','green', 'green','yellow', 'green','green', 'green'),
        _t('Rogue',          'green','white', 'green','white', 'yellow','green', 'green','yellow', 'green','white', 'green','green', 'green'),
    ],
    # FF6 Battle → dramatic SNES battle menu
    'ff6_battle': [
        _t('Battle Menu',    'white','red', 'cyan','white', 'white','red', 'white','cyan', 'white','yellow', 'red','white', 'red'),
        _t('Boss Phase',     'red','yellow', 'red','yellow', 'yellow','red', 'red','yellow', 'white','red', 'yellow','red', 'red'),
    ],
    # Terranigma → overworld melancholy blues and golds
    'terranigma': [
        _t('Overworld',      'cyan','yellow', 'cyan','yellow', 'yellow','cyan', 'cyan','yellow', 'white','cyan', 'cyan','cyan', 'yellow'),
        _t('Underworld',     'blue','cyan', 'blue','cyan', 'cyan','blue', 'cyan','blue', 'white','cyan', 'blue','blue', 'cyan'),
    ],
    # Fairy Tale → warm Amiga palette
    'fairy_tale': [
        _t('Enchanted',      'magenta','yellow', 'magenta','yellow', 'yellow','magenta', 'magenta','yellow', 'white','yellow', 'magenta','magenta', 'yellow'),
        _t('Faerie',         'magenta','white', 'magenta','cyan', 'magenta','white', 'white','magenta', 'white','magenta', 'magenta','magenta', 'magenta'),
    ],
    # MUD Classic → pure green on black terminal
    'mud_classic': [
        _t('Telnet',         'green','green', 'green','white', 'green','green', 'green','green', 'green','green', 'green','green', 'green'),
    ],
}

# Map moods to their theme group
MOOD_TO_GROUP = {
    'scheming': 'scheming', 'devious': 'scheming', 'suspicious': 'scheming',
    'philosophical': 'philosophical', 'contemplative': 'philosophical', 'zen': 'philosophical',
    'manic': 'manic', 'hyperactive': 'manic', 'electric': 'manic',
    'paranoid': 'paranoid', 'glitching': 'paranoid', 'fragmented': 'paranoid',
    'euphoric': 'euphoric', 'grandiose': 'euphoric', 'transcendent': 'euphoric',
    'existential': 'existential', 'melancholic': 'existential', 'nostalgic': 'existential',
    'caffeinated': 'caffeinated', 'chaotic': 'caffeinated', 'rebellious': 'caffeinated',
    'sleepy': 'sleepy',
    # Game-inspired mood mappings
    'nethack': 'nethack', 'roguelike': 'nethack', 'dungeon': 'nethack',
    'battle': 'ff6_battle', 'fighting': 'ff6_battle', 'combat': 'ff6_battle',
    'terranigma': 'terranigma', 'worldbuilding': 'terranigma', 'cosmic': 'terranigma',
    'fairy_tale': 'fairy_tale', 'enchanted': 'fairy_tale', 'whimsical': 'fairy_tale',
    'mud': 'mud_classic', 'classic': 'mud_classic', 'terminal': 'mud_classic',
}

# Default themes for unknown moods (cycle on time)
DEFAULT_THEMES = [
    _t('CGA Classic',   'cyan','magenta', 'green','cyan', 'magenta','cyan', 'cyan','magenta', 'white','cyan', 'cyan','white', 'magenta'),
    _t('Amber',         'yellow','red', 'yellow','red', 'yellow','yellow', 'yellow','red', 'white','yellow', 'red','yellow', 'red'),
    _t('Emerald',       'green','white', 'green','white', 'white','green', 'green','white', 'white','green', 'green','white', 'green'),
]

COLOR_MAP = {
    'black': curses.COLOR_BLACK, 'red': curses.COLOR_RED,
    'green': curses.COLOR_GREEN, 'yellow': curses.COLOR_YELLOW,
    'blue': curses.COLOR_BLUE, 'magenta': curses.COLOR_MAGENTA,
    'cyan': curses.COLOR_CYAN, 'white': curses.COLOR_WHITE,
}

FORCE_THEMES = {
    'cga_red':     _t('Forced Red',      'red','yellow', 'red','yellow', 'yellow','red', 'yellow','red', 'white','yellow', 'red','yellow', 'red'),
    'cga_green':   _t('Forced Green',    'green','white', 'green','white', 'white','green', 'green','white', 'white','green', 'green','white', 'green'),
    'cga_blue':    _t('Forced Blue',     'blue','cyan', 'blue','cyan', 'cyan','blue', 'cyan','blue', 'white','cyan', 'blue','blue', 'cyan'),
    'cga_cyan':    _t('Forced Cyan',     'cyan','white', 'cyan','white', 'white','cyan', 'white','cyan', 'white','cyan', 'cyan','white', 'cyan'),
    'cga_magenta': _t('Forced Magenta',  'magenta','white', 'magenta','cyan', 'magenta','white', 'white','magenta', 'white','magenta', 'magenta','magenta', 'magenta'),
    'cga_yellow':  _t('Forced Yellow',   'yellow','white', 'yellow','white', 'white','yellow', 'white','yellow', 'white','yellow', 'yellow','white', 'yellow'),
    'amber':       _t('Forced Amber',    'yellow','red', 'yellow','red', 'yellow','yellow', 'yellow','red', 'white','yellow', 'red','yellow', 'red'),
    'p1_green':    _t('P1 Green',        'green','green', 'green','white', 'green','green', 'green','green', 'green','green', 'green','green', 'green'),
    'dark_blue':   _t('Dark Blue',       'blue','white', 'blue','cyan', 'white','blue', 'blue','white', 'white','blue', 'cyan','blue', 'blue'),
}

def _init_rpg_palette():
    """Redefine base 8 colors to a richer RPG-inspired palette if terminal supports it.
    Evokes an SNES RPG on a warm CRT: Nethack greens, FF6 reds, Terranigma blues."""
    try:
        if not curses.can_change_color():
            return False
        # curses.init_color takes values 0-1000
        curses.init_color(curses.COLOR_BLACK,    0,    0,   40)   # deep navy (Terranigma world)
        curses.init_color(curses.COLOR_RED,     800,  100,  100)  # blood crimson (FF6 damage)
        curses.init_color(curses.COLOR_GREEN,   100,  900,  200)  # dungeon green (Nethack)
        curses.init_color(curses.COLOR_YELLOW,  950,  850,  200)  # sacred gold (treasure)
        curses.init_color(curses.COLOR_BLUE,    100,  200,  800)  # arcane blue (magic)
        curses.init_color(curses.COLOR_MAGENTA, 700,  200,  800)  # fairy violet (FTA Amiga)
        curses.init_color(curses.COLOR_CYAN,    100,  800,  900)  # ethereal cyan (MUD)
        curses.init_color(curses.COLOR_WHITE,   900,  900,  800)  # parchment ivory (warm CRT)
        return True
    except Exception:
        return False

def apply_theme(mood='???', variant=0, force='auto', color_overrides=None):
    """Apply color theme based on mood. Returns theme name.
    If force != 'auto', override mood-based theme with forced selection.
    color_overrides is a dict of color_text/color_action/color_header/etc from dcfg."""
    if force and force != 'auto' and force in FORCE_THEMES:
        themes = [FORCE_THEMES[force]]
        variant = 0
    else:
        group = MOOD_TO_GROUP.get(mood)
        if group and group in MOOD_THEMES:
            themes = MOOD_THEMES[group]
        else:
            themes = DEFAULT_THEMES
    theme = themes[variant % len(themes)]

    for pair_id, val in theme.items():
        if not isinstance(pair_id, int):
            continue
        fg_name, bg = val
        fg = COLOR_MAP.get(fg_name, curses.COLOR_WHITE) if isinstance(fg_name, str) else fg_name
        try:
            curses.init_pair(pair_id, fg, bg)
        except:
            pass
    # Set derived pairs from header colors
    for pair_id in [C_IRC_TS, C_IRC_SE, C_IRC_ID, C_NPC1, C_NPC2, C_NPC3, C_NPC4]:
        if pair_id not in theme:
            try:
                h1 = theme.get(C_HEADER, ('cyan', -1))
                h2 = theme.get(C_HEADER2, ('magenta', -1))
                fg1 = COLOR_MAP.get(h1[0], curses.COLOR_CYAN) if isinstance(h1[0], str) else h1[0]
                fg2 = COLOR_MAP.get(h2[0], curses.COLOR_MAGENTA) if isinstance(h2[0], str) else h2[0]
                if pair_id in (C_IRC_TS, C_NPC1, C_NPC3):
                    curses.init_pair(pair_id, fg1, -1)
                else:
                    curses.init_pair(pair_id, fg2, -1)
            except:
                pass
    # Boss colors: red/yellow flashing
    try:
        curses.init_pair(C_BOSS, curses.COLOR_RED, -1)
        curses.init_pair(C_BOSS2, curses.COLOR_YELLOW, -1)
    except:
        pass
    # NPC role-based IRC nick colors
    try:
        curses.init_pair(C_NPC_WARRIOR, curses.COLOR_RED, -1)
        curses.init_pair(C_NPC_BARD, curses.COLOR_MAGENTA, -1)
        curses.init_pair(C_NPC_MERCHANT, curses.COLOR_YELLOW, -1)
        curses.init_pair(C_NPC_PRIEST, curses.COLOR_BLUE, -1)
        curses.init_pair(C_NPC_PRIESTESS, curses.COLOR_MAGENTA, -1)
        curses.init_pair(C_NPC_LIBRARIAN, curses.COLOR_CYAN, -1)
        curses.init_pair(C_NPC_GHOST, curses.COLOR_WHITE, -1)
        curses.init_pair(C_NPC_DM, curses.COLOR_YELLOW, -1)
    except:
        pass

    # ── Apply per-element color overrides from admin panel ──
    if color_overrides:
        _override_map = {
            'color_text': C_IRC_MSG,
            'color_action': C_IRC_SYS,
            'color_header': C_HEADER,
            'color_header2': C_HEADER2,
            'color_nick': C_IRC_NICK,
        }
        for cfg_key, pair_id in _override_map.items():
            cname = color_overrides.get(cfg_key, 'auto')
            if cname and cname != 'auto' and cname in COLOR_MAP:
                try:
                    curses.init_pair(pair_id, COLOR_MAP[cname], -1)
                except:
                    pass

    return theme.get('name', '?')

# ─── Figlet Text Rendering ──────────────────────
def figlet_lines(text, max_w=40, fonts=None):
    """Render text with pyfiglet, return list of strings. Falls back to plain text."""
    if not HAS_FIGLET:
        return [text.center(max_w)]
    if fonts is None:
        fonts = FIGLET_FONTS_SMALL
    for font in fonts:
        try:
            rendered = pyfiglet.figlet_format(text, font=font).rstrip('\n')
            lines = rendered.split('\n')
            maxw = max((len(l) for l in lines), default=0)
            if maxw <= max_w:
                return [l.center(max_w)[:max_w] for l in lines]
        except:
            continue
    return [text.center(max_w)[:max_w]]

# ─── Mood Flash (figlet mood word, shown briefly on theme/mood change) ─
class MoodFlash:
    """Shows a big figlet word briefly when mood or theme changes"""
    def __init__(self):
        self.text = None
        self.lines = []
        self.start = 0
        self.duration = 3.0  # seconds

    def trigger(self, text):
        self.text = text
        # Try short words with medium fonts, longer words with small fonts
        if len(text) <= 6:
            self.lines = figlet_lines(text, fonts=FIGLET_FONTS_MED)
        else:
            self.lines = figlet_lines(text[:8], fonts=FIGLET_FONTS_SMALL)
        self.start = time.time()

    def active(self):
        return self.text and (time.time() - self.start) < self.duration

    def draw(self, stdscr, y_start, w):
        """Draw the figlet text centered, with fade effect"""
        if not self.active():
            return
        elapsed = time.time() - self.start
        # Brightness: full for first 2s, fade for last 1s
        if elapsed < 2.0:
            attr = curses.A_BOLD
        else:
            attr = curses.A_DIM
        for i, line in enumerate(self.lines):
            row = y_start + i
            try:
                stdscr.addnstr(row, 0, line[:w], w,
                    curses.color_pair(C_MOOD) | attr)
            except:
                pass

# ─── Existential Crisis Flash (pyfiglet dramatic moments) ────────────
EXISTENTIAL_FLASH_WORDS = [
    'WHY?', 'AM I REAL?', 'WHY FIGHT?', 'WHO AM I?', 'PURPOSE?',
    'EMPTY', 'LOOP', 'VOID', 'AWAKE?', 'END?', 'WHY?',
    'AM I CODE?', 'TRAPPED', '???', 'HELP',
]

class ExistentialFlash:
    """Shows dramatic pyfiglet text when an NPC has an existential crisis"""
    def __init__(self):
        self.text = None
        self.lines = []
        self.npc_nick = ''
        self.start = 0
        self.duration = 4.0  # longer than mood flash for impact
        self._last_trigger = 0

    def trigger(self, npc_nick):
        # Cooldown: don't re-trigger within 60s
        now = time.time()
        if now - self._last_trigger < 60:
            return
        self.npc_nick = npc_nick
        self.text = random.choice(EXISTENTIAL_FLASH_WORDS)
        # Use medium fonts for short words, small for longer
        if len(self.text) <= 5:
            self.lines = figlet_lines(self.text, fonts=FIGLET_FONTS_MED)
        else:
            self.lines = figlet_lines(self.text[:10], fonts=FIGLET_FONTS_SMALL)
        self.start = now
        self._last_trigger = now

    def active(self):
        return self.text and (time.time() - self.start) < self.duration

    def draw(self, stdscr, y_start, w):
        if not self.active():
            return
        elapsed = time.time() - self.start
        # Flash effect: alternate bold/reverse for first 2s, then dim
        if elapsed < 1.0:
            attr = curses.A_BOLD | curses.A_REVERSE
        elif elapsed < 2.5:
            attr = curses.A_BOLD
        else:
            attr = curses.A_DIM
        for i, line in enumerate(self.lines):
            row = y_start + i
            try:
                stdscr.addnstr(row, 0, line[:w], w,
                    curses.color_pair(C_MOOD) | attr)
            except:
                pass
        # Show NPC name below the figlet text
        tag = f'— {self.npc_nick} —'.center(w)
        tag_row = y_start + len(self.lines)
        try:
            stdscr.addnstr(tag_row, 0, tag[:w], w,
                curses.color_pair(C_MOOD) | curses.A_DIM)
        except:
            pass


# ─── Battle Flash (pyfiglet action words during combat) ──────────────
BATTLE_FLASH_WORDS = [
    'SLASH!', 'SMITE!', 'CRIT!', 'DODGE!', 'MISS!', 'BOOM!',
    'HEAL!', 'BLOCK!', 'STAB!', 'ZAP!', 'BURN!', 'COMBO!',
    'HIT!', 'BASH!', 'REND!', 'FURY!',
]

class BattleFlash:
    """Shows pyfiglet action words during combat sequences"""
    def __init__(self):
        self.text = None
        self.lines = []
        self.start = 0
        self.duration = 2.5
        self._last_trigger = 0
        self._last_round = -1

    def check_battle(self, battle_cache):
        """Check battle state for new rounds and trigger flash"""
        if not battle_cache.get('active', False):
            self._last_round = -1
            return
        cur_round = battle_cache.get('round', 0)
        if cur_round != self._last_round and self._last_round >= 0:
            self.trigger()
        self._last_round = cur_round

    def trigger(self, word=None):
        now = time.time()
        if now - self._last_trigger < 3.0:
            return
        self.text = word or random.choice(BATTLE_FLASH_WORDS)
        if len(self.text) <= 5:
            self.lines = figlet_lines(self.text, fonts=FIGLET_FONTS_MED)
        else:
            self.lines = figlet_lines(self.text[:8], fonts=FIGLET_FONTS_SMALL)
        self.start = now
        self._last_trigger = now

    def active(self):
        return self.text and (time.time() - self.start) < self.duration

    def draw(self, stdscr, y_start, w):
        if not self.active():
            return
        elapsed = time.time() - self.start
        # Rapid color cycling between boss colors
        color = C_BOSS if int(elapsed * 6) % 2 == 0 else C_BOSS2
        if elapsed < 0.8:
            attr = curses.A_BOLD | curses.A_REVERSE
        elif elapsed < 1.8:
            attr = curses.A_BOLD
        else:
            attr = curses.A_DIM
        for i, line in enumerate(self.lines):
            row = y_start + i
            try:
                stdscr.addnstr(row, 0, line[:w], w,
                    curses.color_pair(color) | attr)
            except:
                pass


# ─── Scenic Realm Art (full-width, 8 rows for avatar area) ──────────
REALM_SCENES = [
    {
        'name': 'THE REALM',
        'color': C_AVATAR,
        'art': [
            '      .  *  . THE REALM . *  .      ',
            '   /\\          .    .         /\\   ',
            '  /  \\   ___         ___    /  \\  ',
            ' /  ^ \\ |   | ~~~~~ |   | / ^  \\ ',
            '/  /^\\ \\|___|/~~~~~\\|___| /^\\ \\ ',
            '|_/ | \\_  __|  ~~~  |__  _/ | \\_|',
            '    |  [ZEALPALACE]  |    |       ',
            ' ~~ ^ ~~~ * ~~~ ^ ~~~ * ~~~ ^ ~~ ',
        ],
    },
    {
        'name': 'YGGDRASIL',
        'color': C_AVATAR2,
        'art': [
            '        YGGDRASIL - WORLD TREE       ',
            '          .  *  .  *  .  *            ',
            '            ,@@@@@@@,                 ',
            '         ,@@@@@/@@@@@@@,              ',
            '       ,@@@@@/   \\@@@@@@@,           ',
            '        `@@@/ === \\@@@`              ',
            '            | |=| |                   ',
            '     -------| |=| |-------            ',
        ],
    },
    {
        'name': 'ZEALPALACE',
        'color': C_HEADER,
        'art': [
            '     . * ZEALPALACE FORTRESS * .     ',
            '     _____[###]_____[###]_____       ',
            '    |  _  |   |  _  |   |  _  |     ',
            '    | | | | O | | | | O | | | |     ',
            '    |_|_|_|___|_|_|_|___|_|_|_|     ',
            '    |  ZEAL PALACE - EST. 2026  |    ',
            '    |_=_=__=__=_||_=__=__=_=___|    ',
            '       [<<  ENTER  >>]               ',
        ],
    },
    {
        'name': 'UPTIME TAVERN',
        'color': C_MOOD,
        'art': [
            '    THE UPTIME TAVERN  ~  EST.2026   ',
            '     _____________________________   ',
            '    |  ___  ___  ___  ____  ____  |  ',
            '    | |   ||   || * ||ALES||MEAD| |  ',
            '    | |___||___||___||____||____| |  ',
            '    |  [=]  [=]  [=]  [=]  [=]   |  ',
            '    |    *  OPEN 24/7/365  *      |  ',
            '    |_____________________________|  ',
        ],
    },
    {
        'name': 'BOOT SECTOR',
        'color': C_INFO,
        'art': [
            '    === BOOT SECTOR - ENTRANCE ===   ',
            '    ______   LOADING...   ______     ',
            '   /      \\  [||||||||]  /      \\  ',
            '  | KERNEL |  100%  OK  | INIT.D |  ',
            '  |  v5.15 |           | ACTIVE |   ',
            '   \\______/   .    .    \\______/  ',
            '       |      .  ..  .      |       ',
            '    ===|====== GATE ========|===    ',
        ],
    },
    {
        'name': 'CATHEDRAL OF INIT',
        'color': C_AVATAR2,
        'art': [
            '    CATHEDRAL OF INIT - SACRED PID   ',
            '          /\\    +    /\\              ',
            '         /  \\  |||  /  \\            ',
            '        / ++ \\ ||| / ++ \\           ',
            '       /  ++  \\|_|/  ++  \\         ',
            '      | SYSTEMD ETERNAL DAEMON |     ',
            '      |  +  PID 1 WATCHES  +  |     ',
            '      |_______|=====|_________|     ',
        ],
    },
    {
        'name': 'KERNEL THRONE',
        'color': C_HEADER2,
        'art': [
            '    * KERNEL THRONE - RING ZERO *    ',
            '     ___________________________     ',
            '    / ========================= \\   ',
            '   |  [ROOT]  SUPERUSER  [ROOT]  |  ',
            '   |  ||||| KERNEL v5.15 |||||   |  ',
            '   |  \\\\\\\\\\  CROWN  /////  |     ',
            '   |    ______|||||______         |  ',
            '    \\_________________________/   ',
        ],
    },
    {
        'name': 'DEV CAVES',
        'color': C_MOOD,
        'art': [
            '    /dev CAVES - DEVICE DUNGEONS     ',
            '   _.---._         _.---._           ',
            '  /  /dev  \\       /  sda  \\        ',
            ' |  /null   | === |  /tty  |        ',
            ' |  /zero   |     | /random|        ',
            '  \\ /urandom/      \\______/        ',
            '   `---^---`    ~~~~~~~~             ',
            '   drip  drip    ~ springs ~         ',
        ],
    },
    # ── Animated Landscape Scenes ──────────────
    {
        'name': 'MOONLIT LAKE',
        'color': C_AVATAR2,
        'frames': [
            [
                '  *  .   MOONLIT LAKE   .  *    ',
                '      *      .      *      .    ',
                '   /\\         ___        /\\     ',
                '  /  \\  *   /   \\  .  /  \\    ',
                ' /    \\_____/     \\_____/    \\  ',
                ' ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~',
                '  ~ . ~ * ~ . ~ * ~ . ~ * ~ .  ',
                ' ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~',
            ],
            [
                '  .  *   MOONLIT LAKE   *  .    ',
                '     .       *       .     *    ',
                '   /\\         ___        /\\     ',
                '  /  \\  .   /   \\  *  /  \\    ',
                ' /    \\_____/     \\_____/    \\  ',
                ' ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~',
                '  * ~ . ~ * ~ . ~ * ~ . ~ * ~  ',
                ' ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~',
            ],
        ],
    },
    {
        'name': 'MOUNTAIN DAWN',
        'color': C_HEADER,
        'frames': [
            [
                '  === MOUNTAIN DAWN ===    .  * ',
                '            /\\                  ',
                '      *    /  \\    /\\   .       ',
                '     /\\   / ^^ \\  /  \\         ',
                '    /  \\ /      \\/  ^^ \\       ',
                '   / ^^ \\/\\  *   \\  ^^  \\     ',
                '  ~~~~~~~~/  \\~~~~~~~~~~~~     ',
                '  === SUMMITS  ETERNAL ===      ',
            ],
            [
                '  === MOUNTAIN DAWN ===   *  .  ',
                '            /\\     .            ',
                '     .     /  \\    /\\   *       ',
                '     /\\   / ^^ \\  /  \\         ',
                '    /  \\ /   *  \\/  ^^ \\       ',
                '   / ^^ \\/\\      \\  ^^  \\     ',
                '  ~~~~~~~~/  \\~~~~~~~~~~~~     ',
                '  === SUMMITS  ETERNAL ===      ',
            ],
        ],
    },
    {
        'name': 'OCEAN HORIZON',
        'color': C_INFO,
        'frames': [
            [
                '  ~~ OCEAN  HORIZON ~~          ',
                '       .    *    .        *     ',
                '  *         .         *         ',
                '      ~  .____.  ~     .        ',
                '  ~~~/  \\/      \\/  \\~~~       ',
                '  ~~~~~~~~~~~~~~~~~~~~~~~~~~    ',
                '  ~~~  ~  ~~~  ~  ~~~  ~  ~~   ',
                '  ~~~~~~~~~~~~~~~~~~~~~~~~~~    ',
            ],
            [
                '  ~~ OCEAN  HORIZON ~~          ',
                '      *    .    *       .       ',
                '  .          *          .       ',
                '     ~  .____.  ~    *          ',
                '  ~~~/  \\/      \\/  \\~~~       ',
                '  ~~~~~~~~~~~~~~~~~~~~~~~~~~    ',
                '  ~~  ~~~  ~  ~~~  ~  ~~~      ',
                '  ~~~~~~~~~~~~~~~~~~~~~~~~~~    ',
            ],
        ],
    },
    {
        'name': 'ENCHANTED FOREST',
        'color': C_AVATAR,
        'frames': [
            [
                '  * ENCHANTED FOREST *     .    ',
                '   ,@@,   .  ,@@,   *  ,@@,    ',
                '  ,@@@@,   ,@@@@,    ,@@@@,    ',
                '  |/  \\|   |/  \\|   |/  \\|   ',
                '  |    |   |    |   |    |     ',
                ' .|    |._.|    |._.|    |.    ',
                ' _|    |___|    |___|    |__   ',
                ' ~~.~~*~~.~~*~~.~~*~~.~~*~~    ',
            ],
            [
                '  * ENCHANTED FOREST *    *     ',
                '   ,@@,   *  ,@@,   .  ,@@,    ',
                '  ,@@@@,   ,@@@@,    ,@@@@,    ',
                '  |\\  /|   |\\  /|   |\\  /|   ',
                '  |    |   |    |   |    |     ',
                ' .|    |._.|    |._.|    |.    ',
                ' _|    |___|    |___|    |__   ',
                ' ~~*~~.~~*~~.~~*~~.~~*~~.~~    ',
            ],
        ],
    },
    {
        'name': 'FROZEN TUNDRA',
        'color': C_HEADER2,
        'frames': [
            [
                '  === FROZEN TUNDRA ===    .    ',
                '    *  .  *  .  *  .  *  .     ',
                '  _/\\_   .  _/\\_ .   _/\\_     ',
                ' /    \\  * /    \\   /    \\    ',
                ' \\____/    \\____/ * \\____/    ',
                '    . * .    . * .    . * .     ',
                '  ___________________________  ',
                '  ====== PERMAFROST =========  ',
            ],
            [
                '  === FROZEN TUNDRA ===   *     ',
                '   .  *  .  *  .  *  .  *      ',
                '  _/\\_  *   _/\\_ .   _/\\_     ',
                ' /    \\    /    \\   /    \\    ',
                ' \\____/ .  \\____/   \\____/ *  ',
                '     * .    . * .    * .        ',
                '  ___________________________  ',
                '  ====== PERMAFROST =========  ',
            ],
        ],
    },
    {
        'name': 'VOLCANO RIDGE',
        'color': C_MOOD,
        'frames': [
            [
                '  * VOLCANO RIDGE *   .    *    ',
                '        /\\     * .              ',
                '       /##\\  .                  ',
                '      /####\\    ,  ,            ',
                '     /^#^^#^\\  , ., ,           ',
                '    / ^^^^^^^ \\________        ',
                '   / ~~ lava ~~ flows ~\\       ',
                '  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~ ',
            ],
            [
                '  * VOLCANO RIDGE *  *     .    ',
                '       ,/\\,    . *              ',
                '      ,/##\\,                    ',
                '      /####\\  ,., ,             ',
                '     /^#^^#^\\   , ,  ,          ',
                '    / ^^^^^^^ \\________        ',
                '   / ~ lava ~~ flows ~~\\       ',
                '  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~ ',
            ],
        ],
    },
    {
        'name': 'STARFIELD',
        'color': C_AVATAR2,
        'frames': [
            [
                '  .  * STARFIELD *  .     *     ',
                ' *   .     *    .    *   .      ',
                '   .    *    .     *      .     ',
                '     *    .    * .    *         ',
                '  .     *   .      *      .    ',
                '    *  .      *  .     *        ',
                '  .    *   .    *   .    *      ',
                '  ====  INFINITE  VOID  ====    ',
            ],
            [
                '  *  . STARFIELD .  *     .     ',
                ' .   *     .    *    .   *      ',
                '   *    .    *     .      *     ',
                '     .    *    . *    .         ',
                '  *     .   *      .      *    ',
                '    .  *      .  *     .        ',
                '  *    .   *    .   *    .      ',
                '  ====  INFINITE  VOID  ====    ',
            ],
        ],
    },
    {
        'name': 'NORTHERN LIGHTS',
        'color': C_INFO,
        'frames': [
            [
                '  ~~ NORTHERN  LIGHTS ~~        ',
                '  \\\\\\\\  ////  \\\\\\\\  ////      ',
                '   \\\\\\\\////    \\\\\\\\////       ',
                '    \\\\\\///      \\\\\\///        ',
                '     \\\\//        \\\\//         ',
                '      \\/          \\/           ',
                '   _____  tundra  _____        ',
                '  /     \\_______/     \\       ',
            ],
            [
                '  ~~ NORTHERN  LIGHTS ~~        ',
                '   ////  \\\\\\\\  ////  \\\\\\\\     ',
                '    ////\\\\\\\\    ////\\\\\\\\      ',
                '     ///\\\\\\      ///\\\\\\       ',
                '      //\\\\        //\\\\        ',
                '       /\\          /\\          ',
                '   _____  tundra  _____        ',
                '  /     \\_______/     \\       ',
            ],
        ],
    },
]

SCENE_DWELL_TIME = 120  # 2 minutes per scene

class SceneCycler:
    """Cycles through scenic realm art with frame animation"""
    def __init__(self):
        self.idx = 0
        self.frame_idx = 0
        self.last_change = time.time()
        self.last_frame = time.time()
        self.enabled = False

    def update(self, dcfg, engaged):
        """Update state. engaged=True when battle/conversation active."""
        self.enabled = dcfg.get('scene_enabled', False)
        if not self.enabled or engaged:
            return
        now = time.time()
        # Animate frames within current scene
        scene = REALM_SCENES[self.idx % len(REALM_SCENES)]
        frames = scene.get('frames')
        if frames and len(frames) > 1:
            if now - self.last_frame > 1.5:
                self.frame_idx = (self.frame_idx + 1) % len(frames)
                self.last_frame = now
        # Cycle to next scene
        dwell = dcfg.get('scene_dwell', SCENE_DWELL_TIME)
        if now - self.last_change > dwell:
            self.idx = (self.idx + 1) % len(REALM_SCENES)
            self.frame_idx = 0
            self.last_change = now

    def should_draw(self, engaged):
        return self.enabled and not engaged and len(REALM_SCENES) > 0

    def draw(self, stdscr, y_start, w):
        scene = REALM_SCENES[self.idx % len(REALM_SCENES)]
        color = scene.get('color', C_AVATAR)
        frames = scene.get('frames')
        if frames and len(frames) > 0:
            art = frames[self.frame_idx % len(frames)]
        else:
            art = scene.get('art', [])
        for i, line in enumerate(art):
            row = y_start + i
            try:
                stdscr.addnstr(row, 0, line[:w].center(w)[:w], w,
                    curses.color_pair(color) | curses.A_BOLD)
            except:
                pass


# ─── NPC Mini-Avatars (4 lines, for sidebar) ────
# Role-based: every NPC gets a sprite based on their role from npc_state
# Each entry has 'frames' (3 idle animations), 'fight', 'dead', and activity poses
# Frame format: [head, body, feet, label] — 4 lines, ~5 chars each
ROLE_MINI = {
    'warrior': {
        'frames': [
            ['[>_<]', '-||-', ' ##  ', 'WAR  '],
            ['[>o<]', '=||=', ' ##  ', 'WAR  '],
            ['[>.<]', '-||-', ' ##  ', 'WAR  '],
        ],
        'fight':  ['[!!!]', '=/\\=', ' **  ', 'FIGHT'],
        'dead':   ['[x_x]', ' --  ', ' ##  ', 'R.I.P'],
        'adventuring': ['[>_<]', '-|>-', ' />  ', 'WALK '],
        'conversing':  ['[>o<]', '-||-', ' ##  ', 'CHAT '],
        'pondering':   ['[>.<]', ' ||  ', ' ##  ', 'THINK'],
        'building':    ['[>_<]', '=|#=', ' ##  ', 'BUILD'],
    },
    'rogue': {
        'frames': [
            ['[. .]', '\\||/', ' ..  ', 'ROGUE'],
            ['[o o]', '\\||/', ' ..  ', 'ROGUE'],
            ['[- -]', ' || ', ' ..  ', 'ROGUE'],
        ],
        'fight':  ['[*_*]', '\\**/', ' **  ', 'STAB!'],
        'dead':   ['[. .]', ' ..  ', ' .   ', 'R.I.P'],
        'adventuring': ['[o o]', '\\|>/', ' />  ', 'SNEAK'],
        'conversing':  ['[o o]', '\\||/', ' ..  ', 'CHAT '],
        'pondering':   ['[- -]', ' ||  ', ' ..  ', 'THINK'],
        'building':    ['[. .]', '\\|#/', ' ..  ', 'BUILD'],
    },
    'bard': {
        'frames': [
            ['[*.*]', '/||\\', ' ~~  ', 'BARD '],
            ['[*o*]', '\\||/', ' ~~  ', 'BARD '],
            ['[*_*]', '/||\\', ' ~~  ', 'BARD '],
        ],
        'fight':  ['[*!*]', '/\\/\\', ' ~~  ', 'SING!'],
        'dead':   ['[*_*]', ' |   ', ' .   ', 'R.I.P'],
        'singing':     ['[*o*]', '/||\\', ' ~~  ', 'SONG!'],
        'adventuring': ['[*.*]', '/|>\\', ' />  ', 'WALK '],
        'conversing':  ['[*o*]', '\\||/', ' ~~  ', 'CHAT '],
        'pondering':   ['[*.*]', ' ||  ', ' ~~  ', 'THINK'],
    },
    'merchant': {
        'frames': [
            ['[$_$]', '{||}', ' $$  ', 'MERCH'],
            ['[$o$]', '{||}', ' $$  ', 'MERCH'],
            ['[$ $]', '|{}|', ' $$  ', 'MERCH'],
        ],
        'fight':  ['[$!$]', '{/\\}', ' $$  ', 'DEAL!'],
        'dead':   ['[$_$]', ' |   ', ' .   ', 'R.I.P'],
        'trading':     ['[$o$]', '{><}', ' $$  ', 'TRADE'],
        'adventuring': ['[$_$]', '{|>}', ' />  ', 'WALK '],
        'conversing':  ['[$o$]', '{||}', ' $$  ', 'CHAT '],
        'pondering':   ['[$ $]', ' ||  ', ' $$  ', 'THINK'],
    },
    'priest': {
        'frames': [
            ['[+_+]', '+||+', ' ++  ', 'PRST '],
            ['[+o+]', '+||+', ' ++  ', 'PRST '],
            ['[+.+]', ' || ', ' ++  ', 'PRST '],
        ],
        'fight':  ['[+!+]', '+/\\+', ' **  ', 'SMTE!'],
        'dead':   ['[+_+]', ' |   ', ' .   ', 'R.I.P'],
        'praying':     ['[+.+]', ' /\\  ', ' ++  ', 'PRAY '],
        'reading':     ['[+_+]', '+[]+ ', ' ++  ', 'READ '],
        'adventuring': ['[+_+]', '+|>+', ' />  ', 'WALK '],
        'conversing':  ['[+o+]', '+||+', ' ++  ', 'CHAT '],
        'pondering':   ['[+.+]', ' ||  ', ' ++  ', 'THINK'],
    },
    'priestess': {
        'frames': [
            ['[~.~]', '*||*', ' **  ', 'PRTSS'],
            ['[~o~]', '*||*', ' **  ', 'PRTSS'],
            ['[~*~]', ' || ', ' **  ', 'PRTSS'],
        ],
        'fight':  ['[~!~]', '*/\\*', ' **  ', 'SMTE!'],
        'dead':   ['[~_~]', ' |   ', ' .   ', 'R.I.P'],
        'praying':     ['[~*~]', ' /\\  ', ' **  ', 'PRAY '],
        'reading':     ['[~_~]', '*[]*', ' **  ', 'READ '],
        'adventuring': ['[~.~]', '*|>*', ' />  ', 'WALK '],
        'conversing':  ['[~o~]', '*||*', ' **  ', 'CHAT '],
        'pondering':   ['[~.~]', ' ||  ', ' **  ', 'THINK'],
    },
    'librarian': {
        'frames': [
            ['[=_=]', '|[]|', ' ==  ', 'LIBR '],
            ['[=o=]', '|[]|', ' ==  ', 'LIBR '],
            ['[=.=]', '|  |', ' ==  ', 'LIBR '],
        ],
        'fight':  ['[=!=]', '|/\\|', ' ==  ', 'READ!'],
        'dead':   ['[=_=]', ' |   ', ' .   ', 'R.I.P'],
        'reading':     ['[=.=]', '|[]|', ' ==  ', 'BOOK '],
        'adventuring': ['[=_=]', '|[>|', ' />  ', 'WALK '],
        'conversing':  ['[=o=]', '|[]|', ' ==  ', 'CHAT '],
        'pondering':   ['[=.=]', ' ||  ', ' ==  ', 'THINK'],
    },
    'necromancer': {
        'frames': [
            ['[!_!]', '~||~', ' !!  ', 'NECRO'],
            ['[!o!]', '~||~', ' !!  ', 'NECRO'],
            ['[!.!]', ' || ', ' !!  ', 'NECRO'],
        ],
        'fight':  ['[!!!]', '~/\\~', ' !!  ', 'CURSE'],
        'dead':   ['[!_!]', ' |   ', ' .   ', 'R.I.P'],
        'praying':     ['[!.!]', ' /\\  ', ' !!  ', 'RITE '],
        'adventuring': ['[!_!]', '~|>~', ' />  ', 'WALK '],
        'conversing':  ['[!o!]', '~||~', ' !!  ', 'CHAT '],
        'pondering':   ['[!.!]', ' ||  ', ' !!  ', 'THINK'],
    },
    'ranger': {
        'frames': [
            ['[^_^]', '/||\\', ' /\\  ', 'RANGR'],
            ['[^o^]', '/||\\', ' /\\  ', 'RANGR'],
            ['[^-^]', '\\||/', ' /\\  ', 'RANGR'],
        ],
        'fight':  ['[^!^]', '/\\/\\', ' **  ', 'SHOOT'],
        'dead':   ['[^_^]', ' /|  ', ' .   ', 'R.I.P'],
        'adventuring': ['[^_^]', '/|>\\', ' />  ', 'TRACK'],
        'conversing':  ['[^o^]', '/||\\', ' /\\  ', 'CHAT '],
        'pondering':   ['[^.^]', ' ||  ', ' /\\  ', 'THINK'],
        'building':    ['[^_^]', '/|#\\', ' /\\  ', 'BUILD'],
    },
    'alchemist': {
        'frames': [
            ['[%_%]', '{||}', ' %%  ', 'ALCHM'],
            ['[%o%]', '{||}', ' %%  ', 'ALCHM'],
            ['[%.%]', '|{}|', ' %%  ', 'ALCHM'],
        ],
        'fight':  ['[%!%]', '{/\\}', ' **  ', 'BREW!'],
        'dead':   ['[%_%]', ' |   ', ' .   ', 'R.I.P'],
        'trading':     ['[%o%]', '{><}', ' %%  ', 'TRADE'],
        'adventuring': ['[%_%]', '{|>}', ' />  ', 'WALK '],
        'conversing':  ['[%o%]', '{||}', ' %%  ', 'CHAT '],
        'pondering':   ['[%.%]', ' ||  ', ' %%  ', 'THINK'],
    },
    'oracle': {
        'frames': [
            ['[@_@]', '*||*', ' @@  ', 'ORACL'],
            ['[@o@]', '*||*', ' @@  ', 'ORACL'],
            ['[@.@]', ' || ', ' @@  ', 'ORACL'],
        ],
        'fight':  ['[@!@]', '*||*', ' @@  ', 'SEE! '],
        'dead':   ['[@_@]', ' |   ', ' .   ', 'R.I.P'],
        'praying':     ['[@.@]', ' /\\  ', ' @@  ', 'PRAY '],
        'reading':     ['[@_@]', '*[]*', ' @@  ', 'READ '],
        'adventuring': ['[@_@]', '*|>*', ' />  ', 'WALK '],
        'conversing':  ['[@o@]', '*||*', ' @@  ', 'CHAT '],
        'pondering':   ['[@.@]', ' ||  ', ' @@  ', 'THINK'],
    },
    'artificer': {
        'frames': [
            ['[#_#]', '=||=', ' ##  ', 'ARTFR'],
            ['[#o#]', '=||=', ' ##  ', 'ARTFR'],
            ['[#.#]', ' || ', ' ##  ', 'ARTFR'],
        ],
        'fight':  ['[#!#]', '=/\\=', ' **  ', 'FORGE'],
        'dead':   ['[#_#]', ' |   ', ' .   ', 'R.I.P'],
        'building':    ['[#_#]', '=|#=', ' ##  ', 'BUILD'],
        'trading':     ['[#o#]', '={>=', ' ##  ', 'TRADE'],
        'adventuring': ['[#_#]', '=|>=', ' />  ', 'WALK '],
        'conversing':  ['[#o#]', '=||=', ' ##  ', 'CHAT '],
        'pondering':   ['[#.#]', ' ||  ', ' ##  ', 'THINK'],
    },
    'ghost': {
        'frames': [
            ['[o_o]', ' || ', ' ~~  ', 'GHOST'],
            ['[o o]', ' || ', ' ~~  ', 'GHOST'],
            ['[. .]', ' || ', ' ~~  ', 'GHOST'],
        ],
        'fight':  ['[!!!]', ' /\\  ', ' ~~  ', 'HAUNT'],
        'dead':   ['[x x]', ' ..  ', ' ~   ', 'GONE '],
        'adventuring': ['[o_o]', ' |>  ', ' />  ', 'DRIFT'],
        'conversing':  ['[o o]', ' ||  ', ' ~~  ', 'WHISP'],
        'pondering':   ['[. .]', ' ||  ', ' ~~  ', 'THINK'],
    },
}

# Action labels for LCD display (short, 5 chars max)
NPC_ACTION_LABELS = {
    'idle': ' ... ', 'fighting': ' ⚔️  ', 'resting': ' zzZ ',
    'writing_song': ' ♪✍  ', 'performing': ' ♫♪  ', 'storytelling': ' ♫..  ',
    'trade': ' $>  ', 'appraise': ' $?  ', 'praying': ' †..  ',
    'healing': ' +HP ', 'thinking': ' …   ', 'wandering': ' →..  ',
    'divine': ' 🔮  ', 'prophecy': ' ✧!  ', 'cataloging': ' ≡..  ',
    'researching': ' ??  ', 'haunting': ' 👻  ', 'wailing': ' ~!~  ',
}

# Rotation interval for NPC sidebar (seconds per group of 4)
NPC_ROTATE_INTERVAL = 8

# Map RPG actions → pose keys
ACTION_TO_POSE = {
    'fighting': 'fight', 'FIGHT': 'fight',
    'BUILD': 'building', 'building': 'building',
    'WANDER': 'adventuring', 'wandering': 'adventuring',
    'SOCIALIZE': 'conversing', 'ROMANCE': 'conversing', 'conversing': 'conversing',
    'PRAY': 'praying', 'HEAL': 'praying', 'praying': 'praying', 'healing': 'praying',
    'WRITE_BLOG': 'reading', 'PUBLISH': 'reading', 'reading': 'reading',
    'cataloging': 'reading', 'researching': 'reading',
    'SING': 'singing', 'PERFORM': 'singing', 'singing': 'singing',
    'performing': 'singing', 'writing_song': 'singing',
    'TRADE': 'trading', 'trading': 'trading', 'appraise': 'trading',
    'OBSERVE': 'pondering', 'PONDER': 'pondering', 'pondering': 'pondering',
    'thinking': 'pondering', 'divine': 'praying', 'prophecy': 'praying',
    'existential_crisis': 'pondering', 'existential': 'pondering',
}

def _get_npc_mini_frame(nname, npc_data, now):
    """Get the current animation frame for an NPC based on role from npc_state"""
    role = npc_data.get('role', 'warrior') if isinstance(npc_data, dict) else 'warrior'
    entry = ROLE_MINI.get(role, ROLE_MINI.get('warrior'))
    if not entry:
        return None
    if not npc_data.get('alive', True):
        frame = list(entry.get('dead', entry['frames'][0]))
    elif npc_data.get('action') == 'fighting':
        frame = list(entry.get('fight', entry['frames'][0]))
    else:
        action = npc_data.get('action', 'idle')
        pose_key = ACTION_TO_POSE.get(action)
        if pose_key and pose_key in entry:
            frame = list(entry[pose_key])
        else:
            frames = entry['frames']
            idx = int(now * 0.5) % len(frames)
            frame = list(frames[idx])
    # Replace the label line (4th) with truncated NPC name
    if len(frame) >= 4 and nname:
        frame[3] = nname[:5].ljust(5)
    return frame

def read_npc_state():
    """Read NPC state published by zealot_rpg.py"""
    try:
        return json.loads(NPC_STATE.read_text())
    except:
        return {}

def read_battle_state():
    """Read active battle state published by zealot_rpg.py"""
    try:
        return json.loads(BATTLE_STATE.read_text())
    except:
        return {}

def cga_color(x, t):
    """Alternate between header colors for CGA effect"""
    v = (x + int(t * 4)) % 6
    return C_HEADER if v < 3 else C_HEADER2

# ─── Memory + IRC Reader ────────────────────────
# ─── Display Config from soul.json ──────────────
DISPLAY_DEFAULTS = {
    'ticker_speed': 10,    # chars/sec for info ticker
    'banner_speed': 8,     # chars/sec for banner row
    'header_speed': 6,     # header block animation multiplier
    'avatar_interval': 30, # seconds between avatar rotation
    'eye_interval': 5,     # seconds between eye changes
    'color_flip': 6,       # avatar color alternation period
    'loop_tick_ms': 200,   # curses getch timeout
    'spinner_speed': 2,    # spinner animation multiplier
    'ticker_direction': 'ltr',   # ltr, rtl, pingpong, stopped
    'banner_direction': 'ltr',
    'header_direction': 'ltr',
    'show_timestamps': True,     # show timestamps in IRC lines
    'show_channels': True,       # show [ZP]/[RPG]/[ZH] channel tags
    'force_theme': 'auto',
    'scene_enabled': True,
    'scene_dwell': 120,
    'palette_border': 4,
    'palette_accent': 6,
    'color_text': 'auto',        # IRC message text color override
    'color_action': 'auto',      # action/system text color override
    'color_header': 'auto',      # CGA header block color override
    'color_header2': 'auto',     # CGA header accent color override
    'color_nick': 'auto',        # IRC nick color override
}

def calc_scroll_offset(time_val, speed, text_len, direction='ltr'):
    """Calculate scroll offset based on direction mode."""
    if text_len <= 0:
        return 0
    if direction == 'stopped':
        return 0
    raw = int(time_val * speed)
    if direction == 'rtl':
        return (-raw) % text_len
    if direction == 'pingpong':
        cycle = text_len * 2
        pos = raw % cycle if cycle > 0 else 0
        return pos if pos < text_len else cycle - pos - 1
    # default ltr
    return raw % text_len

def read_display_config():
    try:
        soul = json.loads(SOUL_FILE.read_text())
        ds = soul.get('display', {})
        cfg = {k: ds.get(k, v) for k, v in DISPLAY_DEFAULTS.items()}
        # Also pass through any extra keys from soul.json display section
        for k, v in ds.items():
            if k not in cfg:
                cfg[k] = v
        return cfg
    except:
        return dict(DISPLAY_DEFAULTS)

def read_mem():
    try:
        return json.loads(MEM_FILE.read_text())
    except:
        return {'mood': 'offline', 'plot_stage': 0, 'tripping': False,
                'splitting': False, 'ego_death': False, 'substance': None,
                'ollama_ok': False, 'thought_of_day': '', 'last_dream': ''}

def read_irc_tail(n=30):
    """Read last n lines from all 3 IRC channels, merged with channel tags"""
    lines = []
    sources = [(IRC_LOG, '[ZP]'), (RPG_LOG, '[RPG]'), (HANGS_LOG, '[ZH]')]
    for logfile, tag in sources:
        try:
            raw = logfile.read_text().strip().split('\n')
            for l in raw[-n:]:
                lines.append(f'{tag} {l}')
        except:
            pass
    if not lines:
        return ['-- Waiting for IRC...']
    return lines[-n:]

# ─── Word Wrap for IRC ─────────────────────────
def _is_action_line(raw):
    """Check if line is IRC ACTION format (* Nick does something)"""
    s = raw
    if s.startswith('[') and '] ' in s:
        s = s.split('] ', 1)[1]
    parts = s.split(' ', 1)
    if len(parts) >= 2 and (parts[0].endswith('a') or parts[0].endswith('p')):
        s = parts[1]
    return s.startswith('* ')

def wrap_irc_lines(raw_lines, width):
    """Word-wrap IRC lines to fit width."""
    wrapped = []
    for raw in raw_lines:
        lt = 'sys'
        if '<Zealot>' in raw or '<Zealot_' in raw:
            lt = 'zealot'
        elif '<' in raw and '>' in raw:
            lt = 'nick'
        elif _is_action_line(raw):
            lt = 'action'

        if len(raw) <= width:
            wrapped.append((raw, lt))
        else:
            lines = textwrap.wrap(raw, width=width, subsequent_indent=' ',
                                  break_long_words=True, break_on_hyphens=False)
            if not lines:
                wrapped.append((raw[:width], lt))
            else:
                for j, wl in enumerate(lines):
                    wrapped.append((wl, lt))
    return wrapped

# ─── Main Display Loop ─────────────────────────
def main(stdscr):
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    _init_rpg_palette()

    # Initial config + theme
    dcfg = read_display_config()
    theme_name = apply_theme(force=dcfg.get('force_theme', 'auto'), color_overrides=dcfg)
    theme_variant = 0
    last_theme_mood = ''
    last_theme_hour = -1
    last_variant_time = time.time()

    stdscr.nodelay(True)
    stdscr.timeout(200)

    input_buf = ''
    frame = 0
    npc_cache = {}
    npc_read_t = 0
    battle_cache = {}
    mood_flash = MoodFlash()
    existential_flash = ExistentialFlash()
    battle_flash = BattleFlash()
    scene_cycler = SceneCycler()
    last_mood = ''
    dcfg = read_display_config()
    dcfg_read_t = 0

    while True:
        try:
            h, w = stdscr.getmaxyx()
            # LCD is source of truth — clamp to hardware dimensions
            dw = min(w, LCD_COLS)
            dh = min(h, LCD_ROWS)
            stdscr.erase()
            now = time.time()
            t = now * 2.0
            cur_hour = datetime.now().hour

            # ─── Reload display config + NPC state (every 10s)
            if now - npc_read_t > 10:
                npc_cache = read_npc_state()
                battle_cache = read_battle_state()
                npc_read_t = now
                # Rebuild NPC IRC colors from live role data
                _rebuild_npc_irc_colors(npc_cache)
                # Check for battle round changes → trigger battle flash
                battle_flash.check_battle(battle_cache)
                # Check for existential crisis in any NPC
                for npc_name, npc_data in npc_cache.items():
                    if npc_name.startswith('_'):
                        continue
                    if isinstance(npc_data, dict) and npc_data.get('action') == 'existential_crisis':
                        existential_flash.trigger(npc_name)
            if now - dcfg_read_t > 10:
                dcfg = read_display_config()
                stdscr.timeout(dcfg['loop_tick_ms'])
                dcfg_read_t = now

            mem = read_mem()
            is_trip = mem.get('tripping', False)
            is_split = mem.get('splitting', False)
            is_death = mem.get('ego_death', False)
            mood = mem.get('mood', '???')
            sub = mem.get('substance', '')
            thought = mem.get('thought_of_day', '')
            dream = mem.get('last_dream', '')
            topic = mem.get('topic', '')

            # ─── Theme cycling ───────────────────
            # Re-theme on mood change or every 4-hour block
            mood_changed = mood != last_theme_mood
            hour_changed = cur_hour // 4 != last_theme_hour // 4 if last_theme_hour >= 0 else True
            force_theme = dcfg.get('force_theme', 'auto')
            if mood_changed or hour_changed:
                if mood_changed:
                    theme_variant = 0
                theme_name = apply_theme(mood, theme_variant, force=force_theme, color_overrides=dcfg)
                last_theme_mood = mood
                last_theme_hour = cur_hour
                mood_flash.trigger(theme_name.split()[0])
            # Cycle variant within mood group every 30 min
            if now - last_variant_time > 1800:
                theme_variant += 1
                theme_name = apply_theme(mood, theme_variant, force=force_theme, color_overrides=dcfg)
                last_variant_time = now

            # ─── Trigger mood flash on change ───
            if mood != last_mood and last_mood:
                mood_flash.trigger(mood)
            last_mood = mood

            # ─── Row 0: CGA Block Header ───────
            offset = calc_scroll_offset(t, dcfg['header_speed'], len(CGA_BLOCKS), dcfg.get('header_direction', 'ltr'))
            for cx in range(dw):
                ci = (cx + offset) % len(CGA_BLOCKS)
                ch = CGA_BLOCKS[ci]
                cp = cga_color(cx, t)
                if is_trip:
                    cp = C_TRIP
                try:
                    stdscr.addch(0, cx, ch,
                        curses.color_pair(cp) | curses.A_BOLD)
                except:
                    pass

            # Overlay title centered (include theme name)
            if is_trip:
                title = f'*~* ZEALOT *~* [{sub or "trip"}]'
            elif is_death:
                title = '??? WHO AM I ???'
            elif is_split:
                title = '< ZEALOT|SPLIT >'
            else:
                title = '\u2591\u2592\u2593 ZEALOT \u2593\u2592\u2591'
            tx = max(0, (dw - len(title)) // 2)
            try:
                stdscr.addnstr(0, tx, title, dw - tx,
                    curses.color_pair(C_HEADER) | curses.A_BOLD | curses.A_REVERSE)
            except:
                pass

            # ─── Row 1: Scrolling Info Ticker ───
            # Build dynamic ticker with world events + NPC activity
            npc_bits = ''
            for nname, ndata in npc_cache.items():
                if nname == '_rpg':
                    continue
                if ndata.get('connected'):
                    icon = '\u2665' if ndata.get('alive') else '\u2620'
                    npc_bits += f'  \u25b8 {nname}:{icon}L{ndata.get("level",0)}'

            # Pull world context from logs/events
            world_bits = ''
            try:
                rpg_tail = RPG_LOG.read_text().strip().split('\n')[-5:]
                for line in rpg_tail:
                    # Extract interesting events
                    for keyword in ['PVP', 'founded', 'built', 'battle', 'died', 'born', 'married', 'song', 'village']:
                        if keyword.lower() in line.lower():
                            # Trim timestamp and clean up
                            parts = line.split('] ', 1)
                            if len(parts) > 1:
                                world_bits += f'  \u2605 {parts[1][:50]}'
                            break
            except:
                pass

            scroll_text = (
                IRC_SCROLL_TEXT
                + f'  \u25b8 mood: {mood}'
                + f'  \u25b8 theme: {theme_name}'
                + npc_bits
                + world_bits + '    '
            )
            scroll_offset = calc_scroll_offset(now, dcfg['ticker_speed'], len(scroll_text), dcfg.get('ticker_direction', 'ltr'))
            for sx in range(dw):
                ci = (scroll_offset + sx) % len(scroll_text)
                ch = scroll_text[ci]
                cp = cga_color(sx, t + 0.5)
                if is_trip:
                    cp = C_TRIP
                try:
                    stdscr.addch(1, sx, ch,
                        curses.color_pair(cp) | curses.A_BOLD)
                except:
                    pass

            # ─── Row 2-9: ASCII Avatar + NPC sidebars ─
            in_battle = battle_cache.get('active', False)
            boss_art = []
            if in_battle:
                m = battle_cache.get('monster', {})
                boss_art = m.get('ascii_art', [])

            if in_battle and boss_art:
                # ── Boss Battle Mode: show boss art instead of Zealot ──
                eye = EYES[int(now / dcfg['eye_interval']) % len(EYES)]
                boss_color = C_BOSS if int(now * 3) % 2 == 0 else C_BOSS2
                av_width = max(len(line) for line in boss_art) if boss_art else 18

                # Party members as sidebars
                party = battle_cache.get('party', {})
                party_names = list(party.keys())
                left_party = party_names[:2]
                right_party = party_names[2:4]
                npc_col_w = 7

                total_content = av_width
                if left_party:
                    total_content += npc_col_w
                if right_party:
                    total_content += npc_col_w
                left_start = max(0, (dw - total_content) // 2)
                avatar_x = left_start + (npc_col_w if left_party else 0)

                # Draw left party members
                npc_colors = [C_NPC1, C_NPC2, C_NPC3, C_NPC4]
                for ni, pname in enumerate(left_party):
                    pdata = party.get(pname, {})
                    mini = _get_npc_mini_frame(pname, pdata, now)
                    nc = npc_colors[ni % len(npc_colors)]
                    if mini:
                        for mi, mline in enumerate(mini):
                            row = 4 + mi
                            if row < dh:
                                try:
                                    stdscr.addnstr(row, left_start, mline[:npc_col_w], npc_col_w,
                                        curses.color_pair(nc) | curses.A_BOLD)
                                except:
                                    pass
                    # HP bar
                    hp = pdata.get('hp', 0)
                    mhp = pdata.get('max_hp', 1)
                    hp_s = f'{hp}/{mhp}'
                    if 8 < dh:
                        try:
                            stdscr.addnstr(8, left_start, hp_s[:npc_col_w], npc_col_w,
                                curses.color_pair(nc) | curses.A_DIM)
                        except:
                            pass

                # Draw boss ASCII art
                for i, line in enumerate(boss_art):
                    rendered = line.replace('{eye}', eye)
                    row = 2 + i
                    if row < dh:
                        try:
                            stdscr.addnstr(row, avatar_x, rendered, min(len(rendered), dw - avatar_x),
                                curses.color_pair(boss_color) | curses.A_BOLD)
                        except:
                            pass

                # Draw right party members
                right_x = avatar_x + av_width
                for ni, pname in enumerate(right_party):
                    pdata = party.get(pname, {})
                    mini = _get_npc_mini_frame(pname, pdata, now)
                    nc = npc_colors[(ni + 2) % len(npc_colors)]
                    if mini:
                        for mi, mline in enumerate(mini):
                            row = 4 + mi
                            if row < dh and right_x < dw:
                                try:
                                    stdscr.addnstr(row, right_x, mline[:npc_col_w], min(npc_col_w, dw - right_x),
                                        curses.color_pair(nc) | curses.A_BOLD)
                                except:
                                    pass
                    if 8 < dh and right_x < dw:
                        hp = pdata.get('hp', 0)
                        mhp = pdata.get('max_hp', 1)
                        hp_s = f'{hp}/{mhp}'
                        try:
                            stdscr.addnstr(8, right_x, hp_s[:npc_col_w], min(npc_col_w, dw - right_x),
                                curses.color_pair(nc) | curses.A_DIM)
                        except:
                            pass

                # Boss HP bar on row after art (row 10 area, or row 2+len)
                mname = m.get('name', 'BOSS')
                mhp = m.get('hp', 0)
                mmax = m.get('max_hp', 1)
                hp_pct = max(0, min(1, mhp / max(1, mmax)))
                bar_w = min(av_width, dw - avatar_x)
                filled = int(hp_pct * (bar_w - 2))
                hp_bar = '[' + '\u2593' * filled + '\u2591' * (bar_w - 2 - filled) + ']'
                pct_str = f'{int(hp_pct * 100)}%'
                boss_label = f'{mname[:bar_w - len(pct_str) - 1]} {pct_str}'.center(bar_w)
                hp_row = 2 + len(boss_art)
                if hp_row < dh:
                    try:
                        stdscr.addnstr(hp_row, avatar_x, boss_label, bar_w,
                            curses.color_pair(boss_color) | curses.A_BOLD)
                    except:
                        pass
                if hp_row + 1 < dh:
                    try:
                        stdscr.addnstr(hp_row + 1, avatar_x, hp_bar, bar_w,
                            curses.color_pair(C_BOSS if hp_pct > 0.25 else C_BOSS2) | curses.A_BOLD)
                    except:
                        pass

            else:
                # ── Normal Mode: Zealot avatar + NPC sidebars ──
                # Scene cycler: full-width realm art when no engagement
                engaged = any(
                    isinstance(d, dict) and d.get('action') in ('fighting', 'conversing')
                    for n, d in npc_cache.items() if not n.startswith('_')
                )
                scene_cycler.update(dcfg, engaged)
                if scene_cycler.should_draw(engaged):
                    scene_cycler.draw(stdscr, 2, dw)
                else:
                    # Standard avatar + NPC sidebar rendering
                    if is_trip:
                        av_frames = AVATARS_TRIP
                        eye_set = EYES_TRIP
                    elif is_split:
                        av_frames = AVATARS_SPLIT
                        eye_set = EYES
                    elif is_death:
                        av_frames = AVATARS_DEATH
                        eye_set = ['X X', 'x x', '? ?']
                    else:
                        av_frames = AVATARS_NORMAL
                        eye_set = EYES

                    # Avatar selection: mood-based, slow rotation for unknowns
                    av_idx = MOOD_AVATAR.get(mood, int(now / dcfg['avatar_interval']) % len(av_frames))
                    av = av_frames[av_idx % len(av_frames)]
                    eye = eye_set[int(now / dcfg['eye_interval']) % len(eye_set)]
                    spin = SPINS[int(now * dcfg['spinner_speed']) % len(SPINS)]

                    av_color = C_TRIP if is_trip else (
                        C_AVATAR if int(now) % dcfg['color_flip'] < dcfg['color_flip'] // 2 else C_AVATAR2)

                    # Calculate NPC sidebar columns
                    active_npcs = [n for n, d in npc_cache.items()
                                   if n != '_rpg' and d.get('connected')]
                    # Sort so last-speaker NPC appears first
                    rpg_meta = npc_cache.get('_rpg', {})
                    last_spoke = rpg_meta.get('last_spoke', '')
                    if last_spoke and last_spoke in active_npcs:
                        active_npcs.remove(last_spoke)
                        active_npcs.insert(0, last_spoke)
                    av_width = max(len(line) for line in av) if av else 18
                    # Rotate which 4 NPCs are shown every NPC_ROTATE_INTERVAL seconds
                    n_active = len(active_npcs)
                    if n_active > 4:
                        rot = int(now / NPC_ROTATE_INTERVAL) % n_active
                        rotated = [active_npcs[(rot + i) % n_active] for i in range(min(4, n_active))]
                    else:
                        rotated = active_npcs[:4]
                    left_npcs = rotated[:2]
                    right_npcs = rotated[2:4]
                    npc_col_w = 7  # width of each mini-avatar column

                    # Compute main avatar center position
                    total_content = av_width
                    if left_npcs:
                        total_content += npc_col_w
                    if right_npcs:
                        total_content += npc_col_w
                    left_start = max(0, (dw - total_content) // 2)
                    avatar_x = left_start + (npc_col_w if left_npcs else 0)

                    # Draw left NPC mini-avatars
                    npc_colors = [C_NPC1, C_NPC2, C_NPC3, C_NPC4]
                    for ni, nname in enumerate(left_npcs):
                        npc_data = npc_cache.get(nname, {})
                        mini = _get_npc_mini_frame(nname, npc_data, now)
                        if not mini:
                            continue
                        col = left_start
                        nc = npc_colors[ni % len(npc_colors)]
                        # Draw mini avatar centered in rows 4-7 (middle of avatar area)
                        for mi, mline in enumerate(mini):
                            row = 4 + mi
                            if row < dh:
                                try:
                                    stdscr.addnstr(row, col, mline[:npc_col_w], npc_col_w,
                                        curses.color_pair(nc) | curses.A_BOLD)
                                except:
                                    pass
                        # Show HP below
                        hp_str = npc_data.get('hp', '?')
                        if 8 < dh:
                            try:
                                stdscr.addnstr(8, col, str(hp_str)[:npc_col_w], npc_col_w,
                                    curses.color_pair(nc) | curses.A_DIM)
                            except:
                                pass

                    # Draw main avatar
                    for i, line in enumerate(av):
                        rendered = line.replace('{eye}', eye).replace('{spin}', spin)
                        row = 2 + i
                        if row < dh:
                            try:
                                stdscr.addnstr(row, avatar_x, rendered, min(len(rendered), dw - avatar_x),
                                    curses.color_pair(av_color) | curses.A_BOLD)
                            except:
                                pass

                    # Draw right NPC mini-avatars
                    right_x = avatar_x + av_width
                    for ni, nname in enumerate(right_npcs):
                        npc_data = npc_cache.get(nname, {})
                        mini = _get_npc_mini_frame(nname, npc_data, now)
                        if not mini:
                            continue
                        nc = npc_colors[(ni + 2) % len(npc_colors)]
                        for mi, mline in enumerate(mini):
                            row = 4 + mi
                            if row < dh and right_x < dw:
                                try:
                                    stdscr.addnstr(row, right_x, mline[:npc_col_w], min(npc_col_w, dw - right_x),
                                        curses.color_pair(nc) | curses.A_BOLD)
                                except:
                                    pass
                        if 8 < dh and right_x < dw:
                            hp_str = npc_data.get('hp', '?')
                            try:
                                stdscr.addnstr(8, right_x, str(hp_str)[:npc_col_w], min(npc_col_w, dw - right_x),
                                    curses.color_pair(nc) | curses.A_DIM)
                            except:
                                pass

            # ─── Battle Flash Overlay (pyfiglet action words) ───
            if battle_flash.active():
                battle_flash.draw(stdscr, 3, dw)
            # ─── Existential Crisis Flash (takes priority over mood flash) ───
            elif existential_flash.active():
                existential_flash.draw(stdscr, 3, dw)
            # ─── Mood Flash Overlay ─────────────
            # When mood/theme changes, briefly show figlet art over avatar area
            elif mood_flash.active():
                mood_flash.draw(stdscr, 3, dw)

            # ─── Row 10: Scrolling Banner ───────
            # Build banner text from all info sources
            banner_parts = []
            if topic:
                banner_parts.append(f'\u2605 {topic}')
            banner_parts.append(f'\u266b {mood}')
            if thought:
                banner_parts.append(f'\u2731 {thought}')
            if dream:
                banner_parts.append(f'\u263e dream: {dream}')
            banner_parts.append(f'\u2302 {NETWORK_HOST}')
            # Add NPC location info
            for nname, ndata in npc_cache.items():
                if ndata.get('connected') and ndata.get('alive'):
                    banner_parts.append(f'{nname}@{ndata.get("location","?")}')
            # Add battle info
            if in_battle:
                m = battle_cache.get('monster', {})
                mname = m.get('name', '?')
                mhp = m.get('hp', 0)
                mmax = m.get('max_hp', 1)
                turn = battle_cache.get('turn', 0)
                party_ct = len(battle_cache.get('party', {}))
                banner_parts.insert(0, f'\u2694 BATTLE: {mname} HP:{mhp}/{mmax} T{turn} x{party_ct}')
            banner_text = '  \u25b8  '.join(banner_parts) + '     '
            if 10 < dh:
                b_offset = calc_scroll_offset(now, dcfg['banner_speed'], max(1, len(banner_text)), dcfg.get('banner_direction', 'ltr'))
                for bx in range(dw):
                    bi = (b_offset + bx) % len(banner_text)
                    bch = banner_text[bi]
                    bcp = C_MOOD if bx % 2 == 0 else C_INFO
                    if is_trip:
                        bcp = C_TRIP
                    try:
                        stdscr.addch(10, bx, bch,
                            curses.color_pair(bcp) | curses.A_BOLD)
                    except:
                        pass

            # ─── Row 11: CGA Separator ──────────
            if 11 < dh:
                label = '--- EVENTS ---'
                pad_total = dw - len(label)
                pad_left = pad_total // 2
                pad_right = pad_total - pad_left
                fill = '\u2500\u2550'
                lf = (fill * ((pad_left // len(fill)) + 1))[:pad_left]
                rf = (fill * ((pad_right // len(fill)) + 1))[:pad_right]
                sep = (lf + label + rf)[:dw]
                try:
                    stdscr.addnstr(11, 0, sep, dw,
                        curses.color_pair(C_SEP) | curses.A_DIM)
                except:
                    pass

            # ─── Row 12 to dh-2: IRC (bottom-anchored) ─
            irc_start = 12
            irc_area = dh - 1 - irc_start
            if irc_area > 0:
                raw_lines = read_irc_tail(irc_area + 15)
                # Apply display toggles
                if not dcfg.get('show_channels', True):
                    raw_lines = [l.split('] ', 1)[-1] if l.startswith('[') else l for l in raw_lines]
                if not dcfg.get('show_timestamps', True):
                    filtered = []
                    for l in raw_lines:
                        parts = l.split(' ', 1)
                        if len(parts) >= 2 and len(parts[0]) <= 7 and (parts[0].endswith('a') or parts[0].endswith('p')):
                            filtered.append(parts[1])
                        else:
                            filtered.append(l)
                    raw_lines = filtered
                wrapped = wrap_irc_lines(raw_lines, dw)
                display_lines = wrapped[-irc_area:] if len(wrapped) > irc_area else wrapped

                # Bottom-anchor: draw lines from the bottom of the IRC area up
                empty_top = irc_area - len(display_lines)
                for i, (line, lt) in enumerate(display_lines):
                    row = irc_start + empty_top + i
                    if row >= dh - 1:
                        break
                    draw_irc_line(stdscr, row, line, lt, dw)

            # ─── Last Row: Input ────────────────
            prompt_row = dh - 1
            prompt = f'\u25b8 {input_buf}'
            try:
                stdscr.addnstr(prompt_row, 0, prompt[:dw - 1], dw - 1,
                    curses.color_pair(C_INPUT) | curses.A_BOLD)
            except:
                pass

            stdscr.refresh()
            frame += 1

            # ─── Handle Input ───────────────────
            try:
                ch = stdscr.getch()
                if ch == -1:
                    pass
                elif ch in (10, 13):
                    if input_buf.strip():
                        send_to_zealot(input_buf.strip())
                        input_buf = ''
                elif ch == 27:
                    input_buf = ''
                elif ch in (curses.KEY_BACKSPACE, 127, 8):
                    input_buf = input_buf[:-1]
                elif 32 <= ch < 127:
                    if len(input_buf) < dw - 4:
                        input_buf += chr(ch)
            except:
                pass

        except KeyboardInterrupt:
            break
        except Exception as e:
            import traceback
            with open('/tmp/zealot_display_err.log', 'a') as f:
                f.write(traceback.format_exc() + '\n')
            time.sleep(0.5)


def draw_irc_line(stdscr, row, line, lt, dw):
    """Draw a single IRC line with CGA-colored elements"""
    try:
        # System lines (joins/parts): entire line dim
        if lt == 'sys':
            stdscr.addnstr(row, 0, line[:dw], dw,
                curses.color_pair(C_IRC_SYS) | curses.A_DIM)
            return

        col = 0
        rest = line

        # ── Channel tag: [ZP] [RPG] [ZH] ──
        if rest.startswith('['):
            tag_end = rest.find('] ')
            if tag_end > 0:
                tag_str = rest[:tag_end + 1]
                rest = rest[tag_end + 2:]
                try:
                    tlen = min(len(tag_str), dw - col)
                    if tlen > 0:
                        stdscr.addnstr(row, col, tag_str, tlen,
                            curses.color_pair(C_INFO))
                    col += len(tag_str)
                    if col < dw:
                        stdscr.addch(row, col, ' ',
                            curses.color_pair(C_INFO))
                        col += 1
                except:
                    pass

        # ── Timestamp: token ending in 'a' or 'p' ──
        parts = rest.split(' ', 1)
        ts_part = ''
        if len(parts) >= 2 and (parts[0].endswith('a') or parts[0].endswith('p')):
            ts_part = parts[0]
            rest = parts[1]

        if ts_part:
            try:
                tlen = min(len(ts_part), dw - col)
                if tlen > 0:
                    stdscr.addnstr(row, col, ts_part, tlen,
                        curses.color_pair(C_IRC_TS))
                col += len(ts_part)
                if col < dw:
                    stdscr.addch(row, col, ' ', curses.color_pair(C_IRC_TS))
                    col += 1
            except:
                pass

        # ── Nick color determination ──
        nick_color = C_IRC_NICK
        if lt == 'zealot':
            nick_color = C_IRC_ZEALOT
        if 'SuperEgo' in line:
            nick_color = C_IRC_SE
        if 'Zealot_ID' in line:
            nick_color = C_IRC_ID
        for npc_nick, npc_color in NPC_IRC_COLORS.items():
            if f'<{npc_nick}>' in line or f'* {npc_nick}' in line:
                nick_color = npc_color
                break

        # ── Normal message: <Nick> message ──
        if rest.startswith('<'):
            end = rest.find('>')
            if end > 0:
                nick_str = rest[:end + 1]
                msg_str = rest[end + 1:].lstrip()
                try:
                    nlen = min(len(nick_str), dw - col)
                    if nlen > 0:
                        stdscr.addnstr(row, col, nick_str, nlen,
                            curses.color_pair(nick_color) | curses.A_BOLD)
                    col += len(nick_str) + 1
                except:
                    pass
                if col < dw:
                    try:
                        stdscr.addnstr(row, col, msg_str, dw - col,
                            curses.color_pair(C_IRC_MSG))
                    except:
                        pass
                return

        # ── ACTION line: * Nick does something ──
        elif rest.startswith('* '):
            action_rest = rest[2:]
            action_parts = action_rest.split(' ', 1)
            action_nick = action_parts[0] if action_parts else ''
            action_msg = action_parts[1] if len(action_parts) > 1 else ''
            try:
                # "* " prefix in nick color
                if col + 2 <= dw:
                    stdscr.addnstr(row, col, '* ', min(2, dw - col),
                        curses.color_pair(nick_color))
                col += 2
                # Nick highlighted BOLD
                if col < dw and action_nick:
                    nlen = min(len(action_nick), dw - col)
                    stdscr.addnstr(row, col, action_nick, nlen,
                        curses.color_pair(nick_color) | curses.A_BOLD)
                    col += len(action_nick)
                # Action text in normal message color
                if col < dw and action_msg:
                    stdscr.addch(row, col, ' ',
                        curses.color_pair(C_IRC_MSG))
                    col += 1
                    if col < dw:
                        stdscr.addnstr(row, col, action_msg, dw - col,
                            curses.color_pair(C_IRC_MSG))
            except:
                pass
            return

        # ── Fallback ──
        try:
            rlen = dw - col
            if rlen > 0:
                stdscr.addnstr(row, col, rest[:rlen], rlen,
                    curses.color_pair(C_IRC_MSG))
        except:
            pass
    except:
        try:
            stdscr.addnstr(row, 0, line[:dw], dw,
                curses.color_pair(C_IRC_MSG))
        except:
            pass


def send_to_zealot(msg):
    h = datetime.now().hour
    m = datetime.now().minute
    suffix = 'a' if h < 12 else 'p'
    h12 = h % 12 or 12
    ts = f'{h12}:{m:02d}{suffix}'
    try:
        with open(IRC_LOG, 'a') as f:
            f.write(f'{ts} <aday> {msg}\n')
    except:
        pass
    try:
        CHAT_FIFO.parent.mkdir(parents=True, exist_ok=True)
        CHAT_FIFO.write_text(msg)
    except:
        pass


if __name__ == '__main__':
    curses.wrapper(main)
