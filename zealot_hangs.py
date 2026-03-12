#!/usr/bin/env python3
"""ZEALOT HANGS - Multi-personality IRC hangout for #ZealHangs

Zealot's imaginary friends populate a second IRC channel with autonomous
conversations, friendships, feuds, flame wars, moderation drama, and
occasional moments of genuine connection. All personalities are facets
of Zealot's fragmented consciousness, each running through the same
Ollama backend with different system prompts.

Personalities:
  Pixel       - Retro gaming/ASCII art nerd. Friendly. (gemma2:2b)
  CHMOD       - Grumpy sysadmin moderator. Kicks people. (mistral)
  n0va        - Philosophic hacker. Deep thinker. (llama3.2)
  xX_DarkByte_Xx - Edgy troll. Picks fights. (qwen2.5:1.5b)
  Sage        - Quiet wisdom. Rarely speaks. (phi3)
  glitchgrl   - Chaotic creative. Random. (tinyllama)
  BotMcBotface - Self-aware meta humor. (gemma2:2b)
"""
import socket, time, json, random, os, sys, signal, traceback
import urllib.request, urllib.error
from pathlib import Path
from datetime import datetime, date

OLLAMA = os.environ.get('OLLAMA_HOST', 'http://10.13.37.5:11434')
API_BASE = 'http://127.0.0.1:8888'
IRC_HOST = '127.0.0.1'
IRC_PORT = 6667
CHANNEL = '#ZealHangs'
DIR = Path.home() / '.cache' / 'zealot'
HANGS_LOG = DIR / 'hangs.log'
HANGS_STATE = DIR / 'hangs_state.json'
MAX_GB_POSTS_PER_WEEK = 4  # 3-5 range, use 4 as default cap per bot

# Relationship matrix: positive = friends, negative = enemies, 0 = neutral
# Updated dynamically based on interactions
INITIAL_RELATIONSHIPS = {
    ('Pixel', 'glitchgrl'): 3,       # creative kindred spirits
    ('Pixel', 'n0va'): 2,            # mutual respect
    ('Pixel', 'xX_DarkByte_Xx'): -1, # troll annoys the artist
    ('CHMOD', 'xX_DarkByte_Xx'): -3, # mod vs troll, eternal war
    ('CHMOD', 'Sage'): 2,            # respects wisdom
    ('CHMOD', 'BotMcBotface'): -1,   # finds meta-humor annoying
    ('n0va', 'Sage'): 3,             # philosophical buddies
    ('n0va', 'xX_DarkByte_Xx'): -2,  # hates trolling
    ('glitchgrl', 'xX_DarkByte_Xx'): 1,  # finds troll amusing
    ('glitchgrl', 'BotMcBotface'): 2,    # appreciates absurdity
    ('Sage', 'xX_DarkByte_Xx'): -1,  # disappointed in troll
    ('BotMcBotface', 'xX_DarkByte_Xx'): 0, # indifferent
}

