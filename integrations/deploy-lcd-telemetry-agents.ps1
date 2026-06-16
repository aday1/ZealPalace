param(
    [string]$PiHost = "zealpalace",
    [string]$ZealTowerHost = "root@zealtower",
    [string]$ZealTowerUrl = "http://100.91.133.101:9199/metrics.json",
    [string]$VectorUrl = "http://10.13.37.60:9199/metrics.json",
    [string]$Port = "9199",
    [string]$Token = ""
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$AgentSrc = Join-Path $PSScriptRoot "lcd-telemetry-agent.mjs"
if (-not (Test-Path $AgentSrc)) {
    throw "Missing telemetry agent: $AgentSrc"
}

$SshOptions = @(
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "ConnectionAttempts=1",
    "-o", "ConnectTimeout=8",
    "-o", "ServerAliveInterval=2",
    "-o", "ServerAliveCountMax=2"
)

function New-Token {
    $Bytes = [byte[]]::new(32)
    [Security.Cryptography.RandomNumberGenerator]::Fill($Bytes)
    return ($Bytes | ForEach-Object { $_.ToString("x2") }) -join ""
}

if (-not $Token) {
    $Token = New-Token
}

function Invoke-Remote {
    param(
        [Parameter(Mandatory = $true)][string]$HostName,
        [Parameter(Mandatory = $true)][string]$Command
    )
    & ssh @SshOptions $HostName $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Remote command failed on $HostName with exit code $LASTEXITCODE"
    }
}

function Copy-Remote {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    & scp @SshOptions $Source $Destination
    if ($LASTEXITCODE -ne 0) {
        throw "Copy failed with exit code $LASTEXITCODE"
    }
}

Write-Host "Installing ZealTower telemetry agent..."
Invoke-Remote $ZealTowerHost "mkdir -p /opt/zeal-lcd-telemetry"
Copy-Remote $AgentSrc "${ZealTowerHost}:/opt/zeal-lcd-telemetry/lcd-telemetry-agent.mjs"
$RemoteTemplate = @'
set -eu
DIR=/opt/zeal-lcd-telemetry
TOKEN='__TOKEN__'
PORT='__PORT__'
printf '%s\n' "$TOKEN" > "$DIR/token"
chmod 0600 "$DIR/token"
cat > "$DIR/restart.sh" <<'SH'
#!/bin/sh
set -eu
DIR=/opt/zeal-lcd-telemetry
if [ -f "$DIR/agent.pid" ]; then
  oldpid=$(cat "$DIR/agent.pid" 2>/dev/null || true)
  if [ -n "$oldpid" ] && kill -0 "$oldpid" 2>/dev/null; then
    kill "$oldpid" 2>/dev/null || true
    sleep 1
  fi
fi
ZEAL_TELEMETRY_NAME=zealtower \
ZEAL_TELEMETRY_PORT=__PORT__ \
ZEAL_TELEMETRY_BIND=0.0.0.0 \
ZEAL_TELEMETRY_DISKS="/,/mnt/cache" \
ZEAL_TELEMETRY_TOKEN_FILE="$DIR/token" \
nohup /usr/local/bin/node "$DIR/lcd-telemetry-agent.mjs" >> "$DIR/agent.log" 2>&1 &
echo $! > "$DIR/agent.pid"
SH
sed -i "s/__PORT__/$PORT/g" "$DIR/restart.sh"
chmod 0755 "$DIR/restart.sh"
if [ -d /etc/cron.d ]; then
  cat > /etc/cron.d/zeal-lcd-telemetry <<SH
SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
@reboot root "$DIR/restart.sh"
SH
  chmod 0644 /etc/cron.d/zeal-lcd-telemetry
fi
"$DIR/restart.sh"
sleep 1
cat "$DIR/agent.pid"
'@
$Remote = $RemoteTemplate -replace "__TOKEN__", $Token -replace "__PORT__", $Port
$Remote = $Remote -replace "`r`n", "`n" -replace "`r", "`n"
Invoke-Remote $ZealTowerHost $Remote

Write-Host "Installing Vector telemetry agent..."
$VectorDir = Join-Path $env:LOCALAPPDATA "ZealPalace\lcd-telemetry"
New-Item -ItemType Directory -Force -Path $VectorDir | Out-Null
$VectorAgent = Join-Path $VectorDir "lcd-telemetry-agent.mjs"
$VectorToken = Join-Path $VectorDir "token"
$VectorRunner = Join-Path $VectorDir "run.cmd"
Copy-Item -LiteralPath $AgentSrc -Destination $VectorAgent -Force
Set-Content -LiteralPath $VectorToken -Value $Token -Encoding ascii
@"
@echo off
set ZEAL_TELEMETRY_NAME=vector
set ZEAL_TELEMETRY_PORT=$Port
set ZEAL_TELEMETRY_BIND=0.0.0.0
set ZEAL_TELEMETRY_DISKS=C:/
set ZEAL_TELEMETRY_TOKEN_FILE=$VectorToken
node "$VectorAgent" >> "$VectorDir\agent.log" 2>&1
"@ | Set-Content -LiteralPath $VectorRunner -Encoding ascii

Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like "*lcd-telemetry-agent.mjs*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

try {
    $Action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$VectorRunner`""
    $Trigger = New-ScheduledTaskTrigger -AtLogOn
    Register-ScheduledTask -TaskName "ZealPalace LCD Telemetry Agent" -Action $Action -Trigger $Trigger -Description "Read-only Vector telemetry endpoint for ZealPalace LCD" -Force -ErrorAction Stop | Out-Null
}
catch {
    $StartupDir = [Environment]::GetFolderPath("Startup")
    if ($StartupDir) {
        $StartupCmd = Join-Path $StartupDir "ZealPalace LCD Telemetry Agent.cmd"
        "@echo off`r`nstart `"`" /min `"$VectorRunner`"`r`n" | Set-Content -LiteralPath $StartupCmd -Encoding ascii
        Write-Warning "Scheduled task registration failed; installed Startup fallback: $StartupCmd"
    }
    else {
        Write-Warning "Scheduled task registration failed and Startup folder is unavailable: $($_.Exception.Message)"
    }
}
Start-Process -FilePath $VectorRunner -WindowStyle Hidden

Write-Host "Writing Pi telemetry source config..."
$Config = [ordered]@{
    sources = @(
        [ordered]@{ name = "zealtower"; url = $ZealTowerUrl; token = $Token },
        [ordered]@{ name = "vector"; url = $VectorUrl; token = $Token }
    )
}
$ConfigPath = Join-Path $env:TEMP "zealpalace-lan-telemetry-sources.json"
$Config | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ConfigPath -Encoding utf8
Invoke-Remote $PiHost "mkdir -p /home/aday/.cache/zealot"
Copy-Remote $ConfigPath "${PiHost}:/home/aday/.cache/zealot/lan_telemetry_sources.json"

Write-Host "Verifying from Pi..."
Invoke-Remote $PiHost "python3 - <<'PY'
import json, urllib.request
cfg=json.load(open('/home/aday/.cache/zealot/lan_telemetry_sources.json'))
for src in cfg['sources']:
    req=urllib.request.Request(src['url'], headers={'X-Zeal-Telemetry-Token':src['token']})
    with urllib.request.urlopen(req, timeout=5) as r:
        data=json.load(r)
    print(src['name'], data.get('ok'), data.get('name'), len(data.get('gpus') or []))
PY"

Write-Host "Telemetry JSON pull deployment complete."
