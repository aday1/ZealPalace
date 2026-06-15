#!/bin/bash
# Run zealot_display.py on the LCD TTY; auto-restart on exit without rebuilding tmux.
export PATH=/usr/bin:/bin:/usr/local/bin:$HOME/.local/bin:$PATH
export TERM=linux
LOG="$HOME/.cache/zealot/lcd_watchdog.log"
mkdir -p "$HOME/.cache/zealot"

while true; do
  python3 "$HOME/.local/bin/zealot_display.py"
  code=$?
  printf '%s display exited rc=%s\n' "$(date -Iseconds)" "$code" >>"$LOG"
  sleep 2
done
