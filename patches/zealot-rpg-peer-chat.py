#!/usr/bin/env python3
"""ZealPalace RPG: peer IRC chat, fast PING drain, join spam fix, faster ticks."""
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "zealot_rpg.py"
text = PATH.read_text(encoding="utf-8")
changed = []

# ── 0. Bootstrap JOIN helpers when missing ──
if "JOIN_IGNORE_NICKS" not in text:
    anchor = "ENTRY_MESSAGES = ["
    ins = """# Mesh agents on #RPG (extend via CRYSTAL_MESH_PARTY rows)
CRYSTAL_MESH_PARTY = []

JOIN_IGNORE_NICKS = frozenset({
    'lcd-ticker', 'lcd_ticker', 'lcd-probe', 'celes-pbx', 'zeallog', 'rpgbot',
    'dungeonmaster', 'hermes-warden', 'joshua-wopr', 'grok-paranoid',
})

def _mesh_party_nicks():
    nicks = set()
    try:
        for row in CRYSTAL_MESH_PARTY:
            if isinstance(row, dict):
                for key in ('irc_nick', 'short'):
                    val = str(row.get(key) or '').strip()
                    if val:
                        nicks.add(val.lower())
    except Exception:
        pass
    return nicks

def join_announce_is_ignored(nick, npcs=None):
    base = nick.rstrip('_').lower()
    if base in JOIN_IGNORE_NICKS:
        return True
    if base in _mesh_party_nicks():
        return True
    if npcs:
        if npcs.is_npc(nick):
            return True
        if nick in npcs.conns or nick.rstrip('_') in npcs.conns:
            return True
        if nick in getattr(npcs, 'npc_nicks', set()):
            return True
    try:
        personas = globals().get('NPC_PERSONAS') or {}
        key = nick.rstrip('_')
        if key in personas or nick in personas:
            return True
    except Exception:
        pass
    if '-' in base and base not in ('yomiko_', 'holybell'):
        if load_player(nick) or load_player(base):
            return False
        return True
    return False

ENTRY_MESSAGES = ["""
    if anchor in text:
        text = text.replace(anchor, ins, 1)
        changed.append("join_bootstrap")

# ── 1. Faster NPC ticks ──
OLD = "NPC_TICK_INTERVAL = 300  # 5 minutes"
NEW = "NPC_TICK_INTERVAL = 90  # 1.5 minutes — more party chatter"
if OLD in text:
    text = text.replace(OLD, NEW, 1)
    changed.append("tick_interval")

# ── 2. JOIN ignore expansion (when bootstrap already ran with full set) ──
OLD = """JOIN_IGNORE_NICKS = frozenset({
    'lcd-ticker', 'lcd_ticker', 'lcd-probe', 'celes-pbx', 'zeallog', 'rpgbot',
})"""
NEW = """JOIN_IGNORE_NICKS = frozenset({
    'lcd-ticker', 'lcd_ticker', 'lcd-probe', 'celes-pbx', 'zeallog', 'rpgbot',
    'dungeonmaster', 'hermes-warden', 'joshua-wopr', 'grok-paranoid',
})"""
if OLD in text:
    text = text.replace(OLD, NEW, 1)
    changed.append("join_ignore")

# ── 3. NPCIRC: inbox + buffered drain ──
OLD = """class NPCIRC:
    \"\"\"Lightweight IRC connection for a single NPC\"\"\"
    def __init__(self, nick):
        self.nick = nick
        self.sock = None
        self.buf = ''
        self.connected = False"""

NEW = """class NPCIRC:
    \"\"\"Lightweight IRC connection for a single NPC\"\"\"
    def __init__(self, nick):
        self.nick = nick
        self.sock = None
        self.buf = ''
        self.connected = False
        self.inbox = []  # recent peer lines for conversational replies"""

if OLD in text and "self.inbox = []" not in text:
    text = text.replace(OLD, NEW, 1)
    changed.append("npcirc_inbox")

