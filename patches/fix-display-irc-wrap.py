#!/usr/bin/env python3
"""Fix IRC wrap: continuation lines use 2-space indent, not full header width."""
from pathlib import Path
import py_compile
import re

p = Path.home() / ".local/bin/zealot_display.py"
t = p.read_text(encoding="utf-8")

# Replace wrap_irc_lines function body
old_wrap = re.search(
    r"def wrap_irc_lines\(raw_lines, width\):.*?return wrapped\n",
    t,
    re.DOTALL,
)
new_wrap = '''def wrap_irc_lines(raw_lines, width):
    """Word-wrap IRC for 40-col LCD; continuations start at column 2."""
    wrapped = []
    w = max(20, width)
    cont_pad = "  "
    for raw in raw_lines:
        if raw.strip().startswith("--"):
            wrapped.append((raw[:w], "sys"))
            continue
        lt = "sys"
        if "<Zealot>" in raw or "<Zealot_" in raw:
            lt = "zealot"
        elif "<" in raw and ">" in raw:
            lt = "nick"
        elif _is_action_line(raw):
            lt = "action"

        prefix, header, msg = _parse_irc_line(raw)
        head = prefix + header
        if not msg:
            wrapped.append(((head or raw)[:w], lt))
            continue
        if len(head) + len(msg) <= w:
            wrapped.append((head + msg, lt))
            continue
        first_room = max(8, w - len(head))
        parts = textwrap.wrap(
            msg,
            width=first_room,
            break_long_words=True,
            break_on_hyphens=False,
        )
        if not parts:
            parts = [msg[: max(1, first_room)]]
        wrapped.append((head + parts[0], lt))
        for part in parts[1:]:
            wrapped.append((cont_pad + part, "cont"))
    return wrapped
'''

if not old_wrap:
    raise SystemExit("wrap_irc_lines block not found")
t = t[: old_wrap.start()] + new_wrap + t[old_wrap.end() :]

# Fix draw_irc_line continuation handler
old_cont = """        if line.startswith("  ") and lt != "sys":
            try:
                stdscr.addnstr(row, 0, line[:dw], dw, curses.color_pair(C_IRC_MSG))
            except Exception:
                pass
            return

        col = 0"""
new_cont = """        if lt == "cont":
            text = line[2:] if line.startswith("  ") else line.lstrip()
            try:
                stdscr.addnstr(row, 0, text[:dw], dw, curses.color_pair(C_IRC_MSG))
            except Exception:
                pass
            return

        col = 0"""

if old_cont not in t:
    raise SystemExit("draw_irc_line cont block not found")
t = t.replace(old_cont, new_cont, 1)

p.write_text(t, encoding="utf-8")
py_compile.compile(str(p), doraise=True)
print("irc wrap fixed OK")
