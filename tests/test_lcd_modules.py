import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import zealot_sip_flash
from zealot_lcd_feeds import LcdEvent, dedupe_events, parse_local_line
from zealot_lcd_render import (
    WIDTH,
    bar,
    calendar_line,
    chunky_scroller,
    compact_bar,
    comet_line,
    demoscene_greetz,
    event_lines,
    fmt_duration_short,
    fmt_uptime,
    gpu_summary,
    mode_art,
    motivational_line,
    panel_lines,
    raster_bar,
    render_text_frame,
    rgb_quote,
    spark,
    sparkle_line,
    tunnel_line,
    transition_text,
)
from zealot_sip_flash import SipCallFlash


class LcdFeedTests(unittest.TestCase):
    def test_parse_local_privmsg(self):
        event = parse_local_line("RPG", "#RPG", "12:54a <Rift> communes with Vector", 1.0)
        self.assertEqual(event.source, "RPG")
        self.assertEqual(event.nick, "Rift")
        self.assertIn("communes", event.text)

    def test_parse_local_action(self):
        event = parse_local_line("RPG", "#RPG", "12:54a * Hex travels to #RPG Channel Road", 1.0)
        self.assertEqual(event.kind, "action")
        self.assertEqual(event.nick, "Hex")

    def test_dedupe_keeps_one(self):
        one = LcdEvent("ST", "bridge", "Yomiko", "memory", sort_ts=1)
        two = LcdEvent("ST", "bridge", "Yomiko", "memory", sort_ts=2)
        self.assertEqual(len(dedupe_events([one, two])), 1)


