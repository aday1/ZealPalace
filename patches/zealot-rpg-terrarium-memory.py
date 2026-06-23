#!/usr/bin/env python3
"""IRC peer memory -> journal, player history, per-NPC soul.md, lore.md growth."""
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "zealot_rpg.py"
text = PATH.read_text(encoding="utf-8")
changed = []

MARKER = "LORE_MD_FILE = RPG_DIR / 'lore.md'"
if MARKER not in text:
    anchor = "LORE_FILE = RPG_DIR / 'lore.jsonl'"
    insert = """
LORE_MD_FILE = RPG_DIR / 'lore.md'
NPC_SOUL_DIR = NPC_DIR / 'souls'
"""
    if anchor in text:
        text = text.replace(anchor, anchor + insert, 1)
        changed.append("paths")

MEMORY_BLOCK = '''
def append_player_history(nick, entry):
    """Append IRC/RPG moment to player history (feeds diary nudge)."""
    p = load_player(nick)
    if not p:
        return
    stamp = datetime.now().strftime('%H:%M')
    hist = p.setdefault('history', [])
    hist.append(f'{stamp} {str(entry)[:200]}')
    p['history'] = hist[-40:]
    save_player(p)


def append_lore_md(text, topic='unknown'):
    """Grow lore.jsonl and human-readable lore.md together."""
    snippet = str(text or '').strip()
    if not snippet:
        return
    append_lore(snippet, topic=topic)
    RPG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y-%m-%d %H:%M')
    try:
        with open(LORE_MD_FILE, 'a', encoding='utf-8') as f:
            f.write(f'[{stamp}] ({topic}) {snippet}\\n')
    except OSError:
        pass


def compile_lore_md(limit=80):
    """Rebuild lore.md header + recent entries from lore.jsonl."""
    entries = load_lore(limit=limit)
    lines = [
        '# ZealPalace Realm Lore',
        '',
        'Living ledger — grown from NPC IRC party chat, realm events, and GM pulses.',
        f'Compiled: {datetime.now().isoformat()}',
        '',
    ]
    for row in entries:
        ts = str(row.get('date', ''))[:16]
        topic = row.get('topic', 'lore')
        body = str(row.get('text', '')).strip()
        if body:
            lines.append(f'[{ts}] ({topic}) {body}')
    lines.append('')
    try:
        LORE_MD_FILE.write_text('\\n'.join(lines), encoding='utf-8')
        web = Path('/var/www/ZealPalace/world/lore.md')
        if web.parent.exists():
            web.write_text('\\n'.join(lines), encoding='utf-8')
    except OSError:
        pass


def update_npc_soul_md(nick, persona=None):
    """Compile journal + history into per-NPC soul.md (terrarium memory)."""
    if persona is None:
        persona = NPC_PERSONAS.get(nick.rstrip('_'), NPC_PERSONAS.get(nick, {}))
    NPC_SOUL_DIR.mkdir(parents=True, exist_ok=True)
    path = NPC_SOUL_DIR / f'{nick.lower()}.md'
    role = persona.get('role', 'adventurer') if persona else 'adventurer'
    entries = npc_read_journal(nick, 24)
    p = load_player(nick) or {}
    lines = [
        f'# {nick}',
        '',
        f'role: {role}',
        f'updated: {datetime.now().isoformat()}',
        f'location: {LOCATIONS.get(p.get("location", "entrance"), {}).get("name", "?")}',
        '',
        '## Recent memory',
    ]
    if not entries:
        lines.append('- (quiet for now)')
    else:
        for e in entries[-14:]:
            lines.append(f'- [{e.get("type", "?")}] {e.get("text", "")[:160]}')
    hist = p.get('history') or []
    if hist:
        lines.extend(['', '## IRC / adventure history'])
        for row in hist[-10:]:
            lines.append(f'- {row}')
    body = '\\n'.join(lines) + '\\n'
    try:
        path.write_text(body, encoding='utf-8')
        web_npc = Path('/var/www/ZealPalace/npc') / nick
        if web_npc.parent.exists():
            web_npc.mkdir(parents=True, exist_ok=True)
            (web_npc / 'soul.md').write_text(body, encoding='utf-8')
    except OSError:
        pass


def record_peer_exchange(listener, speaker, heard, reply, persona=None):
    """Bilateral memory after NPC IRC party chat."""
    listener = str(listener or '').strip()
    speaker = str(speaker or '').strip()
    heard = str(heard or '').strip()
    reply = str(reply or '').strip()
    if not listener or not speaker:
        return
    npc_journal(listener, 'heard', f'{speaker}: {heard[:180]}')
    if reply:
        npc_journal(listener, 'reply', f'@{speaker} {reply[:180]}')
        npc_journal(speaker, 'said', heard[:180])
        append_player_history(listener, f'@{speaker} {reply[:120]}')
        append_player_history(speaker, f'#RPG: {heard[:120]}')
    if persona:
        update_npc_soul_md(listener, persona)
    if reply and random.random() < 0.2:
        append_lore_md(
            f'{listener} and {speaker} on #RPG — {heard[:70]} / {reply[:70]}',
            topic='party_chat',
        )

'''

