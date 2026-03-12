#!/usr/bin/env python3
"""ZEALOT Boot Plasma - Demoscene boot/login animation for TFT LCD
Runs once on first SSH login or tty boot, then hands off to tmux.
Uses pyfiglet for animated ASCII art typography.
Duration: ~40 seconds plasma + 40 seconds info screen
"""
import sys, math, time, os, random, shutil, subprocess

os.environ['TERM'] = 'linux'

try:
    import pyfiglet
    HAS_FIGLET = True
except ImportError:
    HAS_FIGLET = False

_cols, _rows = shutil.get_terminal_size((40, 34))
W, H = _cols, _rows - 1  # leave 1 row for tmux status
DURATION = 40.0
FPS = 15

# ─── Figlet Banners (morph between fonts) ───────
FIGLET_FONTS = ['small', 'smslant', 'cybermedium', 'digital', 'doom',
                'rectangles', 'standard', 'thin', 'mini']

def _render_figlet(text, font, max_w=None):
    """Render text with pyfiglet, center within max_w"""
    if max_w is None:
        max_w = W
    if not HAS_FIGLET:
        return [text.center(max_w)]
    try:
        rendered = pyfiglet.figlet_format(text, font=font).rstrip('\n')
        lines = rendered.split('\n')
        # Center each line within width
        out = []
        for l in lines:
            if len(l) > max_w:
                l = l[:max_w]
            out.append(l.center(max_w))
        return out
    except:
        return [text.center(max_w)]

# Pre-render fallback banner if figlet unavailable
BANNER_FALLBACK = [
    " \u2592\u2592\u2592\u2592\u2592\u2592 \u2592\u2592\u2592\u2592\u2592\u2592 \u2592\u2592\u2592\u2592\u2592 \u2592\u2592     \u2592\u2592\u2592\u2592\u2592\u2592 \u2592\u2592\u2592\u2592\u2592\u2592\u2592",
    "     \u2592\u2592  \u2592\u2592     \u2592\u2592  \u2592\u2592 \u2592\u2592    \u2592\u2592    \u2592\u2592    \u2592\u2592   ",
    "    \u2592\u2592   \u2592\u2592\u2592\u2592\u2592  \u2592\u2592\u2592\u2592\u2592\u2592 \u2592\u2592    \u2592\u2592    \u2592\u2592    \u2592\u2592   ",
    "   \u2592\u2592    \u2592\u2592     \u2592\u2592  \u2592\u2592 \u2592\u2592    \u2592\u2592    \u2592\u2592    \u2592\u2592   ",
    "  \u2592\u2592\u2592\u2592\u2592\u2592 \u2592\u2592\u2592\u2592\u2592\u2592 \u2592\u2592  \u2592\u2592 \u2592\u2592\u2592\u2592\u2592  \u2592\u2592\u2592\u2592\u2592\u2592    \u2592\u2592   ",
]

SCROLL_TEXTS = [
    "ZEALOT SYSTEM v1.0 ... PERSONALITY MATRIX LOADING ... ",
    "JUNGIAN SUBSYSTEM INITIALIZING ... EGO/SUPEREGO/ID ONLINE ... ",
    "CONNECTING TO IRSSI ... JOINING #ZEALPALACE ... ",
    "IRC: ZealPalace.Yggdrasil.aday.net.au:6667 | #ZealPalace #ZealHangs #RPG ... ",
    "NETWORK: Zeal.Yggdrasil.aday.net.au | YGGDRASIL MESH | ALL WELCOME ... ",
    "DEMOSCENE GREETS TO: ADAY * ZEAL * OLLAMA * YGGDRASIL ... ",
    "... ALL YOUR BASE ARE BELONG TO US ... SYSTEM READY ... ",
    "NPC SUBSYSTEM: Pixel * CHMOD * n0va * glitchgrl ... SPAWNING ... ",
    "OLLAMA AI CORTEX: llama3.2 * gemma2 * mistral * tinyllama * qwen2.5 ... ",
    "PERSONALITY ENGINE: MOOD CYCLING * DREAMS * SUBSTANCES * SPLITTING ... ",
    "RPG DUNGEON: /LOOK /FIGHT /EXPLORE ... ADVENTURE AWAITS ... ",
]

