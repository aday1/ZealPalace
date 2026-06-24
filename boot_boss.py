#!/usr/bin/env python3
"""BOSS ENCOUNTER — ~14s boss reveal for the ZealPalace TFT."""
from __future__ import annotations

import random

from boot_anim_common import (
    CYN,
    H,
    MAG,
    RED,
    W,
    WHT,
    YEL,
    blit,
    blit_colored,
    center,
    draw_frame,
    make_color_grid,
    run_timeline,
    star_field,
)

DURATION = 14.0
FPS = 10

BOSS = [
    "   /\\_/\\   ",
    "  ( o.o )  ",
    "  > ^ <   ",
    " /|   |\\  ",
    "  |   |   ",
]


def draw(elapsed: float, _duration: float) -> None:
    lines = star_field(elapsed, density=0.04)
    colors = make_color_grid()
    cy = H // 2 - 2

    if elapsed >= 1.0:
        blit_colored(lines, colors, 1, center("BOSS ENCOUNTER"), RED)

    grow = min(1.0, max(0.0, (elapsed - 2.0) / 4.0))
    if grow > 0:
        for i, row in enumerate(BOSS):
            if random.random() > grow:
                continue
            blit_colored(lines, colors, cy + i, center(row), RED if i < 3 else MAG)

    if elapsed >= 6.0:
        shake = int(elapsed * 8) % 2
        blit_colored(lines, colors, cy - 1, center("!!! WARNING !!!"), YEL if shake else WHT)
    if elapsed >= 10.0:
        blit_colored(lines, colors, H - 4, center("KERNEL THRONE GUARDIAN"), MAG)
        blit_colored(lines, colors, H - 3, center("/fight to engage"), CYN if False else YEL)

    pct = int(min(100, (elapsed / DURATION) * 100))
    blit(lines, H - 1, center(f"[{'#' * (pct // 5)}{'.' * (20 - pct // 5)}] {pct:3d}%"))

    draw_frame(lines, colors)


def main() -> None:
    run_timeline(DURATION, FPS, draw)


if __name__ == "__main__":
    main()
