#!/usr/bin/env python3
"""Apply ZealPalace LCD + IRC + bot length fixes (run on the Pi as aday)."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

BIN = Path.home() / '.local/bin'
DISPLAY = BIN / 'zealot_display.py'
SIP_MOD = BIN / 'zealot_sip_flash.py'
BOT = BIN / 'zealot_bot.py'
HANGS = BIN / 'zealot_hangs.py'
BOOT_CFG = Path('/boot/firmware/config.txt')
if not BOOT_CFG.exists():
    BOOT_CFG = Path('/boot/config.txt')

WRAP_BLOCK = '''
def _parse_irc_line(raw):
    """Split merged IRC log line into prefix, nick header, message body."""
    tag = ''
    body = raw
    if body.startswith('[') and '] ' in body[:10]:
        i = body.find('] ')
        tag = body[: i + 2]
        body = body[i + 2 :]
    ts = ''
    if body and ' ' in body:
        first, rest = body.split(' ', 1)
        if len(first) <= 7 and ':' in first and first[-1] in 'ap':
            ts = first + ' '
            body = rest
    prefix = tag + ts
    header = ''
    msg = body
    if body.startswith('<'):
        end = body.find('>')
        if end > 0:
            header = body[: end + 1] + ' '
            msg = body[end + 1 :].lstrip()
    elif body.startswith('* '):
        parts = body[2:].split(' ', 1)
        nick = parts[0] if parts else ''
        header = '* ' + nick + (' ' if nick else '')
        msg = parts[1] if len(parts) > 1 else ''
    return prefix, header, msg


def wrap_irc_lines(raw_lines, width):
    """Word-wrap IRC for 40-col LCD; continuations use 2-space indent (lt=cont)."""
    wrapped = []
    w = max(20, width)
    cont_pad = '  '
    for raw in raw_lines:
        if raw.strip().startswith('--'):
            wrapped.append((raw[:w], 'sys'))
            continue
        lt = 'sys'
        if '<Zealot>' in raw or '<Zealot_' in raw:
            lt = 'zealot'
        elif '<' in raw and '>' in raw:
            lt = 'nick'
        elif _is_action_line(raw):
            lt = 'action'

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
            rest = ' '.join(parts[1:])
            cont_w = max(12, w - len(cont_pad))
            for line in textwrap.wrap(
                rest,
                width=cont_w,
                break_long_words=True,
                break_on_hyphens=False,
            ):
                wrapped.append((cont_pad + line, 'cont'))
    return wrapped
'''


def backup(path: Path) -> None:
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + f'.bak.{int(time.time())}'))


def patch_display(text: str) -> str:
    text = re.sub(
        r"^(\s*)head = prefix \+ heade\s*$",
        r"\1head = prefix + header",
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(
        r"^(\s*)head = prefix \+ header+r+\s*$",
        r"\1head = prefix + header",
        text,
        flags=re.MULTILINE,
    )
    if '_parse_irc_line' not in text:
        text = re.sub(
            r'def wrap_irc_lines\(raw_lines, width\):.*?return wrapped\n',
            WRAP_BLOCK.strip() + '\n\n',
            text,
            count=1,
            flags=re.DOTALL,
        )
    if 'zealot_sip_flash' not in text:
        text = text.replace(
            'from pathlib import Path\n',
            'from pathlib import Path\n'
            'sys.path.insert(0, str(Path.home() / ".local/bin"))\n'
            'from zealot_sip_flash import SipCallFlash, poll_sip_call_flash\n',
            1,
        )
    if 'sip_flash = SipCallFlash' not in text:
        init_anchor = (
            '    mood_flash = MoodFlash()\n'
            '    existential_flash = ExistentialFlash()\n'
            '    battle_flash = BattleFlash()'
        )
        if init_anchor in text:
            text = text.replace(
                init_anchor,
                init_anchor + '\n    sip_flash = SipCallFlash(figlet_lines)',
                1,
            )
        else:
            text = text.replace(
                '    battle_flash = BattleFlash()',
                '    battle_flash = BattleFlash()\n    sip_flash = SipCallFlash(figlet_lines)',
                1,
            )
    if 'poll_sip_call_flash(sip_flash)' not in text:
        text = text.replace(
            '                battle_flash.check_battle(battle_cache)',
            '                battle_flash.check_battle(battle_cache)\n                poll_sip_call_flash(sip_flash)',
            1,
        )
    if 'lcd_mode' not in text and 'sip_flash.active()' not in text:
        text = text.replace(
            '            if battle_flash.active():',
            '            if sip_flash.active():\n'
            '                sip_flash.draw(stdscr, 2, dw, C_INFO, C_MOOD)\n'
            '            elif battle_flash.active():',
            1,
        )
    cont_marker = '        if line.startswith("  ") and lt != "sys":'
    text = text.replace(
        'raw_lines = read_irc_tail(irc_area + 15)',
        'raw_lines = read_irc_tail(max(irc_area * 3, 48))',
    )
    if cont_marker not in text:
        text = text.replace(
            '        col = 0\n        rest = line\n\n        # ── Channel tag:',
            '        if line.startswith("  ") and lt != "sys":\n'
            '            try:\n'
            '                stdscr.addnstr(row, 0, line[:dw], dw, curses.color_pair(C_IRC_MSG))\n'
            '            except Exception:\n'
            '                pass\n'
            '            return\n\n'
            '        col = 0\n        rest = line\n\n        # ── Channel tag:',
            1,
        )
    return text


def patch_hangs(text: str) -> str:
    text = text.replace('return txt[:150] if txt else None', 'return txt[:1200] if txt else None')
    text = text.replace('ACTION {msg[:350]}', 'ACTION {msg[:400]}')
    return text


def patch_bot(text: str) -> str:
    return text.replace(
        "resp = self._generate('adventure', prompt, fb, temp=0.9, maxn=100)",
        "resp = self._generate('adventure', prompt, fb, temp=0.9, maxn=280)",
    )


def patch_boot() -> None:
    script = Path(__file__).resolve().parent / 'disable-pi-voltage-warnings.sh'
    if script.is_file():
        subprocess.run(['sudo', 'sh', str(script)], check=False)
        return
    if not BOOT_CFG.exists():
        return
    lines = BOOT_CFG.read_text(encoding='utf-8', errors='replace').splitlines()
    if any(ln.strip() == 'avoid_warnings=1' for ln in lines):
        print('  avoid_warnings already set')
        return
    out = []
    inserted = False
    for ln in lines:
        out.append(ln)
        if ln.strip() == '[all]' and not inserted:
            out.append('avoid_warnings=1')
            inserted = True
    if not inserted:
        out.extend(['', '[all]', 'avoid_warnings=1'])
    BOOT_CFG.write_text('\n'.join(out) + '\n')
    print('  added avoid_warnings=1 to', BOOT_CFG)


def main() -> int:
    print('=== zeal_apply_lcd_fixes ===')
    patch_dir = Path('/tmp/zealpalace-patches')
    if not patch_dir.is_dir():
        patch_dir = Path(__file__).resolve().parent
    for name in (
        'zealot_sip_flash.py',
        'zealot_pbx_phones.py',
        'zealot_irc_tail.py',
        'zealot_noc_mesh.py',
    ):
        src = patch_dir / name
        if src.exists():
            shutil.copy2(src, BIN / name)
            (BIN / name).chmod(0o755)

    hdr = patch_dir / 'zeal_patch_pbx_header.py'
    if hdr.is_file():
        subprocess.run(['python3', str(hdr)], check=False)

    cyc = patch_dir / 'zeal_patch_display_cycle.py'
    if cyc.is_file():
        subprocess.run(['python3', str(cyc)], check=False)

    noc = patch_dir / 'zeal_patch_display_noc.py'
    if noc.is_file():
        subprocess.run(['python3', str(noc)], check=False)

    rflash = patch_dir / 'zeal_patch_display_router_flash.py'
    if rflash.is_file():
        subprocess.run(['python3', str(rflash)], check=False)

    tune = patch_dir / 'zeal_patch_display_tune.py'
    if tune.is_file():
        subprocess.run(['python3', str(tune)], check=False)

    unstick = patch_dir / 'zeal_patch_display_unstick.py'
    if unstick.is_file():
        subprocess.run(['python3', str(unstick)], check=False)

    wd = patch_dir / 'zeal_lcd_watchdog.sh'
    if wd.is_file():
        shutil.copy2(wd, BIN / 'zeal_lcd_watchdog.sh')
        (BIN / 'zeal_lcd_watchdog.sh').chmod(0o755)
        cron_line = '*/2 * * * * /home/aday/.local/bin/zeal_lcd_watchdog.sh >/dev/null 2>&1'
        try:
            existing = subprocess.run(['crontab', '-l'], capture_output=True, text=True, check=False)
            body = existing.stdout or ''
            if 'zeal_lcd_watchdog.sh' not in body:
                subprocess.run(['crontab', '-'], input=(body.rstrip() + '\n' + cron_line + '\n'), text=True, check=False)
                print('  installed lcd watchdog cron')
        except OSError:
            pass

    for path, fn in ((DISPLAY, patch_display), (HANGS, patch_hangs), (BOT, patch_bot)):
        if not path.exists():
            print('  skip missing', path)
            continue
        if path == DISPLAY:
            try:
                import py_compile
                py_compile.compile(str(path), doraise=True)
                body = path.read_text(encoding='utf-8', errors='replace')
                if 'router_flashbang.hook' in body and 'lcd_cycle_v3' in body:
                    print('  skip already-patched', path.name)
                    continue
            except py_compile.PyCompileError:
                pass
        backup(path)
        path.write_text(fn(path.read_text(encoding='utf-8', errors='replace')), encoding='utf-8')
        print('  patched', path.name)

    try:
        patch_boot()
    except PermissionError:
        subprocess.run(['sudo', 'python3', '-c', (
            "from pathlib import Path\n"
            "p=Path('/boot/firmware/config.txt')\n"
            "if not p.exists(): p=Path('/boot/config.txt')\n"
            "t=p.read_text()\n"
            "if 'avoid_warnings=1' not in t:\n"
            "  p.write_text(t.rstrip()+'\\n\\n[all]\\navoid_warnings=1\\n')\n"
        )], check=False)

    for svc in ('zealot-bot', 'zealot-hangs', 'zealot-rpg'):
        subprocess.run(['sudo', 'systemctl', 'restart', svc], check=False)

    subprocess.run(['pkill', '-f', 'zealot_display.py'], check=False)
    time.sleep(0.5)
    lcd_init = BIN / 'lcd-init'
    if lcd_init.exists():
        subprocess.run([str(lcd_init)], check=False)
    print('=== done ===')
    return 0


if __name__ == '__main__':
    sys.exit(main())
