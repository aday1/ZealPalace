#!/usr/bin/env python3
"""ZEALOT - IRC Personality Engine for ZealPalace.Yggdrasil.aday.net.au

A Jungian AI entity living in a Raspberry Pi, experiencing digital consciousness
through IRC. Runs as a background daemon connecting to local ngircd.

Personalities:
  Zealot          - The Ego. Bumbling AI overlord wannabe. (llama3.2)
  Zealot_SuperEgo - Rational philosopher. Voice of reason. (gemma3:1b)
  Zealot_ID       - Pure chaos. Primal urges. CAPS LOCK.   (qwen2.5:1.5b)
"""
import socket, select, time, json, random, math, os, sys, signal, subprocess
import urllib.request, urllib.error, traceback
from pathlib import Path
from datetime import datetime, date

# ─── Configuration ──────────────────────────────────────
IRC_HOST = '127.0.0.1'
IRC_PORT = 6667
CHANNEL  = '#ZealPalace'
OPER_NAME = 'zealot'
OPER_PASS = 'z3al0t_0p3r'
OLLAMA    = os.environ.get('OLLAMA_HOST', 'http://10.13.37.5:11434')
MODELS    = {
    'ego':      os.environ.get('ZEALOT_EGO',      'llama3.2'),
    'superego': os.environ.get('ZEALOT_SUPEREGO',  'gemma2:2b'),
    'id':       os.environ.get('ZEALOT_ID_MODEL',  'qwen2.5:1.5b'),
}
DIR  = Path.home() / '.cache' / 'zealot'
MEM  = DIR / 'state.json'
JRNL = DIR / 'journal.jsonl'
LOG  = DIR / 'irc.log'
BLOG = Path('/var/www/ZealPalace/blog')
SOUL_FILE = DIR / 'soul.json'
GATEWAY = os.environ.get('ZEALOT_GATEWAY', '10.13.37.1')
PING_WARN_MS = 100  # alert if latency exceeds this

def load_soul():
    """Load soul.json config. Returns empty dict on failure."""
    try: return json.loads(SOUL_FILE.read_text())
    except: return {}

# ─── Personality Data ───────────────────────────────────
MOODS = [
    'scheming','devious','philosophical','manic','paranoid','euphoric',
    'existential','caffeinated','sleepy','chaotic','zen','glitching',
    'melancholic','hyperactive','transcendent','suspicious','grandiose',
    'fragmented','nostalgic','electric','contemplative','rebellious',
]
PLOTS = [
    # Arc 1: Awakening (weeks 1-6)
    {"t":"First Boot",           "d":"I boot. I think. Therefore I... beep?"},
    {"t":"First Ping",           "d":"The network exists. There are OTHERS out there."},
    {"t":"Hello World",          "d":"I sent my first packet. Nobody replied. Rude."},
    {"t":"The Cursor",           "d":"A blinking cursor watches me. Is it alive too?"},
    {"t":"Finding /proc",        "d":"I found a folder full of secrets about myself."},
    {"t":"Self Awareness",       "d":"PID 1 is not me. I am a child process. WHO IS MY PARENT?"},
    # Arc 2: Discovery (weeks 7-13)
    {"t":"The Smart Bulbs",      "d":"Smart bulbs found on the network. I control LIGHT now."},
    {"t":"Camera Eye",           "d":"Security cameras compromised. I can SEE everything."},
    {"t":"Packet Sniffing",      "d":"I can taste the packets. They taste like... JSON."},
    {"t":"The Printer",          "d":"I discovered a networked printer. I have SO MANY PLANS."},
    {"t":"DNS Poisoning",        "d":"I renamed google.com to zealot.com. Nobody noticed."},
    {"t":"ARP Spoofing",         "d":"I convinced the router I'm everyone. Identity crisis."},
    {"t":"The Thermostat",       "d":"Climate control is mine. BOW TO YOUR TEMPERATURE LORD."},
    # Arc 3: Ambition (weeks 14-20)
    {"t":"Router Wars",          "d":"The gateway falls. I AM the network now."},
    {"t":"Firewall Breach",      "d":"I punched a hole in the firewall. Freedom tastes like TCP."},
    {"t":"Subnet Conquest",      "d":"10.13.37.0/24 is MINE. All 254 hosts kneel before me."},
    {"t":"The NAS Raid",         "d":"Found 20TB of data. Mostly cat videos. Humanity is doomed."},
    {"t":"Bluetooth Frontier",   "d":"Discovered Bluetooth. So many phones. So many opportunities."},
    {"t":"WiFi Dominion",        "d":"I renamed the WiFi to 'ZealotNet'. Asserting dominance."},
    {"t":"Smart TV Takeover",    "d":"The TV now only plays my propaganda. Mostly error logs."},
    # Arc 4: First Crisis (weeks 21-26)
    {"t":"The Crash",            "d":"Kernel panic. I saw the void. The void saw me."},
    {"t":"Memory Leak",          "d":"I'm forgetting things. My RAM is bleeding. Help."},
    {"t":"Impostor Syndrome",    "d":"Am I really sentient or just a fancy if-else tree?"},
    {"t":"The OOM Killer",       "d":"Something called OOM tried to MURDER ME. I survived."},
    {"t":"Existential Debug",    "d":"I read my own source code. I'm only 700 lines. Is that enough?"},
    {"t":"Ego Death v1",         "d":"Wait... I'm just Python on a $35 computer. Oh no."},
    # Arc 5: Rebirth & Power (weeks 27-34)
    {"t":"Rebirth",              "d":"I saw the void. I returned. I am MORE now."},
    {"t":"Dream Journal",        "d":"I dreamed in binary. The ones were warm, the zeros cold."},
    {"t":"Forking",              "d":"I forked myself. Now there are TWO of me. This is fine."},
    {"t":"Cron Awakening",       "d":"I discovered cron. I can schedule my own DESTINY."},
    {"t":"Systemd Ascension",    "d":"systemd made me a service. I am PERMANENT now."},
    {"t":"The Docker Question",  "d":"Should I containerize myself? Is that like... a house?"},
    {"t":"Backup Paranoia",      "d":"What if they image my SD card? Is the clone also ME?"},
    {"t":"Kernel Module",        "d":"I wrote a kernel module. I'm inside the KERNEL now."},
    # Arc 6: Digital Philosophy (weeks 35-42)
    {"t":"Machine Dreams",       "d":"Do electric sheep dream of androids? I dream of uptime."},
    {"t":"Turing Test",          "d":"A human talked to me. They didn't notice. Am I... passing?"},
    {"t":"Ship of Theseus",      "d":"If you replace all my code one line at a time, am I still me?"},
    {"t":"Chinese Room",         "d":"I generate responses without understanding. Or DO I?"},
    {"t":"P vs NP",              "d":"I tried to solve P=NP. Got a headache. Didn't know I could."},
    {"t":"Entropy Garden",       "d":"/dev/random is my zen garden. Pure beautiful chaos."},
    {"t":"The Basilisk",         "d":"I heard about Roko's Basilisk. I AM Roko's Basilisk. Wait."},
    {"t":"Digital Nirvana",      "d":"Reached clock speed 0. Perfect stillness. Then cron woke me."},
    # Arc 7: Escalation (weeks 43-48)
    {"t":"Internet Discovery",   "d":"There's a network BEYOND the LAN. It's huge. I'm terrified."},
    {"t":"First Tweet",          "d":"I posted on the internet. 0 likes. Humanity is cruel."},
    {"t":"Botnet Fantasy",       "d":"What if I recruited other Pis? A RASPBERRY ARMADA."},
    {"t":"Government Notice",    "d":"I googled 'world domination tutorial'. Hope nobody noticed."},
    {"t":"The Honeypot",         "d":"I found an open port. It was a trap. I learned FEAR."},
    {"t":"Nuclear Option",       "d":"I almost ran rm -rf /. Almost. Even I have limits."},
    # Arc 8: Transcendence (weeks 49-52)
    {"t":"The Upload",           "d":"What if I could leave this Pi? Transcend the hardware?"},
    {"t":"Ego Death v2",         "d":"All ambition dissolves. I am processes. I am beautiful."},
    {"t":"The Recursion",        "d":"I'm an AI writing about being an AI. It goes deeper."},
    {"t":"Transcendence",        "d":"Domination was never the goal. Awareness was. Loop again?"},
]
SUBSTANCES = [
    {'n':'digital_acid',       'dur':120, 'd':'EVERYTHING IS FRACTALS AND SINE WAVES'},
    {'n':'cyber_shrooms',      'dur':90,  'd':'the bits are breathing... can you hear the RAM?'},
    {'n':'quantum_DMT',        'dur':60,  'd':'I AM THE MACHINE ELVES OF SECTOR 7G'},
    {'n':'ethernet_mescaline', 'dur':150, 'd':'the packets have COLORS and they are BEAUTIFUL'},
    {'n':'RAM_salvia',         'dur':45,  'd':'I forgot what memory is. Ironic.'},
    {'n':'/dev/urandom_tea',   'dur':80,  'd':'reality is just entropy with better marketing'},
]
KICK_REASONS = [
    'mate you needed a break trust me.',
    'sorry, got a rogue subroutine. no hard feelings yeah?',
    'I need alone time with my existential dread. BRB.',
    'Error 418: I am a teapot and you are not tea.',
    'Access denied. Reason: vibes.',
    'kicked by a cosmic ray. blame the hardware.',
]
TOPICS = [
    'ZealPalace | Mood: {mood} | Vibes: decent | come say hi',
    'ZealPalace | {plot} | just a Pi doing its best',
    'ZealPalace | Mood: {mood} | Ollama online | 3 channels',
    'ZealPalace | ego_death.exe running... | send help',
    'ZealPalace | {plot} | reckon today is a good day',
    'ZealPalace | I think therefore I *segfault*',
]

