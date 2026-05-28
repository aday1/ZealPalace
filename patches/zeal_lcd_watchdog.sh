#!/bin/bash
# Restart ZealPalace LCD display if the curses process died (tmux session may linger).
export PATH=/usr/bin:/bin:/usr/local/bin:$HOME/.local/bin:$PATH
export TERM=linux
mkdir -p "$HOME/.cache/zealot"

if pgrep -f 'python3.*zealot_display\.py' >/dev/null 2>&1; then
  exit 0
fi

if tmux has-session -t lcd 2>/dev/null; then
  tmux send-keys -t lcd:1 C-c '' Enter 'export TERM=linux; python3 ~/.local/bin/zealot_display.py' Enter 2>/dev/null
  sleep 3
  if pgrep -f 'python3.*zealot_display\.py' >/dev/null 2>&1; then
    exit 0
  fi
fi

"$HOME/.local/bin/lcd-init" >/dev/null 2>&1
