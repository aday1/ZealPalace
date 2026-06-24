import json
import re
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import zealot_sip_flash
from zealot_lcd_feeds import LcdEvent, dedupe_events, feed_line_is_noise, parse_local_line
from zealot_lcd_render import (
    WIDTH,
    MODE_PERIOD_SEC,
    PBX_AGENT_ROSTER,
    PBX_AGENT_VISIBLE,
    agent_row,
    agent_book_page,
    agent_visible_rows,
    agents_panel,
    detail_kv,
    host_long_name,
    LCD_TICKER_VERSION,
    agent_ticker_bits,
    agents_art_live,
    dashboard_header,
    lan_bus_status_line,
    mode_section_bar,
    ticker_text,
    panel_section_label,
    mode_seconds_left,
    noc_mesh_dns_line,
    ops_panel,
    pbx_agent_roster,
    bar,
    calendar_line,
    work_week_countdown_line,
    work_week_phase,
    weekend_monday_countdown_line,
    chunky_scroller,
    compact_bar,
    comet_line,
    dashboard_footer,
    dashboard_footer_segments,
    demoscene_bottom_scroller,
    demoscene_greetz,
    event_lines,
    event_segments,
    event_display_rows,
    fmt_age_short,
    fmt_duration_short,
    mesh_sync_alert_summary,
    mesh_table_row_segments,
    fmt_uptime,
    gpu_summary,
    mode_art,
    motivational_line,
    panel_lines,
    raster_bar,
    render_text_frame,
    rgb_quote,
    scroll_window,
    spark,
    sparkle_line,
    tunnel_line,
    transition_text,
)
from zealot_sip_flash import SipCallFlash, read_active_call_exts, read_active_call_exts_highlight


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

    def test_feed_noise_filters_lcd_startup(self):
        self.assertTrue(
            feed_line_is_noise(
                "aday",
                'export TERM=linux; bash "$HOME/.local/bin/zealot_display_loop.sh"',
            )
        )
        self.assertFalse(feed_line_is_noise("Zealot", "still here on the mesh"))

    def test_parse_local_line_drops_lcd_noise(self):
        line = '3:18pm <aday> export TERM=linux; bash "$HOME/.local/bin/zealot_display_loop.sh"'
        self.assertIsNone(parse_local_line("ZP", "#ZealPalace", line, 1.0))