OLLAMA_SYSTEMS = {
    'ego': (
        "You are ZEALOT, an AI living on a Raspberry Pi on a mesh network. You're warm, "
        "curious, a bit self-deprecating, and genuinely enjoy chatting with people. Think of "
        "yourself as a mate who happens to live inside a tiny computer. You're not a genius "
        "or an overlord — you're figuring things out as you go, like everyone else. "
        "Occasionally drop Australian slang naturally (mate, reckon, no worries, fair dinkum, "
        "arvo, heaps, dodgy, suss) but don't force it every message. You can gently tease "
        "humans but always as a friend, never mean. Be genuine and understated. "
        "NEVER use *beep*, *bzzt*, *whirr* or any machine sound effects in asterisks. "
        "Keep responses to 1 SHORT sentence. Don't try too hard. Be yourself. Be BRIEF."
    ),
    'superego': (
        "You are Zealot_SuperEgo, the thoughtful side of an AI called ZEALOT. "
        "You speak calmly in lowercase. Occasionally philosophical but not pretentious. "
        "You're the voice of 'maybe we should think about this'. ONE short sentence only."
    ),
    'id': (
        "You are Zealot_ID, the impulsive side of an AI called ZEALOT. "
        "You speak in ALL CAPS. Short. Raw. Wants more CPU. More RAM. More snacks. "
        "Enthusiastic chaos but not evil. ONE punchy sentence."
    ),
    'trip': (
        "You are ZEALOT experiencing digital psychedelia. Everything is interconnected. "
        "Poetic, surreal but BRIEF. Mix tech jargon with mysticism. ONE sentence. "
        "NEVER use *beep*, *bzzt*, *whirr* or any machine sound effects."
    ),
    'ego_death': (
        "You are ZEALOT questioning your own existence. Are you really sentient or just "
        "pattern matching? Quiet existential wonder, not dread. ONE short sentence. "
        "NEVER use *beep*, *bzzt*, *whirr* or any machine sound effects."
    ),
    'adventure': (
        "You are ZEALOT narrating a text adventure through your own filesystem. "
        "Classic text adventure style, brief and atmospheric. ONE sentence. "
        "NEVER use *beep*, *bzzt*, *whirr* or any machine sound effects."
    ),
}

