#!/usr/bin/env python3
"""REALM EVENT — ~12s portal / cosmic event for the ZealPalace TFT."""
from __future__ import annotations

import math
import random

from boot_anim_common import (
    CYN,
    H,
    MAG,
    RST,
    W,
    WHT,
    YEL,
    blit,
    blit_colored,
    center,
    draw_frame,
    make_color_grid,
    run_timeline,
)

DURATION = 12.0
FPS = 12


def draw(elapsed: float, _duration: float) -> None:
    lines = [" "] * H
    colors = make_color_grid()
    cx, cy = W // 2, H // 2

    # Spinning portal ring
    ring_t = elapsed * 1.5
    for y in range(H):
        for x in range(W):
            dx, dy = x - cx, (y - cy) * 2
            dist = math.hypot(dx, dy)
            ang = math.atan2(dy, dx) + ring_t
            if 6 < dist < 14 and int(ang * 3) % 2 == 0:
                lines[y] = lines[y][:x] + random.choice(".oO*") + lines[y][x + 1 :]
                colors[y][x] = MAG if dist < 10 else CYN

    if elapsed >= 2.0:
        blit_colored(lines, colors, 2, center("REALM EVENT"), WHT)
    if elapsed >= 4.0:
        blit_colored(lines, colors, cy - 1, center("PORTAL OPEN"), YEL)
    if elapsed >= 7.0:
        titles = ["COSMIC SHIFT", "ZONE FLUX", "MESH RIFT", "ERA PULSE"]
        t = titles[int(elapsed) % len(titles)]
        blit_colored(lines, colors, cy + 2, center(t), CYN)
    if elapsed >= 9.5:
        blit_colored(lines, colors, H - 3, center("THE REALM STIRS..."), MAG)

    pct = int(min(100, (elapsed / DURATION) * 100))
    blit(lines, H - 1, center(f"[{'#' * (pct // 5)}{'.' * (20 - pct // 5)}] {pct:3d}%"))

    draw_frame(lines, colors)


def main() -> None:
    run_timeline(DURATION, FPS, draw)


if __name__ == "__main__":
    main()
