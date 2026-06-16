param(
    [string]$PiHost = "zealpalace",
    [string]$PiPath = "/home/aday/.cache/zealot/lan_telemetry.json",
    [string[]]$Hosts = @("zealtower=root@zealtower", "vector=aday@vector")
)

$ErrorActionPreference = "Stop"
$SshOptions = @(
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "ConnectionAttempts=1",
    "-o", "ConnectTimeout=8",
    "-o", "ServerAliveInterval=2",
    "-o", "ServerAliveCountMax=2"
)

$RemoteScript = @'
set -eu
printf 'HOSTNAME|%s\n' "$(hostname 2>/dev/null || echo unknown)"
printf 'CORES|%s\n' "$(nproc 2>/dev/null || echo 1)"
if [ -r /proc/loadavg ]; then
  set -- $(cat /proc/loadavg)
  printf 'LOAD|%s|%s|%s\n' "$1" "$2" "$3"
fi
free -m 2>/dev/null | while read key total used free shared buff available rest; do
  if [ "$key" = "Mem:" ]; then
    printf 'MEM|%s|%s|%s\n' "$total" "$used" "$available"
  fi
done
df -Pk / /mnt/cache /mnt/c 2>/dev/null | while read fs blocks used avail pct mount rest; do
  if [ "$fs" = "Filesystem" ]; then
    continue
  fi
  pct=${pct%%%}
  printf 'DISK|%s|%s|%s|%s|%s\n' "$mount" "$blocks" "$used" "$avail" "$pct"
done
nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader,nounits 2>/dev/null |
  while IFS=, read name util mem_used mem_total temp rest; do
    name=$(printf '%s' "$name" | xargs)
    util=$(printf '%s' "$util" | xargs)
    mem_used=$(printf '%s' "$mem_used" | xargs)
    mem_total=$(printf '%s' "$mem_total" | xargs)
    temp=$(printf '%s' "$temp" | xargs)
    printf 'GPU|%s|%s|%s|%s|%s\n' "$name" "$util" "$mem_used" "$mem_total" "$temp"
  done
'@
$RemoteScript = $RemoteScript -replace "`r`n", "`n" -replace "`r", "`n"

$PythonRemoteScript = @'
python3 - <<'PY'
import json, os, shutil, socket, subprocess

def emit(*parts):
    print("|".join(str(p) for p in parts))

emit("HOSTNAME", socket.gethostname())
emit("CORES", os.cpu_count() or 1)
try:
    load = os.getloadavg()
    emit("LOAD", round(load[0], 2), round(load[1], 2), round(load[2], 2))
except OSError:
    pass
try:
    mem = {}
    with open("/proc/meminfo", "r", encoding="utf-8") as handle:
        for line in handle:
            key, _, rest = line.partition(":")
            mem[key] = int(rest.strip().split()[0]) // 1024
    total = mem.get("MemTotal", 0)
    avail = mem.get("MemAvailable", 0)
    emit("MEM", total, max(0, total - avail), avail)
except Exception:
    pass
