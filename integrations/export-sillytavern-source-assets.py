#!/usr/bin/env python3
"""Export CELES/PSEUDOCORP continuity truth into SillyTavern assets.

The output is intentionally plain SillyTavern data:
- PNG character cards with chara/ccv3 text chunks.
- World Info JSON files with entries keyed by character/source concepts.
- A manifest for deployment and health checks.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import datetime as dt
import json
import re
import shutil
import struct
from pathlib import Path
from typing import Any


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
FALLBACK_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGA"
    "WjR9awAAAABJRU5ErkJggg=="
)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def slugify(value: str, fallback: str = "character") -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "-", value.strip()).strip("-").lower()
    return value or fallback


def clean_text(value: Any, limit: int | None = None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if limit and len(text) > limit:
        return text[: limit - 1].rstrip() + "..."
    return text


def now_utc() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    crc = binascii.crc32(kind)
    crc = binascii.crc32(payload, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)


def png_text_chunk(key: str, value: str) -> bytes:
    return png_chunk(b"tEXt", key.encode("utf-8") + b"\x00" + value.encode("utf-8"))


def strip_card_text_chunks(png: bytes) -> tuple[bytes, bytes]:
    if not png.startswith(PNG_SIGNATURE):
        return FALLBACK_PNG[:-12], FALLBACK_PNG[-12:]

    head = bytearray(PNG_SIGNATURE)
    offset = len(PNG_SIGNATURE)
    iend = b""
    while offset + 12 <= len(png):
        length = struct.unpack(">I", png[offset : offset + 4])[0]
        kind = png[offset + 4 : offset + 8]
        chunk_end = offset + 12 + length
        if chunk_end > len(png):
            break

        chunk = png[offset:chunk_end]
        if kind == b"IEND":
            iend = chunk
            break

        if kind == b"tEXt":
            payload = png[offset + 8 : offset + 8 + length]
            key = payload.split(b"\x00", 1)[0].decode("utf-8", errors="ignore")
            if key in {"chara", "ccv3"}:
                offset = chunk_end
                continue

        head.extend(chunk)
        offset = chunk_end

    if not iend:
        iend = png_chunk(b"IEND", b"")
    return bytes(head), iend


def embed_card_payload(source_png: bytes, card: dict[str, Any]) -> bytes:
    payload = json.dumps(card, ensure_ascii=False, separators=(",", ":"))
    encoded = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    head, iend = strip_card_text_chunks(source_png)
    return head + png_text_chunk("chara", encoded) + png_text_chunk("ccv3", encoded) + iend


def maybe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def indexed_by_ext(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        ext = str(row.get("ext") or "").strip()
        if ext:
            out[ext] = row
    return out


def crystal_index(crystal_party: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in crystal_party.get("companions", []):
        ext = str(row.get("ext") or "").strip()
        if ext:
            out[ext] = row
    return out


def source_image_for(row: dict[str, Any], crystal: dict[str, Any] | None, public_root: Path) -> Path | None:
    candidates: list[Path] = []
    if crystal and crystal.get("avatar_url"):
        candidates.append(public_root / str(crystal["avatar_url"]).lstrip("/"))

    fresh = row.get("fresh_scenery") or {}
    integrity = fresh.get("asset_integrity") or {}
    for key in ("pseudocorp", "zealpalace"):
        path = ((integrity.get(key) or {}).get("path"))
        if path:
            candidates.append(Path(path))
    if fresh.get("ref"):
        candidates.append(public_root / "characters" / str(row.get("slug")) / str(fresh["ref"]))

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def first_message(row: dict[str, Any], crystal: dict[str, Any] | None) -> str:
    name = row.get("name") or "Character"
    ext = row.get("ext")
    if row.get("backend") == "phone":
        return (
            f"*{name} comes online as an operator reference card.* "
            "I am here for continuity, routing, and identity context. Do not impersonate this human line unless the operator explicitly asks for a simulation."
        )
    if crystal:
        title = crystal.get("title") or crystal.get("rpg_class") or "Crystal Mesh companion"
        return f"*{name} steps through the Crystal Mesh gate.* {title} online. What are we reading, fixing, mapping, or protecting?"
    if ext:
        return f"*{name} answers on PSEUDOCORP extension {ext}.* I am in character and synced to the ZealPalace continuity ledger."
    return f"*{name} materializes in the ZealPalace IRC lounge.* The public continuity ledger is loaded."


def character_description(row: dict[str, Any], crystal: dict[str, Any] | None) -> str:
    chunks = [
        clean_text(row.get("persona_excerpt"), 1600),
        "",
        "Source of truth:",
        f"- Slug: {row.get('slug')}",
        f"- Type: {row.get('type')}",
        f"- Backend: {row.get('backend')}",
    ]
    if row.get("ext"):
        chunks.append(f"- PBX extension: {row.get('ext')}")
    if row.get("voice"):
        chunks.append(f"- Voice: {row.get('voice')}")
    if row.get("voice_signature"):
        chunks.append(f"- Voice signature: {row.get('voice_signature')}")
    if crystal:
        chunks.extend(
            [
                f"- RPG class: {crystal.get('rpg_class')}",
                f"- Guild role: {crystal.get('guild_role')}",
                f"- Zone: {crystal.get('zone')}",
                f"- Visual signature: {crystal.get('visual_signature')}",
            ]
        )
    memory = row.get("memory_continuity") or {}
    if memory.get("detail"):
        chunks.append(f"- Memory continuity: {memory.get('detail')}")
    lore = row.get("lore_continuity") or {}
    if lore.get("cue"):
        chunks.append(f"- Lore cue: {clean_text(lore.get('cue'), 500)}")
    fresh = row.get("fresh_scenery") or {}
    if fresh.get("url"):
        chunks.append(f"- Latest scenery: {fresh.get('url')}")
    if isinstance(row.get("card"), str):
        chunks.append(f"- Public character sheet: {row.get('card')}")
    return "\n".join(str(c) for c in chunks if c is not None).strip()


def build_card(row: dict[str, Any], crystal: dict[str, Any] | None, generated_at: str) -> dict[str, Any]:
    name = str(row.get("name") or row.get("slug") or "Character")
    slug = str(row.get("slug") or slugify(name))
    ext = str(row.get("ext") or "")
    tags = [
        "PSEUDOCORP",
        "ZealPalace",
        "source-of-truth",
        str(row.get("type") or "character"),
    ]
    if ext:
        tags.append(f"ext-{ext}")
    if crystal:
        tags.extend(["Crystal Mesh", crystal.get("rpg_class") or "Crystal"])

    public_card_url = row.get("card") if isinstance(row.get("card"), str) else ""
    fresh = row.get("fresh_scenery") or {}
    lore = row.get("lore_continuity") or {}
    memory = row.get("memory_continuity") or {}
    voice_coverage = row.get("voice_coverage") or {}
    status = row.get("status") if isinstance(row.get("status"), dict) else {}

    data = {
        "name": name,
        "description": character_description(row, crystal),
        "personality": clean_text(row.get("persona_excerpt"), 900),
        "scenario": (
            "ZealPalace is a private LAN/Tailscale cyberpunk filesystem RPG tied to real homelab state, "
            "IRC #RPG traffic, CELES/PSEUDOCORP PBX characters, Crystal Mesh companions, and daily continuity reports. "
            "Stay in character, respect the source of truth, and treat the live IRC worldbook as recent state rather than permanent canon."
        ),
        "first_mes": first_message(row, crystal),
        "mes_example": (
            "{{user}}: What should I know about you right now?\n"
            f"{{{{char}}}}: I am {name}, synced from the PSEUDOCORP continuity ledger as `{slug}`. "
            "I keep my voice, memory boundary, and ZealPalace lore distinct."
        ),
        "creator_notes": (
            f"Generated from CELES continuity on {generated_at}. "
            "Rebuild with integrations/export-sillytavern-source-assets.py; deploy with sync-sillytavern-source-assets.ps1."
        ),
        "system_prompt": (
            "Stay in character. Keep the character voice, lore continuity, and memory continuity distinct. "
            "Be honest about what is persistent memory, recent IRC state, or source-truth context. "
            "Do not claim private logs or secrets unless they appear in the visible prompt/context."
        ),
        "post_history_instructions": (
            "Use ZealPalace Source of Truth and ZealPalace IRC RPG Live world entries when relevant. "
            "If source truth and chat history disagree, prefer source truth and mention uncertainty in character."
        ),
        "tags": list(dict.fromkeys(t for t in tags if t)),
        "creator": "PSEUDOCORP continuity exporter",
        "character_version": str(status.get("updated") or generated_at),
        "alternate_greetings": [],
        "extensions": {
            "zealpalace": {
                "slug": slug,
                "ext": ext,
                "type": row.get("type") or "",
                "backend": row.get("backend") or "",
                "workspace": row.get("workspace") or "",
                "voice": row.get("voice") or "",
                "voice_signature": row.get("voice_signature") or "",
                "voice_sample": row.get("voice_sample") or "",
                "public_card_url": public_card_url,
                "fresh_scenery_url": fresh.get("url") or "",
                "lore_continuity": lore,
                "memory_continuity": memory,
                "voice_coverage": voice_coverage,
                "crystal_party": crystal or {},
            }
        },
        "character_book": {
            "name": f"{name} source notes",
            "description": "Character-local source of truth notes exported from CELES.",
            "scan_depth": 50,
            "token_budget": 500,
            "recursive_scanning": False,
            "entries": [
                {
                    "keys": [name, slug, ext] if ext else [name, slug],
                    "content": character_description(row, crystal),
                    "enabled": True,
                    "insertion_order": 100,
                    "case_sensitive": False,
                    "name": f"{name} continuity",
                }
            ],
        },
    }

    card = {
        "name": data["name"],
        "description": data["description"],
        "personality": data["personality"],
        "first_mes": data["first_mes"],
        "avatar": "none",
        "chat": f"{name} - ZealPalace Source",
        "mes_example": data["mes_example"],
        "scenario": data["scenario"],
        "create_date": generated_at,
        "talkativeness": "0.5",
        "fav": False,
        "creatorcomment": data["creator_notes"],
        "spec": "chara_card_v2",
        "spec_version": "2.0",
        "data": data,
        "tags": data["tags"],
    }
    return card


def world_entry(
    uid: int,
    keys: list[str],
    comment: str,
    content: str,
    *,
    constant: bool = False,
    selective: bool = True,
    order: int = 100,
    depth: int = 4,
) -> dict[str, Any]:
    return {
        "uid": uid,
        "key": [k for k in keys if k],
        "keysecondary": [],
        "comment": comment,
        "content": content.strip(),
        "constant": constant,
        "selective": selective,
        "order": order,
        "position": 0,
        "disable": False,
        "displayIndex": uid,
        "addMemo": True,
        "group": "",
        "groupOverride": False,
        "groupWeight": 100,
        "sticky": 0,
        "cooldown": 0,
        "delay": 0,
        "probability": 100,
        "depth": depth,
        "useProbability": True,
        "role": None,
        "vectorized": False,
        "excludeRecursion": False,
        "preventRecursion": False,
        "delayUntilRecursion": False,
        "scanDepth": None,
        "caseSensitive": None,
        "matchWholeWords": None,
        "useGroupScoring": None,
        "automationId": "",
    }


def build_worldbooks(
    rows: list[dict[str, Any]],
    crystals: dict[str, dict[str, Any]],
    summary: dict[str, Any],
    generated_at: str,
) -> dict[str, dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    entries.append(
        world_entry(
            0,
            ["ZealPalace", "PSEUDOCORP", "source of truth", "runtime contract"],
            "Runtime character contract",
            (
                "ZealPalace/PSEUDOCORP runtime contract: stay in character; keep voice, lore, and memory continuity distinct; "
                "be honest about memory; treat live IRC context as recent state; prefer CELES continuity source truth over stale chat; "
                "never expose secrets or private tokens. Discord Imagine is discontinued; local scenery fallback is the supported image path."
            ),
            constant=True,
            selective=False,
            order=10,
            depth=2,
        )
    )
    entries.append(
        world_entry(
            1,
            ["#RPG", "SillyTavern bridge", "IRC", "ZealPalace IRC"],
            "Bridge commands and live-state rule",
            (
                "The SillyTavern bridge joins ZealPalace IRC #RPG as sillytavern-bridge. "
                "Explicit triggers include !st <character> <message>, !st sync, !st list, and @Character mentions. "
                "The ZealPalace IRC RPG Live worldbook is rewritten by the bridge with recent traffic; use it as current scene pressure, not permanent canon unless repeated in play."
            ),
            constant=True,
            selective=False,
            order=20,
            depth=2,
        )
    )
    entries.append(
        world_entry(
            2,
            ["continuity report", "image pipeline", "voice pipeline", "Crystal Mesh"],
            "Continuity health summary",
            (
                f"Continuity summary at export: characters={summary.get('characters')}, personas={summary.get('personas')}, "
                f"lore={summary.get('lore_continuity')}, memory={summary.get('memory_continuity')}, "
                f"fresh_scenery={summary.get('fresh_scenery')}, image_integrity={summary.get('scenery_image_integrity')}, "
                f"voice_coverage={summary.get('voice_coverage')}, crystal_agents={summary.get('crystal_agents')}. "
                f"XTTS endpoint: {summary.get('xtts_endpoint')}. Grok Build status: {summary.get('grok_build')}. "
                f"Export generated: {generated_at}."
            ),
            constant=True,
            selective=False,
            order=30,
            depth=2,
        )
    )

    for idx, row in enumerate(rows, start=10):
        ext = str(row.get("ext") or "")
        slug = str(row.get("slug") or "")
        name = str(row.get("name") or slug)
        crystal = crystals.get(ext)
        fresh = row.get("fresh_scenery") or {}
        memory = row.get("memory_continuity") or {}
        lore = row.get("lore_continuity") or {}
        voice_coverage = row.get("voice_coverage") or {}
        keys = [name, slug, ext, row.get("type") or ""]
        if crystal:
            keys.extend([crystal.get("irc_nick"), crystal.get("short"), crystal.get("rpg_class"), crystal.get("zone")])

        content = [
            f"Character: {name}",
            f"Slug: {slug}",
            f"Type/backend: {row.get('type')} / {row.get('backend')}",
        ]
        if ext:
            content.append(f"PBX extension: {ext}")
        if row.get("voice"):
            content.append(f"Voice: {row.get('voice')}")
        if row.get("voice_signature"):
            content.append(f"Voice signature: {row.get('voice_signature')}")
        elif voice_coverage.get("detail"):
            content.append(f"Voice coverage: {voice_coverage.get('detail')}")
        if crystal:
            content.extend(
                [
                    f"Crystal RPG class: {crystal.get('rpg_class')}",
                    f"Guild role: {crystal.get('guild_role')}",
                    f"Zone: {crystal.get('zone')}",
                    f"Visual signature: {crystal.get('visual_signature')}",
                ]
            )
        if lore.get("cue"):
            content.append(f"Continuity: {clean_text(lore.get('cue'), 700)}")
        if memory.get("detail"):
            content.append(f"Memory: {memory.get('detail')}")
        if fresh.get("url"):
            content.append(f"Latest scenery: {fresh.get('url')}")
        if isinstance(row.get("card"), str):
            content.append(f"Public character sheet: {row.get('card')}")

        entries.append(
            world_entry(
                idx,
                [str(k) for k in keys if k],
                f"Character: {name}",
                "\n".join(content),
                order=100 + idx,
                depth=4,
            )
        )

    cast_index = ", ".join(str(row.get("name")) for row in rows)
    index_book = {
        "entries": {
            "0": world_entry(
                0,
                ["PSEUDOCORP cast", "ZealPalace cast", "all characters", "roster"],
                "Full source-of-truth cast index",
                f"Current exported cast ({len(rows)}): {cast_index}",
                constant=True,
                selective=False,
                order=5,
                depth=2,
            )
        }
    }

    source_book = {"entries": {str(entry["uid"]): entry for entry in entries}}
    return {
        "ZealPalace Source of Truth.json": source_book,
        "PSEUDOCORP Cast Index.json": index_book,
    }


def export_assets(args: argparse.Namespace) -> dict[str, Any]:
    continuity = load_json(args.continuity_json)
    crystal_party = load_json(args.crystal_party_json) if args.crystal_party_json else {"companions": []}
    rows = continuity.get("characters") or []
    summary = continuity.get("summary") or {}
    crystals = crystal_index(crystal_party)
    generated_at = now_utc()

    if len(rows) < args.min_characters:
        raise SystemExit(f"continuity only has {len(rows)} characters; expected at least {args.min_characters}")

    output = args.output_dir
    characters_dir = output / "characters"
    worlds_dir = output / "worlds"
    if output.exists():
        shutil.rmtree(output)
    characters_dir.mkdir(parents=True)
    worlds_dir.mkdir(parents=True)

    manifest_cards = []
    for row in rows:
        ext = str(row.get("ext") or "")
        slug = str(row.get("slug") or slugify(str(row.get("name") or "character")))
        crystal = crystals.get(ext)
        card = build_card(row, crystal, generated_at)
        source_image = source_image_for(row, crystal, args.public_root)
        source_bytes = source_image.read_bytes() if source_image else FALLBACK_PNG
        card_png = embed_card_payload(source_bytes, card)
        prefix = f"{ext}-" if ext else ""
        filename = f"{prefix}{slugify(slug)}.png"
        (characters_dir / filename).write_bytes(card_png)
        manifest_cards.append(
            {
                "name": row.get("name"),
                "slug": slug,
                "ext": ext,
                "type": row.get("type"),
                "file": filename,
                "source_image": str(source_image) if source_image else "fallback",
            }
        )

    for filename, world in build_worldbooks(rows, crystals, summary, generated_at).items():
        (worlds_dir / filename).write_text(json.dumps(world, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    manifest = {
        "generated_at": generated_at,
        "continuity_updated": continuity.get("updated") or summary.get("updated"),
        "source": {
            "continuity_json": str(args.continuity_json),
            "crystal_party_json": str(args.crystal_party_json) if args.crystal_party_json else "",
            "public_root": str(args.public_root),
        },
        "output_dir": str(output),
        "summary": summary,
        "characters": len(manifest_cards),
        "worldbooks": 2,
        "cards": manifest_cards,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--continuity-json", type=Path, default=Path("/var/www/pseudocorp/characters/continuity.json"))
    parser.add_argument("--crystal-party-json", type=Path, default=Path("/opt/voip/crystal-mesh-party.json"))
    parser.add_argument("--public-root", type=Path, default=Path("/var/www/pseudocorp"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--min-characters", type=int, default=37)
    return parser.parse_args()


def main() -> None:
    manifest = export_assets(parse_args())
    print(
        json.dumps(
            {
                "ok": True,
                "generated_at": manifest["generated_at"],
                "characters": manifest["characters"],
                "worldbooks": manifest["worldbooks"],
                "output": manifest["output_dir"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
