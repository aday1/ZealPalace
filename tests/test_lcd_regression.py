"""LCD regression contract — run before every deploy.

    python -m pytest tests/test_lcd_regression.py tests/test_lcd_modules.py -q
"""
from __future__ import annotations

import unittest
from pathlib import Path

from zealot_lcd_feeds import (
    LcdEvent,
    LCD_EVENT_TEXT_CLIP,
    collect_snapshot,
    dedupe_events,
    event_is_recurring_noise,
)
from zealot_lcd_render import (
    WIDTH,
    LCD_EVENT_MAX_BODY_LINES,
    LCD_EVENT_OLD_MAX_LINES,
    LCD_TICKER_VERSION,
    LCD_TYPEWRITER_CPS,
    compact_event_draw_rows,
    event_display_entries,
    event_msg_style,
    _event_body_key,
    _fit_event_body_lines,
    _line_ends_complete_thought,
)

REPO = Path(__file__).resolve().parents[1]
LCD_CANONICAL = (
    "zealot_display.py",
    "zealot_lcd_render.py",
    "zealot_lcd_feeds.py",
)


class LcdRegressionContract(unittest.TestCase):
    def test_patches_match_canonical_lcd_sources(self):
        for name in LCD_CANONICAL:
            root = (REPO / name).read_text(encoding="utf-8")
            patch = (REPO / "patches" / name).read_text(encoding="utf-8")
            self.assertEqual(root, patch, f"patches/{name} is stale — sync before deploy")

    def test_ticker_version_is_set(self):
        self.assertTrue(LCD_TICKER_VERSION.startswith("tkr"))
        self.assertGreaterEqual(len(LCD_TICKER_VERSION), 7)

    def test_event_budget_constants(self):
        self.assertGreaterEqual(LCD_EVENT_MAX_BODY_LINES, 6)
        self.assertGreater(LCD_EVENT_OLD_MAX_LINES, 0)
        self.assertLess(LCD_EVENT_OLD_MAX_LINES, LCD_EVENT_MAX_BODY_LINES)
        self.assertGreaterEqual(LCD_EVENT_TEXT_CLIP, 200)
        self.assertLessEqual(LCD_EVENT_TEXT_CLIP, 600)

    def test_meteor_strike_age_label_format(self):
        from zealot_lcd_render import meteor_strike_age_label

        label = meteor_strike_age_label(now=2_000_000_000.0)
        self.assertTrue(label.startswith("MET+") or label == "MET ?")

    def test_typewriter_not_too_slow(self):
        self.assertGreaterEqual(LCD_TYPEWRITER_CPS, 20.0)

    def test_no_duplicate_irc_when_tap_live(self):
        event = LcdEvent(
            "RPG",
            "#RPG",
            "DM",
            "The realms atmosphere shifts as storms gather",
            sort_ts=100.0,
        )
        dup = LcdEvent(
            "IRC",
            "#RPG",
            "DM",
            "The realms atmosphere shifts as storms gather",
            sort_ts=100.5,
        )
        self.assertEqual(len(dedupe_events([event, dup])), 1)

    def test_presence_join_hidden(self):
        join = LcdEvent("IRC", "#RPG", "bot", "join #RPG", kind="presence", sort_ts=1.0)
        self.assertTrue(event_is_recurring_noise(join))

    def test_per_kind_event_colors_differ(self):
        from zealot_lcd_render import event_body_style, event_msg_style

        battle = event_msg_style(LcdEvent("ST", "x", "b", "fight", kind="battle", sort_ts=1.0))
        lore = event_msg_style(LcdEvent("ST", "x", "l", "text", kind="lore", sort_ts=1.0))
        talk = event_body_style(LcdEvent("ZP", "#RPG", "Yomiko", "hi", kind="message", sort_ts=1.0))
        self.assertEqual(battle, "RED")
        self.assertEqual(lore, "ST")
        self.assertEqual(talk, "MAG")
        self.assertNotEqual(battle, lore)

    def test_no_dangling_battle_against_the(self):
        body = (
            "The party joins battle against the corrupted disk sectors while packets "
            "fly across the mesh like sparks."
        )
        lines = _fit_event_body_lines(body, 26, 38, 4)
        self.assertTrue(_line_ends_complete_thought(lines[-1]))
        self.assertNotRegex(lines[-1], r"\bthe\s*$")

    def test_lore_old_budget_shows_ellipsis_not_silent_chop(self):
        body = (
            "mesh atmosphere shift: critical levels as packet loss spikes and "
            "throughput collapses across the terrarium mesh."
        )
        lines = _fit_event_body_lines(body, 31, 39, 2)
        self.assertLessEqual(len(lines), 2)
        self.assertTrue(lines[-1].endswith("..."))

    def test_narrative_old_events_keep_head_not_tail(self):
        row = lambda base, idx, kind="message", ts=1.0: (
            [],
            [(f"line{idx}", "IRC_MSG")],
            f"{base}|{idx}",
            f"ST|bridge:lore|lore|{kind}|{ts}|body",
            ts,
            False,
        )
        lore_base = "ST|bridge:lore|lore|lore|1.0|body"
        rows = [row(lore_base, 0, "lore"), row(lore_base, 1, "lore"), row(lore_base, 2, "lore")]
        out = compact_event_draw_rows(rows, 2, "other|#RPG|x|message|9|fresh")
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0][2], f"{lore_base}|0")

    def test_build_event_zone_rows_fills_slots(self):
        from zealot_lcd_render import build_event_zone_rows

        slots = 12
        events = [
            LcdEvent("RPG", "#RPG", "A", "older one-liner", sort_ts=1.0),
            LcdEvent(
                "RPG",
                "#RPG",
                "B",
                "fresh " + ("word " * 80),
                kind="message",
                sort_ts=2.0,
            ),
        ]
        rows = build_event_zone_rows(events, slots, WIDTH, now=100.0)
        self.assertGreaterEqual(len(rows), min(slots, 6))
        self.assertEqual(rows[-1][3], _event_body_key(events[-1]))

    def test_newest_event_keeps_wrap_rows(self):
        row = lambda base, idx, ts=1.0: (
            [],
            [("line", "IRC_MSG")],
            f"{base}|{idx}",
            base,
            ts,
            True,
        )
        newest = _event_body_key(
            LcdEvent("RPG", "#RPG", "A", "fresh battle cry", sort_ts=999.0)
        )
        rows = [row("old", 0), row("old", 1), row(newest, 0), row(newest, 1), row(newest, 2)]
        out = compact_event_draw_rows(rows, 4, newest, older_tail_lines=LCD_EVENT_OLD_MAX_LINES)
        self.assertEqual(sum(1 for r in out if r[3] == newest), 3)

    def test_event_entries_respect_width(self):
        event = LcdEvent(
            "RPG",
            "#RPG",
            "LongSpeaker",
            "word " * 40,
            kind="message",
            sort_ts=1.0,
        )
        for prefix, body, _key, _base, _ts, _typeable in event_display_entries(
            event, WIDTH, now=100.0, max_body_lines=LCD_EVENT_MAX_BODY_LINES
        ):
            text = "".join(t for t, _s in prefix) + "".join(t for t, _s in body)
            self.assertLessEqual(len(text), WIDTH)

    def test_collect_snapshot_shape(self):
        snap = collect_snapshot(irc_tap=None, limit=8)
        self.assertIn("events", snap)
        self.assertIn("bridge", snap)
        self.assertIsInstance(snap["events"], list)


if __name__ == "__main__":
    unittest.main()
