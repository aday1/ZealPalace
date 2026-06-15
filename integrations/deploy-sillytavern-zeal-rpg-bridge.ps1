param(
    [string]$HostName = "zealtower",
    [string]$BridgeDir = "/opt/sillytavern/zeal-bridge",
    [string]$ExtensionDir = "/opt/sillytavern/extensions/zealpalace-rp-suite",
    [string]$ServiceName = "sillytavern-zeal-rpg-bridge"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$BridgeScript = Join-Path $PSScriptRoot "sillytavern-zeal-rpg-bridge.mjs"
$ServiceFile = Join-Path $PSScriptRoot "sillytavern-zeal-rpg-bridge.service"
$PatchScript = Join-Path $PSScriptRoot "patch-sillytavern-rp-suite.cjs"
$SshOptions = @(
    "-o", "BatchMode=yes",
    "-o", "ConnectionAttempts=1",
    "-o", "ConnectTimeout=8",
    "-o", "ServerAliveInterval=2",
    "-o", "ServerAliveCountMax=2"
)

foreach ($Path in @($BridgeScript, $ServiceFile, $PatchScript)) {
    if (-not (Test-Path $Path)) {
        throw "Missing required file: $Path"
    }
}

function Invoke-BridgeRemote {
    param([Parameter(Mandatory = $true)][string]$Command)
    & ssh @SshOptions $HostName $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Remote command failed with exit code $LASTEXITCODE"
    }
}

function Copy-BridgeRemote {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    & scp @SshOptions $Source $Destination
    if ($LASTEXITCODE -ne 0) {
        throw "Copy failed with exit code $LASTEXITCODE"
    }
}

function Test-SshBanner {
    param([Parameter(Mandatory = $true)][string]$TargetHost)

    $Client = [System.Net.Sockets.TcpClient]::new()
    try {
        $Connect = $Client.BeginConnect($TargetHost, 22, $null, $null)
        if (-not $Connect.AsyncWaitHandle.WaitOne(5000)) {
            throw "TCP connect to $TargetHost:22 timed out"
        }

        $Client.EndConnect($Connect)
        $Stream = $Client.GetStream()
        $Stream.ReadTimeout = 5000
        $Buffer = New-Object byte[] 128
        $Count = $Stream.Read($Buffer, 0, $Buffer.Length)
        if ($Count -le 0) {
            throw "SSH port closed before sending a banner"
        }

        $Banner = [Text.Encoding]::ASCII.GetString($Buffer, 0, $Count).Trim()
        if (-not $Banner.StartsWith("SSH-")) {
            throw "unexpected SSH banner: $Banner"
        }

        Write-Host "SSH banner OK: $Banner"
    }
    finally {
        $Client.Close()
    }
}

Write-Host "Checking SSH access to $HostName..."
try {
    Test-SshBanner $HostName
}
catch {
    Write-Warning "SSH banner preflight failed; continuing with OpenSSH config: $($_.Exception.Message)"
}
Invoke-BridgeRemote "hostname; command -v node; command -v docker"

Write-Host "Creating bridge directory..."
Invoke-BridgeRemote "mkdir -p '$BridgeDir'"

Write-Host "Copying bridge files..."
Copy-BridgeRemote $BridgeScript "${HostName}:/tmp/sillytavern-zeal-rpg-bridge.mjs"
Copy-BridgeRemote $ServiceFile "${HostName}:/tmp/sillytavern-zeal-rpg-bridge.service"
Copy-BridgeRemote $PatchScript "${HostName}:/tmp/patch-sillytavern-rp-suite.cjs"

Write-Host "Installing bridge service and patching SillyTavern extension..."
$RemoteTemplate = @'
set -e
BRIDGE_DIR='__BRIDGE_DIR__'
EXTENSION_DIR='__EXTENSION_DIR__'
SERVICE_NAME='__SERVICE_NAME__'
CARD_INSPECT='/home/node/app/public/scripts/extensions/third-party/zealpalace-rp-suite/inspect-cards.mjs'
install -m 0755 /tmp/sillytavern-zeal-rpg-bridge.mjs "$BRIDGE_DIR/sillytavern-zeal-rpg-bridge.mjs"
node --check "$BRIDGE_DIR/sillytavern-zeal-rpg-bridge.mjs"
node /tmp/patch-sillytavern-rp-suite.cjs "$EXTENSION_DIR/index.js"

restart_sillytavern() {
    systemctl restart sillytavern 2>/dev/null || docker restart sillytavern >/dev/null
}

wait_for_cards() {
    for attempt in 1 2 3 4 5 6 7 8 9 10; do
        if docker exec sillytavern node "$CARD_INSPECT" >/dev/null 2>&1; then
            return 0
        fi
        sleep 2
    done
    echo "SillyTavern card export did not become ready" >&2
    return 1
}

if command -v systemctl >/dev/null 2>&1 && [ -d /etc/systemd/system ]; then
    install -m 0644 /tmp/sillytavern-zeal-rpg-bridge.service "/etc/systemd/system/$SERVICE_NAME.service"
    systemctl daemon-reload
    restart_sillytavern
    wait_for_cards
    systemctl enable "$SERVICE_NAME.service"
    systemctl restart "$SERVICE_NAME.service"
    systemctl --no-pager --full status "$SERVICE_NAME.service" | sed -n '1,18p'
else
    cat > "$BRIDGE_DIR/restart-bridge.sh" <<'SH'
#!/bin/sh
set -e
BRIDGE_DIR=/opt/sillytavern/zeal-bridge
if [ -f "$BRIDGE_DIR/bridge.pid" ]; then
    oldpid=$(cat "$BRIDGE_DIR/bridge.pid" 2>/dev/null || true)
    if [ -n "$oldpid" ] && kill -0 "$oldpid" 2>/dev/null; then
        kill "$oldpid" || true
        sleep 1
    fi
fi
nohup /usr/local/bin/node "$BRIDGE_DIR/sillytavern-zeal-rpg-bridge.mjs" >> "$BRIDGE_DIR/bridge.log" 2>&1 &
echo $! > "$BRIDGE_DIR/bridge.pid"
SH
    chmod 0755 "$BRIDGE_DIR/restart-bridge.sh"
    restart_sillytavern
    wait_for_cards
    "$BRIDGE_DIR/restart-bridge.sh"
    sleep 3
    ps -ef | grep -F 'sillytavern-zeal-rpg-bridge.mjs' | grep -v grep
fi
'@

$Remote = $RemoteTemplate `
    -replace "__BRIDGE_DIR__", $BridgeDir `
    -replace "__EXTENSION_DIR__", $ExtensionDir `
    -replace "__SERVICE_NAME__", $ServiceName

Invoke-BridgeRemote $Remote

Write-Host "Checking bridge health..."
Invoke-BridgeRemote "curl --max-time 8 -sS http://100.91.133.101:8787/health || curl --max-time 8 -sS http://127.0.0.1:8787/health"

Write-Host "Deployment complete."