OLD = """    def drain(self):
        \"\"\"Read and discard incoming data, handle PINGs\"\"\"
        try:
            data = self.sock.recv(4096).decode('utf-8', 'replace')
            for ln in data.split('\\r\\n'):
                if ln.startswith('PING'):
                    tok = ln.split('PING ')[-1]
                    self._tx(f'PONG {tok}')
        except:
            pass"""

NEW = """    def drain(self):
        \"\"\"Handle PINGs and queue peer IRC lines for party replies.\"\"\"
        if not self.sock:
            return
        try:
            while True:
                try:
                    chunk = self.sock.recv(4096)
                except BlockingIOError:
                    break
                except socket.timeout:
                    break
                if not chunk:
                    self.connected = False
                    return
                self.buf += chunk.decode('utf-8', 'replace')
                if len(self.buf) > 16000:
                    self.buf = self.buf[-8000:]
                while '\\r\\n' in self.buf:
                    ln, self.buf = self.buf.split('\\r\\n', 1)
                    if not ln:
                        continue
                    if ln.startswith('PING'):
                        tok = ln.split('PING ', 1)[-1].strip()
                        self._tx(f'PONG {tok}')
                        continue
                    if f' PRIVMSG {CHANNEL} ' not in ln and f' PRIVMSG {CHANNEL}:' not in ln:
                        continue
                    try:
                        prefix = ln[1:].split('!', 1)[0]
                        speaker = prefix
                        msg = ln.split(' :', 1)[-1].strip()
                        if not msg or speaker == self.nick:
                            continue
                        if speaker.rstrip('_').lower() == self.nick.rstrip('_').lower():
                            continue
                        self.inbox.append({'nick': speaker, 'text': msg[:320], 'ts': time.time()})
                    except Exception:
                        pass
            if len(self.inbox) > 16:
                self.inbox = self.inbox[-16:]
        except Exception:
            pass"""

if OLD in text:
    text = text.replace(OLD, NEW, 1)
    changed.append("npcirc_drain")

OLD = """                    if ' 001 ' in self.buf:
                        self.sock.settimeout(0.3)
                        self.connected = True
                        return True"""
NEW = """                    if ' 001 ' in self.buf:
                        self.sock.settimeout(0.0)
                        self.sock.setblocking(False)
                        self.connected = True
                        return True"""
if OLD in text and "setblocking(False)" not in text:
    text = text.replace(OLD, NEW, 1)
    changed.append("npcirc_nonblock")

INSERT_BEFORE = """    def tick(self):
        \"\"\"Called from main loop. Makes one random NPC do something if it's time.\"\"\"
        now = time.time()"""

PEER_METHOD = '''
    def _process_peer_replies(self, now):
        """Reply to other bots/humans on #RPG — conversational party RP."""
        pending = []
        for name, irc in self.conns.items():
            if self.budgets.get(name, 0) <= 0:
                irc.inbox.clear()
                continue
            for msg in list(irc.inbox):
                age = now - float(msg.get('ts') or 0)
                if age > 180:
                    continue
                speaker = str(msg.get('nick') or '')
                body = str(msg.get('text') or '').strip()
                if not body or 'Type /new' in body:
                    continue
                if speaker.lower() in ('dungeonmaster', 'rpgbot'):
                    continue
                pending.append((name, irc, msg))
            irc.inbox.clear()
        if not pending:
            return
        name, irc, msg = random.choice(pending)
        persona = NPC_PERSONAS.get(name.rstrip('_'), NPC_PERSONAS.get(name))
        if not persona:
            return
        p = load_player(irc.nick)
        if not p:
            p = default_player(irc.nick)
            save_player(p)
        loc = LOCATIONS.get(p.get('location', 'entrance'), LOCATIONS['entrance'])
        mem_ctx = npc_memory_summary(irc.nick, persona)
        speaker = msg['nick']
        body = msg['text'][:200]
        if not is_ollama_up():
            irc.say(f'{persona.get("cga_prefix", "")} @{speaker}: heard you — {body[:60]}')
            self.budgets[name] -= 1
            self.last_action[name] = {'action': 'reply', 'target': speaker, 'time': now}
            return
        prompt = (
            f'{mem_ctx}On IRC #RPG at {loc["name"]}, {speaker} said: "{body}". '
            f'You are {irc.nick}. Reply IN CHARACTER directly to {speaker} — '
            f'banter, question them, disagree, or build on their idea. '
            f'Reference the LAN mesh or your quest if it fits. 1-2 SHORT sentences.'
        )
        resp = npc_gen(prompt, persona, maxn=90)
        if resp:
            irc.say(f'{persona.get("cga_prefix", "")} @{speaker} {resp}')
            rpg_log(irc.nick, f'replies to {speaker}: {resp[:80]}')
            npc_journal(irc.nick, 'reply', f'@{speaker}: {resp[:80]}')
            self.last_spoke = name
            self.last_spoke_time = now
            self.budgets[name] -= 1
            self.last_action[name] = {'action': 'reply', 'target': speaker, 'time': now}
            self._publish_state()

'''