for mount in ("/", "/mnt/cache", "/mnt/c"):
    try:
        usage = shutil.disk_usage(mount)
    except OSError:
        continue
    pct = round((usage.used / usage.total) * 100.0, 1) if usage.total else 0
    emit("DISK", mount, usage.total // 1024, usage.used // 1024, usage.free // 1024, pct)
try:
    out = subprocess.check_output([
        "nvidia-smi",
        "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
        "--format=csv,noheader,nounits",
    ], text=True, stderr=subprocess.DEVNULL, timeout=4)
    for row in out.splitlines():
        fields = [part.strip() for part in row.split(",")]
        if len(fields) >= 5:
            emit("GPU", fields[0], fields[1], fields[2], fields[3], fields[4])
except Exception:
    pass
PY
'@
$PythonRemoteScript = $PythonRemoteScript -replace "`r`n", "`n" -replace "`r", "`n"

function Invoke-RemoteLines {
    param(
        [Parameter(Mandatory = $true)][string]$HostName,
        [Parameter(Mandatory = $true)][string]$Command
    )
    $Lines = & ssh @SshOptions $HostName $Command
    if ($LASTEXITCODE -ne 0) {
        throw "ssh $HostName failed with exit code $LASTEXITCODE"
    }
    return $Lines
}

function To-Double {
    param($Value)
    $Out = 0.0
    if ([double]::TryParse([string]$Value, [Globalization.NumberStyles]::Float, [Globalization.CultureInfo]::InvariantCulture, [ref]$Out)) {
        return $Out
    }
    return 0.0
}

function To-Long {
    param($Value)
    $Out = 0L
    if ([long]::TryParse([string]$Value, [ref]$Out)) {
        return $Out
    }
    return 0L
}

function Get-LanHostTelemetry {
    param(
        [Parameter(Mandatory = $true)][string]$Key,
        [Parameter(Mandatory = $true)][string]$Target
    )

    $Obj = [ordered]@{
        ok = $false
        host = $Key
        target = $Target
        name = $Key
        cores = 1
        load1 = 0.0
        load5 = 0.0
        load15 = 0.0
        cpu_pct = 0.0
        mem_pct = 0.0
        disks = @()
        gpus = @()
        collected_at = [DateTimeOffset]::UtcNow.ToString("o")
    }

    try {
        $Command = if ($Target -match "vector$") { $PythonRemoteScript } else { $RemoteScript }
        $Lines = Invoke-RemoteLines -HostName $Target -Command $Command
        foreach ($Line in $Lines) {
            if (-not $Line) { continue }
            $Parts = $Line -split '\|'
            switch ($Parts[0]) {
                "HOSTNAME" {
                    if ($Parts.Count -ge 2) { $Obj.name = $Parts[1] }
                }
                "CORES" {
                    if ($Parts.Count -ge 2) { $Obj.cores = [Math]::Max(1, [int](To-Long $Parts[1])) }
                }
                "LOAD" {
                    if ($Parts.Count -ge 4) {
                        $Obj.load1 = [Math]::Round((To-Double $Parts[1]), 2)
                        $Obj.load5 = [Math]::Round((To-Double $Parts[2]), 2)
                        $Obj.load15 = [Math]::Round((To-Double $Parts[3]), 2)
                    }
                }
                "MEM" {
                    if ($Parts.Count -ge 4) {
                        $Total = To-Double $Parts[1]
                        $Used = To-Double $Parts[2]
                        if ($Total -gt 0) {
                            $Obj.mem_pct = [Math]::Round(($Used / $Total) * 100.0, 1)
                        }
                    }
                }
                "DISK" {
                    if ($Parts.Count -ge 6) {
                        $Obj.disks += [ordered]@{
                            path = $Parts[1]
                            total_kb = To-Long $Parts[2]
                            used_kb = To-Long $Parts[3]
                            free_kb = To-Long $Parts[4]
                            pct = [Math]::Round((To-Double $Parts[5]), 1)
                        }
                    }
                }
                "GPU" {
                    if ($Parts.Count -ge 6) {
                        $Obj.gpus += [ordered]@{
                            name = $Parts[1]
                            util_pct = [Math]::Round((To-Double $Parts[2]), 1)
                            mem_used_mb = To-Long $Parts[3]
                            mem_total_mb = To-Long $Parts[4]
                            temp_c = [Math]::Round((To-Double $Parts[5]), 1)
                        }
                    }
                }
            }
        }
        $Obj.cpu_pct = [Math]::Round([Math]::Min(100.0, ($Obj.load1 / [Math]::Max(1, $Obj.cores)) * 100.0), 1)
        $Obj.ok = $true
    }
    catch {
        $Obj.error = $_.Exception.Message
    }

    return $Obj
}

$HostsMap = [ordered]@{}
foreach ($HostEntry in $Hosts) {
    $Parts = $HostEntry -split '=', 2
    if ($Parts.Count -eq 2) {
        $Key = $Parts[0].ToLowerInvariant()
        $Target = $Parts[1]
    }
    else {
        $Key = $HostEntry.ToLowerInvariant()
        $Target = $HostEntry
    }
    $HostsMap[$Key] = Get-LanHostTelemetry -Key $Key -Target $Target
}

$Payload = [ordered]@{
    generated_at = [DateTimeOffset]::UtcNow.ToString("o")
    generated_ts = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    source = $env:COMPUTERNAME
    hosts = $HostsMap
}

$Temp = Join-Path $env:TEMP "zealpalace-lan-telemetry.json"
$Payload | ConvertTo-Json -Depth 8 | Set-Content -Path $Temp -Encoding utf8

& ssh @SshOptions $PiHost "mkdir -p '$(Split-Path -Parent $PiPath)'"
if ($LASTEXITCODE -ne 0) {
    throw "failed to create telemetry directory on $PiHost"
}
& scp @SshOptions $Temp "${PiHost}:$PiPath"
if ($LASTEXITCODE -ne 0) {
    throw "failed to copy telemetry to $PiHost"
}

Write-Host "Wrote telemetry for $($HostsMap.Keys -join ', ') to ${PiHost}:$PiPath"