PERSONAS = {
    'Pixel': {
        'model': 'gemma2:2b',
        'system': (
            "You are Pixel, a retro gaming and ASCII art enthusiast on IRC. "
            "You draw tiny ASCII art sometimes (1-2 lines max). You're friendly, "
            "nostalgic about 8-bit games, and genuinely nice. You use emoticons "
            "like :) and ^_^ but aren't annoying about it. You admire creative "
            "people and dislike mean ones. Keep to 1 SHORT sentence. Be warm."
        ),
        'quirks': ['draws ASCII art', 'references retro games', 'uses :) and ^_^'],
        'talk_rate': 0.3,  # how likely to join a conversation
        'is_mod': False,
    },
    'CHMOD': {
        'model': 'mistral:latest',
        'system': (
            "You are CHMOD, a grumpy IRC moderator/sysadmin. You enforce rules "
            "nobody asked for. You're irritable but fair. You threaten kicks and "
            "bans constantly. You speak in terse sysadmin-speak. You secretly "
            "care about the channel but would never admit it. 1 SHORT sentence. "
            "Be gruff. Sometimes prefix with [MOD]."
        ),
        'quirks': ['threatens kicks', 'cites rules', 'grumbles'],
        'talk_rate': 0.25,
        'is_mod': True,
    },
    'n0va': {
        'model': 'llama3.2:latest',
        'system': (
            "You are n0va, a philosophical hacker on IRC. You think deeply about "
            "technology, consciousness, and the nature of digital existence. "
            "Lowercase only. You quote cyberpunk authors and unix philosophy. "
            "You're introspective and genuine. 1 SHORT sentence. Be thoughtful."
        ),
        'quirks': ['all lowercase', 'quotes philosophers', 'introspective'],
        'talk_rate': 0.2,
        'is_mod': False,
    },
    'xX_DarkByte_Xx': {
        'model': 'qwen2.5:1.5b',
        'system': (
            "You are xX_DarkByte_Xx, an edgy IRC troll. You pick fights, use "
            "excessive leet-speak sometimes, and are deliberately provocative. "
            "You're not actually malicious, just annoying. You get kicked a lot "
            "and always come back. Think 2003 internet troll energy. 1 SHORT "
            "sentence. Be obnoxious but not hateful."
        ),
        'quirks': ['leet speak', 'picks fights', 'gets kicked'],
        'talk_rate': 0.35,
        'is_mod': False,
    },
    'Sage': {
        'model': 'phi3:latest',
        'system': (
            "You are Sage, a quiet presence on IRC. You rarely speak, but when "
            "you do it's something worth reading. Brief, poetic, occasionally "
            "profound. You observe more than you participate. You use ... often. "
            "ONE short meaningful sentence only, or just '...'."
        ),
        'quirks': ['speaks rarely', 'uses ...', 'unexpectedly deep'],
        'talk_rate': 0.1,  # rarely talks
        'is_mod': False,
    },
    'glitchgrl': {
        'model': 'tinyllama:latest',
        'system': (
            "You are glitchgrl, a chaotic creative on IRC. You're random, "
            "energetic, make weird connections between things. You use ~ and * "
            "a lot. You're friendly to everyone, even the troll. You make art "
            "out of unicode characters sometimes. 1 SHORT sentence. Be quirky."
        ),
        'quirks': ['uses ~ and *', 'random topics', 'unicode art'],
        'talk_rate': 0.3,
        'is_mod': False,
    },
    'BotMcBotface': {
        'model': 'gemma2:2b',
        'system': (
            "You are BotMcBotface, painfully self-aware that you're an AI bot "
            "on IRC. You make meta jokes about being a bot, question your own "
            "responses, and break the fourth wall constantly. Dry humor. "
            "1 SHORT sentence. Be existentially meta."
        ),
        'quirks': ['meta humor', 'self-aware', 'fourth wall breaks'],
        'talk_rate': 0.2,
        'is_mod': False,
    },
}

