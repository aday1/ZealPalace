#!/usr/bin/env python3
"""SIP call banner overlay for ZealPalace LCD (fed by CELES pbx-zealpalace-lcd-call.sh)."""
import json
import re
import textwrap
import time
from datetime import datetime
from pathlib import Path

SIP_FLASH = Path.home() / '.cache' / 'zealot' / 'sip_call_flash.json'
LAST_CALL_LEDGER = Path.home() / '.cache' / 'zealot' / 'pbx_last_calls.json'
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


def _short_ts(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return time.strftime("%H:%M")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.strftime("%H:%M")
    except ValueError:
        return raw[:5] if len(raw) >= 5 else time.strftime("%H:%M")


def _normalize_turns(raw) -> list[dict]:
    if not isinstance(raw, list):
        return []
    turns: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = re.sub(r"\s+", " ", str(item.get("text") or "")).strip()
        if not text:
            continue
        role = str(item.get("role") or "user").strip().lower()
        label = str(item.get("label") or ("YOU" if role == "user" else "AGENT")).strip()
        turns.append(
            {
                "role": role,
                "label": label[:18],
                "text": text,
                "ts": str(item.get("ts") or ""),
            }
        )
    return turns


def _wrap_turn_line(prefix: str, text: str, width: int) -> list[str]:
    prefix = prefix[:width]
    wrap_w = max(8, width - len(prefix))
    chunks = textwrap.wrap(
        text,
        width=wrap_w,
        break_long_words=True,
        break_on_hyphens=False,
    ) or [""]
    lines: list[str] = []
    for idx, chunk in enumerate(chunks):
        if idx == 0:
            lines.append(f"{prefix}{chunk}")
        else:
            lines.append(f"{' ' * len(prefix)}{chunk}")
    return lines


def _turn_label_style(role: str) -> str:
    return "GREEN" if role in ("user", "caller") else "MAG"


def _trim_segments(segments: list[tuple[str, str]], width: int) -> list[tuple[str, str]]:
    total = sum(len(text) for text, _style in segments)
    if total <= width:
        if total < width:
            segments = [*segments, (" " * (width - total), "SYS")]
        return segments
    trim = total - width
    last_text, last_style = segments[-1]
    return [*segments[:-1], (last_text[: max(0, len(last_text) - trim)], last_style)]


def transcript_turn_segment_lines(
    turn: dict,
    width: int,
    now: float | None = None,
) -> list[list[tuple[str, str]]]:
    """Bracketed, color-ready segment rows for one transcript turn."""
    width = max(16, int(width or 40))
    role = str(turn.get("role") or "user").strip().lower()
    label = str(turn.get("label") or ("YOU" if role in ("user", "caller") else "AGENT")).strip()
    stamp = _short_ts(str(turn.get("ts") or ""))
    label_disp = label[:8]
    head = f"[{stamp}][{label_disp}] "
    indent = " " * len(head)
    body = re.sub(r"\s+", " ", str(turn.get("text") or "")).strip()
    wrap_w = max(8, width - len(head))
    chunks = textwrap.wrap(
        body,
        width=wrap_w,
        break_long_words=True,
        break_on_hyphens=False,
    ) or [""]
    msg_style = "IRC_MSG"
    label_style = _turn_label_style(role)
    rows: list[list[tuple[str, str]]] = []
    for idx, chunk in enumerate(chunks):
        if idx == 0:
            segments: list[tuple[str, str]] = [
                ("[", "SYS"),
                (stamp, "CYAN"),
                ("][", "SYS"),
                (label_disp, label_style),
                ("] ", "SYS"),
                (chunk, msg_style),
            ]
        else:
            segments = [(indent, "SYS"), (chunk, msg_style)]
        rows.append(_trim_segments(segments, width))
    return rows


def transcript_panel_segment_rows(
    turns: list[dict],
    width: int,
    max_rows: int,
    now: float | None = None,
) -> list[tuple[list[tuple[str, str]], str]]:
    """Tail-pinned colorful transcript rows for the agents panel."""
    if max_rows <= 0:
        return []
    width = max(16, int(width or 40))
    rows: list[tuple[list[tuple[str, str]], str]] = []
    for turn in turns:
        for segments in transcript_turn_segment_lines(turn, width, now=now):
            role = str(turn.get("role") or "user").strip().lower()
            row_style = "PBX_CALL" if role in ("user", "caller") else "MAG"
            rows.append((segments, row_style))
    if not rows:
        return [([(" [awaiting transcript...]", "SYS")], "SYS")]
    if len(rows) <= max_rows:
        return rows
    return rows[-max_rows:]


def transcript_display_lines(
    turns: list[dict],
    width: int,
    max_rows: int,
    now: float | None = None,
) -> list[tuple[str, str]]:
    """Flat text rows (tests/legacy) — bracketed labels, tail-pinned."""
    if max_rows <= 0:
        return []
    width = max(16, int(width or 40))
    rows: list[tuple[str, str]] = []
    for segments, style in transcript_panel_segment_rows(turns, width, 999, now=now):
        rows.append(("".join(text for text, _ in segments), style))
    if not rows:
        return [("[awaiting transcript...]", "dim")]
    if len(rows) <= max_rows:
        return rows
    return rows[-max_rows:]


def _extract_active_exts(data: dict) -> set[str]:
    exts: set[str] = set()
    for key in ('from_ext', 'to_ext'):
        value = str(data.get(key) or '').strip()
        if value and value != '?':
            exts.add(value)
    for call in data.get('calls') or []:
        if not isinstance(call, dict):
            continue
        for key in ('from_ext', 'to_ext', 'ext'):
            value = str(call.get(key) or '').strip()
            if value and value != '?':
                exts.add(value)
    for item in data.get('active_exts') or []:
        value = str(item or '').strip()
        if value and value != '?':
            exts.add(value)
    return exts


def _read_call_flash(path: Path | None = None) -> tuple[dict, float, str]:
    target = SIP_FLASH if path is None else path
    try:
        st = target.stat()
        data = json.loads(target.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}, 0.0, ''
    if not isinstance(data, dict):
        return {}, 0.0, ''
    state = str(data.get('state') or '').lower()
    event_ts = _parse_ts(data.get('ts'))
    newest_ts = max(st.st_mtime, event_ts)
    return data, newest_ts, state


def read_active_call_exts(path: Path | None = None) -> tuple[set[str], str]:
    """Return agent/human extensions currently in an active SIP call."""
    data, newest_ts, state = _read_call_flash(path)
    if not data:
        return set(), state
    if state in CLEAR_CALL_STATES:
        return set(), state
    if newest_ts and time.time() - newest_ts > SIP_EVENT_MAX_AGE_SEC:
        return set(), state
    if not _state_can_overlay(state):
        return set(), state
    raw_lines = data.get('active_lines')
    if raw_lines not in (None, ''):
        try:
            if int(raw_lines) <= 0:
                return set(), state
        except (TypeError, ValueError):
            pass
    return _extract_active_exts(data), state


def _read_last_call_ledger() -> dict[str, float]:
    try:
        raw = json.loads(LAST_CALL_LEDGER.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for ext, ts in raw.items():
        try:
            out[str(ext)] = float(ts)
        except (TypeError, ValueError):
            continue
    return out


def _write_last_call_ledger(updates: dict[str, float]) -> None:
    if not updates:
        return
    ledger = _read_last_call_ledger()
    for ext, ts in updates.items():
        ledger[ext] = max(ledger.get(ext, 0.0), float(ts))
    try:
        LAST_CALL_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        LAST_CALL_LEDGER.write_text(json.dumps(ledger, indent=2) + '\n', encoding='utf-8')
    except OSError:
        pass


def read_ext_last_call_ts(path: Path | None = None) -> dict[str, float]:
    """Per-extension timestamp of the newest SIP flash event (even if call cleared)."""
    data, newest_ts, _state = _read_call_flash(path)
    out = _read_last_call_ledger()
    if not data:
        return out
    event_ts = _parse_ts(data.get('ts'))
    stamp = max(event_ts, newest_ts)
    if not stamp:
        return out
    flash_updates: dict[str, float] = {}
    for ext in _extract_active_exts(data):
        flash_updates[ext] = max(flash_updates.get(ext, 0.0), stamp)
        out[ext] = max(out.get(ext, 0.0), stamp)
    for key in ('from_ext', 'to_ext'):
        ext = str(data.get(key) or '').strip()
        if ext and ext != '?':
            flash_updates[ext] = max(flash_updates.get(ext, 0.0), stamp)
            out[ext] = max(out.get(ext, 0.0), stamp)
    _write_last_call_ledger(flash_updates)
    return out


def read_active_call_exts_highlight(path: Path | None = None) -> set[str]:
    """Active call extensions for PBX agent row highlights (no active_lines gate)."""
    data, newest_ts, state = _read_call_flash(path)
    if not data:
        return set()
    if state in CLEAR_CALL_STATES:
        return set()
    if newest_ts and time.time() - newest_ts > SIP_EVENT_MAX_AGE_SEC:
        return set()
    if not _state_can_overlay(state):
        return set()
    return _extract_active_exts(data)


class SipCallFlash:
    """ASCII figlet banner while a PSEUDOCORP call is active."""

    def __init__(self, figlet_fn):
        self._figlet = figlet_fn
        self.active_state = ''
        self.headline = ''
        self.subline = ''
        self.detail = ''
        self.from_ext = ''
        self.to_ext = ''
        self.active_exts: set[str] = set()
        self.start = 0.0
        self.duration = 0.0
        self._last_mtime = 0.0
        self.active_lines = 0
        self.turns: list[dict] = []
        self._turn_seq = 0

    def clear(self):
        self.active_state = ''
        self.headline = ''
        self.subline = ''
        self.detail = ''
        self.from_ext = ''
        self.to_ext = ''
        self.active_exts = set()
        self.duration = 0.0
        self.active_lines = 0
        self.turns = []
        self._turn_seq = 0

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

    def _apply_flash_data(self, data: dict, file_mtime: float = 0.0) -> None:
        state = str(data.get('state') or '').lower()
        if state in CLEAR_CALL_STATES:
            self.clear()
            return
        event_ts = _parse_ts(data.get('ts'))
        newest_ts = max(file_mtime, event_ts)
        if newest_ts and time.time() - newest_ts > SIP_EVENT_MAX_AGE_SEC:
            self.clear()
            return
        from_ext = str(data.get('from_ext') or '?')
        to_ext = str(data.get('to_ext') or '?')
        self.from_ext = from_ext
        self.to_ext = to_ext
        self.active_exts = _extract_active_exts(data)
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
        new_turns = _normalize_turns(data.get("turns"))
        if new_turns:
            self.turns = new_turns
            self._turn_seq = len(new_turns)
        self.trigger(headline, sub, det, state, duration=dur)

    def poll_file(self):
        try:
            st = SIP_FLASH.stat()
        except OSError:
            self.clear()
            return
        now = time.time()
        if st.st_mtime == self._last_mtime:
            if self.active_state and self.duration > 0 and (now - self.start) >= self.duration:
                self.clear()
                return
            if self.active_state:
                try:
                    data = json.loads(SIP_FLASH.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError, ValueError):
                    return
                new_turns = _normalize_turns(data.get("turns"))
                if new_turns and len(new_turns) != self._turn_seq:
                    self.turns = new_turns
                    self._turn_seq = len(new_turns)
            return
        self._last_mtime = st.st_mtime
        try:
            data = json.loads(SIP_FLASH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            return
        self._apply_flash_data(data, st.st_mtime)

    def transcript_lines(self, width: int, max_rows: int, now: float | None = None) -> list[tuple[str, str]]:
        return transcript_display_lines(self.turns, width, max_rows, now)

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