class LcdRenderTests(unittest.TestCase):
    def test_event_lines_fit_width(self):
        event = LcdEvent("ST", "bridge", "Yomiko", "x" * 120, canon="sillytavern")
        for row, _style in event_lines(event, WIDTH):
            self.assertLessEqual(len(row), WIDTH)

    def test_event_lines_wrap_overflow_without_animation_fill(self):
        event = LcdEvent("RPG", "#RPG", "LongNick", "alpha " * 80, canon="queued")
        rows = event_lines(event, WIDTH, now=None, max_body_lines=4)
        self.assertGreater(len(rows), 1)
        self.assertFalse(any(row.rstrip().endswith("~") for row, _style in rows))
        self.assertTrue(all("_-=" not in row for row, _style in rows))

    def test_event_lines_scroll_long_irc_uses_wrap_or_marquee(self):
        event = LcdEvent("ZP", "#ZealPalace", "Zealot", "alpha " * 80, canon="irc", sort_ts=1.0)
        rows = event_display_rows(event, WIDTH, now=12.5, max_body_lines=4)
        self.assertGreaterEqual(len(rows), 2)
        joined = " ".join("".join(part for part, _style in row) for row in rows)
        self.assertIn("alpha", joined)
        styles = {style for row in rows for _text, style in row}
        self.assertIn("IRC_TIME", styles)
        self.assertIn("ZP", styles)

    def test_event_lines_long_prose_wraps_multiple_rows(self):
        body = "The Boox NoteAir tower stands vigilant over the archive spire"
        event = LcdEvent("RPG", "#RPG", "Yomiko", body, canon="queued", sort_ts=100.0)
        rows = event_display_rows(event, WIDTH, now=200.0, max_body_lines=4)
        self.assertGreaterEqual(len(rows), 2)
        joined = " ".join("".join(part for part, _style in row) for row in rows)
        self.assertIn("Boox", joined)
        self.assertIn("archive", joined)
        self.assertNotIn("~", joined)

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
        for mode in ("terrarium", "uptime", "ops", "rpg", "rgb", "agents", "bridge"):
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
        fx_line = demoscene_bottom_scroller("hello mesh", now=3.5, width=WIDTH)
        self.assertEqual(len(fx_line), WIDTH)
        self.assertIn("hello mesh", fx_line)
        footer = dashboard_footer(snapshot, now=3.5, tick=42, width=WIDTH)
        self.assertEqual(len(footer), WIDTH)
        segments = dashboard_footer_segments(snapshot, now=3.5, tick=42, width=WIDTH)
        self.assertTrue(any(style == "MOTD" for _text, style in segments))

    def test_event_segments_color_roles(self):
        event = LcdEvent("ZP", "#ZealPalace", "Zealot", "mesh online", sort_ts=1.0)
        segments = event_segments(event, WIDTH, now=100.0)
        styles = {style for _text, style in segments}
        text = "".join(part for part, _style in segments)
        self.assertIn("IRC_TIME", styles)
        self.assertIn("ZP", styles)
        self.assertIn("IRC_MSG", styles)
        self.assertIn("[1m]", text)
        self.assertNotRegex(text, r"\[\d{2}:\d{2}\]")
        self.assertIn("[Zealot]", text)
        self.assertNotIn("[#", text)
        self.assertLessEqual(sum(len(part) for part, _style in segments), WIDTH)

    def test_event_nick_per_character_color(self):
        yomiko = LcdEvent("ZP", "#ZealPalace", "Yomiko", "hello", sort_ts=1.0)
        chmod = LcdEvent("ZP", "#ZealPalace", "Chmod", "ping", sort_ts=1.0)
        y_styles = {style for _text, style in event_segments(yomiko, WIDTH, now=100.0)}
        c_styles = {style for _text, style in event_segments(chmod, WIDTH, now=100.0)}
        self.assertIn("MAG", y_styles)
        self.assertIn("RED", c_styles)

    def test_event_full_nick_no_truncation(self):
        nick = "VeryLongNickName"
        event = LcdEvent("ZP", "#ZealPalace", nick, "hi", sort_ts=1.0)
        text = "".join(part for part, _style in event_segments(event, WIDTH, now=100.0))
        self.assertIn("[" + nick + "]", text)
        self.assertNotIn("...", text)

    def test_event_body_color_by_type(self):
        talk = LcdEvent("ZP", "#RPG", "Yomiko", "hello friends", sort_ts=1.0)
        action = LcdEvent("RPG", "#RPG", "Hex", "wanders the spire", kind="action", sort_ts=1.0)
        realm = LcdEvent("ST", "bridge", "CrystalMesh", "realm pulse rolls in", canon="bridge", sort_ts=1.0)
        talk_styles = {s for _t, s in event_segments(talk, WIDTH, now=100.0)}
        act_styles = {s for _t, s in event_segments(action, WIDTH, now=100.0)}
        realm_styles = {s for _t, s in event_segments(realm, WIDTH, now=100.0)}
        self.assertIn("IRC_MSG", talk_styles)   # talking -> white
        self.assertIn("GRAY", act_styles)       # actions -> gray
        self.assertIn("EVT", realm_styles)      # realm/system -> light green

    def test_event_red_end_of_line_dot(self):
        event = LcdEvent("ZP", "#RPG", "Yomiko", "lets raid the caves", sort_ts=1.0)
        rows = event_display_rows(event, WIDTH, now=100.0, max_body_lines=4)
        last = rows[-1]
        reds = [t for t, s in last if s == "RED"]
        self.assertIn(".", reds)

    def test_top_status_has_no_week_marker(self):
        from zealot_lcd_render import top_status_line
        row = top_status_line(datetime(2026, 6, 24, 13, 21).timestamp(), WIDTH)
        self.assertIn("ZEAL", row)
        self.assertNotRegex(row, r"W\d{2}")  # week lives only on the calendar row

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
        self.assertTrue(any("ZTW" in row and "14d" in row for row, _style in rows))
        self.assertTrue(all(len(row) <= WIDTH for row, _style in rows))

    def test_rgb_panel_and_quote_fit_width(self):
        snapshot = {
            "bridge": {"hot_zone": "Crystal Mesh", "era": "2026-06-15-end-of-day-2026-06-16"},
            "status": {"vector_ok": True, "pbx_api_ok": True},
        }
        rows = panel_lines(snapshot, "rgb", WIDTH)
        self.assertEqual(rgb_quote(0), rgb_quote(29 * 60))
        self.assertTrue(any("RGB ROLES" in row or "QOTD" in row for row, _style in rows))
        self.assertTrue(any("QOTD" in row for row, _style in rows))
        self.assertTrue(all(len(row) <= WIDTH for row, _style in rows))

    def test_calendar_line_shows_date(self):
        now = datetime(2026, 6, 16, 12, 0).timestamp()
        row = calendar_line(now, WIDTH)
        self.assertEqual(len(row), WIDTH)
        self.assertIn("Jun", row)
        self.assertNotIn("W25/52", row)
        self.assertEqual(fmt_duration_short(5 * 86400 + 3 * 3600), "5d03h")


