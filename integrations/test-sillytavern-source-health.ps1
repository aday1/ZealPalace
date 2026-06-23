param(
    [string]$BridgeUrl = "http://100.91.133.101:8787",
    [string]$SillyTavernUrl = "http://100.91.133.101:8000",
    [string]$ZealTowerHost = "zealtower",
    [int]$MinCharacters = 37,
    [int]$MinWorldEntries = 43
)

$ErrorActionPreference = "Stop"

$SshOptions = @(
    "-o", "BatchMode=yes",
    "-o", "ConnectionAttempts=1",
    "-o", "ConnectTimeout=10",
    "-o", "ServerAliveInterval=2",
    "-o", "ServerAliveCountMax=2"
)

$Failures = New-Object System.Collections.Generic.List[string]

function Add-Failure {
    param([Parameter(Mandatory = $true)][string]$Message)
    $Failures.Add($Message) | Out-Null
}

function Assert-True {
    param(
        [Parameter(Mandatory = $true)][bool]$Condition,
        [Parameter(Mandatory = $true)][string]$Message
    )
    if (-not $Condition) {
        Add-Failure $Message
    }
}

function Get-Json {
    param([Parameter(Mandatory = $true)][string]$Url)
    Invoke-RestMethod -Uri $Url -TimeoutSec 8
}

Write-Host "Checking SillyTavern bridge health at $BridgeUrl..."
$Health = Get-Json "$BridgeUrl/health"
Assert-True ($Health.ok -eq $true) "Bridge health did not return ok=true"
Assert-True ($Health.ircReady -eq $true) "Bridge is not IRC-ready"
Assert-True ([int]$Health.characters -ge $MinCharacters) "Bridge exposes $($Health.characters) characters; expected at least $MinCharacters"
Assert-True ($Health.characterSource -eq "png-card-metadata") "Bridge characterSource is '$($Health.characterSource)', expected png-card-metadata"
Assert-True ([int]$Health.worlds -ge $MinWorldEntries) "Bridge exposes $($Health.worlds) world entries; expected at least $MinWorldEntries"

Write-Host "Checking public character surface..."
$CharactersResponse = Get-Json "$BridgeUrl/characters"
$Characters = @($CharactersResponse.characters)
Assert-True ($Characters.Count -ge $MinCharacters) "Character endpoint returned $($Characters.Count) characters; expected at least $MinCharacters"
Assert-True (-not ($Characters | Where-Object { $_.name -match "Seraphina" -or $_.file -match "Seraphina" })) "Default Seraphina sample is still active in the bridge character list"

$RequiredCrystals = @{
    "690" = @{ name = "Yomiko Readline"; ircNick = "Yomiko"; voice = "yomiko_archive_quiet" }
    "691" = @{ name = "Rei Patchbay"; ircNick = "Rei"; voice = "zeal_companion_bright" }
    "695" = @{ name = "Celes Runecompiler"; ircNick = "Celes"; voice = "celes_theater_curt" }
    "697" = @{ name = "Vexara Skyforge"; ircNick = "Vexara"; voice = "zeal_companion_bright" }
    "698" = @{ name = "Aeris Gardenbyte"; ircNick = "Aeris"; voice = "zeal_companion_calm" }
}

foreach ($Ext in $RequiredCrystals.Keys) {
    $Expected = $RequiredCrystals[$Ext]
    $Row = $Characters | Where-Object { $_.ext -eq $Ext } | Select-Object -First 1
    Assert-True ($null -ne $Row) "Missing Crystal extension $Ext ($($Expected.name))"
    if ($null -ne $Row) {
        Assert-True ($Row.name -eq $Expected.name) "Crystal ext $Ext name is '$($Row.name)', expected '$($Expected.name)'"
        Assert-True ($Row.ircNick -eq $Expected.ircNick) "Crystal ext $Ext ircNick is '$($Row.ircNick)', expected '$($Expected.ircNick)'"
        Assert-True ($Row.voice -eq $Expected.voice) "Crystal ext $Ext voice is '$($Row.voice)', expected '$($Expected.voice)'"
    }
}