class LcdRenderTests(unittest.TestCase):
    def test_event_lines_fit_width(self):
        event = LcdEvent("ST", "bridge", "Yomiko", "x" * 120, canon="sillytavern")
        for row, _style in event_lines(event, WIDTH):
            self.assertLessEqual(len(row), WIDTH)

    def test_event_lines_wrap_overflow_without_animation_fill(self):
        event = LcdEvent("RPG", "#RPG", "LongNick", "alpha " * 80, canon="queued")
        rows = event_lines(event, WIDTH)
        self.assertGreater(len(rows), 1)
        self.assertTrue(any(row.rstrip().endswith("~") for row, _style in rows))
        self.assertTrue(all("_-=" not in row for row, _style in rows))

    def test_frame_is_fixed_size(self):
        snapshot = {
            "events": [LcdEvent("RPG", "#RPG", "DM", "hello", sort_ts=1)],
            "bridge": {"ok": True, "hot_zone": "Crystal Mesh", "npc_count": 1, "players_total": 2, "gm_pending": []},
            "status": {"vector_ok": True, "pbx_api_ok": True},
            "celes": {"fresh": False},
            "direct_irc": {"ok": True},
        }
        frame = render_text_frame(snapshot, now=0)
        self.assertEqual(len(frame), 34)
        self.assertTrue(all(len(row) == WIDTH for row in frame))

    def test_flourish_lines_fit_width(self):
        self.assertEqual(len(comet_line("ZEAL", now=1, width=WIDTH)), WIDTH)
        self.assertEqual(len(sparkle_line(now=1, width=WIDTH)), WIDTH)
        for mode in ("terrarium", "uptime", "ops", "rpg", "rgb", "agents", "bridge", "lounge"):
            for row in mode_art(mode, now=1, width=WIDTH):
                self.assertEqual(len(row), WIDTH)

    def test_graph_helpers_are_fixed_width(self):
        self.assertEqual(len(bar(55, width=8)), 10)
        self.assertIn("█", bar(55, width=8))
        self.assertEqual(len(compact_bar(55, width=6)), 6)
        self.assertEqual(len(spark([0, 25, 50, 75, 100], width=12)), 12)
        self.assertIn("█", spark([100], width=1))
        self.assertEqual(transition_text("stable text", now=0, row=0, width=WIDTH), "stable text".ljust(WIDTH))

    def test_demoscene_helpers_fit_width(self):
        snapshot = {
            "status": {
                "telemetry": {
                    "remote": {
                        "hosts": {
                            "vector": {"gpus": [{"util_pct": 42, "mem_used_mb": 2048, "mem_total_mb": 8192}]},
                            "zealtower": {"gpus": [{"util_pct": 7, "mem_used_mb": 512, "mem_total_mb": 6144}]},
                        }
                    }
                }
            }
        }
        self.assertIn("VEC GPU", gpu_summary(snapshot))
        self.assertEqual(len(chunky_scroller("hyperbusiness", now=1, width=WIDTH)), WIDTH)
        self.assertEqual(len(raster_bar(now=1, width=WIDTH)), WIDTH)
        self.assertEqual(len(tunnel_line(now=1, width=WIDTH)), WIDTH)
        self.assertEqual(len(demoscene_greetz(snapshot, now=1, width=WIDTH)), WIDTH)
        self.assertEqual(len(motivational_line(snapshot, now=1, width=WIDTH)), WIDTH)

    def test_uptime_slide_fits_width(self):
        snapshot = {
            "status": {
                "telemetry": {
                    "local": {
                        "uptime_sec": 3661,
                        "cpu_pct": 12,
                        "load1": 0.2,
                        "load5": 0.3,
                        "mem_pct": 36,
                        "disks": [{"path": "/", "pct": 52}],
                    },
                    "remote": {
                        "age_sec": 3,
                        "fresh": True,
                        "hosts": {
                            "zealtower": {
                                "uptime_sec": 14 * 86400 + 3 * 3600,
                                "cpu_pct": 8,
                                "load1": 0.1,
                                "load5": 0.2,
                                "mem_pct": 44,
                                "disks": [{"path": "/mnt/cache", "pct": 89}],
                            },
                            "vector": {
                                "uptime_sec": 3 * 86400 + 4 * 3600,
                                "cpu_pct": 21,
                                "load1": 1.1,
                                "load5": 0.8,
                                "mem_pct": 61,
                                "disks": [{"path": "/mnt/c", "pct": 96}],
                            },
                        },
                    },
                }
            }
        }
        rows = panel_lines(snapshot, "uptime", WIDTH)
        self.assertEqual(fmt_uptime(90061), "1d01h")
        self.assertTrue(any("ztwr up 14d03h" in row for row, _style in rows))
        self.assertTrue(all(len(row) <= WIDTH for row, _style in rows))

    def test_rgb_panel_and_quote_fit_width(self):
        snapshot = {
            "bridge": {"hot_zone": "Crystal Mesh", "era": "2026-06-15-end-of-day-2026-06-16"},
            "status": {"vector_ok": True, "pbx_api_ok": True},
        }
        rows = panel_lines(snapshot, "rgb", WIDTH)
        self.assertEqual(rgb_quote(0), rgb_quote(29 * 60))
        self.assertTrue(any("RGB BATTLE" in row for row, _style in rows))
        self.assertTrue(any("QOTD" in row for row, _style in rows))
        self.assertTrue(all(len(row) <= WIDTH for row, _style in rows))

    def test_calendar_line_includes_week_countdowns(self):
        now = datetime(2026, 6, 16, 12, 0).timestamp()
        row = calendar_line(now, WIDTH)
        self.assertEqual(len(row), WIDTH)
        self.assertIn("Jun", row)
        self.assertIn("W25/52", row)
        self.assertIn("Y-27w", row)
        self.assertIn("WK", row)
        self.assertIn("WB", row)
        self.assertEqual(fmt_duration_short(5 * 86400 + 3 * 3600), "5d03h")


class SipFlashTests(unittest.TestCase):
    def test_sip_overlay_hidden_without_active_lines(self):
        original = zealot_sip_flash.SIP_FLASH
        with tempfile.TemporaryDirectory() as tmp:
            zealot_sip_flash.SIP_FLASH = Path(tmp) / "sip_call_flash.json"
            try:
                zealot_sip_flash.SIP_FLASH.write_text(
                    json.dumps({"state": "talking", "active_lines": 0, "duration": 30}),
                    encoding="utf-8",
                )
                flash = SipCallFlash(lambda text, fonts=None: [text])
                flash.poll_file()
                self.assertFalse(flash.active())
                self.assertEqual(flash.header_title(), "")
            finally:
                zealot_sip_flash.SIP_FLASH = original

    def test_sip_overlay_shows_for_active_call(self):
        original = zealot_sip_flash.SIP_FLASH
        with tempfile.TemporaryDirectory() as tmp:
            zealot_sip_flash.SIP_FLASH = Path(tmp) / "sip_call_flash.json"
            try:
                zealot_sip_flash.SIP_FLASH.write_text(
                    json.dumps({"state": "talking", "active_lines": 1, "duration": 30}),
                    encoding="utf-8",
                )
                flash = SipCallFlash(lambda text, fonts=None: [text])
                flash.poll_file()
                self.assertTrue(flash.active())
                self.assertEqual(flash.header_title(), "PBX LINE ACTIVE")
            finally:
                zealot_sip_flash.SIP_FLASH = original


if __name__ == "__main__":
    unittest.main()