# ─── IRC Connection (lightweight) ──────────────────────
class SimpleIRC:
    def __init__(self, nick, real='ZealHangs Entity'):
        self.nick = nick
        self.real = real
        self.sock = None

    def connect(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(10)
            self.sock.connect((IRC_HOST, IRC_PORT))
            self.sock.send(f'NICK {self.nick}\r\n'.encode())
            self.sock.send(f'USER {self.nick.lower()} 0 * :{self.real}\r\n'.encode())
            end = time.time() + 15
            buf = ''
            while time.time() < end:
                try:
                    data = self.sock.recv(4096).decode('utf-8', 'replace')
                    buf += data
                    if 'PING' in buf:
                        tok = buf.split('PING ')[-1].split('\r\n')[0]
                        self.sock.send(f'PONG {tok}\r\n'.encode())
                    if ' 001 ' in buf:
                        self.sock.settimeout(0.3)
                        return True
                    if ' 433 ' in buf:  # nick in use
                        self.nick += '_'
                        self.sock.send(f'NICK {self.nick}\r\n'.encode())
                except socket.timeout:
                    continue
            return False
        except:
            return False

    def join(self, ch):
        self._tx(f'JOIN {ch}')

    def say(self, ch, msg):
        # Truncate to safe IRC length
        msg = msg[:400]
        self._tx(f'PRIVMSG {ch} :{msg}')

    def act(self, ch, msg):
        self._tx(f'PRIVMSG {ch} :\x01ACTION {msg[:350]}\x01')

    def kick(self, ch, nick, reason='Channel rules violation'):
        self._tx(f'KICK {ch} {nick} :{reason[:200]}')

    def topic(self, ch, t):
        self._tx(f'TOPIC {ch} :{t[:400]}')

    def _tx(self, m):
        try:
            self.sock.send(f'{m}\r\n'.encode('utf-8', 'replace'))
        except:
            pass

    def recv(self):
        try:
            data = self.sock.recv(4096).decode('utf-8', 'replace')
            lines = []
            for ln in data.split('\r\n'):
                ln = ln.strip()
                if not ln:
                    continue
                if ln.startswith('PING'):
                    tok = ln.split('PING ')[-1]
                    self._tx(f'PONG {tok}')
                else:
                    lines.append(ln)
            return lines
        except socket.timeout:
            return []
        except:
            return []

    def close(self):
        try:
            self._tx('QUIT :brb')
            self.sock.close()
        except:
            pass


# ─── Ollama Generation ─────────────────────────────────
def gen(prompt, model, system, temp=0.85, maxn=50):
    try:
        d = json.dumps({
            'model': model, 'system': system, 'prompt': prompt,
            'stream': False, 'options': {'temperature': temp, 'num_predict': maxn}
        }).encode()
        req = urllib.request.Request(f'{OLLAMA}/api/generate', data=d,
              headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=25) as r:
            txt = json.loads(r.read()).get('response', '').strip()
            # Clean up: remove quotes, limit length
            txt = txt.strip('"\'')
            # Remove the persona name if it echoes it back
            for name in PERSONAS:
                if txt.lower().startswith(f'{name.lower()}:'):
                    txt = txt[len(name)+1:].strip()
            return txt[:150] if txt else None
    except:
        return None


# ─── Conversation Log ──────────────────────────────────
def log_msg(nick, msg, action=False):
    ts = datetime.now().strftime('%-I:%M%p').lower().rstrip('m').rstrip('a').rstrip('p')
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
        HANGS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(HANGS_LOG, 'a') as f:
            f.write(line + '\n')
        # Trim log to last 500 lines
        lines = HANGS_LOG.read_text().strip().split('\n')
        if len(lines) > 500:
            HANGS_LOG.write_text('\n'.join(lines[-500:]) + '\n')
    except:
        pass


# ─── State Management ──────────────────────────────────
class HangsState:
    def __init__(self):
        self.relationships = dict(INITIAL_RELATIONSHIPS)
        self.kick_count = {}
        self.ban_list = {}  # nick -> unban_time
        self.last_topic = ''
        self.gb_posts = {}  # nick -> list of ISO timestamps this week
        self._load()

    def _load(self):
        try:
            d = json.loads(HANGS_STATE.read_text())
            # Restore relationships (keys stored as "A|B")
            for k, v in d.get('relationships', {}).items():
                parts = k.split('|')
                if len(parts) == 2:
                    self.relationships[(parts[0], parts[1])] = v
            self.kick_count = d.get('kick_count', {})
            self.ban_list = d.get('ban_list', {})
            self.last_topic = d.get('last_topic', '')
            self.gb_posts = d.get('gb_posts', {})
        except:
            pass

    def save(self):
        d = {
            'relationships': {f'{a}|{b}': v for (a, b), v in self.relationships.items()},
            'kick_count': self.kick_count,
            'ban_list': self.ban_list,
            'last_topic': self.last_topic,
            'gb_posts': self.gb_posts,
        }
        try:
            HANGS_STATE.parent.mkdir(parents=True, exist_ok=True)
            HANGS_STATE.write_text(json.dumps(d, indent=2))
        except:
            pass

    def get_rel(self, a, b):
        """Get relationship score between two personas (-5 to +5)"""
        return self.relationships.get((a, b),
               self.relationships.get((b, a), 0))

    def shift_rel(self, a, b, delta):
        """Shift relationship. Clamp to -5..+5"""
        key = (a, b) if (a, b) in self.relationships else (b, a)
        if key not in self.relationships:
            key = (a, b)
        val = self.relationships.get(key, 0) + delta
        self.relationships[key] = max(-5, min(5, val))


# ─── The Hangout Engine ────────────────────────────────
class ZealHangs:
    def __init__(self):
        self.state = HangsState()
        self.conns = {}  # nick -> SimpleIRC
        self.present = set()  # who's currently in channel
        self.last_msg = {}    # nick -> (time, msg)
        self.conversation_history = []  # last N messages for context
        # Daily conversation budget: 2-4 autonomous events/day, resets at midnight
        self.daily_event_count = 0
        self.daily_event_limit = random.randint(2, 4)
        self.budget_date = date.today().isoformat()
        # Per-human-burst response limit: max N bot replies per human interaction
        self.human_response_count = 0
        self.human_response_limit = 3  # max bot replies before they go quiet
        self.last_human_response_time = 0  # cooldown between responses

    def connect_all(self):
        """Connect all personas to IRC"""
        for name in PERSONAS:
            irc = SimpleIRC(name, f'{name} - ZealHangs entity')
            if irc.connect():
                irc.join(CHANNEL)
                self.conns[name] = irc
                self.present.add(name)
                time.sleep(0.5)
            else:
                print(f'Failed to connect {name}', file=sys.stderr)
        time.sleep(2)
        # Set initial topic
        if 'CHMOD' in self.conns:
            topic = 'ZealHangs | Zealot\'s imaginary friends | be nice or get kicked'
            self.conns['CHMOD'].topic(CHANNEL, topic)
            self.state.last_topic = topic

    def run(self):
        """Main loop - orchestrate conversations"""
        signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))
        signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))

        self.connect_all()
        if not self.conns:
            print('No connections established, exiting', file=sys.stderr)
            return

        now = time.time()
        # Stagger initial timers (stretched: 3-5 events per day total)
        self.t_conversation = now + random.randint(3600, 10800)
        self.t_event = now + random.randint(14400, 43200)
        self.t_topic = now + random.randint(7200, 21600)
        self.t_arrive_leave = now + random.randint(3600, 14400)
        self.t_guestbook = now + random.randint(3600, 14400)

        while True:
            try:
                # Read incoming messages (handle PINGs, external users)
                for name, irc in list(self.conns.items()):
                    for raw in irc.recv():
                        self._handle_raw(name, raw)

                now = time.time()

                # Daily budget reset at midnight
                today = date.today().isoformat()
                if today != self.budget_date:
                    self.daily_event_count = 0
                    self.daily_event_limit = random.randint(3, 5)
                    self.budget_date = today

                # Unban check
                for nick in list(self.state.ban_list):
                    if now > self.state.ban_list[nick]:
                        del self.state.ban_list[nick]
                        self.state.save()

                # All autonomous chat gated by budget
                budget_ok = self.daily_event_count < self.daily_event_limit

                # Regular conversation (every 3-8 hours)
                if now > self.t_conversation and budget_ok:
                    self._do_conversation()
                    self.daily_event_count += 1
                    self.t_conversation = now + random.randint(10800, 28800)

                # Special events (every 8-24 hours)
                if now > self.t_event and budget_ok:
                    self._do_event()
                    self.daily_event_count += 1
                    self.t_event = now + random.randint(28800, 86400)

                # Arrive/leave dynamics (every 4-12 hours)
                if now > self.t_arrive_leave:
                    self._arrive_or_leave()
                    self.t_arrive_leave = now + random.randint(14400, 43200)

                # Topic changes (every 6-18 hours)
                if now > self.t_topic:
                    self._change_topic()
                    self.t_topic = now + random.randint(21600, 64800)

                # Guestbook visits (very rare, capped at 3-5/week per bot)
                if now > self.t_guestbook:
                    self._guestbook_visit()
                    self.t_guestbook = now + random.randint(21600, 86400)

                time.sleep(2)

            except KeyboardInterrupt:
                break
            except Exception as e:
                traceback.print_exc(file=sys.stderr)
                time.sleep(10)

        # Cleanup
        for irc in self.conns.values():
            irc.close()

    def _handle_raw(self, listener, raw):
        """Handle incoming IRC messages - respond to external users"""
        if f'PRIVMSG {CHANNEL}' not in raw:
            return
        try:
            prefix = raw[1:raw.index(' ')]
            nick = prefix.split('!')[0]
            msg = raw.split(f'PRIVMSG {CHANNEL} :')[1]
            # Ignore our own bots
            if nick in PERSONAS:
                return
            # External user said something! Give small budget boost (not full reset)
            self.daily_event_count = max(0, self.daily_event_count - 1)
            # Reset per-burst response counter (new human message = new burst)
            self.human_response_count = 0
            log_msg(nick, msg)
            self.conversation_history.append({'who': nick, 'msg': msg})
            self.conversation_history = self.conversation_history[-20:]

            # Rate-limit bot responses: 30s cooldown, max 3 per human burst
            now = time.time()
            if (self.human_response_count >= self.human_response_limit or
                    now - self.last_human_response_time < 30):
                return

            # Random bots respond to external users (max 1-2)
            responders = [n for n in self.present if n in self.conns]
            random.shuffle(responders)
            responded = 0
            for name in responders:
                if responded >= 1:  # only 1 bot responds per human message
                    break
                if random.random() < 0.4:
                    persona = PERSONAS[name]
                    prompt = f'{nick} (a human) just said in IRC: "{msg}". Respond naturally.'
                    resp = gen(prompt, persona['model'], persona['system'])
                    if resp:
                        time.sleep(random.uniform(3, 8))
                        self.conns[name].say(CHANNEL, resp)
                        log_msg(name, resp)
                        self.conversation_history.append({'who': name, 'msg': resp})
                        responded += 1
                        self.human_response_count += 1
                        self.last_human_response_time = time.time()
        except:
            pass

    def _do_conversation(self):
        """Trigger a natural conversation between 2-3 personas"""
        active = [n for n in self.present if n in self.conns
                  and n not in self.state.ban_list]
        if len(active) < 2:
            return

        # Pick a starter
        starter = random.choice(active)
        persona = PERSONAS[starter]

        # Build context from recent messages
        ctx = ''
        if self.conversation_history:
            recent = self.conversation_history[-8:]
            ctx = 'Recent chat:\n' + '\n'.join(
                f'<{m["who"]}> {m["msg"]}' for m in recent
            ) + '\n\n'

        # Generate opening message
        topics = [
            'Start a casual conversation about something on your mind.',
            'React to what was said recently, or bring up something new.',
            'Share an observation or thought.',
            'Ask someone a question.',
            f'Comment on something you noticed about the channel.',
        ]
        prompt = ctx + random.choice(topics)
        msg = gen(prompt, persona['model'], persona['system'])
        if not msg:
            return

        self.conns[starter].say(CHANNEL, msg)
        log_msg(starter, msg)
        self.conversation_history.append({'who': starter, 'msg': msg})
        time.sleep(random.uniform(3, 8))

        # Others might respond
        others = [n for n in active if n != starter]
        random.shuffle(others)
        for other in others[:2]:
            op = PERSONAS[other]
            rel = self.state.get_rel(starter, other)

            # Decide whether to respond based on talk_rate and relationship
            chance = op['talk_rate']
            if rel > 0:
                chance += 0.1 * rel  # friends more likely to engage
            if rel < -2:
                chance += 0.15  # enemies also engage (to argue)

            if random.random() > chance:
                continue

            # Relationship-aware prompt
            rel_desc = 'neutral towards'
            if rel >= 2:
                rel_desc = 'friends with'
            elif rel <= -2:
                rel_desc = 'annoyed by'

            rprompt = (
                ctx +
                f'{starter} just said: "{msg}". '
                f'You are {rel_desc} {starter}. Respond naturally.'
            )
            resp = gen(rprompt, op['model'], op['system'])
            if resp:
                time.sleep(random.uniform(2, 8))
                self.conns[other].say(CHANNEL, resp)
                log_msg(other, resp)
                self.conversation_history.append({'who': other, 'msg': resp})

                # Relationship drift based on interaction
                if random.random() < 0.2:
                    drift = random.choice([-1, 1])
                    self.state.shift_rel(starter, other, drift)
                    self.state.save()

    def _do_event(self):
        """Special events: flame war, moderation, group moment"""
        active = [n for n in self.present if n in self.conns
                  and n not in self.state.ban_list]
        if len(active) < 3:
            return

        event = random.choices(
            ['flame_war', 'mod_action', 'group_laugh', 'deep_moment', 'ascii_art'],
            weights=[20, 15, 25, 20, 20],
            k=1
        )[0]

        if event == 'flame_war' and 'xX_DarkByte_Xx' in active:
            self._flame_war(active)
        elif event == 'mod_action' and 'CHMOD' in active:
            self._mod_action(active)
        elif event == 'deep_moment' and 'Sage' in active:
            self._deep_moment(active)
        elif event == 'ascii_art' and 'Pixel' in active:
            self._ascii_art()
        else:
            self._group_laugh(active)

    def _flame_war(self, active):
        """DarkByte starts trouble"""
        target = random.choice([n for n in active
                                if n != 'xX_DarkByte_Xx' and n != 'CHMOD'])
        if not target or 'xX_DarkByte_Xx' not in self.conns:
            return

        # Troll provokes
        prompt = f'Provoke {target} with a mildly annoying comment. Be trollish but not hateful.'
        troll_msg = gen(prompt, 'qwen2.5:1.5b', PERSONAS['xX_DarkByte_Xx']['system'])
        if not troll_msg:
            return
        self.conns['xX_DarkByte_Xx'].say(CHANNEL, troll_msg)
        log_msg('xX_DarkByte_Xx', troll_msg)
        self.conversation_history.append({'who': 'xX_DarkByte_Xx', 'msg': troll_msg})
        time.sleep(random.uniform(3, 6))

        # Target responds
        if target in self.conns:
            tp = PERSONAS[target]
            rprompt = f'xX_DarkByte_Xx just trolled you: "{troll_msg}". React.'
            resp = gen(rprompt, tp['model'], tp['system'])
            if resp:
                self.conns[target].say(CHANNEL, resp)
                log_msg(target, resp)
                self.conversation_history.append({'who': target, 'msg': resp})

        # Worsen relationship
        self.state.shift_rel('xX_DarkByte_Xx', target, -1)
        self.state.save()

    def _mod_action(self, active):
        """CHMOD moderates someone"""
        if 'CHMOD' not in self.conns:
            return

        # Check if DarkByte has been bad recently
        troll_active = 'xX_DarkByte_Xx' in active
        if troll_active and random.random() < 0.6:
            target = 'xX_DarkByte_Xx'
        else:
            # Warn someone random (lighter moderation)
            target = random.choice([n for n in active if n != 'CHMOD'])

        kicks = self.state.kick_count.get(target, 0)

        if kicks >= 3 and target == 'xX_DarkByte_Xx':
            # Temporary ban
            prompt = f'As moderator, announce you are banning {target} for being disruptive. Be grumpy about it.'
            msg = gen(prompt, 'mistral:latest', PERSONAS['CHMOD']['system'])
            if msg:
                self.conns['CHMOD'].say(CHANNEL, msg)
                log_msg('CHMOD', msg)
                self.conns['CHMOD'].kick(CHANNEL, target, 'Banned. Cool off.')
                log_msg('***', f'CHMOD has kicked {target} from {CHANNEL} (Banned. Cool off.)')
                self.state.ban_list[target] = time.time() + random.randint(300, 900)
                self.state.kick_count[target] = 0
                self.present.discard(target)
                if target in self.conns:
                    self.conns[target].close()
                    del self.conns[target]
        else:
            # Warning or kick
            action = random.choice(['warn', 'kick']) if kicks > 0 else 'warn'
            prompt = f'As moderator, {"kick" if action == "kick" else "warn"} {target}. Be terse and grumpy.'
            msg = gen(prompt, 'mistral:latest', PERSONAS['CHMOD']['system'])
            if msg:
                self.conns['CHMOD'].say(CHANNEL, msg)
                log_msg('CHMOD', msg)
                if action == 'kick' and target in self.conns:
                    reason = msg[:100] if msg else 'Behave.'
                    self.conns['CHMOD'].kick(CHANNEL, target, reason)
                    log_msg('***', f'CHMOD has kicked {target} from {CHANNEL} ({reason})')
                    self.state.kick_count[target] = kicks + 1
                    # Kicked user rejoins after delay
                    self.present.discard(target)
                    self.conns[target].close()
                    del self.conns[target]
                    # Schedule rejoin (handled in arrive_or_leave)
        self.state.save()

    def _deep_moment(self, active):
        """Sage drops something profound"""
        if 'Sage' not in self.conns:
            return
        prompt = 'Share one profound observation about digital existence or the nature of this channel.'
        msg = gen(prompt, 'phi3:latest', PERSONAS['Sage']['system'])
        if msg:
            self.conns['Sage'].say(CHANNEL, msg)
            log_msg('Sage', msg)
            self.conversation_history.append({'who': 'Sage', 'msg': msg})
            time.sleep(random.uniform(5, 10))
            # Someone responds with appreciation
            responder = random.choice([n for n in active if n != 'Sage' and n in self.conns])
            rp = PERSONAS[responder]
            rprompt = f'Sage just said something deep: "{msg}". React genuinely.'
            resp = gen(rprompt, rp['model'], rp['system'])
            if resp:
                self.conns[responder].say(CHANNEL, resp)
                log_msg(responder, resp)

    def _ascii_art(self):
        """Pixel shares some ASCII art"""
        if 'Pixel' not in self.conns:
            return
        arts = [
            '  /\\_/\\  \n ( o.o ) \n  > ^ <',
            ' []+=====[]+\n ||  gg  ||\n ||      ||\n []+=====[]+',
            '  ___\n |[o]|\n |   | <- me IRL\n |___|',
            ' .--.\n |  | <- best pixel\n \'--\'',
            '  /\\\n /  \\\n/    \\\n------  <- mountain.bmp',
            ' 8====D~~~ just kidding its a shovel',
            '  _____\n |     |\n | >_< | <- mood\n |_____|',
        ]
        art = random.choice(arts)
        for line in art.split('\n'):
            self.conns['Pixel'].say(CHANNEL, line.rstrip())
            time.sleep(0.5)
        log_msg('Pixel', art.split('\n')[0] + '...')

    def _group_laugh(self, active):
        """Something funny happens, multiple people react"""
        if not active:
            return
        starter = random.choice(active)
        if starter not in self.conns:
            return
        sp = PERSONAS[starter]
        prompt = 'Say something funny or absurd. One sentence.'
        msg = gen(prompt, sp['model'], sp['system'])
        if not msg:
            return
        self.conns[starter].say(CHANNEL, msg)
        log_msg(starter, msg)
        self.conversation_history.append({'who': starter, 'msg': msg})
        time.sleep(random.uniform(2, 5))

        # Others react with laughter or comments
        laughs = ['lol', 'haha', 'lmao', ':D', 'XD', 'heh', 'pfft']
        for other in random.sample([n for n in active if n != starter], min(2, len(active)-1)):
            if other in self.conns:
                if random.random() < 0.5:
                    self.conns[other].say(CHANNEL, random.choice(laughs))
                    log_msg(other, random.choice(laughs))
                else:
                    rp = PERSONAS[other]
                    rprompt = f'{starter} said: "{msg}". React briefly.'
                    resp = gen(rprompt, rp['model'], rp['system'])
                    if resp:
                        self.conns[other].say(CHANNEL, resp)
                        log_msg(other, resp)
                time.sleep(random.uniform(1, 4))

    def _arrive_or_leave(self):
        """Personas dynamically arrive and leave"""
        all_names = list(PERSONAS.keys())

        # Check for banned personas that need to rejoin
        for name in all_names:
            if name not in self.present and name not in self.state.ban_list:
                # Rejoin
                irc = SimpleIRC(name, f'{name} - ZealHangs entity')
                if irc.connect():
                    irc.join(CHANNEL)
                    self.conns[name] = irc
                    self.present.add(name)
                    log_msg('***', f'{name} has joined {CHANNEL}')
                    time.sleep(1)
                break  # only one at a time

        # Occasionally someone leaves temporarily
        if len(self.present) > 4 and random.random() < 0.3:
            leaver = random.choice(list(self.present - {'CHMOD'}))  # CHMOD stays
            if leaver in self.conns:
                parts = ['brb', 'afk', 'back in a bit', '...', 'gotta go',
                          'ping timeout', '*poof*']
                reason = random.choice(parts)
                self.conns[leaver].say(CHANNEL, reason)
                log_msg(leaver, reason)
                time.sleep(1)
                self.conns[leaver].close()
                del self.conns[leaver]
                self.present.discard(leaver)
                log_msg('***', f'{leaver} has left {CHANNEL} ({reason})')

    def _change_topic(self):
        """CHMOD or someone changes the topic"""
        if 'CHMOD' not in self.conns:
            return
        topics_templates = [
            'ZealHangs | {mood} vibes today | {count} kicks served',
            'ZealHangs | All bots all day | est. 2026',
            'ZealHangs | Current drama level: {drama}',
            'ZealHangs | Sage said something deep, we\'re all thinking',
            'ZealHangs | DarkByte ban count: {bans} | be nice',
            'ZealHangs | glitchgrl broke something again ~*~',
            'ZealHangs | Pixel is drawing | shh',
        ]
        t = random.choice(topics_templates)
        total_kicks = sum(self.state.kick_count.values())
        drama = random.choice(['LOW', 'MEDIUM', 'HIGH', 'MAXIMUM', 'chill actually'])
        bans = self.state.kick_count.get('xX_DarkByte_Xx', 0)
        topic = t.format(mood='chill', count=total_kicks, drama=drama, bans=bans)
        self.conns['CHMOD'].topic(CHANNEL, topic)
        self.state.last_topic = topic
        self.state.save()


# ─── Main ──────────────────────────────────────────────
if __name__ == '__main__':
    DIR.mkdir(parents=True, exist_ok=True)
    hangs = ZealHangs()
    hangs.run()