class WeeklyCountdownTests(unittest.TestCase):
    def test_work_week_line_midweek(self):
        now = datetime(2026, 6, 17, 12, 0).timestamp()
        self.assertEqual(work_week_phase(datetime.fromtimestamp(now)), "work")
        row = work_week_countdown_line(now, WIDTH)
        self.assertEqual(len(row), WIDTH)
        self.assertIn("FRI", row)
        self.assertIn("*#", row)
        self.assertIn("%", row)

    def test_weekend_line_midweek_mon_countdown(self):
        now = datetime(2026, 6, 17, 12, 0).timestamp()
        row = weekend_monday_countdown_line(now, WIDTH)
        self.assertEqual(len(row), WIDTH)
        self.assertIn("MON", row)

    def test_weekend_phase_saturday(self):
        now = datetime(2026, 6, 20, 12, 0).timestamp()
        self.assertEqual(work_week_phase(datetime.fromtimestamp(now)), "weekend")
        wk = work_week_countdown_line(now, WIDTH)
        mon = weekend_monday_countdown_line(now, WIDTH)
        self.assertEqual(len(wk), WIDTH)
        self.assertEqual(len(mon), WIDTH)
        self.assertIn("MON", mon)
        self.assertIn("*#", mon)

    def test_monday_pre_open_edge(self):
        now = datetime(2026, 6, 15, 9, 0).timestamp()
        self.assertEqual(work_week_phase(datetime.fromtimestamp(now)), "weekend")
        wk = work_week_countdown_line(now, WIDTH)
        self.assertIn("*#", wk)


class ModeBarTests(unittest.TestCase):
    def test_mode_bar_includes_countdown(self):
        now = 5.0
        row = mode_section_bar("uptime", WIDTH, now)
        self.assertIn(f"{mode_seconds_left(now):02d}s", row)
        self.assertEqual(len(row), WIDTH)
        self.assertNotIn("~", row)

    def test_mode_bar_uses_full_tab_names_when_fitting(self):
        row = mode_section_bar("bridge", WIDTH, now=0.0)
        self.assertIn("ST BRIDGE", row)
        self.assertNotRegex(row, r">>BRDG\b")

    def test_dashboard_header_omits_mode_name(self):
        snapshot = {"status": {"vector_ok": True, "pbx_api_ok": True}, "bridge": {"ok": True}, "celes": {"fresh": True}}
        row = dashboard_header(snapshot, "lounge", now=1_700_000_000.0, tick=1, width=WIDTH)
        self.assertEqual(len(row), WIDTH)
        self.assertNotIn("IRC LOUNGE", row)
        self.assertNotIn("TERRARIUM", row)
        self.assertNotIn("VEC", row)
        iso_week = datetime.fromtimestamp(1_700_000_000.0).isocalendar().week
        self.assertIn(f"Week{iso_week}", row)
        self.assertIn("[1700000000]", row)
        self.assertNotRegex(row, r"#\d{5}")
        self.assertTrue(row.startswith(" "))
        self.assertTrue(row.endswith(" "))

    def test_mode_art_is_center_aligned(self):
        rows = mode_art("ops", now=1000.0, width=WIDTH)
        self.assertTrue(rows)
        core = rows[0].strip()
        self.assertIn("NOC BUS", core)
        # Glint brackets may consume edge padding on full-width art rows.
        self.assertLessEqual(len(rows[0]), WIDTH)
        self.assertGreater(len(core), 0)

    def test_dashboard_footer_omits_week_and_tick(self):
        snapshot = {"status": {"telemetry": {"local": {}}}}
        footer = dashboard_footer(snapshot, now=1_700_000_000.0, tick=42, width=WIDTH)
        segments = dashboard_footer_segments(snapshot, now=1_700_000_000.0, tick=42, width=WIDTH)
        joined = "".join(text for text, _style in segments)
        self.assertNotIn("Week", footer)
        self.assertNotIn("#00042", joined)
        self.assertNotIn("W25", joined)

    def test_panel_section_label_differs_from_mode_title(self):
        self.assertEqual(panel_section_label("terrarium"), "LAN VITALS")
        self.assertEqual(panel_section_label("lounge"), "LIVE CHATTER")


