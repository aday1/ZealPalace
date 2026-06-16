#!/usr/bin/env python3
import json
import sys
import tempfile
import unittest
from pathlib import Path

LCD = Path(__file__).resolve().parents[1]
if str(LCD) not in sys.path:
    sys.path.insert(0, str(LCD))

import zealot_sip_flash  # noqa: E402
from zealot_sip_flash import SipCallFlash, transcript_display_lines  # noqa: E402


class TranscriptLineTests(unittest.TestCase):
    def test_word_wrap_and_speaker_labels(self):
        turns = [
            {
                "role": "user",
                "label": "aday",
                "text": "please check the mesh status for zeal palace and report back",
                "ts": "2026-06-16T12:04:00Z",
            },
            {
                "role": "assistant",
                "label": "Hermes",
                "text": "ZealPalace is online. Mesh links are stable.",
                "ts": "2026-06-16T12:04:05Z",
            },
        ]
        lines = transcript_display_lines(turns, width=40, max_rows=20, now=1000.0)
        self.assertTrue(any("aday:" in row for row, _style in lines))
        self.assertTrue(any("Hermes:" in row for row, _style in lines))
        self.assertTrue(all(len(row) <= 40 for row, _style in lines))

    def test_scroll_pins_to_latest_rows(self):
        turns = []
        for i in range(12):
            turns.append(
                {
                    "role": "user" if i % 2 == 0 else "assistant",
                    "label": "YOU" if i % 2 == 0 else "Navi",
                    "text": f"turn-{i}",
                    "ts": f"2026-06-16T12:{i:02d}:00Z",
                }
            )
        lines = transcript_display_lines(turns, width=40, max_rows=6, now=2000.0)
        self.assertEqual(len(lines), 6)
        joined = " ".join(row for row, _style in lines)
        self.assertIn("turn-11", joined)
        self.assertNotIn("turn-0", joined)


class SipFlashTurnTests(unittest.TestCase):
    def test_poll_loads_turns_from_flash_json(self):
        original = zealot_sip_flash.SIP_FLASH
        with tempfile.TemporaryDirectory() as tmp:
            zealot_sip_flash.SIP_FLASH = Path(tmp) / "sip_call_flash.json"
            zealot_sip_flash.SIP_FLASH.write_text(
                json.dumps(
                    {
                        "state": "talking",
                        "active_lines": 1,
                        "duration": 600,
                        "from_ext": "100",
                        "to_ext": "111",
                        "turns": [
                            {
                                "role": "user",
                                "label": "aday",
                                "text": "hello hermes",
                                "ts": "2026-06-16T12:00:00Z",
                            },
                            {
                                "role": "assistant",
                                "label": "Hermes",
                                "text": "hello operator",
                                "ts": "2026-06-16T12:00:02Z",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            flash = SipCallFlash(lambda text, fonts=None: [text])
            flash.poll_file()
            self.assertTrue(flash.active())
            self.assertEqual(len(flash.turns), 2)
            rows = flash.transcript_lines(40, 8, now=100.0)
            self.assertTrue(any("hello hermes" in row for row, _style in rows))
            self.assertTrue(any("hello operator" in row for row, _style in rows))
        zealot_sip_flash.SIP_FLASH = original


if __name__ == "__main__":
    unittest.main()