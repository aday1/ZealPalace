import base64
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
EXPORTER_PATH = ROOT / "integrations" / "export-sillytavern-source-assets.py"


def load_exporter():
    spec = importlib.util.spec_from_file_location("sillytavern_exporter", EXPORTER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def png_text_chunks(payload):
    chunks = {}
    offset = 8
    while offset + 12 <= len(payload):
        length = int.from_bytes(payload[offset : offset + 4], "big")
        kind = payload[offset + 4 : offset + 8]
        start = offset + 8
        end = start + length
        if kind == b"tEXt":
            key, value = payload[start:end].split(b"\x00", 1)
            chunks[key.decode("utf-8")] = value.decode("utf-8")
        offset = end + 4
        if kind == b"IEND":
            break
    return chunks


class SillyTavernExporterTests(unittest.TestCase):
    def test_exports_native_card_and_worldbooks(self):
        exporter = load_exporter()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            public_root = root / "public"
            avatar = public_root / "agents" / "st" / "yomiko.png"
            avatar.parent.mkdir(parents=True)
            avatar.write_bytes(exporter.FALLBACK_PNG)

            continuity = {
                "updated": "2026-06-23T01:37:05Z",
                "summary": {
                    "characters": 1,
                    "personas": 1,
                    "lore_continuity": 1,
                    "memory_continuity": 1,
                    "fresh_scenery": 1,
                    "scenery_image_integrity": 1,
                    "voice_coverage": 1,
                    "crystal_agents": 1,
                    "xtts_endpoint": "http://10.13.37.60:8022",
                    "grok_build": "local fallback active",
                },
                "characters": [
                    {
                        "slug": "crystal-690-yomiko-readline",
                        "name": "Yomiko Readline",
                        "ext": "690",
                        "type": "vector-voice-crystal",
                        "backend": "VECTOR Scribe + Grok chat + VECTOR XTTS",
                        "voice": "yomiko_archive_quiet",
                        "voice_signature": "Quiet archive cadence.",
                        "voice_sample": "https://example.invalid/yomiko.wav",
                        "workspace": "/opt/voip/workspaces/crystal-690-yomiko-readline",
                        "persona_excerpt": "Character: Yomiko is the archive mage. Voice signature: quiet. Continuity: sources first.",
                        "card": "https://pseudocorp.example/characters/crystal-690-yomiko-readline/",
                        "fresh_scenery": {"url": "https://example.invalid/scene.png"},
                        "lore_continuity": {"cue": "Character: Yomiko. Voice signature: quiet. Continuity: archive."},
                        "memory_continuity": {"detail": "persistent Crystal/ZealPalace shared-memory stream"},
                        "voice_coverage": {"detail": "XTTS sample available"},
                    }
                ],
            }
            crystal_party = {
                "companions": [
                    {
                        "ext": "690",
                        "irc_nick": "Yomiko",
                        "short": "Yomiko",
                        "st_name": "Yomiko Readline",
                        "rpg_class": "Archive Mage",
                        "guild_role": "Mesh Webmaster",
                        "zone": "archive_spire",
                        "tts_voice": "yomiko_archive_quiet",
                        "avatar_url": "/agents/st/yomiko.png",
                        "visual_signature": "Archive Mage portrait.",
                        "voice_signature": "Quiet archive cadence.",
                        "title": "Keeper of the Archive Spire",
                    }
                ]
            }

            continuity_path = root / "continuity.json"
            crystal_path = root / "crystal.json"
            output_dir = root / "out"
            continuity_path.write_text(json.dumps(continuity), encoding="utf-8")
            crystal_path.write_text(json.dumps(crystal_party), encoding="utf-8")

            manifest = exporter.export_assets(
                SimpleNamespace(
                    continuity_json=continuity_path,
                    crystal_party_json=crystal_path,
                    public_root=public_root,
                    output_dir=output_dir,
                    min_characters=1,
                )
            )

            self.assertEqual(manifest["characters"], 1)
            self.assertEqual(manifest["worldbooks"], 2)
            card_path = output_dir / "characters" / "690-crystal-690-yomiko-readline.png"
            self.assertTrue(card_path.exists())
            chunks = png_text_chunks(card_path.read_bytes())
            self.assertIn("chara", chunks)
            self.assertIn("ccv3", chunks)
            card = json.loads(base64.b64decode(chunks["chara"]).decode("utf-8"))
            zeal = card["data"]["extensions"]["zealpalace"]
            self.assertEqual(card["spec"], "chara_card_v2")
            self.assertEqual(card["data"]["name"], "Yomiko Readline")
            self.assertEqual(zeal["ext"], "690")
            self.assertEqual(zeal["crystal_party"]["irc_nick"], "Yomiko")
            self.assertEqual(zeal["voice"], "yomiko_archive_quiet")
            self.assertTrue((output_dir / "worlds" / "ZealPalace Source of Truth.json").exists())
            self.assertTrue((output_dir / "worlds" / "PSEUDOCORP Cast Index.json").exists())


if __name__ == "__main__":
    unittest.main()
