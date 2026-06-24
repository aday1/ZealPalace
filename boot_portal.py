#!/usr/bin/env python3
"""PORTAL FLUX — ~8s quick lore burst for the ZealPalace TFT."""
from __future__ import annotations

import math

from boot_anim_common import (
    CYN,
    GRN,
    H,
    MAG,
    W,
    blit,
    blit_colored,
    center,
    draw_frame,
    make_color_grid,
    run_timeline,
)

DURATION = 8.0
FPS = 14


def draw(elapsed: float, _duration: float) -> None:
    lines = [" "] * H
    colors = make_color_grid()
    cx, cy = W // 2, H // 2
    pulse = 0.5 + 0.5 * math.sin(elapsed * 4)

    for y in range(H):
        for x in range(W):
            d = math.hypot(x - cx, (y - cy) * 1.4)
            if abs(d - (8 + pulse * 4)) < 1.0:
                ch = "+" if pulse > 0.5 else "."
                lines[y] = lines[y][:x] + ch + lines[y][x + 1 :]
                colors[y][x] = CYN

    blit_colored(lines, colors, cy - 2, center("PORTAL FLUX"), MAG)
    if elapsed >= 2.0:
        blit_colored(lines, colors, cy, center("DATA STREAM"), GRN)
    if elapsed >= 5.0:
        blit_colored(lines, colors, cy + 2, center("LORE INCOMING"), CYN)

    pct = int(min(100, (elapsed / DURATION) * 100))
    blit(lines, H - 1, center(f"[{'=' * (pct // 5)}{'.' * (20 - pct // 5)}] {pct:3d}%"))

    draw_frame(lines, colors)


def main() -> None:
    run_timeline(DURATION, FPS, draw)


if __name__ == "__main__":
    main()
