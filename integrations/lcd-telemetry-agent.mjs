#!/usr/bin/env node
import { execFile } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

const PORT = Number.parseInt(process.env.ZEAL_TELEMETRY_PORT || "9199", 10);
const BIND = process.env.ZEAL_TELEMETRY_BIND || "0.0.0.0";
const HOST_NAME = process.env.ZEAL_TELEMETRY_NAME || os.hostname();
const DISK_PATHS = (process.env.ZEAL_TELEMETRY_DISKS || defaultDiskPaths())
  .split(",")
  .map((row) => row.trim())
  .filter(Boolean);
const ALLOW_PREFIXES = (process.env.ZEAL_TELEMETRY_ALLOW ||
  "127.,::1,::ffff:127.,10.13.37.,::ffff:10.13.37.,100.,::ffff:100.,172.,::ffff:172.")
  .split(",")
  .map((row) => row.trim())
  .filter(Boolean);
const TOKEN = readToken();

let previousCpuSample = null;
let previousNetSample = null;

function defaultDiskPaths() {
  if (process.platform === "win32") {
    return "C:/";
  }
  return "/,/mnt/cache,/mnt/c";
}

function readToken() {
  if (process.env.ZEAL_TELEMETRY_TOKEN) {
    return process.env.ZEAL_TELEMETRY_TOKEN.trim();
  }
  const tokenFile = process.env.ZEAL_TELEMETRY_TOKEN_FILE;
  if (!tokenFile) {
    return "";
  }
  try {
    return fs.readFileSync(tokenFile, "utf8").trim();
  } catch {
    return "";
  }
}

function remoteAllowed(remoteAddress = "") {
  if (!ALLOW_PREFIXES.length) {
    return true;
  }
  return ALLOW_PREFIXES.some((prefix) => remoteAddress.startsWith(prefix));
}

function tokenAllowed(req) {
  if (!TOKEN) {
    return true;
  }
  const rawAuth = req.headers.authorization || "";
  const bearer = rawAuth.toLowerCase().startsWith("bearer ") ? rawAuth.slice(7).trim() : "";
  const header = req.headers["x-zeal-telemetry-token"] || "";
  return constantEqual(String(header), TOKEN) || constantEqual(String(bearer), TOKEN);
}

function constantEqual(a, b) {
  const left = Buffer.from(a);
  const right = Buffer.from(b);
  if (left.length !== right.length) {
    return false;
  }
  return crypto.timingSafeEqual(left, right);
}

function cpuSample() {
  const cpus = os.cpus();
  let idle = 0;
  let total = 0;
  for (const cpu of cpus) {
    idle += cpu.times.idle;
    total += Object.values(cpu.times).reduce((sum, value) => sum + value, 0);
  }
  const now = { idle, total };
  if (!previousCpuSample) {
    previousCpuSample = now;
    return 0;
  }
  const idleDelta = idle - previousCpuSample.idle;
  const totalDelta = total - previousCpuSample.total;
  previousCpuSample = now;
  if (totalDelta <= 0) {
    return 0;
  }
  return clampPct((1 - idleDelta / totalDelta) * 100);
}

function clampPct(value) {
  if (!Number.isFinite(value)) {
    return 0;
  }
  return Math.max(0, Math.min(100, value));
}

function diskRows() {
  const rows = [];
  for (const diskPath of DISK_PATHS) {
    try {
      const stat = fs.statfsSync(diskPath);
      const total = Number(stat.blocks) * Number(stat.bsize);
      const free = Number(stat.bavail) * Number(stat.bsize);
      const used = Math.max(0, total - free);
      rows.push({
        path: diskPath,
        total,
        used,
        free,
        pct: round((used / total) * 100),
      });
    } catch {
      rows.push({ path: diskPath, ok: false, pct: 0 });
    }
  }
  return rows;
}

