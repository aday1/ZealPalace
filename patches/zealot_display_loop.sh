#!/bin/bash
# Run zealot_display.py on the LCD TTY; auto-restart on exit without rebuilding tmux.
export PATH=/usr/bin:/bin:/usr/local/bin:$HOME/.local/bin:$PATH
export TERM=linux
# 320x480 TFT + TerminusBold14 = 40 columns (must match lcd-init tmux -x)
export LCD_COLS="${LCD_COLS:-40}"
export LCD_ROWS="${LCD_ROWS:-34}"
LOG="$HOME/.cache/zealot/lcd_watchdog.log"
mkdir -p "$HOME/.cache/zealot"

while true; do
  python3 "$HOME/.local/bin/zealot_display.py"
  code=$?
  printf '%s display exited rc=%s\n' "$(date -Iseconds)" "$code" >>"$LOG"
  sleep 2
done