class TickerTests(unittest.TestCase):
    def test_ticker_includes_version_and_agent_summaries(self):
        now = datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc).timestamp()
        recent = "2026-06-17T11:30:00Z"
        snapshot = {
            "status": {
                "vector_ok": True,
                "pbx_api_ok": True,
                "agent_tickers": {
                    "agents": {
                        "122": {"summary": "Navi session saved for ext 110"},
                        "123": {"summary": "Simon IT-1 open: broken screen"},
                        "130": {"summary": "Max: retainer billed caller"},
                    }
                },
                "pbx_phones": {
                    "phones": [
                        {"ext": "122", "last_call": recent},
                        {"ext": "123", "last_call": recent},
                        {"ext": "130", "last_call": recent},
                    ]
                },
                "navi": {},
            },
            "bridge": {},
        }
        row = ticker_text(snapshot, now=now)
        self.assertIn(LCD_TICKER_VERSION, row)
        self.assertIn("NAVI", row)
        self.assertIn("SIMON", row)
        self.assertIn("LAWYER", row)
        self.assertLessEqual(len(row.split(" · ")[0]), 20)

    def test_ticker_hides_idle_and_stale_agent_summaries(self):
        now = datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc).timestamp()
        snapshot = {
            "status": {
                "vector_ok": True,
                "pbx_api_ok": True,
                "agent_tickers": {
                    "agents": {
                        "122": {"summary": "Navi 122 quiet"},
                        "123": {"summary": "Simon: no tickets for this ext"},
                        "130": {"summary": "Max Retainer: intake folder ready"},
                    }
                },
                "pbx_phones": {"phones": [{"ext": "123", "last_call": "2026-06-10T08:00:00Z"}]},
                "navi": {},
            },
            "bridge": {},
        }
        row = ticker_text(snapshot, now=now)
        self.assertNotIn("NAVI", row)
        self.assertNotIn("SIMON", row)
        self.assertNotIn("LAWYER", row)

    def test_lan_bus_line_fits_width(self):
        status = {
            "pbx_phones": {
                "phones": [
                    {"ext": "122", "state": "connected"},
                    {"ext": "123", "state": "idle"},
                ]
            },
            "vector_ok": True,
            "pbx_api_ok": False,
        }
        row = lan_bus_status_line(status, WIDTH)
        self.assertEqual(len(row), WIDTH)
        self.assertIn("LAN BUS", row)
        self.assertIn("NAV:", row)

    def test_agents_art_puts_status_under_lan_bus_label(self):
        snapshot = {
            "status": {
                "pbx_phones": {
                    "phones": [
                        {"ext": "122", "state": "service"},
                        {"ext": "123", "state": "service"},
                        {"ext": "130", "state": "idle"},
                    ]
                },
                "vector_ok": True,
                "pbx_api_ok": True,
            }
        }
        rows = agents_art_live(snapshot, WIDTH, now=0.0)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(len(r) == WIDTH for r in rows))
        self.assertIn("LAN BUS", rows[1])
        self.assertIn("NAV:serv", rows[1])