Write-Host "Checking SillyTavern UI at $SillyTavernUrl..."
$UiStatus = (& curl.exe -sS -o NUL -w "%{http_code}" --max-time 8 "$SillyTavernUrl/").Trim()
Assert-True ($UiStatus -eq "200") "SillyTavern UI returned HTTP $UiStatus, expected 200"

Write-Host "Checking ZealTower installed files and manifest..."
$Remote = @'
set -e
DATA=/opt/sillytavern/data/default-user
BRIDGE=/opt/sillytavern/zeal-bridge
cards=$(find "$DATA/characters" -maxdepth 1 -type f -name '*.png' | wc -l)
world_files=$(find "$DATA/worlds" -maxdepth 1 -type f -name '*.json' | wc -l)
processes=$(pgrep -fc 'sillytavern-zeal-rpg-bridge.mjs' || true)
manifest_characters=0
manifest_worldbooks=0
manifest_generated=missing
if [ -f "$BRIDGE/source-assets-manifest.json" ]; then
    manifest_characters=$(node -e 'const fs=require("fs"); const m=JSON.parse(fs.readFileSync(process.argv[1],"utf8")); console.log(m.characters || 0)' "$BRIDGE/source-assets-manifest.json")
    manifest_worldbooks=$(node -e 'const fs=require("fs"); const m=JSON.parse(fs.readFileSync(process.argv[1],"utf8")); console.log(m.worldbooks || 0)' "$BRIDGE/source-assets-manifest.json")
    manifest_generated=$(node -e 'const fs=require("fs"); const m=JSON.parse(fs.readFileSync(process.argv[1],"utf8")); console.log(m.generated_at || "missing")' "$BRIDGE/source-assets-manifest.json")
fi
active_seraphina=$(find "$DATA/characters" -maxdepth 2 -iname '*Seraphina*' | wc -l)
echo "cards=$cards"
echo "world_files=$world_files"
echo "processes=$processes"
echo "manifest_characters=$manifest_characters"
echo "manifest_worldbooks=$manifest_worldbooks"
echo "manifest_generated=$manifest_generated"
echo "active_seraphina=$active_seraphina"
'@

$RemoteOutput = $Remote | & ssh @SshOptions $ZealTowerHost "bash" "-s"
if ($LASTEXITCODE -ne 0) {
    throw "ssh $ZealTowerHost health probe failed with exit code $LASTEXITCODE"
}

$RemoteState = @{}
foreach ($Line in $RemoteOutput) {
    if ($Line -match "^([^=]+)=(.*)$") {
        $RemoteState[$Matches[1]] = $Matches[2]
    }
}

Assert-True ([int]$RemoteState.cards -ge $MinCharacters) "ZealTower has $($RemoteState.cards) active card PNGs; expected at least $MinCharacters"
Assert-True ([int]$RemoteState.world_files -ge 3) "ZealTower has $($RemoteState.world_files) world files; expected at least 3"
Assert-True ([int]$RemoteState.processes -ge 1) "ZealTower bridge process is not running"
Assert-True ([int]$RemoteState.manifest_characters -ge $MinCharacters) "Manifest records $($RemoteState.manifest_characters) characters; expected at least $MinCharacters"
Assert-True ([int]$RemoteState.manifest_worldbooks -ge 2) "Manifest records $($RemoteState.manifest_worldbooks) worldbooks; expected at least 2"
Assert-True ($RemoteState.manifest_generated -and $RemoteState.manifest_generated -ne "missing") "Manifest generated_at is missing"
Assert-True ([int]$RemoteState.active_seraphina -eq 0) "Default Seraphina files are still active in the character library"

if ($Failures.Count -gt 0) {
    Write-Error ("SillyTavern source health check failed:`n - " + ($Failures -join "`n - "))
    exit 1
}

$Summary = [ordered]@{
    ok = $true
    bridge = @{
        characters = [int]$Health.characters
        characterSource = $Health.characterSource
        worlds = [int]$Health.worlds
        recent = [int]$Health.recent
    }
    zealtower = $RemoteState
}

$Summary | ConvertTo-Json -Depth 5
