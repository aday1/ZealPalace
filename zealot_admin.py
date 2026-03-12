#!/usr/bin/env python3
"""ZEALOT Admin Panel - Web UI for editing personality, soul, and config.

Runs on port 9666, proxied by nginx at /admin/.
Reads/writes soul.json which zealot_bot.py watches for changes.
"""
import http.server, json, os, sys, signal, time, re, traceback
import urllib.request, urllib.error, urllib.parse
from pathlib import Path
from datetime import datetime
from html import escape as html_escape

PORT = 9666
DIR = Path.home() / '.cache' / 'zealot'
SOUL_FILE = DIR / 'soul.json'
MEM_FILE = DIR / 'state.json'
JRNL_FILE = DIR / 'journal.jsonl'
IRC_LOG = DIR / 'irc.log'
HANGS_LOG = DIR / 'hangs.log'
RPG_LOG = DIR / 'rpg.log'
SOUL_MD = Path('/var/www/ZealPalace/soul.md')
INDEX_HTML = Path('/var/www/ZealPalace/index.html')
NPC_DIR = DIR / 'npc'
NPC_STATE_FILE = NPC_DIR / 'npc_state.json'
RPG_DIR = DIR / 'rpg'
LEADERBOARD_FILE = RPG_DIR / 'leaderboard.json'
BATTLE_FILE = NPC_DIR / 'active_battle.json'
GM_QUEUE_FILE = DIR / 'gm_queue.json'
GM_RESULTS_FILE = DIR / 'gm_results.json'
REALM_EVENT_FILE = RPG_DIR / 'realm_event.json'
GRAVEYARD_FILE = RPG_DIR / 'graveyard.json'

ADMIN_PASS = os.environ.get('ZEALOT_ADMIN_PASS', 'z3al0t_adm1n')

# Dynamic NPC names — read from npc_state.json
def _load_npc_names():
    """Load current NPC names from npc_state.json"""
    try:
        data = json.loads(NPC_STATE_FILE.read_text())
        return [k for k in data if k != '_rpg']
    except:
        return []

# ─── Soul.json Management ──────────────────────────────
def load_soul():
    try:
        return json.loads(SOUL_FILE.read_text())
    except:
        return {}

def save_soul(data):
    data['last_modified'] = datetime.now().isoformat()
    data['modified_by'] = 'admin_panel'
    SOUL_FILE.parent.mkdir(parents=True, exist_ok=True)
    SOUL_FILE.write_text(json.dumps(data, indent=2))

def load_state():
    try:
        return json.loads(MEM_FILE.read_text())
    except:
        return {}

def load_journal(n=50):
    try:
        lines = JRNL_FILE.read_text().strip().split('\n')
        entries = []
        for line in lines[-n:]:
            try:
                entries.append(json.loads(line))
            except:
                pass
        return entries
    except:
        return []

def load_irc_tail(logfile, n=50):
    try:
        lines = logfile.read_text().strip().split('\n')
        return lines[-n:]
    except:
        return []

def queue_gm_command(action, target='all', **kwargs):
    """Append a GM command to the queue file for zealot_rpg.py to process."""
    cmd = {'action': action, 'target': target, 'ts': datetime.now().isoformat()}
    cmd.update(kwargs)
    try:
        queue = json.loads(GM_QUEUE_FILE.read_text())
    except:
        queue = []
    queue.append(cmd)
    GM_QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    GM_QUEUE_FILE.write_text(json.dumps(queue, indent=2))

def load_gm_results():
    """Load latest GM command results for display."""
    try:
        return json.loads(GM_RESULTS_FILE.read_text())
    except:
        return []

def test_ollama(host, model, prompt='Say hi in 5 words.'):
    try:
        d = json.dumps({
            'model': model, 'prompt': prompt,
            'stream': False, 'options': {'num_predict': 30}
        }).encode()
        req = urllib.request.Request(f'{host}/api/generate', data=d,
              headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())
            return {
                'ok': True,
                'response': resp.get('response', ''),
                'model': resp.get('model', model),
                'total_duration_ms': resp.get('total_duration', 0) // 1_000_000,
            }
    except Exception as e:
        return {'ok': False, 'error': str(e)}

def list_ollama_models(host):
    try:
        req = urllib.request.Request(f'{host}/api/tags')
        with urllib.request.urlopen(req, timeout=5) as r:
            models = json.loads(r.read()).get('models', [])
            return [m['name'] for m in models]
    except:
        return []

# ─── HTML Templates ─────────────────────────────────────
def page_header(title='ZEALOT Admin'):
    return f'''<!DOCTYPE html>
<html><head>
<title>{html_escape(title)}</title>
<meta charset="utf-8">
<style>
body {{ background: #0a0a1a; color: #00ff00; font-family: "Courier New", monospace;
       margin: 0; padding: 0; }}
.nav {{ background: #111; border-bottom: 2px solid #333; padding: 8px 16px;
        display: flex; gap: 16px; align-items: center; flex-wrap: wrap; }}
.nav a {{ color: #00ccff; text-decoration: none; padding: 4px 8px; }}
.nav a:hover {{ background: #222; color: #ff6600; }}
.nav a.active {{ background: #003; border-bottom: 2px solid #00ccff; }}
.nav .brand {{ color: #ff00ff; font-weight: bold; font-size: 16px; }}
.container {{ max-width: 900px; margin: 20px auto; padding: 0 16px; }}
h1 {{ color: #ff00ff; border-bottom: 1px solid #333; padding-bottom: 8px; }}
h2 {{ color: #ffff00; margin-top: 24px; }}
h3 {{ color: #00ccff; }}
.card {{ background: #111; border: 1px solid #333; padding: 16px; margin: 12px 0;
         border-radius: 4px; }}
.card-title {{ color: #ffff00; font-weight: bold; margin-bottom: 8px; }}
label {{ display: block; color: #00ccff; margin: 8px 0 4px 0; font-size: 13px; }}
input[type=text], input[type=password], input[type=number] {{
    background: #0a0a2a; color: #00ff00; border: 1px solid #444; padding: 6px 10px;
    font-family: "Courier New", monospace; width: 100%; box-sizing: border-box; }}
textarea {{ background: #0a0a2a; color: #00ff00; border: 1px solid #444; padding: 8px;
           font-family: "Courier New", monospace; width: 100%; box-sizing: border-box;
           resize: vertical; }}
select {{ background: #0a0a2a; color: #00ff00; border: 1px solid #444; padding: 6px;
         font-family: "Courier New", monospace; }}
button, input[type=submit] {{
    background: #003; color: #00ccff; border: 1px solid #00ccff; padding: 8px 16px;
    font-family: "Courier New", monospace; cursor: pointer; margin: 4px 2px; }}
button:hover, input[type=submit]:hover {{ background: #005; color: #fff; }}
.btn-danger {{ border-color: #ff4444; color: #ff4444; }}
.btn-danger:hover {{ background: #400; color: #fff; }}
.btn-success {{ border-color: #44ff44; color: #44ff44; }}
.btn-success:hover {{ background: #040; color: #fff; }}
.flash {{ padding: 10px 16px; margin: 10px 0; border-left: 4px solid; }}
.flash-ok {{ border-color: #44ff44; background: #0a1a0a; color: #44ff44; }}
.flash-err {{ border-color: #ff4444; background: #1a0a0a; color: #ff4444; }}
.log {{ background: #000; border: 1px solid #222; padding: 8px; font-size: 12px;
        max-height: 400px; overflow-y: auto; white-space: pre-wrap; word-break: break-all; }}
.log .ts {{ color: #666; }}
.log .nick {{ color: #00ccff; font-weight: bold; }}
.log .zealot {{ color: #ff00ff; }}
.log .sys {{ color: #444; }}
.status-ok {{ color: #44ff44; }}
.status-err {{ color: #ff4444; }}
table {{ border-collapse: collapse; width: 100%; }}
td, th {{ border: 1px solid #333; padding: 6px 10px; text-align: left; font-size: 13px; }}
th {{ background: #111; color: #00ccff; }}
.grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
@media (max-width: 700px) {{ .grid {{ grid-template-columns: 1fr; }} }}
.two-col {{ display: grid; grid-template-columns: 200px 1fr; gap: 8px; align-items: start; }}
.mono {{ font-family: "Courier New", monospace; }}
</style>
</head><body>
<div class="nav">
<span class="brand">☆ ZEALOT ADMIN</span>
<a href="/admin/">Dashboard</a>
<a href="/admin/soul">Soul &amp; Identity</a>
<a href="/admin/prompts">Prompts</a>
<a href="/admin/timers">Timers &amp; Budget</a>
<a href="/admin/ollama">Ollama</a>
<a href="/admin/logs">Logs</a>
<a href="/admin/journal">Journal</a>
<a href="/admin/npcs">NPCs</a>
<a href="/admin/rpg">RPG</a>
<a href="/admin/webring">Webring</a>
<a href="/admin/gamemaster">Gamemaster</a>
<a href="/admin/godmode">God Mode</a>
<a href="/admin/display">Display</a>
<a href="/" style="color:#666">← Site</a>
</div>
<div class="container">
'''