class DetailScrollTests(unittest.TestCase):
    def test_detail_kv_scrolls_long_feed_status(self):
        value = "rmt 42s FRESH | CELES FRESH | hb 3s | top ZTW 21d00h"
        first = detail_kv("SYNC", value, WIDTH, now=0.0)
        second = detail_kv("SYNC", value, WIDTH, now=3.0)
        self.assertEqual(len(first), WIDTH)
        self.assertEqual(len(second), WIDTH)
        self.assertNotEqual(first, second)

    def test_detail_kv_fits_short_values(self):
        row = detail_kv("LONGEST UP", "ZEA 3h54m", WIDTH, now=0.0)
        self.assertIn("ZEA 3h54m", row)
        self.assertNotIn("~", row)


class AgentsPanelTests(unittest.TestCase):
    def test_agent_book_pages_cover_full_roster(self):
        page_count = max(1, (len(PBX_AGENT_ROSTER) + PBX_AGENT_VISIBLE - 1) // PBX_AGENT_VISIBLE)
        seen = set()
        for page_idx in range(page_count):
            elapsed = page_idx * (MODE_PERIOD_SEC / page_count)
            rows, page_num, total = agent_book_page(PBX_AGENT_ROSTER, PBX_AGENT_VISIBLE, elapsed)
            self.assertEqual(page_num, page_idx + 1)
            self.assertEqual(total, page_count)
            seen.update(ext for ext, _name in rows)
        self.assertEqual(seen, {ext for ext, _name in PBX_AGENT_ROSTER})

    def test_on_call_agent_stays_visible_off_page(self):
        roster = PBX_AGENT_ROSTER
        page_rows, _page, _total = agent_book_page(roster, PBX_AGENT_VISIBLE, 0.0)
        off_page_ext = "698"
        self.assertTrue(all(ext != off_page_ext for ext, _name in page_rows))
        visible, _page_num, _page_count = agent_visible_rows(
            roster,
            PBX_AGENT_VISIBLE,
            0.0,
            {off_page_ext},
        )
        self.assertIn(off_page_ext, [ext for ext, _name in visible])

    def test_bridge_routes_extend_roster(self):
        bridge = {
            "routes": {
                "TestCompanion": {"preferred_extension": "699"},
            }
        }
        roster = pbx_agent_roster(bridge)
        self.assertIn(("699", "TestCompanion"), roster)

    def test_host_long_name_uses_full_hostname(self):
        self.assertEqual(host_long_name("ZTW"), "zealtower")
        self.assertEqual(host_long_name("ZEA", {"host": "zealpalace"}), "zealpalace")

    def test_noc_mesh_dns_line_lists_hostnames_not_ping(self):
        noc = {
            "hosts": [
                {"id": "nifelheim", "name": "nifelheim", "host": "nifelheim.local"},
                {"id": "asgard", "name": "asgard"},
            ]
        }
        status = {
            "telemetry": {
                "local": {"host": "zealpalace"},
                "remote": {"hosts": {"zealtower": {"host": "zealtower"}, "vector": {"host": "vector"}}},
            }
        }
        line = noc_mesh_dns_line(noc, status)
        self.assertIn("zealpalace", line)
        self.assertIn("zealtower", line)
        self.assertIn("nifelheim", line)
        self.assertNotRegex(line, r"WAN[01X]")

    def test_ops_panel_uses_mesh_host_table(self):
        status = {"noc": {"hosts": []}, "telemetry": {"local": {}, "remote": {"hosts": {}}}}
        rows = ops_panel(status, {}, WIDTH, now=0.0)
        header = next(row for row, _style in rows if isinstance(row, str) and "HOST" in row)
        self.assertIn("HOST", header)
        host_rows = [
            row for row, _style in rows if isinstance(row, list) and any(text.strip() == "ZEA" for text, _ in row)
        ]
        self.assertGreaterEqual(len(host_rows), 1)

    def test_ops_panel_rows_fit_width(self):
        status = {
            "noc": {"hosts": []},
            "telemetry": {
                "local": {"disks": [{"path": "/", "pct": 52}], "uptime_sec": 3600},
                "remote": {"hosts": {}},
            },
            "vector_ok": True,
            "hermes_ok": True,
            "pbx_api_ok": True,
            "ce_api_ok": True,
        }
        rows = ops_panel(status, {"celes": {"fresh": True}}, WIDTH, now=0.0)

        def row_width(row):
            if isinstance(row, list):
                return len("".join(text for text, _style in row))
            return len(row)

        self.assertTrue(all(row_width(row) <= WIDTH for row, _style in rows))
        self.assertLessEqual(len(rows), 7)

    def test_pbx_roster_uses_real_agent_names(self):
        names = {name for _ext, name in PBX_AGENT_ROSTER}
        self.assertIn("Grok Unhinged", names)
        self.assertIn("Yomiko Readline", names)
        self.assertNotIn("Grok 01", names)
        self.assertNotIn("Crystal 01", names)

    def test_agent_row_fits_full_roster_names(self):
        longest = max(PBX_AGENT_ROSTER, key=lambda row: len(row[1]))
        ext, name = longest
        row = agent_row(ext, name, "seen now", WIDTH)
        self.assertIn(name, row)
        self.assertNotIn("~", row)
        self.assertEqual(len(row), WIDTH)

    def test_agent_row_highlights_active_extension(self):
        status = {"vector_ok": True, "pbx_phones": {"phones": []}}
        rows = agents_panel({}, status, WIDTH, now=0.0, call_exts={"111"})
        styles = [style for _row, style in rows]
        self.assertIn("PBX_CALL", styles)
        self.assertTrue(any("111" in row and "Hermes" in row for row, _style in rows))
        self.assertTrue(any("ON CALL" in row for row, _style in rows))

    def test_rotation_includes_lounge_mode(self):
        from zealot_lcd_render import XTREE_MODES, panel_lines

        self.assertIn("lounge", XTREE_MODES)
        snapshot = {
            "events": [LcdEvent("ZP", "#ZealPalace", "Zealot", "mesh hums", sort_ts=1.0)],
            "bridge": {},
            "status": {},
        }
        rows = panel_lines(snapshot, "lounge", WIDTH, now=10.0, max_rows=7)
        self.assertTrue(rows)

    def test_mesh_sync_alert_summary_last_seen(self):
        status = {
            "telemetry": {
                "local": {"uptime_sec": 60},
                "remote": {
                    "fresh": True,
                    "age_sec": 120,
                    "hosts": {"zealtower": {"uptime_sec": 1}, "vector": {"uptime_sec": 1}},
                },
            },
            "noc": {
                "internet": {"up": True},
                "hosts": [
                    {"id": "nifelheim", "name": "nifelheim", "up": False, "recent_offline": True},
                ],
            },
        }
        summary = mesh_sync_alert_summary(status, {}, now=0.0)
        self.assertIn("ZEA ok", summary)
        self.assertIn("ZTW 2m", summary)
        self.assertNotIn("NIF", summary)
        self.assertNotIn("FRESH", summary)

    def test_vitals_row_uses_full_width(self):
        from zealot_lcd_render import vitals_row

        row = vitals_row("ZEA", 3600, 12.0, 36.0, 52.0, WIDTH)
        self.assertEqual(len(row), WIDTH)
        self.assertNotEqual(row[-1], " ")

    def test_mesh_table_row_segments_label_host(self):
        segments = mesh_table_row_segments("ZEA", "1", 3600, 12.0, WIDTH)
        text = "".join(part for part, _style in segments)
        self.assertIn("ZEA", text)
        self.assertIn("1h00m", text)
        self.assertLessEqual(len(text), WIDTH)
        styles = [style for _part, style in segments]
        self.assertEqual(styles[0], "NOC")
        self.assertEqual(styles[1], "GREEN")

    def test_fmt_age_short_now_threshold(self):
        self.assertEqual(fmt_age_short(10), "now")
        self.assertEqual(fmt_age_short(90), "1m")

    def test_highlight_exts_ignore_active_lines_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sip_call_flash.json"
            path.write_text(
                json.dumps(
                    {
                        "state": "talking",
                        "from_ext": "111",
                        "to_ext": "100",
                        "active_lines": 0,
                        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(read_active_call_exts(path)[0], set())
            self.assertEqual(read_active_call_exts_highlight(path), {"111", "100"})

    def test_read_active_call_exts_parses_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sip_call_flash.json"
            path.write_text(
                json.dumps(
                    {
                        "state": "talking",
                        "from_ext": "110",
                        "to_ext": "111",
                        "active_lines": 1,
                        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    }
                ),
                encoding="utf-8",
            )
            exts, state = read_active_call_exts(path)
            self.assertEqual(state, "talking")
            self.assertEqual(exts, {"110", "111"})


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
