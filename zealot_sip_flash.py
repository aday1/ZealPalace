#!/usr/bin/env python3
"""SIP call banner overlay for ZealPalace LCD (fed by CELES pbx-zealpalace-lcd-call.sh)."""
import json
import time
from datetime import datetime
from pathlib import Path

SIP_FLASH = Path.home() / '.cache' / 'zealot' / 'sip_call_flash.json'
SIP_EVENT_MAX_AGE_SEC = 15 * 60
ACTIVE_CALL_STATES = ('ring', 'ringing', 'incoming', 'outgoing', 'dialing', 'calling', 'talking', 'connected', 'answered', 'active', 'inuse', 'up')
CLEAR_CALL_STATES = ('', 'clear', 'idle', 'hangup', 'hangup_complete', 'ended', 'complete', 'closed', 'none')


def _parse_ts(value):
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except ValueError:
        return 0.0


def _state_can_overlay(state):
    return state in ACTIVE_CALL_STATES


class SipCallFlash:
    """ASCII figlet banner while a PSEUDOCORP call is active."""

    def __init__(self, figlet_fn):
        self._figlet = figlet_fn
        self.active_state = ''
        self.headline = ''
        self.subline = ''
        self.detail = ''
        self.start = 0.0
        self.duration = 0.0
        self._last_mtime = 0.0
        self.active_lines = 0

    def clear(self):
        self.active_state = ''
        self.headline = ''
        self.subline = ''
        self.detail = ''
        self.duration = 0.0
        self.active_lines = 0

    def trigger(self, headline, subline, detail, state, duration=12.0):
        self.headline = (headline or 'CALL')[:20]
        self.subline = (subline or '')[:38]
        self.detail = (detail or '')[:38]
        self.active_state = state or 'ring'
        self.start = time.time()
        self.duration = duration

    def active(self):
        if not self.active_state:
            return False
        if self.active_lines <= 0:
            return False
        if not _state_can_overlay(self.active_state):
            return False
        if self.duration <= 0:
            return True
        return (time.time() - self.start) < self.duration

    def poll_file(self):
        try:
            st = SIP_FLASH.stat()
        except OSError:
            self.clear()
            return
        if st.st_mtime == self._last_mtime:
            if self.active_state and self.duration > 0:
                if (time.time() - self.start) >= self.duration:
                    self.clear()
            return
        self._last_mtime = st.st_mtime
        try:
            data = json.loads(SIP_FLASH.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError, ValueError):
            return
        state = str(data.get('state') or '').lower()
        if state in CLEAR_CALL_STATES:
            self.clear()
            return
        event_ts = _parse_ts(data.get('ts'))
        newest_ts = max(st.st_mtime, event_ts)
        if newest_ts and time.time() - newest_ts > SIP_EVENT_MAX_AGE_SEC:
            self.clear()
            return
        from_ext = str(data.get('from_ext') or '?')
        to_ext = str(data.get('to_ext') or '?')
        from_name = str(data.get('from_name') or from_ext)
        to_name = str(data.get('to_name') or to_ext)
        headline = str(data.get('headline') or f'EXT {from_ext}>{to_ext}')
        sub = f'{from_name} ({from_ext})'
        det = f'{to_name} ({to_ext})'
        dur = float(data.get('duration', 30))
        raw_lines = data.get('active_lines')
        if raw_lines in (None, ''):
            active_lines = 1 if _state_can_overlay(state) else 0
        else:
            try:
                active_lines = max(0, int(raw_lines))
            except (TypeError, ValueError):
                active_lines = 1 if _state_can_overlay(state) else 0
        if active_lines <= 0 or not _state_can_overlay(state):
            self.clear()
            return
        self.active_lines = active_lines
        if str(data.get('headline') or '').upper().startswith('PBX'):
            headline = str(data.get('headline') or 'PBX ACTIVE')[:20]
        self.trigger(headline, sub, det, state, duration=dur)

    def header_title(self, width: int = 40) -> str:
        """Short title for row 0 of the LCD (replaces ZEALOT banner)."""
        if not self.active():
            return ''
        n = max(1, int(self.active_lines or 1))
        if n > 1:
            return f'PBX {n} LINES ACTIVE'[:width]
        return 'PBX LINE ACTIVE'[:width]

    def draw(self, stdscr, y_start, w, c_pair, c_mood):
        if not self.active():
            return
        elapsed = time.time() - self.start
        if elapsed < 1.2:
            attr = __import__('curses').A_BOLD | __import__('curses').A_REVERSE
        elif elapsed < 4.0:
            attr = __import__('curses').A_BOLD
        else:
            attr = __import__('curses').A_DIM
        curses = __import__('curses')
        fonts_med = ['small', 'smslant', 'thin']
        fonts_small = ['mini', 'digital', 'cybermedium']
        word = self.headline.split()[0][:10]
        if len(word) <= 5:
            lines = self._figlet(word, fonts=fonts_med)
        else:
            lines = self._figlet(word[:8], fonts=fonts_small)
        row = y_start
        for line in lines[:4]:
            try:
                stdscr.addnstr(row, 0, line[:w], w, curses.color_pair(c_mood) | attr)
            except Exception:
                pass
            row += 1
        tag = self.active_state.upper().center(w)[:w]
        try:
            stdscr.addnstr(row, 0, tag, w, curses.color_pair(c_pair) | curses.A_BOLD)
            row += 1
        except Exception:
            pass
        for extra in (self.subline, self.detail):
            if not extra:
                continue
            try:
                stdscr.addnstr(row, 0, extra.center(w)[:w], w, curses.color_pair(c_pair))
                row += 1
            except Exception:
                pass


def poll_sip_call_flash(flash):
    flash.poll_file()
