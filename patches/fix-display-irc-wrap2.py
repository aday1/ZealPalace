#!/usr/bin/env python3
"""IRC wrap: first line uses room after header; continuations use full row width."""
from pathlib import Path
import py_compile
import re

p = Path.home() / ".local/bin/zealot_display.py"
t = p.read_text(encoding="utf-8")

new_wrap = '''def wrap_irc_lines(raw_lines, width):
    """Word-wrap IRC for 40-col LCD; continuations use nearly full row width."""
    wrapped = []
    w = max(20, width)
    cont_pad = "  "
    cont_w = max(12, w - len(cont_pad))

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
        if len(parts) > 1:
            rest = " ".join(parts[1:])
            for line in textwrap.wrap(
                rest,
                width=cont_w,
                break_long_words=True,
                break_on_hyphens=False,
            ):
                wrapped.append((cont_pad + line, "cont"))
    return wrapped
'''

old = re.search(r"def wrap_irc_lines\(raw_lines, width\):.*?return wrapped\n", t, re.DOTALL)
if not old:
    raise SystemExit("wrap_irc_lines not found")
t = t[: old.start()] + new_wrap + t[old.end() :]

p.write_text(t, encoding="utf-8")
py_compile.compile(str(p), doraise=True)
print("wrap2 OK")