if "_process_peer_replies" not in text:
    text = text.replace(INSERT_BEFORE, PEER_METHOD + INSERT_BEFORE, 1)
    changed.append("peer_reply_method")

OLD_TICK = """    def tick(self):
        \"\"\"Called from main loop. Makes one random NPC do something if it's time.\"\"\"
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

        # Pick a random NPC that still has budget"""

NEW_TICK = """    def tick(self):
        \"\"\"Called from main loop. Makes one random NPC do something if it's time.\"\"\"
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

        # Always drain PING + peer IRC (main loop calls tick() every ~1s)
        for irc in self.conns.values():
            irc.drain()
        if random.random() < 0.35:
            self._process_peer_replies(now)

        if now - self.last_tick < self.cfg['tick_interval']:
            return
        self.last_tick = now

        # Pick a random NPC that still has budget"""

if OLD_TICK in text:
    text = text.replace(OLD_TICK, NEW_TICK, 1)
    changed.append("tick_drain")

OLD_SOC = """        resp = npc_gen(prompt, persona, maxn=40)
        if resp:
            irc.say(f'{persona["cga_prefix"]} *to {oirc.nick}* {resp}')
            rpg_log(irc.nick, f'socializes with {oirc.nick}: {resp[:60]}')"""

NEW_SOC = """        prompt += f' End with a question or prompt for {oirc.nick} to answer.'
        resp = npc_gen(prompt, persona, maxn=80)
        if resp:
            irc.say(f'{persona["cga_prefix"]} @{oirc.nick} {resp}')
            rpg_log(irc.nick, f'socializes with {oirc.nick}: {resp[:60]}')"""

if OLD_SOC in text:
    text = text.replace(OLD_SOC, NEW_SOC, 1)
    changed.append("socialize")

OLD_ACT = """        action_prompt += 'Reply with just the action word.'

        if not is_ollama_up():"""
NEW_ACT = """        others = [n for n in self.conns if n != name and (load_player(self.conns[n].nick) or {}).get('location') == p.get('location')]
        if others:
            action_prompt += f'Others here: {", ".join(self.conns[n].nick for n in others[:4])}. Prefer SOCIALIZE or OBSERVE to talk with them. '
        action_prompt += 'Reply with just the action word.'

        if not is_ollama_up():"""
if OLD_ACT in text and "Prefer SOCIALIZE" not in text:
    text = text.replace(OLD_ACT, NEW_ACT, 1)
    changed.append("action_prompt")

OLD_JOIN = """                    if nick != NICK and nick != f'{NICK}_':
                        entry_msg = random.choice(ENTRY_MESSAGES).format(nick=nick)"""
NEW_JOIN = """                    if nick != NICK and nick != f'{NICK}_':
                        if join_announce_is_ignored(nick, self.npcs):
                            return
                        entry_msg = random.choice(ENTRY_MESSAGES).format(nick=nick)"""
if OLD_JOIN in text and "join_announce_is_ignored(nick, self.npcs)" not in text:
    text = text.replace(OLD_JOIN, NEW_JOIN, 1)
    changed.append("join_handler")

if not changed:
    print('peer-chat: already applied or anchors missing')
else:
    PATH.write_text(text, encoding='utf-8')
    print('peer-chat patched:', ', '.join(changed))