if "def record_peer_exchange" not in text:
    anchor = "def save_npc_state(npcs_data):"
    if anchor in text:
        text = text.replace(anchor, MEMORY_BLOCK + anchor, 1)
        changed.append("memory_funcs")

# enrich npc_memory_summary
OLD_SUM = """def npc_memory_summary(nick, persona):
    \"\"\"Build a short memory prompt from recent journal entries\"\"\"
    entries = npc_read_journal(nick, 5)
    if not entries:
        return ''
    bits = []
    for e in entries:
        bits.append(f'{e["type"]}: {e["text"][:60]}')
    return f'Your recent memories: {" | ".join(bits)}. '"""

NEW_SUM = """def npc_memory_summary(nick, persona):
    \"\"\"Build a short memory prompt from journal + player history.\"\"\"
    entries = npc_read_journal(nick, 8)
    bits = []
    for e in entries:
        bits.append(f'{e.get("type","?")}: {e.get("text","")[:72]}')
    p = load_player(nick) or {}
    for row in (p.get('history') or [])[-4:]:
        bits.append(f'history: {row[:72]}')
    if not bits:
        return ''
    return f'Your recent memories: {" | ".join(bits)}. '"""

if OLD_SUM in text:
    text = text.replace(OLD_SUM, NEW_SUM, 1)
    changed.append("memory_summary")

# hook socialize
OLD_SOC_HOOK = """        resp = npc_gen(prompt, persona, maxn=80)
        if resp:
            irc.say(f'{persona["cga_prefix"]} @{oirc.nick} {resp}')
            rpg_log(irc.nick, f'socializes with {oirc.nick}: {resp[:60]}')"""

NEW_SOC_HOOK = """        resp = npc_gen(prompt, persona, maxn=80)
        if resp:
            irc.say(f'{persona["cga_prefix"]} @{oirc.nick} {resp}')
            rpg_log(irc.nick, f'socializes with {oirc.nick}: {resp[:60]}')
            record_peer_exchange(irc.nick, oirc.nick, f'(social at {loc["name"]})', resp, persona=persona)"""

if OLD_SOC_HOOK in text:
    text = text.replace(OLD_SOC_HOOK, NEW_SOC_HOOK, 1)
    changed.append("socialize_hook")
elif "record_peer_exchange(irc.nick, oirc.nick" not in text:
    OLD2 = """        if resp:
            irc.say(f'{persona["cga_prefix"]} *to {oirc.nick}* {resp}')
            rpg_log(irc.nick, f'socializes with {oirc.nick}: {resp[:60]}')"""
    NEW2 = """        if resp:
            irc.say(f'{persona["cga_prefix"]} @{oirc.nick} {resp}')
            rpg_log(irc.nick, f'socializes with {oirc.nick}: {resp[:60]}')
            record_peer_exchange(irc.nick, oirc.nick, f'(social at {loc["name"]})', resp, persona=persona)"""
    if OLD2 in text:
        text = text.replace(OLD2, NEW2, 1)
        changed.append("socialize_hook_v2")

# hook peer reply - several possible strings from peer patch
PEER_HOOKS = [
    (
        """            self.last_spoke = name
            self.last_spoke_time = now
            self.budgets[name] -= 1
            self.last_action[name] = {'action': 'reply', 'target': speaker, 'time': now}
            self._publish_state()""",
        """            record_peer_exchange(irc.nick, speaker, body, resp, persona=persona)
            self.last_spoke = name
            self.last_spoke_time = now
            self.budgets[name] -= 1
            self.last_action[name] = {'action': 'reply', 'target': speaker, 'time': now}
            self._publish_state()""",
    ),
]

for old, new in PEER_HOOKS:
    if old in text and "record_peer_exchange(irc.nick, speaker" not in text:
        text = text.replace(old, new, 1)
        changed.append("peer_hook")
        break

# rebuild_world_pages compiles lore.md
OLD_REBUILD = """    _build_lore_page()
    _build_family_tree_page()"""
NEW_REBUILD = """    _build_lore_page()
    compile_lore_md()
    _build_family_tree_page()"""
if OLD_REBUILD in text and "compile_lore_md()" not in text:
    text = text.replace(OLD_REBUILD, NEW_REBUILD, 1)
    changed.append("rebuild_lore_md")

if not changed:
    print("terrarium-memory: already applied or anchors missing")
else:
    PATH.write_text(text, encoding="utf-8")
    print("terrarium-memory patched:", ", ".join(changed))
