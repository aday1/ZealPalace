# ZealPalace integrations

## SillyTavern source sync

ZealTower hosts the live SillyTavern instance at `http://100.91.133.101:8000/`.
The bridge runs on the ZealTower host from `/opt/sillytavern/zeal-bridge` and
reads character cards/worldbooks from `/opt/sillytavern/data/default-user`.

Use this command from Holybell/Windows to rebuild SillyTavern from the current
CELES/PSEUDOCORP continuity source of truth:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:/aday.repo/ZealPalace/integrations/sync-sillytavern-source-assets.ps1
```

The sync script:

- runs `export-sillytavern-source-assets.py` on `celes`;
- generates native SillyTavern PNG cards with embedded `chara`/`ccv3` metadata;
- installs the generated cards plus `ZealPalace Source of Truth.json` and
  `PSEUDOCORP Cast Index.json` on `zealtower`;
- moves existing active cards and default/sample worldbooks into a timestamped
  SillyTavern backup directory;
- restarts the `sillytavern` container and the ZealPalace bridge;
- fails if fewer than 37 source characters are exported.

Expected post-sync bridge health:

```json
{"ok":true,"ircReady":true,"characters":37,"characterSource":"png-card-metadata","worlds":43}
```

Run the live regression guard after syncs, bridge deploys, or ZealTower restarts:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:/aday.repo/ZealPalace/integrations/test-sillytavern-source-health.ps1
```

The guard fails if the bridge falls back to default/sample character state,
stops reading PNG card metadata, loses Crystal aliases, drops below 37 cards,
loses source worldbook coverage, loses its ZealTower manifest, or the
SillyTavern UI/bridge process is down.

Deploy bridge-only changes with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:/aday.repo/ZealPalace/integrations/deploy-sillytavern-zeal-rpg-bridge.ps1
```

The optional browser UI extension is not required for core health. The bridge
parses PNG card metadata directly first and only falls back to the extension
exporter when no card files are present.
