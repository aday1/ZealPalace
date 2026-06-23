param(
    [string]$CelesHost = "celes",
    [string]$ZealTowerHost = "zealtower",
    [int]$MinCharacters = 37,
    [switch]$SkipBridgeDeploy
)

$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Exporter = Join-Path $ScriptRoot "export-sillytavern-source-assets.py"
$BridgeScript = Join-Path $ScriptRoot "sillytavern-zeal-rpg-bridge.mjs"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$RemoteExporter = "/tmp/export-sillytavern-source-assets-$Stamp.py"
$RemoteCelesOut = "/tmp/sillytavern-source-assets-$Stamp"
$RemoteTowerOut = "/tmp/sillytavern-source-assets-$Stamp"
$LocalRoot = Join-Path $env:TEMP "sillytavern-source-assets-$Stamp"
$LocalPackage = Join-Path $LocalRoot (Split-Path -Leaf $RemoteCelesOut)

$SshOptions = @(
    "-o", "BatchMode=yes",
    "-o", "ConnectionAttempts=1",
    "-o", "ConnectTimeout=10",
    "-o", "ServerAliveInterval=2",
    "-o", "ServerAliveCountMax=2"
)

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath failed with exit code $LASTEXITCODE"
    }
}

foreach ($Path in @($Exporter, $BridgeScript)) {
    if (-not (Test-Path $Path)) {
        throw "Missing required file: $Path"
    }
}

New-Item -ItemType Directory -Force -Path $LocalRoot | Out-Null

Write-Host "Copying exporter to $CelesHost..."
Invoke-Checked scp (@($Exporter, "${CelesHost}:$RemoteExporter"))

Write-Host "Generating SillyTavern source package on $CelesHost..."
$GenerateCommand = @"
rm -rf '$RemoteCelesOut' &&
python3 '$RemoteExporter' \
  --continuity-json /var/www/pseudocorp/characters/continuity.json \
  --crystal-party-json /opt/voip/crystal-mesh-party.json \
  --public-root /var/www/pseudocorp \
  --output-dir '$RemoteCelesOut' \
  --min-characters $MinCharacters
"@
Invoke-Checked ssh (@($CelesHost, $GenerateCommand))

Write-Host "Pulling package to local staging..."
Invoke-Checked scp (@("-r", "${CelesHost}:$RemoteCelesOut", $LocalRoot))

if (-not (Test-Path $LocalPackage)) {
    throw "Expected local package missing: $LocalPackage"
}

Write-Host "Pushing package to $ZealTowerHost..."
Invoke-Checked scp (@("-r", $LocalPackage, "${ZealTowerHost}:$RemoteTowerOut"))

if (-not $SkipBridgeDeploy) {
    Write-Host "Pushing updated bridge to $ZealTowerHost..."
    Invoke-Checked scp (@($BridgeScript, "${ZealTowerHost}:/tmp/sillytavern-zeal-rpg-bridge.mjs"))
}

$InstallRemote = @'
set -e
PACKAGE='__PACKAGE__'
STAMP='__STAMP__'
MIN_CHARACTERS='__MIN_CHARACTERS__'
DATA=/opt/sillytavern/data/default-user
BRIDGE=/opt/sillytavern/zeal-bridge
BACKUP="$DATA/backups/source-sync-$STAMP"

test -d "$PACKAGE/characters"
test -d "$PACKAGE/worlds"
test -f "$PACKAGE/manifest.json"

mkdir -p "$DATA/characters" "$DATA/worlds" "$BRIDGE" "$BACKUP/characters" "$BACKUP/worlds"

for item in "$DATA/characters"/*; do
    [ -e "$item" ] || continue
    mv "$item" "$BACKUP/characters/"
done

for world in \
    "$DATA/worlds/Eldoria.json" \
    "$DATA/worlds/ZealPalace Source of Truth.json" \
    "$DATA/worlds/PSEUDOCORP Cast Index.json"; do
    [ -f "$world" ] || continue
    mv "$world" "$BACKUP/worlds/"
done

cp "$PACKAGE/characters/"*.png "$DATA/characters/"
cp "$PACKAGE/worlds/"*.json "$DATA/worlds/"
cp "$PACKAGE/manifest.json" "$BRIDGE/source-assets-manifest.json"

if [ -f /tmp/sillytavern-zeal-rpg-bridge.mjs ]; then
    install -m 0755 /tmp/sillytavern-zeal-rpg-bridge.mjs "$BRIDGE/sillytavern-zeal-rpg-bridge.mjs"
    node --check "$BRIDGE/sillytavern-zeal-rpg-bridge.mjs"
fi

cards=$(find "$DATA/characters" -maxdepth 1 -type f -name '*.png' | wc -l)
if [ "$cards" -lt "$MIN_CHARACTERS" ]; then
    echo "Only $cards SillyTavern cards installed; expected at least $MIN_CHARACTERS" >&2
    exit 1
fi

docker restart sillytavern >/dev/null
if [ -x "$BRIDGE/restart-bridge.sh" ]; then
    "$BRIDGE/restart-bridge.sh"
else
    oldpid=$(cat "$BRIDGE/bridge.pid" 2>/dev/null || true)
    if [ -n "$oldpid" ] && kill -0 "$oldpid" 2>/dev/null; then
        kill "$oldpid" || true
        sleep 1
    fi
    nohup /usr/local/bin/node "$BRIDGE/sillytavern-zeal-rpg-bridge.mjs" >> "$BRIDGE/bridge.log" 2>&1 &
    echo $! > "$BRIDGE/bridge.pid"
fi

sleep 4
curl --max-time 8 -sS http://100.91.133.101:8787/health || curl --max-time 8 -sS http://127.0.0.1:8787/health
echo
echo "Installed $cards SillyTavern source cards"
echo "Backup: $BACKUP"
'@

$InstallRemote = $InstallRemote `
    -replace "__PACKAGE__", $RemoteTowerOut `
    -replace "__STAMP__", $Stamp `
    -replace "__MIN_CHARACTERS__", [string]$MinCharacters

Write-Host "Installing source package on $ZealTowerHost..."
Invoke-Checked ssh (@($ZealTowerHost, $InstallRemote))

Write-Host "Public bridge health:"
curl.exe -sS --max-time 8 http://100.91.133.101:8787/health
Write-Host

Write-Host "Public bridge characters sample:"
curl.exe -sS --max-time 8 http://100.91.133.101:8787/characters
Write-Host

Write-Host "SillyTavern source sync complete."