function netCounters() {
  if (process.platform === "win32") {
    return { rx: 0, tx: 0, rx_bps: 0, tx_bps: 0 };
  }
  let rx = 0;
  let tx = 0;
  try {
    const lines = fs.readFileSync("/proc/net/dev", "utf8").split(/\r?\n/).slice(2);
    for (const line of lines) {
      const [ifaceRaw, restRaw] = line.split(":");
      const iface = (ifaceRaw || "").trim();
      if (!iface || iface === "lo") {
        continue;
      }
      const fields = (restRaw || "").trim().split(/\s+/);
      rx += Number.parseInt(fields[0] || "0", 10);
      tx += Number.parseInt(fields[8] || "0", 10);
    }
  } catch {
    return { rx: 0, tx: 0, rx_bps: 0, tx_bps: 0 };
  }
  const now = Date.now() / 1000;
  if (!previousNetSample) {
    previousNetSample = { ts: now, rx, tx };
    return { rx, tx, rx_bps: 0, tx_bps: 0 };
  }
  const elapsed = Math.max(0.2, now - previousNetSample.ts);
  const rx_bps = Math.max(0, (rx - previousNetSample.rx) / elapsed);
  const tx_bps = Math.max(0, (tx - previousNetSample.tx) / elapsed);
  previousNetSample = { ts: now, rx, tx };
  return { rx, tx, rx_bps: Math.round(rx_bps), tx_bps: Math.round(tx_bps) };
}

async function gpuRows() {
  try {
    const { stdout } = await execFileAsync(
      "nvidia-smi",
      [
        "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
        "--format=csv,noheader,nounits",
      ],
      { timeout: 3500, windowsHide: true },
    );
    return stdout
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const [name, util, memUsed, memTotal, temp] = line.split(",").map((part) => part.trim());
        return {
          name,
          util_pct: round(Number.parseFloat(util)),
          mem_used_mb: Number.parseInt(memUsed || "0", 10),
          mem_total_mb: Number.parseInt(memTotal || "0", 10),
          temp_c: round(Number.parseFloat(temp)),
        };
      });
  } catch {
    return [];
  }
}

async function metrics() {
  const totalMem = os.totalmem();
  const freeMem = os.freemem();
  const load = os.loadavg();
  const now = Date.now() / 1000;
  return {
    ok: true,
    schema: "zeal-lcd-telemetry/v1",
    generated_at: new Date().toISOString(),
    generated_ts: Math.floor(now),
    host: HOST_NAME.toLowerCase(),
    name: HOST_NAME,
    platform: process.platform,
    arch: process.arch,
    uptime_sec: Math.round(os.uptime()),
    cores: os.cpus().length,
    load1: round(load[0] || 0),
    load5: round(load[1] || 0),
    load15: round(load[2] || 0),
    cpu_pct: round(cpuSample()),
    mem_pct: round(((totalMem - freeMem) / totalMem) * 100),
    mem_total: totalMem,
    mem_used: totalMem - freeMem,
    disks: diskRows(),
    gpus: await gpuRows(),
    net: netCounters(),
  };
}

function round(value) {
  if (!Number.isFinite(value)) {
    return 0;
  }
  return Math.round(value * 10) / 10;
}

function sendJson(res, code, body) {
  const payload = JSON.stringify(body);
  res.writeHead(code, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
  });
  res.end(payload);
}

const server = http.createServer(async (req, res) => {
  const remote = req.socket.remoteAddress || "";
  if (!remoteAllowed(remote)) {
    sendJson(res, 403, { ok: false, error: "remote not allowed" });
    return;
  }
  if (req.method !== "GET") {
    sendJson(res, 405, { ok: false, error: "read-only endpoint" });
    return;
  }
  if (!tokenAllowed(req)) {
    sendJson(res, 401, { ok: false, error: "unauthorized" });
    return;
  }
  const url = new URL(req.url || "/", `http://${req.headers.host || "localhost"}`);
  if (url.pathname === "/health") {
    sendJson(res, 200, {
      ok: true,
      service: "zeal-lcd-telemetry",
      host: HOST_NAME,
      generated_at: new Date().toISOString(),
    });
    return;
  }
  if (url.pathname === "/metrics.json") {
    sendJson(res, 200, await metrics());
    return;
  }
  sendJson(res, 404, { ok: false, error: "not found" });
});

server.listen(PORT, BIND, () => {
  console.log(`[zeal-lcd-telemetry] ${new Date().toISOString()} listening on ${BIND}:${PORT}`);
});
