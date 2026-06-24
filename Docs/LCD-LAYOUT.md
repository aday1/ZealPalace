# ZealPalace LCD layout contract

Authoritative spec to recreate the `zealot_display.py` + `zealot_lcd_render.py`
dashboard on the 3.5" TFT (320x480, Terminus 8x14 -> 40 cols x 34 rows).
No emoji in code. CGA/demoscene aesthetic. All rows are exactly WIDTH (40) wide.

## Frame budget (fixed zones)

`lcd_frame_zones(frame_h)` carves the 34 rows so header/panel/footer/events
never overlap. Constants live at the top of `zealot_lcd_render.py`:

    LCD_HEADER_ROWS       = 3
    LCD_MODE_BAR_ROWS     = 1
    LCD_ART_ROWS          = 3
    LCD_PANEL_MAX_ROWS    = 7
    LCD_FX_ROWS           = 1
    LCD_EVENTS_HEADER_ROWS= 1
    LCD_EVENTS_MIN_ROWS   = 8
    LCD_EVENT_MAX_BODY_LINES = 4

Resulting row map at 40x34:

    row  zone           renderer (zealot_display.draw)
    ---  -------------  ---------------------------------------------------
    0    header_start   top_status_segments        ZEAL clock + Wk + FRI counter
    1    header+1       wopr_header_segments        DEFCON/WOPR strip + mode rotator
    2    header+2       chunky_scroller(ticker_scroll_body)  rotating mesh ticker
    3    mode_bar       weekend_monday_countdown_segments    MON weekend counter
    4-6  art_start      mode_art_compact (3 rows)   centered ANSI box per mode
                        agents_art_live             animated LAN BUS when mode=agents
    7-13 panel_start    panel_lines (max 7)         per-mode body (see below)
    14   calendar_row   calendar_segments           full weekday + date + ISO week
    15   status_row     dashboard_footer_segments   host IP + MOTD scroller
    16   fx_row         demoscene_fx_row            rotating greetz/tunnel/sparkle/raster
    17   events_hdr     comet_line("EVENTS")        animated comet header
    18-32 events        event_display_rows          colored chatter, BOTTOM-pinned
    33   input_row      lcd_status_line / input buf

Events are reserved >= LCD_EVENTS_MIN_ROWS; if the panel zone would starve them
the panel start slides up.

## Two weekly counters (distinct, never duplicated)

- Row 0 right side: FRI counter - progress through the work week toward Fri 17:00
  (`_fri_progress`, label "FRI", green bar). Fills the wasted space next to the clock.
- Row 3: MON counter - progress through the weekend toward Mon 10:00
  (`_mon_progress`, label "MON", magenta bar). 0% fill while still inside the work week.

Both render through `labeled_week_rail(now, width, label, pct_val, dur_secs, style)`
which produces `<LABEL> [*###----*] pct countdown`, dropping the countdown then the
pct as width shrinks, never overflowing. The bar is `progress_bar_segments`
(`*###----*` ANSI block, colored fill + dim empty). Do NOT put a week bar on the
calendar row - that was the old duplication bug.

## Header detail

- `top_status_segments`: `ZEAL HH:MM:SS W##` (cyan) + space + FRI rail in the
  remaining width. No unix epoch (it was noise/wasted space).
- `wopr_header_segments`: centered DEFCON tokens (level-colored) + mode rotator,
  glint rails on the edges. Falls back to plain DEFCON if width is tight.
- Ticker row: `ticker_scroll_body` returns ONE frame at a time (alerts, zone, npc,
  agent call summaries, GPU) rotated every TICKER_FRAME_PERIOD_SEC, fed through
  `chunky_scroller`. Never join everything into one chopped mega-line.

## ANSI mode art (rows 4-6)

`mode_art` block-centers the whole ASCII box with one shared left margin
(use `pad`, not `fit` - fit() strips the leading spaces). `MODE_ART` holds the
4-line boxes; `MODE_ART_PICK` selects 3 rows; `mode_art_compact` returns them.
RGB mode animates `RGB_BATTLE_FRAMES`. When mode=agents, `agents_art_live`
replaces the art with an animated LAN BUS rail + live phone state + scrolling roster.

## Panel zone (rows 7-13) by mode

`panel_lines(snapshot, mode, ...)` dispatches:

    terrarium -> terrarium_panel    LAN telemetry
    uptime    -> uptime_panel       boot age / load
    ops       -> ops_panel          NOC HOST TABLE + ascii_bar/bar graphs
    rpg       -> rpg_panel          Crystal Mesh quest state
    rgb       -> rgb_battle_panel
    agents    -> agents_panel       PBX roster, call highlight
    bridge    -> bridge_panel       SillyTavern co-canon
    lounge    -> lounge_panel       latest colored IRC chatter, bottom-pinned

Mode rotation `XTREE_MODES` cycles all eight every MODE_PERIOD_SEC.

## Live chatter (events + lounge)

- EVENTS zone is bottom-pinned (newest line hugs the input row, scrollback above)
  like a real IRC log. `event_display_rows` wraps up to LCD_EVENT_MAX_BODY_LINES,
  full nicks (no truncation), no channel tags, age-only prefix `[1m]`.
- Per-character color via `IRC_NICK_STYLES` (+ stable hash fallback through
  `COMPANION_LINE_COLORS`). Nick and body share the character's hue.
- `lounge_panel` fills all 7 panel rows with the freshest chatter, bottom-pinned,
  no header/rule waste.

## Demoscene FX strip (row 16)

`demoscene_fx_row` rotates every FX_ROW_PERIOD_SEC through:
greetz+GPU, tunnel bus, sparkle field, raster bar. Keeps the board alive.

## Full-screen overlays (pre-empt the dashboard)

- WarGames: `poll_joshua_wopr()` returns a live session (ext 124) -> `draw_wopr_overlay`
  takes the whole screen, dashboard returns on hangup.
- PBX call: `sip_active` (active call, not ext 124) -> `draw_sip_overlay` shows the
  full-screen live transcript. Returns to mesh dashboard on hangup.

## Color styles -> curses pairs

`attr_for` in `zealot_display.py` maps style names to pairs. Character/bar styles
that get A_BOLD: IRC_CHAN, IRC_NICK, ZP, ZH, RPG, ST, PBX, NOC, CYAN, MAG, RGB,
GREEN, YELLOW, RED, TICK, ART, LOG, GMQ. IRC_TIME/SYS are dim. Keep new style names
in both the `attr_for` pair map and the bold set.

## Deploy

Copy `zealot_display.py` + `zealot_lcd_render.py` to the Pi `~/.local/bin/`, run
`lcd-init`. Keep `patches/zealot_display.py` and `patches/zealot_lcd_render.py` in
sync with the repo root - `patches/apply-on-zeal.sh` rsyncs them to the Pi and a
stale copy will silently revert the layout.

Windows path: scp to CELES (10.13.37.37), then CELES scp to zeal (10.13.37.76);
direct scp -J / ProxyJump from Windows tends to hang.

## Regression guardrails (what "lost features" looked like)

- Header downgraded to plain mono strings instead of `*_segments`.
- Mode art shrunk to 2 rows or left-aligned (broke the centered box).
- Duplicate week bar on both mode_bar and calendar rows.
- Events top-pinned leaving a large blank gap at the bottom.
- `lounge` dropped from `XTREE_MODES`; lounge_panel unreachable.
- Full-screen SIP overlay disconnected from `draw()`.
- `patches/` left stale so deploys reverted the live layout.
