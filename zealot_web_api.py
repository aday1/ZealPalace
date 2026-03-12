#!/usr/bin/env python3
"""ZEALOT Web API - Guestbook, Hit Counter, Server Status, Bot Guestbooks

Lightweight HTTP API on port 8888, proxied by nginx.

Endpoints:
  GET  /api/status     - Server status (Ollama, IRCd, services)
  GET  /api/counter    - Hit counter (returns JSON)
  POST /api/counter    - Increment counter
  GET  /api/guestbook  - Read main guestbook entries
  POST /api/guestbook  - Sign the guestbook (name, message)
  GET  /api/guestbook/<bot> - Read a bot's guestbook
  POST /api/guestbook/<bot> - Sign a bot's guestbook
"""
import http.server, json, os, sys, time, signal, traceback, re
import urllib.request, urllib.error
import socket
from pathlib import Path
from datetime import datetime
from html import escape as html_escape

PORT = 8888
DIR = Path.home() / '.cache' / 'zealot'
GB_DIR = DIR / 'guestbooks'
COUNTER_FILE = DIR / 'hit_counter.json'
OLLAMA = os.environ.get('OLLAMA_HOST', 'http://10.13.37.5:11434')

BOTS = ['Pixel', 'CHMOD', 'n0va', 'xX_DarkByte_Xx', 'Sage', 'glitchgrl', 'BotMcBotface']
MAX_GB_ENTRIES = 200
MAX_MSG_LEN = 500
MAX_NAME_LEN = 32


def check_ollama():
    try:
        req = urllib.request.Request(f'{OLLAMA}/api/tags')
        with urllib.request.urlopen(req, timeout=3) as r:
            models = json.loads(r.read()).get('models', [])
            return {'status': 'online', 'models': len(models)}
    except:
        return {'status': 'offline', 'models': 0}

def check_ircd():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect(('127.0.0.1', 6667))
        s.close()
        return {'status': 'online', 'port': 6667}
    except:
        return {'status': 'offline', 'port': 6667}

def check_service(name):
    try:
        import subprocess
        r = subprocess.run(['systemctl', 'is-active', name],
                          capture_output=True, text=True, timeout=3)
        return r.stdout.strip()
    except:
        return 'unknown'


def load_counter():
    try:
        return json.loads(COUNTER_FILE.read_text())
    except:
        return {'hits': 0, 'since': datetime.now().isoformat()}

def save_counter(data):
    COUNTER_FILE.parent.mkdir(parents=True, exist_ok=True)
    COUNTER_FILE.write_text(json.dumps(data))


def load_guestbook(name='main'):
    safe = re.sub(r'[^a-zA-Z0-9_]', '', name)
    f = GB_DIR / f'{safe}.json'
    try:
        return json.loads(f.read_text())
    except:
        return []

def save_guestbook(entries, name='main'):
    safe = re.sub(r'[^a-zA-Z0-9_]', '', name)
    GB_DIR.mkdir(parents=True, exist_ok=True)
    f = GB_DIR / f'{safe}.json'
    f.write_text(json.dumps(entries[-MAX_GB_ENTRIES:], indent=2))


class APIHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress access logs

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self._cors()
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = self.path.rstrip('/')

        if path == '/api/status':
            self._get_status()
        elif path == '/api/counter':
            self._get_counter()
        elif path == '/api/guestbook':
            self._get_guestbook('main')
        elif path.startswith('/api/guestbook/'):
            bot = path.split('/api/guestbook/')[1]
            self._get_guestbook(bot)
        else:
            self._json(404, {'error': 'not found'})

    def do_POST(self):
        path = self.path.rstrip('/')
        try:
            length = int(self.headers.get('Content-Length', 0))
            if length > 4096:
                self._json(413, {'error': 'too large'})
                return
            body = self.rfile.read(length) if length else b'{}'
            data = json.loads(body) if body else {}
        except:
            self._json(400, {'error': 'invalid json'})
            return

        if path == '/api/counter':
            self._post_counter()
        elif path == '/api/guestbook':
            self._post_guestbook('main', data)
        elif path.startswith('/api/guestbook/'):
            bot = path.split('/api/guestbook/')[1]
            self._post_guestbook(bot, data)
        else:
            self._json(404, {'error': 'not found'})

    def _get_status(self):
        status = {
            'timestamp': datetime.now().isoformat(),
            'ollama': check_ollama(),
            'ircd': check_ircd(),
            'services': {
                'zealot-bot': check_service('zealot-bot'),
                'zealot-hangs': check_service('zealot-hangs'),
                'zealot-rpg': check_service('zealot-rpg'),
                'nginx': check_service('nginx'),
                'ngircd': check_service('ngircd'),
                'pihole-FTL': check_service('pihole-FTL'),
            },
            'uptime': self._get_uptime(),
        }
        self._json(200, status)

    def _get_uptime(self):
        try:
            with open('/proc/uptime') as f:
                secs = float(f.read().split()[0])
                days = int(secs // 86400)
                hours = int((secs % 86400) // 3600)
                mins = int((secs % 3600) // 60)
                return f'{days}d {hours}h {mins}m'
        except:
            return 'unknown'

    def _get_counter(self):
        c = load_counter()
        self._json(200, c)

    def _post_counter(self):
        c = load_counter()
        c['hits'] += 1
        c['last_hit'] = datetime.now().isoformat()
        save_counter(c)
        self._json(200, c)

    def _get_guestbook(self, name):
        entries = load_guestbook(name)
        self._json(200, {'guestbook': name, 'entries': entries})

    def _post_guestbook(self, name, data):
        author = str(data.get('name', 'Anonymous'))[:MAX_NAME_LEN]
        message = str(data.get('message', ''))[:MAX_MSG_LEN]
        if not message.strip():
            self._json(400, {'error': 'message required'})
            return

        # Sanitize
        author = html_escape(author)
        message = html_escape(message)

        entries = load_guestbook(name)
        entry = {
            'author': author,
            'message': message,
            'timestamp': datetime.now().isoformat(),
        }
        entries.append(entry)
        save_guestbook(entries, name)
        self._json(201, {'ok': True, 'entry': entry})


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))
    DIR.mkdir(parents=True, exist_ok=True)
    GB_DIR.mkdir(parents=True, exist_ok=True)

    server = http.server.HTTPServer(('127.0.0.1', PORT), APIHandler)
    print(f'ZealPalace API running on 127.0.0.1:{PORT}', file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()