# ─── Character sets for plasma phases ───────────
PLASMA_LIGHT = ' .:-=+*#%@'
PLASMA_HEAVY = ' \u2591\u2592\u2593\u2588\u2593\u2592\u2591'
PLASMA_RUNE  = ' .oO\u00f8\u221e\u03a9\u2588'

def plasma_val(x, y, t):
    v  = math.sin(x * 0.12 + t)
    v += math.sin(y * 0.15 + t * 1.3)
    v += math.sin((x + y) * 0.1 + t * 0.7)
    v += math.sin(math.sqrt(max(1, x*x + y*y)) * 0.08 + t * 0.5)
    v += math.sin(x * 0.05 + y * 0.07 + t * 2.0) * 0.5  # fast wobble
    return v

def render_plasma(t, chars):
    lines = []
    for y in range(H):
        row = ''
        for x in range(W):
            v = plasma_val(x, y, t)
            idx = int((v + 5) / 10 * (len(chars) - 1))
            idx = max(0, min(len(chars) - 1, idx))
            row += chars[idx]
        lines.append(row)
    return lines

def home():
    sys.stdout.write('\033[H')  # cursor home

def clear():
    sys.stdout.write('\033[2J\033[H')

def hide_cursor():
    sys.stdout.write('\033[?25l')

def show_cursor():
    sys.stdout.write('\033[?25h')

