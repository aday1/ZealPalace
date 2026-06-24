#!/usr/bin/env python3
"""NPC BATTLE — ~12s ANSI clash sequence for the ZealPalace TFT."""
from __future__ import annotations

import math
import random

from boot_anim_common import (
    CYN,
    GRN,
    H,
    MAG,
    RED,
    RST,
    W,
    YEL,
    blit,
    blit_colored,
    center,
    draw_frame,
    make_color_grid,
    run_timeline,
    star_field,
)

DURATION = 12.0
FPS = 12


def draw(elapsed: float, _duration: float) -> None:
    lines = star_field(elapsed, density=0.05)
    colors = make_color_grid()
    cx, cy = W // 2, H // 2

    if elapsed >= 1.0:
        blit_colored(lines, colors, 2, center("NPC BATTLE"), MAG)
        blit_colored(lines, colors, 3, center("COMBO STRIKE"), CYN)

    # Two fighters closing (1-5s)
    if 1.0 <= elapsed <= 5.0:
        prog = (elapsed - 1.0) / 4.0
        lx = int(W * 0.15 + prog * (cx - W * 0.15 - 4))
        rx = int(W * 0.85 - prog * (W * 0.85 - cx - 4))
        blit_colored(lines, colors, cy, "(@@)", GRN, lx)
        blit_colored(lines, colors, cy, "(@@)", RED, rx)
        if prog > 0.7:
            blit_colored(lines, colors, cy - 1, "*** CLASH ***", YEL)

    # Impact sparks (5-9s)
    if elapsed >= 5.0:
        wave = min(1.0, (elapsed - 5.0) / 3.0)
        for i in range(int(8 * wave) + 2):
            ang = i * 0.9 + elapsed * 2
            r = int(3 + wave * 10)
            ox = int(cx + math.cos(ang) * r)
            oy = int(cy + math.sin(ang) * r * 0.5)
            blit_colored(lines, colors, oy, random.choice("*+#"), YEL, ox)

    # HP bars + result (8s+)
    if elapsed >= 8.0:
        hp = max(0, 100 - int((elapsed - 8.0) * 25))
        bar = f"PARTY HP [{'#' * (hp // 5)}{'.' * (20 - hp // 5)}] {hp}%"
        blit_colored(lines, colors, H - 3, center(bar[:W]), GRN if hp > 30 else RED)
        if elapsed >= 10.0:
            blit_colored(lines, colors, cy + 3, center("VICTORY / LOOT DROP"), CYN)

    pct = int(min(100, (elapsed / DURATION) * 100))
    blit(lines, H - 1, center(f"[{'#' * (pct // 5)}{'.' * (20 - pct // 5)}] {pct:3d}%"))

    draw_frame(lines, colors)


def main() -> None:
    run_timeline(DURATION, FPS, draw)


if __name__ == "__main__":
    main()
