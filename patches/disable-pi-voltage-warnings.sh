#!/bin/sh
# Hide Raspberry Pi undervoltage / throttling warnings on the framebuffer (LCD/console).
# Puts avoid_warnings=1 in the FIRST [all] section of config.txt (firmware ignores a
# duplicate trailing [all] block). Lowers console log level and suppresses dmesg spam.
set -eu

BOOT_CFG="/boot/firmware/config.txt"
[ -f "$BOOT_CFG" ] || BOOT_CFG="/boot/config.txt"

CMDLINE="/boot/firmware/cmdline.txt"
[ -f "$CMDLINE" ] || CMDLINE="/boot/cmdline.txt"

patch_config() {
  if [ ! -f "$BOOT_CFG" ]; then
    echo "no $BOOT_CFG" >&2
    return 1
  fi
  tmp=$(mktemp)
  awk '
    BEGIN { all_seen=0; in_first_all=0 }
    /^\[all\]/ {
      all_seen++
      if (all_seen == 1) {
        in_first_all=1
        print
        print "avoid_warnings=1"
        next
      }
      in_first_all=1
      next
    }
    /^\[/ { in_first_all=0; print; next }
    /^avoid_warnings=/ { next }
    { print }
    END {
      if (all_seen == 0) {
        print ""
        print "[all]"
        print "avoid_warnings=1"
      }
    }
  ' "$BOOT_CFG" >"$tmp"
  if ! cmp -s "$BOOT_CFG" "$tmp"; then
    cp "$tmp" "$BOOT_CFG"
    echo "patched $BOOT_CFG (avoid_warnings in first [all])"
  else
    echo "config ok: avoid_warnings in first [all]"
  fi
  rm -f "$tmp"
}

patch_cmdline() {
  if [ ! -f "$CMDLINE" ]; then
    return 0
  fi
  line=$(tr -d '\n' <"$CMDLINE")
  changed=0
  for token in loglevel=3 logo.nologo printk.devkmsg=off; do
    case " $line " in
      *" $token "*) ;;
      *)
        line="$line $token"
        changed=1
        ;;
    esac
  done
  if [ "$changed" -eq 1 ]; then
    printf '%s\n' "$line" >"$CMDLINE"
    echo "patched $CMDLINE"
  else
    echo "cmdline ok"
  fi
}

runtime_quiet() {
  if [ -w /proc/sys/kernel/printk ] 2>/dev/null; then
    echo "3 4 1 3" >/proc/sys/kernel/printk 2>/dev/null || true
    echo "lowered console printk level"
  fi
  if [ -w /sys/module/printk/parameters/time ] 2>/dev/null; then
    echo 0 >/sys/module/printk/parameters/time 2>/dev/null || true
  fi
  if command -v dmesg >/dev/null 2>&1; then
    dmesg -D 2>/dev/null || true
    echo "dmesg console output disabled"
  fi
}

patch_config
patch_cmdline
runtime_quiet

if command -v vcgencmd >/dev/null 2>&1; then
  vcgencmd get_throttled 2>/dev/null || true
fi

echo "voltage warnings suppressed (reboot once if config.txt changed)"