def main():
    hide_cursor()
    clear()
    start = time.time()
    scroll_pos = 0
    frame = 0

    # Pre-render figlet banners for font morphing effect
    figlet_banners = []
    if HAS_FIGLET:
        for font in FIGLET_FONTS:
            lines = _render_figlet('ZEALOT', font)
            figlet_banners.append(lines)
    if not figlet_banners:
        figlet_banners = [BANNER_FALLBACK]

    # Pre-render sub-texts with figlet
    sub_texts = []
    if HAS_FIGLET:
        for word, font in [('BOOT', 'mini'), ('AI', 'small'), ('READY', 'mini')]:
            sub_texts.append(_render_figlet(word, font))

    try:
        while True:
            elapsed = time.time() - start
            if elapsed > DURATION:
                break

            progress = elapsed / DURATION  # 0.0 -> 1.0

            # Phase selection
            if progress < 0.3:
                chars = PLASMA_LIGHT
                speed = 1.5 + progress * 8
            elif progress < 0.6:
                chars = PLASMA_HEAVY
                speed = 4.0 + progress * 6
            else:
                chars = PLASMA_RUNE
                speed = 5.0 + progress * 8

            t = elapsed * speed
            lines = render_plasma(t, chars)

            # Overlay figlet banner - morph between fonts
            if progress > 0.2:
                # Choose font based on time (morph through them)
                font_idx = int(elapsed * 1.5) % len(figlet_banners)
                banner = figlet_banners[font_idx]
                banner_y = (H - len(banner)) // 2 - 3
                banner_brightness = min(1.0, (progress - 0.2) * 3)

                for i, bline in enumerate(banner):
                    by = banner_y + i
                    if 0 <= by < H:
                        bx = max(0, (W - len(bline)) // 2)
                        row = list(lines[by])
                        for j, ch in enumerate(bline):
                            cx = bx + j
                            if cx < W and ch != ' ':
                                if random.random() < banner_brightness:
                                    row[cx] = ch
                        lines[by] = ''.join(row)

                # Show sub-text below banner in later phases
                if progress > 0.5 and sub_texts:
                    st_idx = int(elapsed * 2) % len(sub_texts)
                    sub = sub_texts[st_idx]
                    sub_y = banner_y + len(banner) + 1
                    for i, sl in enumerate(sub):
                        sy = sub_y + i
                        if 0 <= sy < H:
                            sx = max(0, (W - len(sl)) // 2)
                            row = list(lines[sy])
                            for j, ch in enumerate(sl):
                                cx = sx + j
                                if cx < W and ch != ' ':
                                    row[cx] = ch
                            lines[sy] = ''.join(row)

            # Scrolltext at bottom
            if progress > 0.35:
                scroll_idx = int(elapsed * 2) % len(SCROLL_TEXTS)
                scroll = SCROLL_TEXTS[scroll_idx]
                scroll_pos = int(elapsed * 12) % (len(scroll) + W)
                scr_row = H - 2
                scr_text = ''
                for sx in range(W):
                    si = scroll_pos - W + sx
                    if 0 <= si < len(scroll):
                        scr_text += scroll[si]
                    else:
                        scr_text += ' '
                lines[scr_row] = scr_text

            # Status line at very bottom
            pct = int(progress * 100)
            bar_w = int(progress * (W - 12))
            status = f' [{"█" * bar_w}'.ljust(W - 6) + f'] {pct:3d}%'
            lines[H-1] = status[:W]

            # Output frame
            home()
            sys.stdout.write('\n'.join(lines[:H]))
            sys.stdout.flush()

            time.sleep(1.0 / FPS)
            frame += 1

        # ─── Final Screen: Figlet Info Display ──
        clear()

        # Render "ZEALOT" in a nice figlet font at top
        if HAS_FIGLET:
            title_lines = _render_figlet('ZEALOT', 'small')
        else:
            title_lines = BANNER_FALLBACK
        for i, tl in enumerate(title_lines):
            y = i + 1
            x = max(0, (W - len(tl)) // 2)
            sys.stdout.write(f'\033[{y+1};{x+1}H{tl}')

        # Separator
        sep_y = len(title_lines) + 2
        sep = '\u2593\u2592\u2591' * (W // 3 + 1)
        sys.stdout.write(f'\033[{sep_y+1};1H{sep[:W]}')

        # "ONLINE" in figlet below
        if HAS_FIGLET:
            online_lines = _render_figlet('ONLINE', 'mini')
        else:
            online_lines = ['S Y S T E M   O N L I N E']
        online_y = sep_y + 1
        for i, ol in enumerate(online_lines):
            y = online_y + i
            x = max(0, (W - len(ol)) // 2)
            sys.stdout.write(f'\033[{y+1};{x+1}H{ol}')

        # Connection info
        info_y = online_y + len(online_lines) + 1
        url = 'Zeal.Yggdrasil.aday.net.au'
        info_lines = [
            f'IRC: {url}:6667',
            '#ZealPalace | #ZealHangs | #RPG',
            '',
            'NPC Party: Pixel CHMOD n0va glitchgrl',
        ]
        for i, line in enumerate(info_lines):
            x = max(0, (W - len(line)) // 2)
            sys.stdout.write(f'\033[{info_y + i + 1};{x+1}H{line}')

        # Try QR code for network address
        qr_y = info_y + len(info_lines) + 1
        try:
            result = subprocess.run(
                ['qrencode', '-t', 'UTF8', '-m', '1', '-s', '1', url],
                capture_output=True, text=True, timeout=3
            )
            if result.returncode == 0:
                qr_lines = result.stdout.strip().split('\n')
                for i, qline in enumerate(qr_lines):
                    if qr_y + i >= H: break
                    x = max(0, (W - len(qline)) // 2)
                    sys.stdout.write(f'\033[{qr_y + i + 1};{x+1}H{qline}')
        except Exception:
            tag = f'>> {url} <<'
            x = max(0, (W - len(tag)) // 2)
            sys.stdout.write(f'\033[{qr_y + 1};{x+1}H{tag}')

        sys.stdout.flush()
        time.sleep(40)

    finally:
        show_cursor()
        clear()

if __name__ == '__main__':
    main()
