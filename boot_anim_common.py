#!/usr/bin/env python3
"""Shared helpers for TFT boot animations (plasma / meteor / genesis)."""
from __future__ import annotations

import math
import os
import random
import shutil
import sys
import time

os.environ.setdefault("TERM", "linux")

_cols, _rows = shutil.get_terminal_size((40, 33))
W = max(40, _cols)
H = max(20, _rows)

RST = "\033[0m"
BLK = "\033[30m"
RED = "\033[31;1m"
GRN = "\033[32;1m"
YEL = "\033[33;1m"
CYN = "\033[36;1m"
MAG = "\033[35;1m"
WHT = "\033[37;1m"
DIM = "\033[2m"


def hide_cursor() -> None:
    sys.stdout.write("\033[?25l")


def show_cursor() -> None:
    sys.stdout.write("\033[?25h")


def clear_screen() -> None:
    sys.stdout.write("\033[2J\033[H")


def home() -> None:
    sys.stdout.write("\033[H")


def center(text: str, width: int = W) -> str:
    text = text[:width]
    return text.center(width)


def blank_frame(fill: str = " ") -> list[str]:
    return [fill * W for _ in range(H)]


def make_color_grid() -> list[list[str]]:
    return [[RST for _ in range(W)] for _ in range(H)]


def blit(lines: list[str], y: int, text: str, x: int | None = None) -> None:
    if x is None:
        x = max(0, (W - len(text)) // 2)
    if y < 0 or y >= H:
        return
    row = list(lines[y][:W].ljust(W))
    for i, ch in enumerate(text):
        col = x + i
        if 0 <= col < W and ch != " ":
            row[col] = ch
    lines[y] = "".join(row)


def blit_colored(lines: list[str], colors: list[list[str]], y: int, text: str, color: str, x: int | None = None) -> None:
    if x is None:
        x = max(0, (W - len(text)) // 2)
    if y < 0 or y >= H:
        return
    row = list(lines[y][:W].ljust(W))
    crow = colors[y]
    for i, ch in enumerate(text):
        col = x + i
        if 0 <= col < W and ch != " ":
            row[col] = ch
            crow[col] = color
    lines[y] = "".join(row)


def render_colored(lines: list[str], colors: list[list[str]]) -> str:
    out: list[str] = []
    for y in range(min(H, len(lines))):
        row = lines[y][:W].ljust(W)
        crow = colors[y] if y < len(colors) else [RST] * W
        buf: list[str] = []
        cur = RST
        for x in range(W):
            ch = row[x]
            co = crow[x] if x < len(crow) else RST
            if co != cur:
                buf.append(co)
                cur = co
            buf.append(ch)
        buf.append(RST)
        out.append("".join(buf))
    return "\n".join(out)


def draw_frame(lines: list[str], colors: list[list[str]] | None = None) -> None:
    home()
    if colors:
        sys.stdout.write(render_colored(lines, colors))
    else:
        sys.stdout.write("\n".join(lines[:H]))
    sys.stdout.flush()


def run_timeline(duration: float, fps: float, draw_fn) -> None:
    hide_cursor()
    clear_screen()
    start = time.time()
    try:
        while True:
            elapsed = time.time() - start
            if elapsed >= duration:
                break
            draw_fn(elapsed, duration)
            time.sleep(1.0 / fps)
    finally:
        show_cursor()
        clear_screen()


def star_field(t: float, density: float = 0.06) -> list[str]:
    lines = blank_frame(".")
    for y in range(H):
        row = list(lines[y])
        for x in range(W):
            seed = (x * 17 + y * 31) % 997
            if (seed / 997.0) > (1.0 - density):
                pulse = 0.5 + 0.5 * math.sin(t * 3.0 + seed * 0.1)
                row[x] = "*" if pulse > 0.65 else "." if pulse > 0.35 else " "
        lines[y] = "".join(row)
    return lines
