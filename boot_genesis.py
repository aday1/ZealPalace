#!/usr/bin/env python3
"""GENESIS — new-era ANSI sequence after meteor wipe."""
from __future__ import annotations

import math
import random

from boot_anim_common import (
    CYN,
    GRN,
    H,
    MAG,
    RST,
    W,
    WHT,
    YEL,
    blit_colored,
    blank_frame,
    center,
    draw_frame,
    make_color_grid,
    run_timeline,
)

DURATION = 10.0
FPS = 12


def _seed_growth(elapsed: float) -> float:
    return min(1.0, max(0.0, (elapsed - 2.0) / 4.0))


def draw(elapsed: float, _duration: float) -> None:
    lines = blank_frame(" ")
    colors = make_color_grid()
    cx, cy = W // 2, H // 2

    # Void noise (0-2s)
    if elapsed < 2.0:
        for y in range(H):
            row = list(lines[y])
            for x in range(W):
                if random.random() < 0.02:
                    row[x] = random.choice(".`")
                    colors[y][x] = CYN
            lines[y] = "".join(row)

    # Growing seed / tree (2-6s)
    growth = _seed_growth(elapsed)
    if growth > 0:
        height = int(growth * (H // 2 - 2))
        trunk = "|"
        for dy in range(height):
            y = cy + dy // 2
            blit_colored(lines, colors, y, trunk, GRN, cx)
        if growth > 0.35:
            spread = int(growth * 8)
            for dx in range(-spread, spread + 1):
                y = cy - int(abs(dx) * 0.4)
                ch = random.choice("*+o") if random.random() > 0.3 else "."
                blit_colored(lines, colors, y, ch, GRN, cx + dx)

    # Orbiting sparks (4s+)
    if elapsed >= 4.0:
        orbit_t = elapsed - 4.0
        for i in range(6):
            ang = orbit_t * 1.8 + i * (math.pi / 3)
            r = 6 + i
            ox = int(cx + math.cos(ang) * r)
            oy = int(cy + math.sin(ang) * r * 0.5)
            blit_colored(lines, colors, oy, "*", CYN, ox)

    # Title block (6s+)
    if elapsed >= 6.0:
        fade = min(1.0, (elapsed - 6.0) / 1.2)
        blit_colored(lines, colors, cy - 4, center("GENESIS"), WHT)
        blit_colored(lines, colors, cy - 2, center("ERA 0"), YEL)
        if fade > 0.5:
            blit_colored(lines, colors, cy + 2, center("NEW WORLD ONLINE"), GRN)
            blit_colored(lines, colors, cy + 4, center("ZEALPALACE RISES"), MAG)

    # Mesh sparkles across screen (8s+)
    if elapsed >= 8.0:
        for _ in range(8):
            y = random.randint(1, H - 2)
            x = random.randint(1, W - 2)
            blit_colored(lines, colors, y, random.choice(".+*"), CYN, x)

    # Status line
    if elapsed >= 1.0:
        msg = "INITIALIZING REALITY..."
        if elapsed >= 6.0:
            msg = "TICKER RESUMING SOON"
        blit_colored(lines, colors, H - 1, center(msg[:W]), CYN)

    draw_frame(lines, colors)


def main() -> None:
    run_timeline(DURATION, FPS, draw)


if __name__ == "__main__":
    main()