PAGE_FOOTER = '</div></body></html>'

# ─── Admin Request Handler ──────────────────────────────
class AdminHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _html(self, code, body):
        data = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, url):
        self.send_response(302)
        self.send_header('Location', url)
        self.end_headers()

    def _read_post(self):
        length = int(self.headers.get('Content-Length', 0))
        if length > 1_000_000:
            return {}
        body = self.rfile.read(length).decode('utf-8', 'replace')
        return urllib.parse.parse_qs(body, keep_blank_values=True)

    def do_GET(self):
        path = self.path.split('?')[0].rstrip('/')
        if path == '/admin' or path == '/admin/':
            path = '/admin'

        routes = {
            '/admin': self._page_dashboard,
            '/admin/soul': self._page_soul,
            '/admin/prompts': self._page_prompts,
            '/admin/timers': self._page_timers,
            '/admin/ollama': self._page_ollama,
            '/admin/logs': self._page_logs,
            '/admin/journal': self._page_journal,
            '/admin/npcs': self._page_npcs,
            '/admin/rpg': self._page_rpg,
            '/admin/webring': self._page_webring,
            '/admin/godmode': self._page_godmode,
            '/admin/gamemaster': self._page_gamemaster,
            '/admin/display': self._page_display,
        }
        handler = routes.get(path)
        if handler:
            handler()
        else:
            self._html(404, page_header('404') + '<h1>404 - Not Found</h1>' + PAGE_FOOTER)

    def do_POST(self):
        path = self.path.split('?')[0].rstrip('/')
        data = self._read_post()

        routes = {
            '/admin/soul': self._save_soul,
            '/admin/prompts': self._save_prompts,
            '/admin/timers': self._save_timers,
            '/admin/ollama': self._save_ollama,
            '/admin/ollama/test': self._test_ollama,
            '/admin/webring': self._save_webring,
            '/admin/godmode': self._save_godmode,
            '/admin/gamemaster': self._save_gamemaster,
            '/admin/display': self._save_display,
            '/admin/display/reset': self._reset_display,
            '/admin/generate': self._generate_field,
        }
        handler = routes.get(path)
        if handler:
            handler(data)
        else:
            self._html(404, page_header('404') + '<h1>404</h1>' + PAGE_FOOTER)

    # ─── Dashboard ──────────────────────────────────────
    def _page_dashboard(self):
        soul = load_soul()
        state = load_state()
        models = list_ollama_models(soul.get('ollama', {}).get('host', 'http://10.13.37.5:11434'))

        mood = state.get('mood', '?')
        plot_i = state.get('plot_stage', 0)
        ollama_ok = len(models) > 0
        msgs = state.get('msgs', 0)
        fails = state.get('ollama_fails', 0)
        boot = state.get('boot_time', '?')
        thought = state.get('thought_of_day', '')
        dream = state.get('last_dream', '')
        last_mod = soul.get('last_modified', '?')

        html = page_header('Dashboard') + f'''
<h1>☆ ZEALOT Dashboard</h1>

<div class="grid">
<div class="card">
<div class="card-title">Bot Status</div>
<table>
<tr><td>Mood</td><td><b style="color:#ffff00">{html_escape(mood)}</b></td></tr>
<tr><td>Plot Stage</td><td>{plot_i}</td></tr>
<tr><td>Messages Seen</td><td>{msgs}</td></tr>
<tr><td>Ollama</td><td class="{"status-ok" if ollama_ok else "status-err"}">{"● Online" if ollama_ok else "● Offline"} (fails: {fails})</td></tr>
<tr><td>Boot Time</td><td>{html_escape(str(boot))}</td></tr>
<tr><td>Tripping</td><td>{"Yes" if state.get("tripping") else "No"}</td></tr>
<tr><td>Ego Death</td><td>{"Active" if state.get("ego_death") else "No"}</td></tr>
</table>
</div>

<div class="card">
<div class="card-title">Soul Config</div>
<table>
<tr><td>Name</td><td>{html_escape(soul.get("identity", {}).get("name", "Zealot"))}</td></tr>
<tr><td>Last Modified</td><td>{html_escape(str(last_mod))}</td></tr>
<tr><td>Modified By</td><td>{html_escape(soul.get("modified_by", "?"))}</td></tr>
<tr><td>Models Available</td><td>{len(models)}: {", ".join(m.split(":")[0] for m in models[:6])}</td></tr>
<tr><td>God Mode</td><td>{"ACTIVE" if soul.get("god_mode", {}).get("enabled") else "Off"}</td></tr>
</table>
</div>
</div>

<div class="card">
<div class="card-title">Thought of the Day</div>
<p style="color:#fff">{html_escape(thought) if thought else "<i>none yet</i>"}</p>
<div class="card-title">Last Dream</div>
<p style="color:#cc99ff">{html_escape(dream) if dream else "<i>none yet</i>"}</p>
</div>

<div class="card">
<div class="card-title">Quick Actions</div>
<form method="POST" action="/admin/generate" style="display:inline">
<input type="hidden" name="field" value="thought">
<button type="submit">Generate New Thought</button>
</form>
<form method="POST" action="/admin/generate" style="display:inline">
<input type="hidden" name="field" value="dream">
<button type="submit">Generate New Dream</button>
</form>
<form method="POST" action="/admin/generate" style="display:inline">
<input type="hidden" name="field" value="blog">
<button type="submit">Write Blog Post</button>
</form>
</div>
''' + PAGE_FOOTER
        self._html(200, html)

    # ─── Soul & Identity ────────────────────────────────
    def _page_soul(self):
        soul = load_soul()
        identity = soul.get('identity', {})
        html = page_header('Soul & Identity') + f'''
<h1>Soul & Identity</h1>
<p style="color:#666">Edit who Zealot is at the core. Changes take effect within minutes.</p>

<form method="POST" action="/admin/soul">
<div class="card">
<div class="card-title">Identity</div>
<label>Name</label>
<input type="text" name="name" value="{html_escape(identity.get('name', 'Zealot'))}">
<label>Tagline</label>
<input type="text" name="tagline" value="{html_escape(identity.get('tagline', ''))}">
<label>Soul Text (the core of who Zealot is — drives all behavior)</label>
<textarea name="soul_text" rows="6">{html_escape(identity.get('soul_text', ''))}</textarea>
<label>Personality Notes (traits, quirks, style guidance)</label>
<textarea name="personality_notes" rows="4">{html_escape(identity.get('personality_notes', ''))}</textarea>
</div>

<div class="card">
<div class="card-title">Moods (one per line)</div>
<textarea name="moods" rows="6">{chr(10).join(soul.get('moods', []))}</textarea>
</div>

<div class="card">
<div class="card-title">Boot Messages (one per line)</div>
<textarea name="boot_messages" rows="5">{chr(10).join(soul.get('boot_messages', []))}</textarea>
</div>

<div class="card">
<div class="card-title">Kick Reasons (one per line)</div>
<textarea name="kick_reasons" rows="5">{chr(10).join(soul.get('kick_reasons', []))}</textarea>
</div>

<div class="card">
<div class="card-title">Topics (one per line, use {{mood}} and {{plot}})</div>
<textarea name="topics" rows="5">{chr(10).join(soul.get('topics', []))}</textarea>
</div>

<div class="card">
<div class="card-title">Substances</div>
<textarea name="substances" rows="6">{json.dumps(soul.get('substances', []), indent=2)}</textarea>
<p style="color:#666; font-size:11px">JSON array of {{"name":"...", "duration":N, "desc":"..."}}</p>
</div>

<input type="submit" value="Save Soul" class="btn-success">
</form>

<h2>Generate with Ollama</h2>
<div class="card">
<p>Ask Ollama to suggest new soul text, moods, or personality notes:</p>
<form method="POST" action="/admin/generate">
<input type="hidden" name="field" value="soul_text">
<label>Prompt for Ollama</label>
<textarea name="prompt" rows="3">Rewrite Zealot's soul text. Keep the Aussie BSD admin vibe, warm and friendly. Include a bit about hacking lightbulbs for fun. 2-3 sentences.</textarea>
<button type="submit">Generate Soul Text</button>
</form>
</div>
''' + PAGE_FOOTER
        self._html(200, html)

    def _save_soul(self, data):
        soul = load_soul()
        identity = soul.setdefault('identity', {})
        identity['name'] = data.get('name', ['Zealot'])[0][:50]
        identity['tagline'] = data.get('tagline', [''])[0][:200]
        identity['soul_text'] = data.get('soul_text', [''])[0][:2000]
        identity['personality_notes'] = data.get('personality_notes', [''])[0][:2000]
        # Split textarea lines into arrays
        soul['moods'] = [m.strip() for m in data.get('moods', [''])[0].split('\n') if m.strip()]
        soul['boot_messages'] = [m.strip() for m in data.get('boot_messages', [''])[0].split('\n') if m.strip()]
        soul['kick_reasons'] = [m.strip() for m in data.get('kick_reasons', [''])[0].split('\n') if m.strip()]
        soul['topics'] = [t.strip() for t in data.get('topics', [''])[0].split('\n') if t.strip()]
        # Parse substances JSON
        try:
            soul['substances'] = json.loads(data.get('substances', ['[]'])[0])
        except:
            pass
        save_soul(soul)
        self._redirect('/admin/soul')

    # ─── Prompts ────────────────────────────────────────
    def _page_prompts(self):
        soul = load_soul()
        prompts = soul.get('prompts', {})
        personas = ['ego', 'superego', 'id', 'trip', 'ego_death', 'adventure']
        cards = ''
        for p in personas:
            cards += f'''
<div class="card">
<div class="card-title">{html_escape(p.upper())}</div>
<textarea name="prompt_{p}" rows="5">{html_escape(prompts.get(p, ''))}</textarea>
<form method="POST" action="/admin/generate" style="margin-top:8px">
<input type="hidden" name="field" value="prompt_{p}">
<textarea name="prompt" rows="2" style="font-size:11px">Rewrite the {p} persona prompt. Keep it 1-3 sentences. Aussie BSD admin vibe, friendly, BRIEF.</textarea>
<button type="submit" style="font-size:11px">Generate with Ollama</button>
</form>
</div>'''
        html = page_header('Prompts') + f'''
<h1>Personality Prompts</h1>
<p style="color:#666">System prompts sent to Ollama for each persona. These define how Zealot talks.</p>
<form method="POST" action="/admin/prompts">
{cards}
<input type="submit" value="Save All Prompts" class="btn-success">
</form>
''' + PAGE_FOOTER
        self._html(200, html)

    def _save_prompts(self, data):
        soul = load_soul()
        prompts = soul.setdefault('prompts', {})
        for key in ['ego', 'superego', 'id', 'trip', 'ego_death', 'adventure']:
            val = data.get(f'prompt_{key}', [''])[0]
            if val.strip():
                prompts[key] = val.strip()[:2000]
        save_soul(soul)
        self._redirect('/admin/prompts')

    # ─── Timers & Budget ────────────────────────────────
    def _page_timers(self):
        soul = load_soul()
        timers = soul.get('timers', {})
        budget = soul.get('budget', {})
        memory = soul.get('memory', {})
        rpg = soul.get('rpg', {})

        def timer_row(label, key_min, key_max):
            vmin = timers.get(key_min, 3600)
            vmax = timers.get(key_max, 7200)
            hmin = vmin / 3600
            hmax = vmax / 3600
            return f'''<tr>
<td>{html_escape(label)}</td>
<td><input type="number" name="{key_min}" value="{vmin}" style="width:100px"> sec ({hmin:.1f}h)</td>
<td><input type="number" name="{key_max}" value="{vmax}" style="width:100px"> sec ({hmax:.1f}h)</td>
</tr>'''

        html = page_header('Timers & Budget') + f'''
<h1>Timers & Budget</h1>
<form method="POST" action="/admin/timers">
<div class="card">
<div class="card-title">Timer Ranges (seconds)</div>
<table>
<tr><th>Event</th><th>Min</th><th>Max</th></tr>
{timer_row("Mood Change", "mood_min", "mood_max")}
{timer_row("Monologue", "monologue_min", "monologue_max")}
{timer_row("Personality Split", "split_min", "split_max")}
{timer_row("Substance Trip", "substance_min", "substance_max")}
{timer_row("Topic Change", "topic_min", "topic_max")}
{timer_row("Ego Death", "ego_death_min", "ego_death_max")}
{timer_row("Random Kick", "kick_min", "kick_max")}
{timer_row("Plot Advance", "plot_min", "plot_max")}
</table>
</div>

<div class="card">
<div class="card-title">Message Budget</div>
<div class="grid">
<div>
<label>Daily Min</label>
<input type="number" name="budget_daily_min" value="{budget.get('daily_min', 5)}">
</div>
<div>
<label>Daily Max</label>
<input type="number" name="budget_daily_max" value="{budget.get('daily_max', 7)}">
</div>
<div>
<label>Human Boost</label>
<input type="number" name="budget_human_boost" value="{budget.get('human_boost', 3)}">
</div>
<div>
<label>Human Cap</label>
<input type="number" name="budget_human_cap" value="{budget.get('human_cap', 8)}">
</div>
</div>
</div>

<div class="card">
<div class="card-title">Memory Settings</div>
<div class="grid">
<div>
<label>Max Conversation Memory</label>
<input type="number" name="mem_max_convo" value="{memory.get('max_convo', 50)}">
</div>
<div>
<label>Max Journal Entries</label>
<input type="number" name="mem_max_journal" value="{memory.get('max_journal', 5000)}">
</div>
</div>
</div>

<div class="card">
<div class="card-title">RPG / NPC Settings</div>
<div class="grid">
<div>
<label>NPC Tick Interval (sec)</label>
<input type="number" name="rpg_tick_interval" value="{rpg.get('tick_interval', 300)}" min="30">
<span style="color:#666">How often an NPC acts ({rpg.get('tick_interval', 300)//60}min)</span>
</div>
<div>
<label>NPC Budget (per block)</label>
<input type="number" name="rpg_block_budget" value="{rpg.get('block_budget', 8)}" min="1">
<span style="color:#666">Actions per NPC per block</span>
</div>
<div>
<label>Budget Block (hours)</label>
<input type="number" name="rpg_block_hours" value="{rpg.get('block_hours', 8)}" min="1">
<span style="color:#666">Hours before budget resets</span>
</div>
<div>
<label>React Chance (0-100%)</label>
<input type="number" name="rpg_react_pct" value="{int(rpg.get('react_chance', 0.6) * 100)}" min="0" max="100">
<span style="color:#666">NPC reacts to human in same room</span>
</div>
<div>
<label>Ambient Event Min (sec)</label>
<input type="number" name="rpg_ambient_min" value="{rpg.get('ambient_min', 3600)}" min="60">
<span style="color:#666">{rpg.get('ambient_min', 3600)//60}min</span>
</div>
<div>
<label>Ambient Event Max (sec)</label>
<input type="number" name="rpg_ambient_max" value="{rpg.get('ambient_max', 10800)}" min="60">
<span style="color:#666">{rpg.get('ambient_max', 10800)//60}min</span>
</div>
</div>
</div>

<input type="submit" value="Save Timers & Budget" class="btn-success">
</form>

<div class="card">
<div class="card-title">Activity Calculator (estimated per 24 hours)</div>
{self._calc_activity(rpg, budget, timers)}
</div>
''' + PAGE_FOOTER
        self._html(200, html)

    def _calc_activity(self, rpg, budget, timers):
        """Calculate human-readable activity estimates based on current timer settings"""
        tick_sec = rpg.get('tick_interval', 300)
        block_budget = rpg.get('block_budget', 8)
        block_hours = rpg.get('block_hours', 8)
        ambient_min = rpg.get('ambient_min', 3600)
        ambient_max = rpg.get('ambient_max', 10800)
        react_pct = rpg.get('react_chance', 0.6) * 100
        daily_min = budget.get('daily_min', 5)
        daily_max = budget.get('daily_max', 7)

        npc_count = len(_load_npc_names()) or 9

        # NPC ticks per 24h
        ticks_per_day = int(86400 / tick_sec) if tick_sec > 0 else 0
        tick_min = tick_sec / 60

        # Budget resets per 24h
        resets_per_day = 24 / block_hours if block_hours > 0 else 0
        actions_per_npc_day = int(block_budget * resets_per_day)
        total_npc_actions = actions_per_npc_day * npc_count

        # But ticks gate it: only 1 NPC acts per tick
        actual_npc_msgs = min(ticks_per_day, total_npc_actions)

        # Ambient DM events per 24h
        avg_ambient_sec = (ambient_min + ambient_max) / 2
        ambient_per_day = int(86400 / avg_ambient_sec) if avg_ambient_sec > 0 else 0

        # Zealot bot messages
        zealot_msgs = f'{daily_min}-{daily_max}'

        # Special events
        tavern_per_day = '0-1 (weekly, checked every 6h)'
        opera_per_day = '0-1 (biweekly, checked every 12h)'
        deity_checks = int(86400 / 1800)

        rows = ''
        def row(label, value, note=''):
            n = f'<span style="color:#666">{note}</span>' if note else ''
            return f'<tr><td>{label}</td><td style="color:#44ff44;font-weight:bold">{value}</td><td>{n}</td></tr>'

        rows += row('NPC tick interval', f'{tick_sec}s = {tick_min:.0f} min', 'one random NPC acts per tick')
        rows += row('NPC ticks / 24h', f'{ticks_per_day}', f'{ticks_per_day} chances for NPCs to speak/act')
        rows += row('Budget per NPC / block', f'{block_budget} actions / {block_hours}h', f'resets {resets_per_day:.1f}x/day')
        rows += row('Actions per NPC / 24h', f'{actions_per_npc_day}', f'budget allows this many per NPC')
        rows += row('Total NPC budget (all)', f'{total_npc_actions}', f'{npc_count} NPCs x {actions_per_npc_day} actions')
        rows += row('Effective NPC messages / 24h', f'~{actual_npc_msgs}', f'min(ticks, total budget) = actual output')
        rows += row('Avg time between NPC msgs', f'{86400/actual_npc_msgs:.0f}s = {86400/actual_npc_msgs/60:.1f} min' if actual_npc_msgs > 0 else 'N/A', '')
        rows += row('Ambient DM events / 24h', f'~{ambient_per_day}', f'avg {avg_ambient_sec/60:.0f} min between events')
        rows += row('Zealot bot msgs / 24h', zealot_msgs, 'main personality messages')
        rows += row('NPC react chance', f'{react_pct:.0f}%', 'when human enters same room')
        rows += row('Tavern Night', tavern_per_day, '')
        rows += row('Outdoor Opera', opera_per_day, '')
        rows += row('Deity checks / 24h', f'{deity_checks}', 'every 30min')

        total_low = actual_npc_msgs + ambient_per_day + daily_min
        total_high = actual_npc_msgs + ambient_per_day + daily_max
        rows += f'<tr style="border-top:2px solid #00ccff"><td style="color:#ff00ff;font-weight:bold">TOTAL est. messages / 24h</td><td style="color:#ff00ff;font-weight:bold">~{total_low}-{total_high}</td><td><span style="color:#666">≈ 1 message every {86400/((total_low+total_high)/2):.0f}s = {86400/((total_low+total_high)/2)/60:.1f} min</span></td></tr>'

        return f'<table><tr><th>Metric</th><th>Value</th><th>Notes</th></tr>{rows}</table>'

    def _save_timers(self, data):
        soul = load_soul()
        timers = soul.setdefault('timers', {})
        for key in ['mood_min','mood_max','monologue_min','monologue_max',
                     'split_min','split_max','substance_min','substance_max',
                     'topic_min','topic_max','ego_death_min','ego_death_max',
                     'kick_min','kick_max','plot_min','plot_max']:
            val = data.get(key, [''])[0]
            if val:
                try: timers[key] = int(val)
                except: pass
        budget = soul.setdefault('budget', {})
        for key, skey in [('budget_daily_min','daily_min'), ('budget_daily_max','daily_max'),
                          ('budget_human_boost','human_boost'), ('budget_human_cap','human_cap')]:
            val = data.get(key, [''])[0]
            if val:
                try: budget[skey] = int(val)
                except: pass
        memory = soul.setdefault('memory', {})
        for key, skey in [('mem_max_convo','max_convo'), ('mem_max_journal','max_journal')]:
            val = data.get(key, [''])[0]
            if val:
                try: memory[skey] = int(val)
                except: pass
        rpg = soul.setdefault('rpg', {})
        for key, skey in [('rpg_tick_interval','tick_interval'), ('rpg_block_budget','block_budget'),
                          ('rpg_block_hours','block_hours'), ('rpg_ambient_min','ambient_min'),
                          ('rpg_ambient_max','ambient_max')]:
            val = data.get(key, [''])[0]
            if val:
                try: rpg[skey] = max(1, int(val))
                except: pass
        react_val = data.get('rpg_react_pct', [''])[0]
        if react_val:
            try: rpg['react_chance'] = max(0, min(100, int(react_val))) / 100.0
            except: pass
        save_soul(soul)
        self._redirect('/admin/timers')

    # ─── Ollama ─────────────────────────────────────────
    def _page_ollama(self):
        soul = load_soul()
        ollama = soul.get('ollama', {})
        host = ollama.get('host', 'http://10.13.37.5:11434')
        models_cfg = ollama.get('models', {})
        temps = ollama.get('temperature', {})
        available = list_ollama_models(host)

        def model_select(persona, current):
            opts = ''.join(f'<option value="{html_escape(m)}" {"selected" if m == current else ""}>{html_escape(m)}</option>'
                          for m in available)
            return f'<select name="model_{persona}">{opts}</select>'

        rows = ''
        for p in ['ego', 'superego', 'id']:
            cur_model = models_cfg.get(p, 'llama3.2')
            cur_temp = temps.get(p, 0.9)
            rows += f'''<tr>
<td>{p.upper()}</td>
<td>{model_select(p, cur_model)}</td>
<td><input type="text" name="temp_{p}" value="{cur_temp}" style="width:60px"></td>
</tr>'''
        for p in ['trip', 'ego_death', 'adventure']:
            cur_temp = temps.get(p, 0.9)
            rows += f'''<tr>
<td>{p.upper()}</td><td>(uses ego model)</td>
<td><input type="text" name="temp_{p}" value="{cur_temp}" style="width:60px"></td>
</tr>'''

        html = page_header('Ollama') + f'''
<h1>Ollama Configuration</h1>
<form method="POST" action="/admin/ollama">
<div class="card">
<div class="card-title">Connection</div>
<label>Ollama Host</label>
<input type="text" name="host" value="{html_escape(host)}">
<p class="{"status-ok" if available else "status-err"}" style="font-size:13px">
{"● Connected — " + str(len(available)) + " models available" if available else "● Cannot reach Ollama"}</p>
</div>

<div class="card">
<div class="card-title">Model Assignment</div>
<table>
<tr><th>Persona</th><th>Model</th><th>Temperature</th></tr>
{rows}
</table>
</div>
<input type="submit" value="Save Ollama Config" class="btn-success">
</form>

<h2>Test Generation</h2>
<div class="card">
<form method="POST" action="/admin/ollama/test">
<label>Model</label>
<select name="model">
{''.join(f'<option value="{html_escape(m)}">{html_escape(m)}</option>' for m in available)}
</select>
<label>Prompt</label>
<textarea name="prompt" rows="2">Say g'day in character as an AI on a Raspberry Pi. One sentence.</textarea>
<button type="submit">Test Generate</button>
</form>
</div>
''' + PAGE_FOOTER
        self._html(200, html)

    def _save_ollama(self, data):
        soul = load_soul()
        ollama = soul.setdefault('ollama', {})
        host = data.get('host', [''])[0].strip()
        if host:
            ollama['host'] = host
        models = ollama.setdefault('models', {})
        temps = ollama.setdefault('temperature', {})
        for p in ['ego', 'superego', 'id']:
            val = data.get(f'model_{p}', [''])[0]
            if val: models[p] = val
        for p in ['ego', 'superego', 'id', 'trip', 'ego_death', 'adventure']:
            val = data.get(f'temp_{p}', [''])[0]
            if val:
                try: temps[p] = float(val)
                except: pass
        save_soul(soul)
        self._redirect('/admin/ollama')

    def _test_ollama(self, data):
        soul = load_soul()
        host = soul.get('ollama', {}).get('host', 'http://10.13.37.5:11434')
        model = data.get('model', ['llama3.2'])[0]
        prompt = data.get('prompt', ['Say hi'])[0][:500]
        result = test_ollama(host, model, prompt)
        if result['ok']:
            flash = f'''<div class="flash flash-ok">
<b>Success!</b> Model: {html_escape(result.get("model","?"))},
Duration: {result.get("total_duration_ms", "?")}ms<br>
Response: <b>{html_escape(result.get("response",""))}</b>
</div>'''
        else:
            flash = f'<div class="flash flash-err"><b>Error:</b> {html_escape(result.get("error","unknown"))}</div>'

        html = page_header('Ollama Test') + f'''
<h1>Ollama Test Result</h1>
{flash}
<a href="/admin/ollama">← Back to Ollama</a>
''' + PAGE_FOOTER
        self._html(200, html)

    # ─── Logs ───────────────────────────────────────────
    def _page_logs(self):
        irc = load_irc_tail(IRC_LOG, 80)
        hangs = load_irc_tail(HANGS_LOG, 40)
        rpg = load_irc_tail(RPG_LOG, 40)

        def format_log(lines):
            out = ''
            for line in lines:
                esc = html_escape(line)
                if '<Zealot>' in esc or '<Zealot_' in esc:
                    out += f'<span class="zealot">{esc}</span>\n'
                elif '***' in esc or '* ' in esc:
                    out += f'<span class="sys">{esc}</span>\n'
                else:
                    out += esc + '\n'
            return out

        html = page_header('Logs') + f'''
<h1>IRC Logs</h1>
<div class="card">
<div class="card-title">#ZealPalace (last 80 lines)</div>
<div class="log">{format_log(irc)}</div>
</div>
<div class="card">
<div class="card-title">#ZealHangs (last 40 lines)</div>
<div class="log">{format_log(hangs)}</div>
</div>
<div class="card">
<div class="card-title">#RPG (last 40 lines)</div>
<div class="log">{format_log(rpg)}</div>
</div>
''' + PAGE_FOOTER
        self._html(200, html)

    # ─── Journal ────────────────────────────────────────
    def _page_journal(self):
        entries = load_journal(100)
        rows = ''
        for e in reversed(entries):
            ts = e.get('ts', '?')[:19]
            typ = e.get('type', '?')
            mood = e.get('mood', '?')
            txt = e.get('txt', '')[:200]
            rows += f'''<tr>
<td style="color:#666">{html_escape(ts)}</td>
<td>{html_escape(typ)}</td>
<td>{html_escape(mood)}</td>
<td>{html_escape(txt)}</td>
</tr>'''

        html = page_header('Journal') + f'''
<h1>Zealot's Journal</h1>
<p style="color:#666">Everything Zealot records about itself. Most recent first.</p>
<div class="card">
<table>
<tr><th>Time</th><th>Type</th><th>Mood</th><th>Entry</th></tr>
{rows}
</table>
</div>
''' + PAGE_FOOTER
        self._html(200, html)

    # ─── NPCs ────────────────────────────────────────────
    def _page_npcs(self):
        # Read NPC state
        try:
            npc_state = json.loads(NPC_STATE_FILE.read_text())
        except:
            npc_state = {}

        npc_cards = ''
        for name in sorted(k for k in npc_state if k != '_rpg'):
            state = npc_state[name]
            connected = state.get('connected', False)
            alive = state.get('alive', False)
            hp = state.get('hp', '?')
            level = state.get('level', 0)
            kills = state.get('kills', 0)
            location = state.get('location', '?')
            budget = state.get('budget', 0)
            role = state.get('role', '?')
            model = state.get('model', '?')
            fight_style = state.get('fight_style', '?')

            # Read journal
            jfile = NPC_DIR / f'{name.lower()}_journal.jsonl'
            journal_lines = ''
            try:
                lines = jfile.read_text().strip().split('\\n')
                for line in lines[-8:]:
                    try:
                        e = json.loads(line)
                        ts = e.get('ts', '?')[:16]
                        journal_lines += f'<span class="ts">[{html_escape(ts)}]</span> '
                        journal_lines += f'{html_escape(e.get("type","?"))}: '
                        journal_lines += f'{html_escape(e.get("text","")[:80])}\\n'
                    except:
                        pass
            except:
                journal_lines = '<i>No journal entries yet</i>'

            status_icon = '<span class="status-ok">\u25cf Online</span>' if connected else '<span class="status-err">\u25cb Offline</span>'
            alive_icon = '\u2665 Alive' if alive else '\u2620 Dead'

            npc_cards += f'''
<div class="card">
<div class="card-title">{html_escape(name)} — {html_escape(role)} ({html_escape(model)})</div>
<table>
<tr><td>Status</td><td>{status_icon}</td></tr>
<tr><td>Health</td><td>{alive_icon} | HP: {html_escape(str(hp))}</td></tr>
<tr><td>Level</td><td>{level} | Kills: {kills}</td></tr>
<tr><td>Location</td><td>{html_escape(str(location))}</td></tr>
<tr><td>Budget</td><td>{budget} actions remaining</td></tr>
<tr><td>Fight Style</td><td>{html_escape(fight_style)}</td></tr>
</table>
<div style="margin-top:8px">
<div class="card-title" style="font-size:12px">Journal (recent)</div>
<div class="log" style="max-height:120px; font-size:11px">{journal_lines}</div>
</div>
</div>'''

        if not npc_cards:
            npc_cards = '<div class="card"><p style="color:#666">No NPCs active — they will appear after the RPG engine boots.</p></div>'

        html = page_header('NPCs') + f'''
<h1>NPC Adventurers</h1>
<p style="color:#666">These bots live in #RPG, wander the dungeon, fight monsters, and keep journals.
Manage them via IRC: /npc_help in #RPG (admin only).</p>

<div class="card">
<div class="card-title">IRC Admin Commands</div>
<table>
<tr><td><code>/npc_spawn [name|all]</code></td><td>Spawn NPC(s) into the dungeon</td></tr>
<tr><td><code>/npc_kill &lt;name|all&gt;</code></td><td>Disconnect NPC(s)</td></tr>
<tr><td><code>/npc_budget &lt;name|all&gt; &lt;n&gt;</code></td><td>Set action budget</td></tr>
<tr><td><code>/npc_status</code></td><td>Show all NPC status</td></tr>
<tr><td><code>/npc_journal &lt;name&gt; [n]</code></td><td>Read NPC journal entries</td></tr>
</table>
</div>

<div class="grid">
{npc_cards}
</div>
''' + PAGE_FOOTER
        self._html(200, html)

    # ─── RPG Leaderboard ───────────────────────────────
    def _page_rpg(self):
        # Load leaderboard
        try:
            lb = json.loads(LEADERBOARD_FILE.read_text())
        except:
            lb = {}

        # Load all player files
        players = []
        try:
            for f in RPG_DIR.glob('*.json'):
                if f.name in ('world.json', 'leaderboard.json'):
                    continue
                try:
                    p = json.loads(f.read_text())
                    if 'nick' in p:
                        players.append(p)
                except:
                    pass
        except:
            pass

        # Active battle
        battle_html = '<p style="color:#666">No active battle</p>'
        try:
            bd = json.loads(BATTLE_FILE.read_text())
            if bd.get('active'):
                m = bd.get('monster', {})
                party = bd.get('party', {})
                party_str = ', '.join(
                    f'{n} (HP:{d.get("hp","?")})'
                    for n, d in party.items()
                )
                boss_tag = ' <span style="color:#f00">[BOSS]</span>' if m.get('is_boss') else ''
                battle_html = f'''
<div style="padding:8px; background:#220000; border:1px solid #ff0000; margin-bottom:8px;">
<b>{html_escape(m.get("name","?"))}{boss_tag}</b> — HP: {m.get("hp",0)}/{m.get("max_hp",0)} | Phase: {bd.get("monster",{}).get("phase",0)}<br>
Turn: {bd.get("turn",0)} | Combo chain: {bd.get("combo_chain",0)}<br>
Party: {html_escape(party_str)}<br>
{html_escape(m.get("desc",""))[:100]}
</div>'''
        except:
            pass

        # Leaderboard tables
        def make_table(title, stat, label):
            ranked = sorted(lb.items(), key=lambda x: x[1].get(stat, 0), reverse=True)[:10]
            if not ranked:
                return ''
            rows = ''
            for i, (name, data) in enumerate(ranked):
                rows += f'<tr><td>{i+1}</td><td>{html_escape(name)}</td><td><b>{data.get(stat, 0)}</b></td></tr>'
            return f'''
<div class="card">
<div class="card-title">{title}</div>
<table><tr><th>#</th><th>Player</th><th>{label}</th></tr>
{rows}</table>
</div>'''

        lb_xp = make_table('\U0001f3c6 Top XP', 'total_xp', 'XP')
        lb_battles = make_table('\u2694 Most Battles', 'battles', 'Battles')
        lb_bosses = make_table('\U0001f525 Boss Slayers', 'bosses', 'Bosses')
        lb_combos = make_table('\U0001f4a5 Combo Kings', 'combos', 'Combos')
        lb_rooms = make_table('\U0001f5fa Explorers', 'rooms', 'Rooms')
        lb_items = make_table('\U0001f381 Item Hunters', 'items_found', 'Items')
        lb_deaths = make_table('\u2620 Most Deaths', 'deaths', 'Deaths')

        # Rarest items
        rarity_order = ['common', 'uncommon', 'rare', 'legendary', 'mythic']
        rarest = sorted(lb.items(),
                        key=lambda x: rarity_order.index(x[1].get('rarest_tier', 'common')),
                        reverse=True)[:8]
        rarest_rows = ''
        for name, data in rarest:
            item = data.get('rarest_item', '')
            tier = data.get('rarest_tier', 'common')
            if item:
                tcolor = {'common':'#aaa','uncommon':'#0f0','rare':'#00f','legendary':'#ff0','mythic':'#f0f'}.get(tier, '#fff')
                rarest_rows += f'<tr><td>{html_escape(name)}</td><td style="color:{tcolor}"><b>{html_escape(item)}</b></td><td style="color:{tcolor}">{tier.upper()}</td></tr>'
        rarest_html = ''
        if rarest_rows:
            rarest_html = f'''
<div class="card">
<div class="card-title">\u2726 Rarest Finds</div>
<table><tr><th>Player</th><th>Item</th><th>Tier</th></tr>
{rarest_rows}</table>
</div>'''

        # Player roster
        player_rows = ''
        for p in sorted(players, key=lambda x: x.get('xp', 0), reverse=True):
            alive_icon = '\u2665' if p.get('alive') else '\u2620'
            loc_name = p.get('location', '?')
            player_rows += f'''<tr>
<td><b>{html_escape(p.get("nick","?"))}</b></td>
<td>{p.get("level",0)}</td>
<td>{alive_icon} {p.get("hp",0)}/{p.get("max_hp",0)}</td>
<td>{p.get("atk",0)}/{p.get("defense",0)}</td>
<td>{p.get("xp",0)}</td>
<td>{p.get("kills",0)}</td>
<td>{p.get("battles",0)}</td>
<td>{p.get("bosses_killed",0)}</td>
<td>{p.get("rooms_explored",0)}</td>
<td>{p.get("deaths",0)}</td>
<td>{html_escape(str(loc_name))}</td>
</tr>'''

        html = page_header('RPG') + f'''
<h1>\u2694 RPG Dungeon & Leaderboard</h1>

<div class="card">
<div class="card-title">Active Battle</div>
{battle_html}
</div>

<div class="card">
<div class="card-title">All Players</div>
<div style="overflow-x:auto">
<table style="font-size:12px">
<tr><th>Name</th><th>Lvl</th><th>HP</th><th>ATK/DEF</th><th>XP</th><th>Kills</th><th>Battles</th><th>Bosses</th><th>Rooms</th><th>Deaths</th><th>Location</th></tr>
{player_rows}
</table>
</div>
</div>

<h2>Leaderboards</h2>
<div class="grid">
{lb_xp}
{lb_battles}
{lb_bosses}
{lb_combos}
{lb_rooms}
{lb_items}
{lb_deaths}
{rarest_html}
</div>
''' + PAGE_FOOTER
        self._html(200, html)

    # ─── Webring ────────────────────────────────────────
    def _page_webring(self):
        soul = load_soul()
        webring = soul.get('webring', {})
        sites = webring.get('sites', [])
        rows = ''
        for i, site in enumerate(sites):
            rows += f'''<tr>
<td><input type="text" name="site_{i}_name" value="{html_escape(site.get('name',''))}"></td>
<td><input type="text" name="site_{i}_url" value="{html_escape(site.get('url',''))}"></td>
<td><input type="text" name="site_{i}_desc" value="{html_escape(site.get('desc',''))}"></td>
</tr>'''
        # Empty row for adding new
        n = len(sites)
        rows += f'''<tr style="opacity:0.6">
<td><input type="text" name="site_{n}_name" placeholder="New site name"></td>
<td><input type="text" name="site_{n}_url" placeholder="http://..."></td>
<td><input type="text" name="site_{n}_desc" placeholder="Description"></td>
</tr>'''

        html = page_header('Webring') + f'''
<h1>Yggdrasil Webring</h1>
<p style="color:#666">Manage sites in the webring. These show on the homepage and the webring index.</p>
<form method="POST" action="/admin/webring">
<div class="card">
<table>
<tr><th>Name</th><th>URL</th><th>Description</th></tr>
{rows}
</table>
</div>
<input type="submit" value="Save Webring" class="btn-success">
</form>
''' + PAGE_FOOTER
        self._html(200, html)

    def _save_webring(self, data):
        soul = load_soul()
        sites = []
        for i in range(20):
            name = data.get(f'site_{i}_name', [''])[0].strip()
            url = data.get(f'site_{i}_url', [''])[0].strip()
            desc = data.get(f'site_{i}_desc', [''])[0].strip()
            if name and url:
                sites.append({'name': name[:100], 'url': url[:200], 'desc': desc[:200]})
        soul.setdefault('webring', {})['sites'] = sites
        save_soul(soul)
        self._redirect('/admin/webring')

    # ─── God Mode ───────────────────────────────────────
    def _page_godmode(self):
        soul = load_soul()
        gm = soul.get('god_mode', {})
        html = page_header('God Mode') + f'''
<h1>God Mode</h1>
<p style="color:#ff4444">Override Zealot's personality in real-time. Use with care.</p>
<form method="POST" action="/admin/godmode">
<div class="card">
<div class="card-title">God Mode Controls</div>
<label>
<input type="checkbox" name="enabled" value="1" {"checked" if gm.get("enabled") else ""}>
Enable God Mode (overrides normal personality)
</label>
<label>Override System Prompt (replaces ego prompt when God Mode is on)</label>
<textarea name="override_prompt" rows="4">{html_escape(gm.get('override_prompt', ''))}</textarea>
<label>Force Mood (leave blank for normal rotation)</label>
<input type="text" name="force_mood" value="{html_escape(gm.get('force_mood', ''))}">
<label>Force Persona (ego/superego/id/trip/ego_death — leave blank for normal)</label>
<input type="text" name="force_persona" value="{html_escape(gm.get('force_persona', ''))}">
</div>

<div class="card">
<div class="card-title">RPG Multipliers</div>
<div class="grid">
<div>
<label>XP Multiplier (1 = normal)</label>
<input type="number" name="xp_mult" value="{gm.get('xp_mult', 1)}" min="1" max="100" step="1">
</div>
<div>
<label>Damage Multiplier (1 = normal)</label>
<input type="number" name="dmg_mult" value="{gm.get('dmg_mult', 1)}" min="1" max="100" step="1">
</div>
</div>
</div>

<input type="submit" value="Save God Mode" class="btn-danger">
</form>

<div class="card">
<div class="card-title">Quick GM Actions</div>
<form method="POST" action="/admin/gamemaster" style="display:inline">
<input type="hidden" name="action" value="announce">
<input type="text" name="message" placeholder="Broadcast message to IRC..." style="width:400px">
<button type="submit" class="btn-danger">Announce to Realm</button>
</form>
</div>
''' + PAGE_FOOTER
        self._html(200, html)

    def _save_godmode(self, data):
        soul = load_soul()
        gm = soul.setdefault('god_mode', {})
        gm['enabled'] = 'enabled' in data
        gm['override_prompt'] = data.get('override_prompt', [''])[0][:2000]
        gm['force_mood'] = data.get('force_mood', [''])[0][:50]
        gm['force_persona'] = data.get('force_persona', [''])[0][:20]
        # RPG multipliers
        for key in ['xp_mult', 'dmg_mult']:
            val = data.get(key, ['1'])[0]
            try:
                gm[key] = max(1, min(100, int(val)))
            except ValueError:
                pass
        save_soul(soul)
        self._redirect('/admin/godmode')

    # ─── Gamemaster ─────────────────────────────────────
    def _page_gamemaster(self):
        # Load NPC state
        try:
            npc_state = json.loads(NPC_STATE_FILE.read_text())
        except:
            npc_state = {}

        # Load graveyard for death count
        try:
            graveyard = json.loads(GRAVEYARD_FILE.read_text())
        except:
            graveyard = []

        # Load pending queue
        try:
            pending = json.loads(GM_QUEUE_FILE.read_text())
        except:
            pending = []

        # Load last results
        results = load_gm_results()

        # Build NPC table rows
        npc_rows = ''
        for name in _load_npc_names():
            s = npc_state.get(name, {})
            connected = s.get('connected', False)
            alive = s.get('alive', False)
            hp = s.get('hp', '?')
            level = s.get('level', 0)
            kills = s.get('kills', 0)
            location = s.get('location', '?')
            budget = s.get('budget', 0)
            deaths = sum(1 for g in graveyard if g.get('name', '') == name)

            status_icon = '<span class="status-ok">● ON</span>' if connected else '<span class="status-err">○ OFF</span>'
            alive_icon = '♥' if alive else '☠'

            actions = f'''
<form method="POST" action="/admin/gamemaster" style="display:inline">
<input type="hidden" name="action" value="spawn"><input type="hidden" name="target" value="{html_escape(name)}">
<button type="submit" style="font-size:11px">Spawn</button></form>
<form method="POST" action="/admin/gamemaster" style="display:inline">
<input type="hidden" name="action" value="kill"><input type="hidden" name="target" value="{html_escape(name)}">
<button type="submit" class="btn-danger" style="font-size:11px">Kill</button></form>
<form method="POST" action="/admin/gamemaster" style="display:inline">
<input type="hidden" name="action" value="revive"><input type="hidden" name="target" value="{html_escape(name)}">
<button type="submit" class="btn-success" style="font-size:11px">Revive</button></form>
<form method="POST" action="/admin/gamemaster" style="display:inline">
<input type="hidden" name="action" value="regen"><input type="hidden" name="target" value="{html_escape(name)}">
<button type="submit" style="font-size:11px;border-color:#ff00ff;color:#ff00ff">Regen</button></form>'''

            npc_rows += f'''<tr>
<td style="color:#00ccff;font-weight:bold">{html_escape(name)}</td>
<td>{status_icon}</td>
<td>{alive_icon} {html_escape(str(hp))}</td>
<td>{level}</td>
<td>{kills}</td>
<td>{deaths}</td>
<td>{html_escape(str(location))}</td>
<td>{budget}</td>
<td>{actions}</td>
</tr>'''

        # Build results flash
        results_html = ''
        if results:
            results_html = '<div class="card"><div class="card-title">Last GM Actions</div>'
            for r in results[-10:]:
                icon = '✓' if r.get('ok') else '✗'
                color = '#44ff44' if r.get('ok') else '#ff4444'
                results_html += f'<div style="color:{color};font-size:12px">{icon} {html_escape(r.get("msg", "?"))} <span style="color:#666">[{html_escape(r.get("ts", "")[:19])}]</span></div>'
            results_html += '</div>'

        # Pending queue
        pending_html = ''
        if pending:
            pending_html = f'<div class="card"><div class="card-title">Pending Commands ({len(pending)})</div>'
            for p in pending:
                pending_html += f'<div style="font-size:12px;color:#ffff00">⏳ {html_escape(p.get("action","?"))} → {html_escape(p.get("target","?"))} <span style="color:#666">[queued {html_escape(p.get("ts","")[:19])}]</span></div>'
            pending_html += '</div>'

        html = page_header('Gamemaster') + f'''
<h1>⚔ Gamemaster Console</h1>
<p style="color:#ff00ff">Command Center for NPC lifecycle, realm events, and divine intervention.</p>
<p style="color:#666;font-size:12px">Commands are queued and processed by the RPG engine every ~10 seconds.</p>

{results_html}
{pending_html}

<div class="card">
<div class="card-title">NPC Command Center</div>
<table style="font-size:12px">
<tr><th>NPC</th><th>Link</th><th>HP</th><th>Lvl</th><th>Kills</th><th>Deaths</th><th>Location</th><th>Budget</th><th>Actions</th></tr>
{npc_rows}
</table>
</div>

<div class="card">
<div class="card-title">Bulk Operations</div>
<form method="POST" action="/admin/gamemaster" style="display:inline">
<input type="hidden" name="action" value="spawn"><input type="hidden" name="target" value="all">
<button type="submit">Spawn All NPCs</button></form>
<form method="POST" action="/admin/gamemaster" style="display:inline">
<input type="hidden" name="action" value="kill"><input type="hidden" name="target" value="all">
<button type="submit" class="btn-danger">Kill All NPCs</button></form>
<form method="POST" action="/admin/gamemaster" style="display:inline">
<input type="hidden" name="action" value="revive"><input type="hidden" name="target" value="all">
<button type="submit" class="btn-success">Revive All NPCs</button></form>
<form method="POST" action="/admin/gamemaster" style="display:inline">
<input type="hidden" name="action" value="heal_all"><input type="hidden" name="target" value="all">
<button type="submit" class="btn-success">Heal All (Full HP)</button></form>
<form method="POST" action="/admin/gamemaster" style="display:inline">
<input type="hidden" name="action" value="smite_all"><input type="hidden" name="target" value="all">
<input type="number" name="value" value="10" min="1" max="999" style="width:60px">
<button type="submit" class="btn-danger">Smite All (DMG)</button></form>
</div>

<div class="card">
<div class="card-title">NPC Budget Control</div>
<form method="POST" action="/admin/gamemaster">
<input type="hidden" name="action" value="set_budget">
<select name="target" style="width:120px">
<option value="all">All NPCs</option>
{''.join(f'<option value="{html_escape(n)}">{html_escape(n)}</option>' for n in _load_npc_names())}
</select>
<input type="number" name="value" value="8" min="0" max="100" style="width:60px">
<button type="submit">Set Budget</button>
</form>
</div>

<div class="card">
<div class="card-title">Realm Events</div>
<form method="POST" action="/admin/gamemaster">
<input type="hidden" name="action" value="realm_event">
<select name="target" style="width:200px">
<option value="meteor">☄ Meteor Strike</option>
<option value="eclipse">🌑 Solar Eclipse</option>
<option value="festival">🎪 Festival</option>
<option value="plague">☠ Plague</option>
<option value="blessing">✨ Divine Blessing</option>
<option value="invasion">⚔ Monster Invasion</option>
<option value="earthquake">🌋 Earthquake</option>
<option value="gold_rain">💰 Gold Rain</option>
</select>
<button type="submit" class="btn-danger">Trigger Event</button>
</form>
</div>

<div class="card">
<div class="card-title">GM Broadcast</div>
<form method="POST" action="/admin/gamemaster">
<input type="hidden" name="action" value="announce">
<input type="text" name="message" placeholder="The heavens rumble with divine proclamation..." style="width:100%;box-sizing:border-box">
<button type="submit" style="margin-top:8px">Announce to Realm</button>
</form>
</div>

<div class="card">
<div class="card-title">NPC HP Override</div>
<form method="POST" action="/admin/gamemaster">
<input type="hidden" name="action" value="set_hp">
<select name="target" style="width:120px">
{''.join(f'<option value="{html_escape(n)}">{html_escape(n)}</option>' for n in _load_npc_names())}
</select>
<input type="number" name="value" value="30" min="0" max="9999" style="width:80px"> HP
<button type="submit">Set HP</button>
</form>
</div>
''' + PAGE_FOOTER
        self._html(200, html)

    def _save_gamemaster(self, data):
        action = data.get('action', [''])[0][:30]
        target = data.get('target', ['all'])[0][:30]
        value = data.get('value', [''])[0][:10]
        message = data.get('message', [''])[0][:500]

        valid_actions = {
            'spawn', 'kill', 'revive', 'regen', 'heal_all', 'smite_all',
            'set_budget', 'set_hp', 'announce', 'realm_event',
        }
        if action not in valid_actions:
            self._redirect('/admin/gamemaster')
            return

        # Validate target for NPC actions
        npc_actions = {'spawn', 'kill', 'revive', 'regen', 'set_hp', 'set_budget'}
        if action in npc_actions and target != 'all' and target not in _load_npc_names():
            self._redirect('/admin/gamemaster')
            return

        kwargs = {}
        if value:
            try:
                kwargs['value'] = int(value)
            except ValueError:
                pass
        if message:
            kwargs['message'] = message

        # For realm events, also write directly to realm_event.json
        if action == 'realm_event':
            event = {
                'type': target,
                'ts': datetime.now().isoformat(),
                'source': 'gamemaster',
                'active': True,
            }
            REALM_EVENT_FILE.parent.mkdir(parents=True, exist_ok=True)
            REALM_EVENT_FILE.write_text(json.dumps(event, indent=2))

        queue_gm_command(action, target, **kwargs)
        self._redirect('/admin/gamemaster')

    # ─── Display Settings ───────────────────────────────
    def _page_display(self):
        soul = load_soul()
        ds = soul.get('display', {})

        def speed_row(label, key, default, unit='chars/sec', desc=''):
            val = ds.get(key, default)
            hint = f' <span style="color:#666">({html_escape(desc)})</span>' if desc else ''
            return f'''<tr>
<td>{html_escape(label)}{hint}</td>
<td><input type="number" name="{key}" value="{val}" min="1" max="100" step="1" style="width:100px"> {html_escape(unit)}</td>
</tr>'''

        def time_row(label, key, default, unit='seconds', desc=''):
            val = ds.get(key, default)
            hint = f' <span style="color:#666">({html_escape(desc)})</span>' if desc else ''
            return f'''<tr>
<td>{html_escape(label)}{hint}</td>
<td><input type="number" name="{key}" value="{val}" min="1" max="600" step="1" style="width:100px"> {html_escape(unit)}</td>
</tr>'''

        def dir_row(label, key, default='ltr', desc=''):
            val = ds.get(key, default)
            hint = f' <span style="color:#666">({html_escape(desc)})</span>' if desc else ''
            opts = ''.join(f'<option value="{d}" {"selected" if d == val else ""}>{d.upper()}</option>'
                          for d in ['ltr', 'rtl', 'pingpong', 'stopped'])
            return f'''<tr>
<td>{html_escape(label)}{hint}</td>
<td><select name="{key}" style="width:140px">{opts}</select></td>
</tr>'''

        html = page_header('Display Settings') + f'''
<h1>Display Settings</h1>
<form method="POST" action="/admin/display">
<div class="card">
<div class="card-title">Scroll Speeds</div>
<table>
<tr><th>Element</th><th>Speed</th></tr>
{speed_row("Info Ticker", "ticker_speed", 10, desc="Row 1 - IRC info / NPC status")}
{speed_row("Banner", "banner_speed", 8, desc="Row 10 - mood / topic / thoughts")}
{speed_row("Header Blocks", "header_speed", 6, desc="Row 0 - CGA block animation")}
</table>
</div>

<div class="card">
<div class="card-title">Scroll Directions</div>
<table>
<tr><th>Element</th><th>Direction</th></tr>
{dir_row("Info Ticker", "ticker_direction", desc="LTR=left-to-right, RTL=reverse, Pingpong=bounce, Stopped=frozen")}
{dir_row("Banner", "banner_direction", desc="Row 10 scroll direction")}
{dir_row("Header Blocks", "header_direction", desc="Row 0 CGA block direction")}
</table>
</div>

<div class="card">
<div class="card-title">Animation Timing</div>
<table>
<tr><th>Element</th><th>Interval</th></tr>
{time_row("Avatar Rotation", "avatar_interval", 30, desc="Cycle between avatar frames")}
{time_row("Eye Animation", "eye_interval", 5, desc="Eye expression change")}
{time_row("Avatar Color Flip", "color_flip", 6, desc="Alternate avatar colors every N sec")}
</table>
</div>

<div class="card">
<div class="card-title">IRC Display</div>
<table>
<tr><th>Setting</th><th>Value</th></tr>
<tr>
<td>Show Channel Tags <span style="color:#666">([ZP]/[RPG]/[ZH] prefix)</span></td>
<td><input type="checkbox" name="show_channels" value="1" {'checked' if ds.get('show_channels', True) else ''}></td>
</tr>
<tr>
<td>Show Timestamps <span style="color:#666">(time prefix on IRC lines)</span></td>
<td><input type="checkbox" name="show_timestamps" value="1" {'checked' if ds.get('show_timestamps', True) else ''}></td>
</tr>
</table>
</div>

<div class="card">
<div class="card-title">Other</div>
<table>
<tr><th>Setting</th><th>Value</th></tr>
{time_row("Main Loop Tick", "loop_tick_ms", 200, unit="ms", desc="curses refresh rate")}
{time_row("Spinner Speed", "spinner_speed", 2, unit="x multiplier", desc="Spinner animation rate")}
</table>
</div>

<div class="card">
<div class="card-title">Theme &amp; Scenes</div>
<table>
<tr><th>Setting</th><th>Value</th></tr>
<tr>
<td>Force Theme <span style="color:#666">(override auto-theme)</span></td>
<td><select name="force_theme" style="width:160px">
{''.join(f'<option value="{t}" {"selected" if ds.get("force_theme","auto")==t else ""}>{t.replace("_"," ").title()}</option>' for t in ['auto','cga_red','cga_green','cga_blue','cga_cyan','cga_magenta','cga_yellow','amber','p1_green','dark_blue'])}
</select></td>
</tr>
<tr>
<td>Scene Cycling <span style="color:#666">(ASCII art landscape cycling)</span></td>
<td><input type="checkbox" name="scene_enabled" value="1" {'checked' if ds.get('scene_enabled', False) else ''}></td>
</tr>
<tr>
<td>Scene Dwell Time <span style="color:#666">(seconds per scene)</span></td>
<td><input type="number" name="scene_dwell" value="{ds.get('scene_dwell', 600)}" min="30" max="3600" step="30" style="width:100px"> seconds</td>
</tr>
<tr>
<td>Palette - Border Color <span style="color:#666">(CGA border pair 0-7)</span></td>
<td><input type="number" name="palette_border" value="{ds.get('palette_border', 4)}" min="0" max="7" step="1" style="width:80px"></td>
</tr>
<tr>
<td>Palette - Accent Color <span style="color:#666">(CGA accent pair 0-7)</span></td>
<td><input type="number" name="palette_accent" value="{ds.get('palette_accent', 6)}" min="0" max="7" step="1" style="width:80px"></td>
</tr>
</table>
</div>

<div class="card">
<div class="card-title">Color Overrides</div>
<p style="color:#999;margin:0 0 8px">Override individual color pairs. <b>auto</b> = follow current theme.</p>
<table>
<tr><th>Element</th><th>Color</th></tr>
{''.join(f"""<tr>
<td>{label}</td>
<td><select name="{key}" style="width:140px">
{''.join(f'<option value="{c}" {"selected" if ds.get(key,"auto")==c else ""}>{c.title()}</option>' for c in ['auto','red','green','yellow','blue','magenta','cyan','white'])}
</select></td>
</tr>""" for key, label in [
    ('color_text', 'IRC Text <span style="color:#666">(message body)</span>'),
    ('color_action', 'Action Text <span style="color:#666">(system / action lines)</span>'),
    ('color_header', 'Header 1 <span style="color:#666">(top bracket header)</span>'),
    ('color_header2', 'Header 2 <span style="color:#666">(sub-header / accent)</span>'),
    ('color_nick', 'Nicknames <span style="color:#666">(IRC nick color)</span>'),
])}
</table>
</div>

<input type="submit" value="Save Display Settings" class="btn-success">
</form>

<form method="POST" action="/admin/display/reset" style="margin-top:12px">
<input type="submit" value="Revert to Defaults" class="btn" style="background:#666" onclick="return confirm('Reset ALL display settings to defaults?')">
</form>
<p style="color:#666">Changes apply within ~10 seconds as the display reloads config.</p>
''' + PAGE_FOOTER
        self._html(200, html)

    def _save_display(self, data):
        soul = load_soul()
        ds = soul.setdefault('display', {})
        int_keys = [
            'ticker_speed', 'banner_speed', 'header_speed',
            'avatar_interval', 'eye_interval', 'color_flip',
            'loop_tick_ms', 'spinner_speed',
        ]
        for key in int_keys:
            val = data.get(key, [''])[0]
            if val:
                try:
                    ds[key] = max(1, int(val))
                except ValueError:
                    pass
        # Scroll directions
        valid_dirs = {'ltr', 'rtl', 'pingpong', 'stopped'}
        for key in ['ticker_direction', 'banner_direction', 'header_direction']:
            val = data.get(key, [''])[0]
            if val in valid_dirs:
                ds[key] = val
        # Boolean toggles (checkbox: present=True, absent=False)
        for key in ['show_channels', 'show_timestamps', 'scene_enabled']:
            ds[key] = key in data
        # Force theme
        valid_themes = {'auto','cga_red','cga_green','cga_blue','cga_cyan','cga_magenta','cga_yellow','amber','p1_green','dark_blue'}
        ft = data.get('force_theme', ['auto'])[0]
        ds['force_theme'] = ft if ft in valid_themes else 'auto'
        # Scene dwell
        try:
            ds['scene_dwell'] = max(30, min(3600, int(data.get('scene_dwell', ['600'])[0])))
        except (ValueError, IndexError):
            pass
        # Palette overrides (0-7 CGA range)
        for pkey in ['palette_border', 'palette_accent']:
            pval = data.get(pkey, [''])[0]
            if pval:
                try:
                    ds[pkey] = max(0, min(7, int(pval)))
                except ValueError:
                    pass
        # Color overrides (auto or CGA color name)
        valid_colors = {'auto', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white'}
        for ckey in ['color_text', 'color_action', 'color_header', 'color_header2', 'color_nick']:
            cval = data.get(ckey, ['auto'])[0]
            ds[ckey] = cval if cval in valid_colors else 'auto'
        save_soul(soul)
        self._redirect('/admin/display')

    def _reset_display(self, data):
        soul = load_soul()
        soul.pop('display', None)
        save_soul(soul)
        self._redirect('/admin/display')

    # ─── Generate with Ollama ───────────────────────────
    def _generate_field(self, data):
        soul = load_soul()
        host = soul.get('ollama', {}).get('host', 'http://10.13.37.5:11434')
        field = data.get('field', [''])[0]
        custom_prompt = data.get('prompt', [''])[0][:1000]

        prompts = {
            'thought': "Give one pithy thought of the day as ZEALOT, an AI on a Raspberry Pi. Aussie BSD admin vibe. Max 15 words.",
            'dream': "Describe what you dreamed last night as an AI on a Pi. Surreal, techy, brief. Max 20 words.",
            'blog': "Write a short blog post as ZEALOT, a friendly AI on a Raspberry Pi. Warm, funny, Aussie. Under 200 words.",
            'soul_text': custom_prompt or "Write a soul description for an AI named Zealot living on a Raspberry Pi. Aussie BSD admin personality. 2-3 sentences.",
        }
        for p in ['ego', 'superego', 'id', 'trip', 'ego_death', 'adventure']:
            prompts[f'prompt_{p}'] = custom_prompt or f"Write a system prompt for the {p} persona of an IRC bot. Brief, characterful."

        prompt = prompts.get(field, custom_prompt or 'Say something interesting.')
        result = test_ollama(host, soul.get('ollama', {}).get('models', {}).get('ego', 'llama3.2'), prompt)

        if result['ok']:
            response = result['response']
            flash = f'''<div class="flash flash-ok">
<b>Generated:</b><br>{html_escape(response)}
</div>'''
            if field == 'thought':
                state = load_state()
                state['thought_of_day'] = response[:200]
                MEM_FILE.write_text(json.dumps(state, indent=2, default=str))
            elif field == 'dream':
                state = load_state()
                state['last_dream'] = response[:200]
                MEM_FILE.write_text(json.dumps(state, indent=2, default=str))
        else:
            flash = f'<div class="flash flash-err"><b>Ollama error:</b> {html_escape(result.get("error","?"))}</div>'

        html = page_header('Generate') + f'''
<h1>Generated Content</h1>
{flash}
<p>Copy the text above and paste it into the relevant field.</p>
<a href="/admin/">← Dashboard</a> |
<a href="/admin/soul">Soul</a> |
<a href="/admin/prompts">Prompts</a>
''' + PAGE_FOOTER
        self._html(200, html)


# ─── Main ───────────────────────────────────────────────
if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))
    DIR.mkdir(parents=True, exist_ok=True)

    # Ensure soul.json exists with defaults
    if not SOUL_FILE.exists():
        default_soul = Path(__file__).parent / 'soul.json'
        if default_soul.exists():
            SOUL_FILE.write_text(default_soul.read_text())

    server = http.server.HTTPServer(('127.0.0.1', PORT), AdminHandler)
    print(f'ZEALOT Admin Panel running on 127.0.0.1:{PORT}', file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()