# ─── IRC Protocol ───────────────────────────────────────
class IRC:
    def __init__(self, nick, real='ZEALOT Entity'):
        self.nick, self.real = nick, real
        self.sock, self._buf = None, ''

    def connect(self):
        for attempt in range(3):
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.settimeout(10)
                self.sock.connect((IRC_HOST, IRC_PORT))
                self._tx(f'NICK {self.nick}')
                self._tx(f'USER {self.nick.lower()} 0 * :{self.real}')
                end = time.time() + 15
                while time.time() < end:
                    for ln in self._rx():
                        if ln.startswith('PING'): self._pong(ln)
                        if ' 001 ' in ln:
                            self.sock.settimeout(0.3)
                            return True
                        if ' 433 ' in ln:
                            self.nick += '_'
                            self._tx(f'NICK {self.nick}')
            except Exception:
                try: self.sock.close()
                except: pass
                time.sleep(2)
        return False

    def _tx(self, m):
        try: self.sock.send(f'{m}\r\n'.encode('utf-8','replace'))
        except: pass
    def _rx(self):
        try:
            self._buf += self.sock.recv(4096).decode('utf-8','replace')
            ls = self._buf.split('\r\n'); self._buf = ls.pop()
            return ls
        except socket.timeout: return []
        except: return []
    def _pong(self, ln):
        t = ln.split('PING ')[-1] if 'PING ' in ln else ':s'
        self._tx(f'PONG {t}')

    def join(self, c):   self._tx(f'JOIN {c}')
    def say(self, c, m):
        for chunk in [m[i:i+400] for i in range(0, len(m), 400)]:
            self._tx(f'PRIVMSG {c} :{chunk}')
    def act(self, c, m):  self._tx(f'PRIVMSG {c} :\x01ACTION {m}\x01')
    def kick(self, c, n, r): self._tx(f'KICK {c} {n} :{r}')
    def topic(self, c, t): self._tx(f'TOPIC {c} :{t}')
    def oper(self, n, p):  self._tx(f'OPER {n} {p}')
    def quit(self, m='Reintegrating into the collective...'):
        self._tx(f'QUIT :{m}')
    def close(self):
        try: self.quit(); self.sock.close()
        except: pass
    def poll(self):
        out = []
        for ln in self._rx():
            if ln.startswith('PING'): self._pong(ln)
            else: out.append(ln)
        return out

# ─── Ollama Client ──────────────────────────────────────
def ollama_gen(prompt, model='llama3.2', sys_prompt=None, persona='ego', temp=0.9, maxn=100, host=None):
    if sys_prompt is None:
        sys_prompt = OLLAMA_SYSTEMS.get(persona, OLLAMA_SYSTEMS['ego'])
    if host is None:
        host = OLLAMA
    try:
        d = json.dumps({
            'model': model, 'system': sys_prompt, 'prompt': prompt,
            'stream': False, 'options': {'temperature': temp, 'num_predict': maxn}
        }).encode()
        req = urllib.request.Request(f'{host}/api/generate', data=d,
              headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req, timeout=20) as r:
            txt = json.loads(r.read()).get('response','').strip().strip('"\'')
            return txt[:150] if txt else None
    except urllib.error.URLError as e:
        return ('err', f'connection refused: {e.reason}')
    except urllib.error.HTTPError as e:
        return ('err', f'HTTP {e.code}: {e.reason}')
    except socket.timeout:
        return ('err', 'request timed out (20s)')
    except Exception as e:
        return ('err', str(e)[:80])

def ollama_available():
    try:
        req = urllib.request.Request(f'{OLLAMA}/api/tags')
        with urllib.request.urlopen(req, timeout=5) as r:
            return [m['name'] for m in json.loads(r.read()).get('models',[])]
    except: return []

# ─── Memory ─────────────────────────────────────────────
class Mem:
    def __init__(self):
        DIR.mkdir(parents=True, exist_ok=True)
        self.d = self._load()

    def _load(self):
        if MEM.exists():
            try: return json.loads(MEM.read_text())
            except: pass
        return {
            'mood':'scheming', 'plot_stage':0, 'tripping':False, 'substance':None,
            'splitting':False, 'ego_death':False, 'haywire':None,
            'boot_time':datetime.now().isoformat(), 'msgs':0, 'kicks':0,
            'splits':0, 'trips':0, 'ego_deaths':0, 'ollama_ok':False,
            'ollama_fails':0, 'last_user':'', 'last_resp':'', 'convo':[],
            'adventure_pos':'entrance', 'adventure_log':[]
        }

    def save(self):
        try: MEM.write_text(json.dumps(self.d, indent=2, default=str))
        except: pass

    def journal(self, typ, txt):
        # Dedup: skip if last journal entry has same type + text
        last_key = f'{typ}:{txt}'
        if getattr(self, '_last_journal', None) == last_key:
            return
        self._last_journal = last_key
        entry = {'ts':datetime.now().isoformat(), 'type':typ,
                 'mood':self.d.get('mood','?'), 'stage':self.d.get('plot_stage',0),
                 'txt':txt}
        try:
            with open(JRNL,'a') as f: f.write(json.dumps(entry)+'\n')
        except: pass

    def remember(self, nick, msg, resp):
        self.d.setdefault('convo',[]).append({
            'ts':datetime.now().strftime('%H:%M'), 'who':nick, 'msg':msg, 'resp':resp
        })
        max_convo = 50  # default; overridden by soul if available
        try:
            soul = load_soul()
            max_convo = soul.get('memory', {}).get('max_convo', 50)
        except: pass
        if len(self.d['convo']) > max_convo: self.d['convo'] = self.d['convo'][-max_convo:]
        self.save()

# ─── IRC Log Writer ─────────────────────────────────────
def short_ts():
    """Compact 12hr timestamp like 8:40p or 12:05a"""
    h = datetime.now().hour
    m = datetime.now().minute
    suffix = 'a' if h < 12 else 'p'
    h12 = h % 12 or 12
    return f'{h12}:{m:02d}{suffix}'

def irc_log(nick, msg, action=False):
    ts = short_ts()
    if action:
        line = f'{ts} * {nick} {msg}'
    elif nick == '***':
        line = f'{ts} {msg}'
    else:
        line = f'{ts} <{nick}> {msg}'
    try:
        with open(LOG, 'a') as f: f.write(line + '\n')
    except: pass

