#!/usr/bin/env python3
"""Dynamic tmux status bar for the ZealPalace TFT (physical row below curses)."""
from __future__ import annotations

import os
import socket
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from zealot_lcd_render import tmux_status_segments
except Exception:  # pragma: no cover - optional on development hosts
    tmux_status_segments = None

try:
    from zealot_lcd_render import LCD_TICKER_VERSION
except Exception:  # pragma: no cover - optional on development hosts
    LCD_TICKER_VERSION = "tkr?"

_SESSION = "lcd"
_LAST_KEY = ""
_LAYOUT_DONE = False
# Header row uses 24h (ZEAL HH:MM:SS); physical tmux bar uses 12h.
TMUX_TIME_FMT = "%I:%M %p"
# Files rewritten on every deploy -- newest mtime is the last-deploy time.
_DEPLOY_STAMP_FILES = (
    "~/.local/bin/zealot_lcd_render.py",
    "~/.local/bin/zealot_display.py",
)


def _build_stamp() -> tuple[str, str]:
    """LCD ticker version + last-deploy date/time (from the deployed file mtime)."""
    dep = "?"
    newest = 0.0
    for cand in _DEPLOY_STAMP_FILES:
        try:
            mt = Path(os.path.expanduser(cand)).stat().st_mtime
            newest = max(newest, mt)
        except OSError:
            continue
    if newest > 0:
        dep = datetime.fromtimestamp(newest).strftime("%b%d %H:%M")
    return LCD_TICKER_VERSION, dep


def _lan_ip() -> str:
    try:
        out = subprocess.check_output(["hostname", "-I"], text=True, timeout=0.6)
        return out.split()[0] if out.split() else ""
    except Exception:
        return ""


def _host_short() -> str:
    try:
        return socket.gethostname().split(".")[0][:8]
    except Exception:
        return "zeal"


def _tmux_run(args: list[str]) -> None:
    try:
        subprocess.run(
            args,
            check=False,
            timeout=0.5,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def _ensure_tmux_layout() -> None:
    """Hide tmux window list (was leaking as '2:$') and reserve bar for mesh info."""
    global _LAYOUT_DONE
    if _LAYOUT_DONE:
        return
    _LAYOUT_DONE = True
    for args in (
        ["tmux", "set-option", "-t", _SESSION, "status-left", ""],
        ["tmux", "set-option", "-t", _SESSION, "status-left-length", "24"],
        ["tmux", "set-window-option", "-t", _SESSION, "window-status-format", ""],
        ["tmux", "set-window-option", "-t", _SESSION, "window-status-current-format", ""],
        ["tmux", "set-option", "-t", _SESSION, "window-status-separator", ""],
        ["tmux", "set-option", "-t", _SESSION, "status-justify", "left"],
        ["tmux", "set-option", "-t", _SESSION, "status-right-length", "24"],
    ):
        _tmux_run(args)


def _ok_tmux(token: str) -> str:
    label, state = token.split(":", 1) if ":" in token else (token, "")
    if state == "OK":
        return f"#[fg=green]{label}:OK#[default]"
    if state == "DN":
        return f"#[fg=red]{label}:DN#[default]"
    return token


def _build_status(
    *,
    snapshot: dict[str, Any] | None,
    mode: str | None,
    wopr_caller: str | None,
) -> tuple[str, str]:
    host = _host_short()
    ip = _lan_ip()
    if wopr_caller:
        caller = str(wopr_caller).strip() or "?"
        left = f"#[fg=red,bold]J124@{caller}#[default] WOPR"
        right = f"#[fg=green]{host} {ip} #[fg=yellow]{TMUX_TIME_FMT}"
        return left, right

    # Bottom physical row: LCD version + last-deploy stamp (left), IP + host (right).
    # No live clock here -- the top ZEAL row already shows the time (don't state it twice).
    if tmux_status_segments is not None and snapshot is not None:
        _plain_left, plain_ip = tmux_status_segments(snapshot, mode)
        ip = plain_ip or ip
    ver, dep = _build_stamp()
    left = f"#[fg=yellow,bold]{ver}#[default] #[fg=cyan]dep {dep}#[default]"
    right = f"#[fg=green]{ip} #[fg=cyan]{host}#[default]"
    return left, right


def set_tmux_bar(
    *,
    snapshot: dict[str, Any] | None = None,
    mode: str | None = None,
    wopr_caller: str | None = None,
    force: bool = False,
) -> None:
    """Update lcd session status bar with mesh summary (not tmux window junk)."""
    global _LAST_KEY
    _ensure_tmux_layout()
    left, right = _build_status(snapshot=snapshot, mode=mode, wopr_caller=wopr_caller)
    key = f"{left}|{right}"
    if not force and key == _LAST_KEY:
        return
    _LAST_KEY = key
    _tmux_run(["tmux", "set-option", "-t", _SESSION, "status-left", left])
    _tmux_run(["tmux", "set-option", "-t", _SESSION, "status-left-length", "24"])
    _tmux_run(["tmux", "set-option", "-t", _SESSION, "status-right", right])
    # Keep the tmux window list ('2:$-' junk) blanked even after window churn.
    _tmux_run(["tmux", "set-window-option", "-t", _SESSION, "window-status-format", ""])
    _tmux_run(["tmux", "set-window-option", "-t", _SESSION, "window-status-current-format", ""])