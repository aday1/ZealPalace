#!/usr/bin/env python3
"""METEOR STRIKE — ~10s ANSI impact animation for the ZealPalace TFT."""
from __future__ import annotations

import math
import random

from boot_anim_common import (
    DIM,
    H,
    W,
    RED,
    RST,
    WHT,
    YEL,
    blit,
    blit,
    blit_colored,
    center,
    draw_frame,
    make_color_grid,
    run_timeline,
    star_field,
)

DURATION = 10.0
FPS = 12


def _impact_point(elapsed: float) -> tuple[int, int]:
    prog = min(1.0, max(0.0, (elapsed - 2.0) / 3.0))
    x = int(W * (0.15 + prog * 0.55))
    y = int(H * (0.2 + prog * 0.45))
    return x, y


def draw(elapsed: float, _duration: float) -> None:
    lines = star_field(elapsed, density=0.08)
    colors = make_color_grid()

    # Incoming meteor trail (2s -> 5s)
    if 1.5 <= elapsed <= 5.5:
        ix, iy = _impact_point(elapsed)
        trail = "===>***"
        angle = -0.55
        for step in range(6):
            tx = int(ix - step * 4 * math.cos(angle))
            ty = int(iy - step * 2 * math.sin(angle))
            shade = YEL if step < 2 else RED if step < 4 else WHT
            blit_colored(lines, colors, ty, trail[: max(3, len(trail) - step)], shade, tx)

    # Shockwave ring (5s -> 8.5s)
    if elapsed >= 5.0:
        ix, iy = _impact_point(min(elapsed, 5.0))
        wave_t = min(1.0, (elapsed - 5.0) / 3.0)
        radius = wave_t * max(W, H) * 0.55
        ring_chars = ".:-=+*#@"
        for y in range(H):
            for x in range(W):
                dist = math.hypot(x - ix, y - iy)
                band = abs(dist - radius)
                if band < 1.2:
                    idx = min(len(ring_chars) - 1, int((1.2 - band) * 4))
                    ch = ring_chars[idx]
                    if ch != " ":
                        lines[y] = lines[y][:x] + ch + lines[y][x + 1 :]
                        colors[y][x] = RED if wave_t < 0.5 else YEL

    # Flash on impact
    if 4.8 <= elapsed <= 5.4:
        flash = int((elapsed - 4.8) * 20) % 2
        if flash:
            for y in range(H):
                colors[y] = [WHT] * W

    # Title + crumble (7s -> end)
    if elapsed >= 7.0:
        title_prog = min(1.0, (elapsed - 7.0) / 1.5)
        title = "METEOR STRIKE"
        blit_colored(lines, colors, H // 2 - 2, center(title), WHT)
        sub = "WORLD ENDS"
        blit_colored(lines, colors, H // 2, center(sub), RED)
        if title_prog > 0.4:
            for _ in range(int(12 * title_prog)):
                y = random.randint(H // 2 + 1, H - 2)
                x = random.randint(0, W - 1)
                lines[y] = lines[y][:x] + random.choice(".:;,") + lines[y][x + 1 :]
                colors[y][x] = DIM if random.random() > 0.5 else RST

    # Progress bar
    pct = int(min(100, (elapsed / DURATION) * 100))
    bar = f"[{'#' * (pct // 5)}{'.' * (20 - pct // 5)}] {pct:3d}%"
    blit(lines, H - 1, center(bar[:W]))

    draw_frame(lines, colors)


def main() -> None:
    run_timeline(DURATION, FPS, draw)


if __name__ == "__main__":
    main()
