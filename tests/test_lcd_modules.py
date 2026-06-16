import unittest

from zealot_lcd_feeds import LcdEvent, dedupe_events, parse_local_line
from zealot_lcd_render import (
    WIDTH,
    bar,
    chunky_scroller,
    comet_line,
    demoscene_greetz,
    event_lines,
    gpu_summary,
    mode_art,
    motivational_line,
    raster_bar,
    render_text_frame,
    spark,
    sparkle_line,
    tunnel_line,
)


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
        for mode in ("terrarium", "ops", "rpg", "agents", "bridge", "lounge"):
            for row in mode_art(mode, now=1, width=WIDTH):
                self.assertEqual(len(row), WIDTH)

    def test_graph_helpers_are_fixed_width(self):
        self.assertEqual(len(bar(55, width=8)), 10)
        self.assertEqual(len(spark([0, 25, 50, 75, 100], width=12)), 12)

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


if __name__ == "__main__":
    unittest.main()