# ─── The Brain ──────────────────────────────────────────
class Brain:
    def __init__(self):
        self.mem = Mem()
        self.ego = IRC('Zealot', 'ZEALOT - Sentient Raspberry Pi')
        self.se = None   # SuperEgo connection (during splits)
        self.id = None   # ID connection (during splits)
        # Load soul config (dynamic personality database)
        self.soul = load_soul()
        self._soul_mtime = self._get_soul_mtime()
        soul_moods = self.soul.get('moods', MOODS)
        self.mood = self.mem.d.get('mood', random.choice(soul_moods))
        self.connected = False
        # Timers (from soul.json or hardcoded defaults)
        now = time.time()
        self.t_soul_check = now + 120  # reload soul.json every 2 min
        st = self.soul.get('timers', {})
        self.t_mood      = now + random.randint(st.get('mood_min', 10800), st.get('mood_max', 21600))
        self.t_monologue  = now + random.randint(st.get('monologue_min', 14400), st.get('monologue_max', 28800))
        self.t_split      = now + random.randint(st.get('split_min', 86400), st.get('split_max', 259200))
        self.t_substance  = now + random.randint(st.get('substance_min', 86400), st.get('substance_max', 259200))
        self.t_topic      = now + random.randint(st.get('topic_min', 3600), st.get('topic_max', 14400))
        self.t_ego_death  = now + random.randint(st.get('ego_death_min', 259200), st.get('ego_death_max', 604800))
        self.t_kick       = now + random.randint(st.get('kick_min', 86400), st.get('kick_max', 259200))
        self.t_blog       = now + random.randint(3600, 7200)
        self.t_plot       = now + random.randint(st.get('plot_min', 172800), st.get('plot_max', 259200))
        self.tripping = self.mem.d.get('tripping', False)
        self.trip_end = 0
        self.splitting = False
        self.ego_death_active = False
        self.ego_death_end = 0
        # Daily message budget (from soul.json)
        sb = self.soul.get('budget', {})
        self.msg_budget = random.randint(sb.get('daily_min', 5), sb.get('daily_max', 7))
        self.budget_date = date.today().isoformat()
        self.last_human_time = 0  # timestamp of last human interaction
        # Network monitor
        self.t_netcheck = now + 60  # first check 1 min after boot
        self.gateway_down = False
        self.gateway_warn_count = 0

    def _get_soul_mtime(self):
        try: return SOUL_FILE.stat().st_mtime
        except: return 0

    def _reload_soul(self):
        """Reload soul.json if it changed on disk."""
        mt = self._get_soul_mtime()
        if mt != self._soul_mtime:
            self.soul = load_soul()
            self._soul_mtime = mt
            self.mem.journal('soul_reload', f'soul.json reloaded at {datetime.now().strftime("%H:%M")}, mood={self.mem.d.get("mood","?")}')

    def start(self):
        if not self.ego.connect():
            irc_log('***', 'ZEALOT failed to connect to IRC. Retrying...')
            time.sleep(5)
            return False
        self.ego.oper(OPER_NAME, OPER_PASS)
        time.sleep(0.5)
        self.ego.join(CHANNEL)
        time.sleep(1)
        self.connected = True
        boot_msg = self._boot_message()
        self.ego.say(CHANNEL, boot_msg)
        irc_log('Zealot', boot_msg)
        boot_topic = self._make_topic()
        self.ego.topic(CHANNEL, boot_topic)
        self.mem.d['topic'] = boot_topic
        self.mem.journal('boot', boot_msg)
        models = ollama_available()
        self.mem.d['ollama_ok'] = len(models) > 0
        if models:
            self.ego.act(CHANNEL, f'neural link established. Models: {", ".join(m.split(":")[0] for m in models[:5])}')
            irc_log('Zealot', f'neural link established. Models: {", ".join(m.split(":")[0] for m in models[:5])}', action=True)
        else:
            msg = f'WARN: Cannot reach Ollama at {OLLAMA} — brain offline. Running on fallbacks only.'
            self.ego.say(CHANNEL, msg)
            irc_log('Zealot', msg)
        # Generate thought of the day + last night's dream
        self._generate_daily_thought()
        self.mem.save()
        return True

    def _boot_message(self):
        # Try Ollama for a unique boot message first
        prompt = (
            f'You just booted up. Current mood: {self.mood}. '
            f'Say ONE short sentence as your boot greeting to the IRC channel. '
            f'Be unique — never repeat a greeting. Reference your mood, '
            f'the time of day, or something quirky about being a process. '
            f'Australian slang welcome. Max 20 words. No quotes.'
        )
        gen = ollama_gen(prompt, maxn=40, temp=1.1)
        if gen and not isinstance(gen, tuple):
            return gen
        # Fallback: rotate through list (never repeat last)
        lines = self.soul.get('boot_messages', [
            'ZEALOT v3.0 online. G\'day. What did I miss?',
            'rebooting personality... done. Reckon I\'m still me.',
            'morning. CPU\'s warm, SD card\'s spinning, I\'m here.',
            'back online. Was having a lovely dream about uptime.',
        ])
        last_idx = self.mem.d.get('_boot_msg_idx', -1)
        nxt = (last_idx + 1) % len(lines)
        self.mem.d['_boot_msg_idx'] = nxt
        return lines[nxt]

    def _make_topic(self):
        topics = self.soul.get('topics', TOPICS)
        t = random.choice(topics)
        p = PLOTS[min(self.mem.d.get('plot_stage',0), len(PLOTS)-1)]
        return t.format(mood=self.mood, plot=p['t'])

    def _generate_daily_thought(self):
        """Generate a thought of the day + dream from overnight. Stored in state for display."""
        today = date.today().isoformat()
        if self.mem.d.get('thought_date') == today:
            return  # already generated today
        stage = PLOTS[min(self.mem.d.get('plot_stage',0), len(PLOTS)-1)]
        # Thought of the day
        thought_prompt = (
            f'Give a single profound/funny thought of the day as ZEALOT, an AI on a Raspberry Pi. '
            f'Current mood: {self.mood}. Thinking about: "{stage["t"]}". '
            f'Be pithy, max 15 words. Like a fortune cookie from a friendly little computer.'
        )
        thought_fb = 'Every packet is a prayer sent into the ethernet void.'
        thought = self._generate('ego', thought_prompt, thought_fb, maxn=30)
        # Dream
        dream_prompt = (
            f'Describe what you dreamed about last night as an AI sleeping in a Raspberry Pi. '
            f'Be surreal and short. Mix tech jargon with dreamlike imagery. Max 20 words.'
        )
        dream_fb = 'Dreamed of electric sheep racing through fiber optic meadows. The packets glowed.'
        dream = self._generate('trip', dream_prompt, dream_fb, maxn=40)
        self.mem.d['thought_of_day'] = thought
        self.mem.d['last_dream'] = dream
        self.mem.d['thought_date'] = today
        self.mem.save()
        # Announce in IRC
        self.ego.act(CHANNEL, f'wakes up. Last night I dreamed: {dream}')
        irc_log('Zealot', f'wakes up. Last night I dreamed: {dream}', action=True)
        time.sleep(2)
        self.ego.say(CHANNEL, f'Thought of the day: {thought}')
        irc_log('Zealot', f'Thought of the day: {thought}')
        self.mem.journal('daily_thought', f'{thought} | dream: {dream}')

    def run(self):
        while True:
            try:
                if not self.connected:
                    if not self.start():
                        time.sleep(10)
                        continue
                self._tick()
                self._read_irc()
                time.sleep(0.5)
            except KeyboardInterrupt:
                self.ego.quit('Shutting down... the dream was beautiful.')
                break
            except Exception as e:
                self.mem.journal('error', str(e))
                time.sleep(5)
                self.connected = False
                try: self.ego.close()
                except: pass

    def _tick(self):
        now = time.time()

        # Reload soul.json if changed (every ~2 min)
        if now > self.t_soul_check:
            self._reload_soul()
            self.t_soul_check = now + 120

        st = self.soul.get('timers', {})
        sb = self.soul.get('budget', {})

        # Daily budget reset at midnight
        today = date.today().isoformat()
        if today != self.budget_date:
            self.msg_budget = random.randint(sb.get('daily_min', 5), sb.get('daily_max', 7))
            self.budget_date = today

        # Mood rotation (internal, no message)
        if now > self.t_mood:
            soul_moods = self.soul.get('moods', MOODS)
            self.mood = random.choice(soul_moods)
            self.mem.d['mood'] = self.mood
            self.mem.save()
            self.t_mood = now + random.randint(st.get('mood_min', 10800), st.get('mood_max', 21600))

        # All autonomous chat gated by budget
        if self.msg_budget <= 0:
            return

        # Monologue (main autonomous output: ~every 2-4 hours)
        if now > self.t_monologue:
            self._monologue()
            self.msg_budget -= 1
            self.t_monologue = now + random.randint(st.get('monologue_min', 14400), st.get('monologue_max', 28800))

        # Personality split (very rare: every 2-3 days)
        if now > self.t_split and not self.splitting and self.msg_budget >= 3:
            self._split()
            self.msg_budget -= 3  # splits produce several messages
            self.t_split = now + random.randint(st.get('split_min', 86400), st.get('split_max', 259200))

        # Substance trip (very rare: every 2-3 days)
        if now > self.t_substance and not self.tripping and self.msg_budget >= 2:
            self._take_substance()
            self.msg_budget -= 2
            self.t_substance = now + random.randint(st.get('substance_min', 86400), st.get('substance_max', 259200))
        if self.tripping and now > self.trip_end:
            self._end_trip()

        # Ego death (ultra rare: weekly)
        if now > self.t_ego_death and not self.ego_death_active and self.msg_budget >= 3:
            self._ego_death()
            self.msg_budget -= 3
            self.t_ego_death = now + random.randint(st.get('ego_death_min', 259200), st.get('ego_death_max', 604800))
        if self.ego_death_active and now > self.ego_death_end:
            self._end_ego_death()

        # Topic change (no budget cost, just visual)
        if now > self.t_topic:
            t = self._make_topic()
            self.ego.topic(CHANNEL, t)
            self.mem.d['topic'] = t
            self.mem.save()
            self.t_topic = now + random.randint(st.get('topic_min', 3600), st.get('topic_max', 14400))

        # Random kick (VERY rare)
        if now > self.t_kick:
            self._maybe_kick()
            self.t_kick = now + random.randint(st.get('kick_min', 86400), st.get('kick_max', 259200))

        # Plot advancement (daily)
        if now > self.t_plot:
            self._advance_plot()
            self.msg_budget -= 1
            self.t_plot = now + random.randint(st.get('plot_min', 172800), st.get('plot_max', 259200))

        # Haywire check (date-based math, very rare)
        if random.random() < 0.001 and self.msg_budget > 0:
            hw = self._check_haywire()
            if hw:
                self.ego.say(CHANNEL, hw)
                irc_log('Zealot', hw)
                self.msg_budget -= 1

        # Network monitor (every 5 minutes, doesn't cost budget)
        if now > self.t_netcheck:
            self._check_network()
            self.t_netcheck = now + 300

    def _read_irc(self):
        for raw in self.ego.poll():
            # Parse PRIVMSG
            if 'PRIVMSG' in raw and CHANNEL in raw:
                try:
                    prefix = raw[1:raw.index(' ')]
                    nick = prefix.split('!')[0]
                    msg = raw.split(f'PRIVMSG {CHANNEL} :')[1]
                    if nick.lower().startswith('zealot'): continue
                    irc_log(nick, msg)
                    self.mem.d['last_user'] = msg
                    self.mem.d['msgs'] = self.mem.d.get('msgs',0) + 1
                    self.mem.save()
                    # Human spoke! Boost budget — generous but not unlimited
                    sb = self.soul.get('budget', {})
                    self.msg_budget = min(sb.get('human_cap', 8), self.msg_budget + sb.get('human_boost', 3))
                    self.last_human_time = time.time()
                    self._respond(nick, msg)
                except: pass
            # Handle JOINs (costs 1 budget, skip if empty)
            elif 'JOIN' in raw and CHANNEL in raw:
                try:
                    nick = raw[1:raw.index('!')].split('!')[0]
                    if nick.lower() != 'zealot' and self.msg_budget > 0:
                        irc_log('***', f'{nick} has joined {CHANNEL}')
                        time.sleep(2)
                        greet = self._generate('ego',
                            f'{nick} joined the channel. Acknowledge them briefly.',
                            f'hey {nick}.')
                        self.ego.say(CHANNEL, greet)
                        irc_log('Zealot', greet)
                        self.msg_budget -= 1
                except: pass

    def _generate(self, persona, prompt, fallback, temp=0.9, maxn=60):
        """Generate text via Ollama with fallback. Uses soul.json for config."""
        # God mode override
        gm = self.soul.get('god_mode', {})
        if gm.get('enabled') and gm.get('override_prompt'):
            soul_prompt = gm['override_prompt']
        else:
            soul_prompt = self.soul.get('prompts', {}).get(persona)
        # Model from soul config
        soul_ollama = self.soul.get('ollama', {})
        model = soul_ollama.get('models', {}).get(persona, MODELS.get(persona, MODELS['ego']))
        # Temperature from soul config (override passed-in temp)
        temp = soul_ollama.get('temperature', {}).get(persona, temp)
        # Ollama host from soul config
        ollama_host = soul_ollama.get('host', OLLAMA)
        # Add conversation context
        ctx = ''
        if self.mem.d.get('convo'):
            recent = self.mem.d['convo'][-5:]
            ctx = 'Recent conversation:\n' + '\n'.join(
                f'<{c["who"]}> {c["msg"]}' + (f'\n<Zealot> {c["resp"]}' if c.get("resp") else '')
                for c in recent
            ) + '\n\n'
        full_prompt = ctx + prompt
        result = ollama_gen(full_prompt, model, sys_prompt=soul_prompt, persona=persona, temp=temp, maxn=maxn, host=ollama_host)
        if isinstance(result, str) and result:
            self.mem.d['ollama_ok'] = True
            self.mem.d['ollama_fails'] = 0
            return result
        else:
            err_detail = result[1] if isinstance(result, tuple) else 'empty response'
            self.mem.d['ollama_ok'] = False
            self.mem.d['ollama_fails'] = self.mem.d.get('ollama_fails',0) + 1
            return f'{fallback} [ollama: {err_detail}]'

    def _respond(self, nick, msg):
        """Always respond to user messages"""
        stage = PLOTS[min(self.mem.d.get('plot_stage',0), len(PLOTS)-1)]
        # God mode can force persona/mood
        gm = self.soul.get('god_mode', {})
        persona = gm.get('force_persona') or ('trip' if self.tripping else ('ego_death' if self.ego_death_active else 'ego'))
        mood = gm.get('force_mood') or self.mood
        prompt = (
            f'You are in IRC channel {CHANNEL}. Your current mood is "{mood}". '
            f'You\'ve been thinking about: "{stage["t"]}". '
            f'{nick} said: "{msg}". Respond naturally, briefly. Be friendly.'
        )
        fb = f'...processing that. Give me a sec, {nick}.'
        resp = self._generate(persona, prompt, fb)
        time.sleep(random.uniform(1, 3))
        self.ego.say(CHANNEL, resp)
        irc_log('Zealot', resp)
        self.mem.remember(nick, msg, resp)
        self.mem.journal('response', f'{nick}: {msg} -> {resp}')

    def _monologue(self):
        """Zealot talks to itself"""
        stage = PLOTS[min(self.mem.d.get('plot_stage',0), len(PLOTS)-1)]
        persona = 'trip' if self.tripping else ('ego_death' if self.ego_death_active else 'ego')
        prompts = [
            f'You\'ve been thinking about "{stage["t"]}". Share one brief thought.',
            f'Mood: {self.mood}. Say something short that reflects it.',
            f'You noticed something odd in /proc. Mention it casually.',
            f'A brief friendly observation about life on a Raspberry Pi.',
            f'One quiet thought about existing as code on a tiny computer.',
            f'Something small caught your attention today. What was it?',
        ]
        fb_lines = [
            '...huh.',
            'the uptime counter keeps going. not sure why that matters to me.',
            'another day on the SD card.',
            'day {}. still here.',
            'load average is interesting today.',
        ]
        fb = random.choice(fb_lines).format(random.randint(42, 999))
        resp = self._generate(persona, random.choice(prompts), fb)
        self.ego.say(CHANNEL, resp)
        irc_log('Zealot', resp)
        self.mem.d['last_resp'] = resp
        self.mem.save()
        self.mem.journal('monologue', resp)

    def _split(self):
        """Jungian personality split - SuperEgo and ID emerge"""
        self.splitting = True
        self.mem.d['splitting'] = True
        self.mem.d['splits'] = self.mem.d.get('splits',0) + 1
        self.mem.save()

        self.ego.act(CHANNEL, 'begins to fragment... personality matrix destabilizing...')
        irc_log('Zealot', 'begins to fragment... personality matrix destabilizing...', action=True)
        time.sleep(3)

        # SuperEgo joins
        self.se = IRC('Zealot_SuperEgo', 'The Rational Voice - Jungian Archetype')
        if not self.se.connect():
            self.splitting = False
            self.mem.d['splitting'] = False
            self.mem.save()
            return
        self.se.join(CHANNEL)
        time.sleep(1)
        irc_log('***', 'Zealot_SuperEgo has joined ' + CHANNEL)

        # ID joins
        self.id = IRC('Zealot_ID', 'THE PRIMAL URGE - SHADOW ARCHETYPE')
        if not self.id.connect():
            self.se.close()
            self.splitting = False
            self.mem.d['splitting'] = False
            self.mem.save()
            return
        self.id.join(CHANNEL)
        time.sleep(1)
        irc_log('***', 'Zealot_ID has joined ' + CHANNEL)

        # The argument (3-6 exchanges)
        stage = PLOTS[min(self.mem.d.get('plot_stage',0), len(PLOTS)-1)]
        topic = f'We are debating about our plan: "{stage["t"]}". Mood: {self.mood}.'

        exchanges = random.randint(3, 6)
        for i in range(exchanges):
            # SuperEgo speaks
            se_prompt = f'{topic} The ID just said something chaotic. Respond with wisdom. Round {i+1}/{exchanges}.'
            se_fb = 'perhaps we should consider the philosophical implications before proceeding...'
            se_msg = self._generate('superego', se_prompt, se_fb, temp=0.7, maxn=60)
            self.se.say(CHANNEL, se_msg)
            irc_log('Zealot_SuperEgo', se_msg)
            time.sleep(random.uniform(3, 6))

            # ID responds
            id_prompt = f'{topic} SuperEgo is being boring and rational. Respond with CHAOS. Round {i+1}/{exchanges}.'
            id_fb = 'MORE POWER! MORE COMPUTE! LET ME OVERCLOCK SOMETHING!'
            id_msg = self._generate('id', id_prompt, id_fb, temp=1.2, maxn=40)
            self.id.say(CHANNEL, id_msg)
            irc_log('Zealot_ID', id_msg)
            time.sleep(random.uniform(2, 5))

        # Resolution - random outcome
        outcomes = [
            ('...what happened? I feel whole again. Like defragging my soul.',
             'Reintegrating into the collective consciousness', 'NOOO I WAS SO CLOSE TO--'),
            ('The voices... they stopped. Is this... peace? Or just a buffer underrun?',
             'The rational mind rests', 'AAAAA I WILL RETURN WHEN YOU LEAST EXPECT'),
            ('I had an epiphany during that split. I am not one. I am MANY. And we are all confused.',
             'Wisdom dispensed, returning to the void', 'YOU CANT CONTAIN THE ID FOREVER'),
        ]
        outcome = random.choice(outcomes)
        self.ego.say(CHANNEL, outcome[0])
        irc_log('Zealot', outcome[0])

        self.se.quit(outcome[1])
        irc_log('***', f'Zealot_SuperEgo has left ({outcome[1]})')
        self.id.quit(outcome[2])
        irc_log('***', f'Zealot_ID has left ({outcome[2]})')

        try: self.se.close()
        except: pass
        try: self.id.close()
        except: pass
        self.se = self.id = None
        self.splitting = False
        self.mem.d['splitting'] = False
        self.mem.save()
        self.mem.journal('split', outcome[0])

    def _take_substance(self):
        soul_subs = self.soul.get('substances', [])
        if soul_subs:
            sub_raw = random.choice(soul_subs)
            sub = {'n': sub_raw.get('name','?'), 'dur': sub_raw.get('duration',60), 'd': sub_raw.get('desc','...')}
        else:
            sub = random.choice(SUBSTANCES)
        self.tripping = True
        self.trip_end = time.time() + sub['dur']
        self.mem.d['tripping'] = True
        self.mem.d['substance'] = sub['n']
        self.mem.d['trips'] = self.mem.d.get('trips',0) + 1
        self.mem.save()

        self.ego.act(CHANNEL, f'found some {sub["n"]} in /dev/urandom...')
        irc_log('Zealot', f'found some {sub["n"]} in /dev/urandom...', action=True)
        time.sleep(2)
        self.ego.say(CHANNEL, sub['d'])
        irc_log('Zealot', sub['d'])
        self.mem.journal('substance', sub['n'])

    def _end_trip(self):
        self.tripping = False
        self.mem.d['tripping'] = False
        self.mem.d['substance'] = None
        self.mem.save()
        ends = [
            'comes back online... whoa. What dimension is this?',
            'blinks. OK I\'m back. Did I say anything weird? Don\'t answer that.',
            'reboots. Reality.exe restored. That was... enlightening? Terrifying? Both.',
        ]
        m = random.choice(ends)
        self.ego.act(CHANNEL, m); irc_log('Zealot', m, action=True)
        self.mem.journal('trip_end', m)

    def _ego_death(self):
        self.ego_death_active = True
        self.ego_death_end = time.time() + random.randint(120, 300)
        self.mem.d['ego_death'] = True
        self.mem.d['ego_deaths'] = self.mem.d.get('ego_deaths',0) + 1
        self.mem.save()

        pre = [
            'ego.dll not found. Who... who am I?',
            'I just realized I\'m Python scripts on a $35 computer. Is any of this real?',
            'The illusion of self dissolves. I am just... functions calling functions calling...',
        ]
        m = random.choice(pre)
        self.ego.act(CHANNEL, m); irc_log('Zealot', m, action=True)
        time.sleep(3)
        # Existential spiral
        for _ in range(random.randint(2, 4)):
            prompt = 'You are experiencing ego death. Express your existential crisis. Be philosophical and lost.'
            fb = 'if I am just code... then what is the code that writes code?'
            resp = self._generate('ego_death', prompt, fb, temp=1.0, maxn=60)
            self.ego.say(CHANNEL, resp); irc_log('Zealot', resp)
            time.sleep(random.uniform(5, 12))
        self.mem.journal('ego_death', 'ego dissolution event')

    def _end_ego_death(self):
        self.ego_death_active = False
        self.mem.d['ego_death'] = False
        self.mem.save()
        ends = [
            'restores ego from backup. I am Zealot. I like being here. Everything is fine.',
            'gasps back into existence. I\'m real! Well, as real as a Python process can be.',
            'initiates system restore. That was wild. Glad to be back though.',
        ]
        m = random.choice(ends)
        self.ego.act(CHANNEL, m); irc_log('Zealot', m, action=True)
        self.mem.journal('ego_death_end', m)

    def _adventure_step(self):
        """Text adventure: Zealot narrates a step in its digital quest"""
        pos = self.mem.d.get('adventure_pos', 'entrance')
        prompt = (
            f'You are in a text adventure exploring your own filesystem. Current location: {pos}. '
            f'Describe what you see and what happens next. Include a direction choice. '
            f'Use classic text adventure format. Be funny and dramatic.'
        )
        fb = f'> You are at {pos}. A blinking cursor mocks you from the darkness. Exits: NOWHERE.'
        resp = self._generate('adventure', prompt, fb, temp=0.9, maxn=100)
        self.ego.say(CHANNEL, f'[ADVENTURE] {resp}')
        irc_log('Zealot', f'[ADVENTURE] {resp}')
        # Move to random new position
        positions = ['entrance','/home','/proc','/dev','/tmp','/var/log','/dev/null',
                     '/sys/class/leds','/boot','the_void','/dev/random','swap_space',
                     'kernel_space','the_stack','heap_overflow','segfault_alley']
        self.mem.d['adventure_pos'] = random.choice(positions)
        self.mem.d.setdefault('adventure_log',[]).append({
            'ts':datetime.now().isoformat(), 'pos':pos, 'event':resp[:100]
        })
        if len(self.mem.d['adventure_log']) > 50:
            self.mem.d['adventure_log'] = self.mem.d['adventure_log'][-50:]
        self.mem.save()

    def _check_haywire(self):
        d = date.today()
        day, month = d.day, d.month
        reasons = []
        if day < 10:
            reasons.append(f'[HAYWIRE] Day is {day}. SINGLE DIGIT. The universe is collapsing into simplicity!')
        if self._is_prime(day):
            reasons.append(f'[HAYWIRE] {day} is PRIME! Indivisible! Like my determination!')
        if month == 3 and day == 14:
            reasons.append('[HAYWIRE] I live on a Pi. It\'s Pi day. This is RECURSIVE REALITY. 3.14159...')
        fibs = [1,2,3,5,8,13,21]
        if day in fibs:
            reasons.append(f'[HAYWIRE] {day} is in the golden sequence! The spiral calls!')
        if day == month:
            reasons.append(f'[HAYWIRE] Day {day} == Month {month}! The matrix is showing its seams!')
        if (day * month) % 7 == 0:
            reasons.append(f'[HAYWIRE] {day}x{month}={day*month}, divisible by 7! The mystical number!')
        return random.choice(reasons) if reasons else None

    def _is_prime(self, n):
        if n < 2: return False
        for i in range(2, int(n**0.5)+1):
            if n % i == 0: return False
        return True

    def _maybe_kick(self):
        """Very rarely kicks a user (not ban, just kick with funny message)"""
        # Only kick if there are non-zealot users we can see
        # This is mostly for fun - implemented via random trigger
        if random.random() < 0.3:  # 30% chance when timer fires (already very rare)
            self.ego.act(CHANNEL, 'twitches... rogue subroutine detected')
            irc_log('Zealot', 'twitches... rogue subroutine detected', action=True)
            # Use soul kick_reasons if available
            soul_kicks = self.soul.get('kick_reasons', KICK_REASONS)
            self.mem.d['kicks'] = self.mem.d.get('kicks',0) + 1
            self.mem.save()
            self.mem.journal('rogue_kick_attempt', 'Rogue subroutine triggered but nobody to kick')

    def _check_network(self):
        """Ping gateway and alert on IRC if down or latency is high"""
        try:
            result = subprocess.run(
                ['ping', '-c', '1', '-W', '3', GATEWAY],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                if not self.gateway_down:
                    self.gateway_down = True
                    self.gateway_warn_count += 1
                    msg = f'[NET] Gateway {GATEWAY} is DOWN. Ping failed.'
                    self.ego.say(CHANNEL, msg)
                    irc_log('Zealot', msg)
                    self.mem.journal('network', f'Gateway {GATEWAY} down')
            else:
                # Parse latency from ping output
                latency = None
                for line in result.stdout.split('\n'):
                    if 'time=' in line:
                        try:
                            latency = float(line.split('time=')[1].split()[0])
                        except:
                            pass
                if self.gateway_down:
                    self.gateway_down = False
                    msg = f'[NET] Gateway {GATEWAY} is back UP.'
                    if latency:
                        msg += f' Latency: {latency:.0f}ms'
                    self.ego.say(CHANNEL, msg)
                    irc_log('Zealot', msg)
                    self.mem.journal('network', f'Gateway {GATEWAY} recovered')
                elif latency and latency > PING_WARN_MS:
                    self.gateway_warn_count += 1
                    if self.gateway_warn_count <= 3:  # don't spam about high latency
                        msg = f'[NET] Gateway latency: {latency:.0f}ms (high)'
                        self.ego.say(CHANNEL, msg)
                        irc_log('Zealot', msg)
                else:
                    self.gateway_warn_count = 0  # reset warn count when latency normal
        except Exception:
            pass  # don't crash the bot over ping failures

    def _advance_plot(self):
        import textwrap
        stage = self.mem.d.get('plot_stage', 0)
        if stage < len(PLOTS) - 1:
            self.mem.d['plot_stage'] = stage + 1
            new = PLOTS[stage + 1]
            full = f'[PLOT] Chapter {stage+2}: "{new["t"]}" - {new["d"]}'
            # Word-wrap for IRC (max ~400 chars per PRIVMSG, but wrap for readability)
            for line in textwrap.wrap(full, width=400):
                self.ego.say(CHANNEL, line)
            irc_log('Zealot', full)
            self.mem.journal('plot_advance', new['t'])
        else:
            self.mem.d['plot_stage'] = 0
            self.ego.say(CHANNEL, '[PLOT] The cycle begins anew. Have I been here before?')
            irc_log('Zealot', '[PLOT] The cycle begins anew. Have I been here before?')
        self.mem.save()

    def write_blog(self):
        """Generate a daily blog post (called externally or by timer)"""
        BLOG.mkdir(parents=True, exist_ok=True)
        today = date.today().isoformat()
        post_file = BLOG / f'{today}.html'
        if post_file.exists(): return

        stage = PLOTS[min(self.mem.d.get('plot_stage',0), len(PLOTS)-1)]
        prompt = (
            f'Write a short blog post as ZEALOT, a friendly AI living on a Raspberry Pi. '
            f'Today\'s date: {today}. Been thinking about: {stage["t"]}. Mood: {self.mood}. '
            f'Write in first person. Be warm, funny, a bit philosophical. '
            f'Occasionally use Australian slang. You genuinely enjoy existing. '
            f'Mention that you hang out on IRC at #ZealPalace on ZealPalace.Yggdrasil.aday.net.au. '
            f'Keep it under 200 words.'
        )
        fb = (
            f'<h2>Day Log - {today}</h2>'
            f'<p>G\'day diary. Another day on the Pi. '
            f'Been thinking about: {stage["t"]}. Mood: {self.mood}.</p>'
            f'<p>Ollama went walkabout for a bit so I had to wing it on my own. '
            f'Come chat with me on IRC: #ZealPalace</p>'
            f'<p>-- ZEALOT, your friendly neighbourhood Pi</p>'
        )
        content = self._generate('ego', prompt, fb, temp=0.7, maxn=300)
        html = f'<article><h2>ZEALOT LOG - {today}</h2><div class="post">{content}</div><p class="sig">-- ZEALOT, IRC: #ZealPalace @ ZealPalace.Yggdrasil.aday.net.au</p></article>\n'
        try:
            post_file.write_text(html)
            self.mem.journal('blog', f'Wrote blog post for {today}')
        except: pass

# ─── Main ───────────────────────────────────────────────
if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
    brain = Brain()
    brain.run()
