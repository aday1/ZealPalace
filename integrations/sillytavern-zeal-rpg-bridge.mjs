#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import http from 'node:http';
import net from 'node:net';
import path from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

const execFileAsync = promisify(execFile);

const CONFIG_PATH = process.env.ZEAL_BRIDGE_CONFIG || '/opt/sillytavern/zeal-bridge/config.json';
const RECENT_LIMIT = 80;

const DEFAULT_CONFIG = {
  irc: {
    host: '10.13.37.76',
    port: 6667,
    channel: '#RPG',
    nick: 'sillytavern-bridge',
    chunk: 390,
    ignoredNicks: [
      'DungeonMaster',
      'hermes-dungeon-master',
      'sillytavern-bridge',
      'Zealot',
      'Zealot_SuperEgo',
      'Zealot_ID',
      'zeallog',
      'mc-bridge',
    ],
  },
  sillytavern: {
    dataRoot: '/opt/sillytavern/data/default-user',
    containerName: 'sillytavern',
    extensionPath: '/home/node/app/public/scripts/extensions/third-party/zealpalace-rp-suite',
    liveWorldName: 'ZealPalace IRC RPG Live.json',
  },
  ollama: {
    primaryUrl: 'http://127.0.0.1:11434',
    fallbackUrl: 'http://10.13.37.60:11434',
    model: 'qwen2.5-coder:7b',
    timeoutMs: 35000,
  },
  http: {
    host: '100.91.133.101',
    port: 8787,
    tokenFile: '/opt/sillytavern/zeal-bridge/token.txt',
    allowedOrigins: [
      'http://100.91.133.101:8000',
      'http://10.13.37.5:8000',
    ],
  },
};

const state = {
  cfg: null,
  token: '',
  characters: [],
  characterSource: 'none',
  worlds: [],
  recent: [],
  irc: null,
  ircReady: false,
  worldWriteTimer: null,
};

function log(message, extra = '') {
  const suffix = extra ? ` ${extra}` : '';
  console.log(`[zeal-bridge] ${new Date().toISOString()} ${message}${suffix}`);
}

async function pathExists(filePath) {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

async function loadOrCreateConfig() {
  const dir = path.dirname(CONFIG_PATH);
  await fs.mkdir(dir, { recursive: true });

  if (!(await pathExists(CONFIG_PATH))) {
    await fs.writeFile(CONFIG_PATH, `${JSON.stringify(DEFAULT_CONFIG, null, 2)}\n`, { mode: 0o640 });
  }

  const cfg = JSON.parse(await fs.readFile(CONFIG_PATH, 'utf8'));
  const merged = {
    ...DEFAULT_CONFIG,
    ...cfg,
    irc: { ...DEFAULT_CONFIG.irc, ...(cfg.irc || {}) },
    sillytavern: { ...DEFAULT_CONFIG.sillytavern, ...(cfg.sillytavern || {}) },
    ollama: { ...DEFAULT_CONFIG.ollama, ...(cfg.ollama || {}) },
    http: { ...DEFAULT_CONFIG.http, ...(cfg.http || {}) },
  };
  state.cfg = merged;
  return merged;
}

async function loadOrCreateToken(cfg) {
  const tokenFile = cfg.http.tokenFile;
  await fs.mkdir(path.dirname(tokenFile), { recursive: true });
  if (!(await pathExists(tokenFile))) {
    const token = crypto.randomBytes(24).toString('hex');
    await fs.writeFile(tokenFile, `${token}\n`, { mode: 0o600 });
  }
  state.token = (await fs.readFile(tokenFile, 'utf8')).trim();
}

function trimText(value, max = 900) {
  return String(value || '').replace(/\s+/g, ' ').trim().slice(0, max);
}

function normalizeName(value) {
  return String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
}

function aliasesFor(character) {
  const out = new Set();
  const name = character.name || character.file || '';
  const normalized = normalizeName(name);
  if (normalized) out.add(normalized);
  const first = normalized.split(' ')[0];
  if (first) out.add(first);
  const fileBase = normalizeName(String(character.file || '').replace(/\.[^.]+$/, ''));
  if (fileBase) out.add(fileBase);
  if (fileBase) {
    const fileFirst = fileBase.split(' ')[0];
    if (fileFirst) out.add(fileFirst);
  }
  for (const value of [
    character.slug,
    character.ext,
    character.ircNick,
    character.short,
    ...(Array.isArray(character.tags) ? character.tags : []),
  ]) {
    const alias = normalizeName(value);
    if (alias) out.add(alias);
  }
  return [...out];
}

function getCardPayloadField(payload, key) {
  if (!payload || typeof payload !== 'object') return '';
  const data = payload.data && typeof payload.data === 'object' ? payload.data : {};
  return data[key] ?? payload[key] ?? '';
}

function decodeCardPayload(text) {
  const raw = String(text || '').trim();
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    try {
      return JSON.parse(Buffer.from(raw, 'base64').toString('utf8'));
    } catch {
      return null;
    }
  }
}

function readPngTextChunks(buffer) {
  const chunks = new Map();
  const signature = buffer.subarray(0, 8).toString('hex');
  if (signature !== '89504e470d0a1a0a') return chunks;

  let offset = 8;
  while (offset + 12 <= buffer.length) {
    const length = buffer.readUInt32BE(offset);
    const type = buffer.subarray(offset + 4, offset + 8).toString('latin1');
    const start = offset + 8;
    const end = start + length;
    if (end + 4 > buffer.length) break;

    if (type === 'tEXt') {
      const data = buffer.subarray(start, end);
      const nul = data.indexOf(0);
      if (nul >= 0) {
        const key = data.subarray(0, nul).toString('utf8');
        chunks.set(key, data.subarray(nul + 1).toString('utf8'));
      }
    }

    offset = end + 4;
    if (type === 'IEND') break;
  }
  return chunks;
}

async function readCharacterCard(filePath, file) {
  const buffer = await fs.readFile(filePath);
  const chunks = readPngTextChunks(buffer);
  const payload = decodeCardPayload(chunks.get('ccv3')) || decodeCardPayload(chunks.get('chara'));
  if (!payload) {
    const name = file.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ');
    return { file, name, aliases: aliasesFor({ file, name }) };
  }

  const data = payload.data && typeof payload.data === 'object' ? payload.data : {};
  const extensions = data.extensions || payload.extensions || {};
  const zeal = extensions.zealpalace || {};
  const tags = [
    ...(Array.isArray(data.tags) ? data.tags : []),
    ...(Array.isArray(payload.tags) ? payload.tags : []),
  ].filter(Boolean);
  const row = {
    file,
    name: trimText(getCardPayloadField(payload, 'name'), 120),
    description: trimText(getCardPayloadField(payload, 'description'), 2400),
    personality: trimText(getCardPayloadField(payload, 'personality'), 1600),
    scenario: trimText(getCardPayloadField(payload, 'scenario'), 1200),
    first_mes: trimText(getCardPayloadField(payload, 'first_mes'), 900),
    mes_example: trimText(getCardPayloadField(payload, 'mes_example'), 1200),
    tags: [...new Set(tags)],
    slug: zeal.slug || data.slug || payload.slug || '',
    ext: zeal.ext || data.ext || payload.ext || '',
    type: zeal.type || data.type || payload.type || '',
    voice: zeal.voice || data.voice || payload.voice || '',
    voiceSignature: zeal.voice_signature || data.voice_signature || payload.voice_signature || '',
    ircNick: zeal.irc_nick || zeal.crystal_party?.irc_nick || data.irc_nick || payload.irc_nick || '',
    short: zeal.short || zeal.crystal_party?.short || data.short || payload.short || '',
    sourceUrl: zeal.public_card_url || data.source_url || payload.source_url || '',
    aliases: [],
  };
  row.aliases = aliasesFor(row);
  return row;
}

async function loadCharactersFromCards(charDir) {
  const files = await fs.readdir(charDir, { withFileTypes: true });
  const cards = [];
  for (const entry of files) {
    if (!entry.isFile() || !entry.name.toLowerCase().endsWith('.png')) continue;
    try {
      const card = await readCharacterCard(path.join(charDir, entry.name), entry.name);
      if (card.name) cards.push(card);
    } catch (error) {
      log(`card parse failed for ${entry.name}`, error.message);
    }
  }
  cards.sort((a, b) => String(a.ext || a.name).localeCompare(String(b.ext || b.name), undefined, { numeric: true }));
  return cards;
}

async function loadCharacters() {
  const cfg = state.cfg;
  const charDir = path.join(cfg.sillytavern.dataRoot, 'characters');
  try {
    state.characters = await loadCharactersFromCards(charDir);
    if (state.characters.length > 0) {
      state.characterSource = 'png-card-metadata';
      log(`loaded ${state.characters.length} SillyTavern characters from PNG cards`);
      return state.characters;
    }
  } catch (error) {
    log('character card load failed', error.message);
  }

  const scriptPath = `${cfg.sillytavern.extensionPath}/inspect-cards.mjs`;
  try {
    const { stdout } = await execFileAsync(
      'docker',
      ['exec', cfg.sillytavern.containerName, 'node', scriptPath],
      { timeout: 15000, maxBuffer: 1024 * 1024 * 4 },
    );
    const parsed = JSON.parse(stdout);
    state.characters = parsed
      .filter((row) => row && row.name)
      .map((row) => ({
        file: row.file,
        name: trimText(row.name, 120),
        description: trimText(row.description, 1200),
        personality: trimText(row.personality, 1200),
        scenario: trimText(row.scenario, 900),
        first_mes: trimText(row.first_mes, 700),
        mes_example: trimText(row.mes_example, 900),
        tags: row.tags || [],
        aliases: aliasesFor(row),
      }));
    state.characterSource = 'extension-export';
    log(`loaded ${state.characters.length} SillyTavern characters from extension export`);
  } catch (error) {
    log('character extension export failed', error.message);
    state.characters = [];
    state.characterSource = 'none';
  }
  return state.characters;
}

async function loadWorlds() {
  const worldDir = path.join(state.cfg.sillytavern.dataRoot, 'worlds');
  const worlds = [];
  try {
    const files = await fs.readdir(worldDir);
    for (const file of files.filter((name) => name.endsWith('.json')).sort()) {
      const fullPath = path.join(worldDir, file);
      const root = JSON.parse(await fs.readFile(fullPath, 'utf8'));
      const entries = Object.values(root.entries || {})
        .filter((entry) => entry && !entry.disable)
        .sort((a, b) => Number(a.order || 0) - Number(b.order || 0));
      for (const entry of entries) {
        worlds.push({
          source: file,
          comment: trimText(entry.comment, 140),
          keys: Array.isArray(entry.key) ? entry.key.slice(0, 10) : [],
          content: trimText(entry.content, 1000),
        });
      }
    }
  } catch (error) {
    log('world load failed', error.message);
  }
  state.worlds = worlds;
  log(`loaded ${worlds.length} SillyTavern world entries`);
  return worlds;
}

async function refreshCache() {
  await loadCharacters();
  await loadWorlds();
  await writeLiveWorld();
}

function findCharacter(name) {
  const target = normalizeName(name);
  if (!target) return null;
  return state.characters.find((character) => character.aliases.includes(target))
    || state.characters.find((character) => normalizeName(character.name).includes(target))
    || null;
}

function findMention(text) {
  for (const character of state.characters) {
    for (const alias of character.aliases) {
      if (!alias || alias.length < 3) continue;
      const first = alias.split(' ')[0];
      const pattern = new RegExp(`(^|\\s)@${first.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(\\b|\\s|:|,)`, 'i');
      if (pattern.test(text)) return character;
    }
  }
  return null;
}

function recentLines(limit = 18) {
  return state.recent.slice(-limit).map((row) => {
    const stamp = row.ts.slice(11, 19);
    return `- ${stamp} ${row.nick}: ${trimText(row.text, 220)}`;
  }).join('\n');
}

function loreSnippet(limit = 4200) {
  const chunks = state.worlds
    .filter((entry) => entry.content)
    .slice(0, 20)
    .map((entry) => `[${entry.source} / ${entry.comment || entry.keys.join(', ')}]\n${entry.content}`);
  const text = chunks.join('\n\n');
  return text.length > limit ? `${text.slice(0, limit)}\n...[truncated]` : text;
}

function characterPrompt(character, nick, message) {
  return [
    `You are ${character.name}, a SillyTavern character stepping into the ZealPalace #RPG IRC channel.`,
    'Stay in character. Keep the reply IRC-friendly, one short paragraph, maximum 360 characters.',
    'Use *asterisk actions* when useful. Do not write analysis, JSON, markdown headings, or OOC notes.',
    'Respect the ZealPalace cyberpunk/Linux-filesystem RPG setting and current IRC context.',
    '',
    `Character description: ${character.description || '(none)'}`,
    `Personality: ${character.personality || '(none)'}`,
    `Scenario: ${character.scenario || '(none)'}`,
    '',
    `SillyTavern lore:\n${loreSnippet() || '(none)'}`,
    '',
    `Recent #RPG IRC:\n${recentLines() || '(none)'}`,
    '',
    `${nick} says: ${message}`,
    '',
    `Reply now as ${character.name}.`,
  ].join('\n');
}

async function ollamaChat(messages) {
  const cfg = state.cfg.ollama;
  const urls = [cfg.primaryUrl, cfg.fallbackUrl].filter(Boolean);
  let lastError = null;

  for (const baseUrl of urls) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), Number(cfg.timeoutMs) || 35000);
    try {
      const response = await fetch(`${baseUrl.replace(/\/$/, '')}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
        body: JSON.stringify({
          model: cfg.model,
          messages,
          stream: false,
          options: { temperature: 0.78, num_predict: 260 },
        }),
      });
      clearTimeout(timer);
      if (!response.ok) {
        throw new Error(`${baseUrl} HTTP ${response.status}`);
      }
      const data = await response.json();
      const content = data?.message?.content?.trim();
      if (content) return content;
      throw new Error(`${baseUrl} empty response`);
    } catch (error) {
      clearTimeout(timer);
      lastError = error;
      log('ollama backend failed', `${baseUrl}: ${error.message}`);
    }
  }

  throw lastError || new Error('no Ollama backend configured');
}

async function generateCharacterReply(character, nick, message) {
  const content = characterPrompt(character, nick, message);
  const raw = await ollamaChat([{ role: 'user', content }]);
  return trimText(raw.replace(/\r?\n+/g, ' '), 360);
}

function ircSay(text) {
  if (!state.ircReady || !state.irc || state.irc.destroyed) {
    throw new Error('IRC is not connected');
  }
  const channel = state.cfg.irc.channel;
  const chunk = Number(state.cfg.irc.chunk) || 390;
  const clean = String(text || '').replace(/[\r\n]+/g, ' ').trim();
  for (let i = 0; i < clean.length; i += chunk) {
    state.irc.write(`PRIVMSG ${channel} :${clean.slice(i, i + chunk)}\r\n`);
  }
}

function recordIrc(nick, text) {
  state.recent.push({
    ts: new Date().toISOString(),
    nick: trimText(nick, 80),
    text: trimText(text, 700),
  });
  state.recent = state.recent.slice(-RECENT_LIMIT);
  scheduleWorldWrite();
}

function liveWorldEntry(uid, comment, keys, content, order) {
  return {
    uid,
    key: keys,
    keysecondary: [],
    comment,
    content,
    constant: false,
    selective: true,
    order,
    position: 0,
    disable: false,
    displayIndex: uid,
    addMemo: true,
    group: 'zealpalace-live-irc',
    groupOverride: false,
    groupWeight: 100,
    sticky: 0,
    cooldown: 0,
    delay: 0,
    probability: 100,
    depth: 4,
    useProbability: true,
    role: null,
    vectorized: false,
    excludeRecursion: false,
    preventRecursion: false,
    delayUntilRecursion: false,
    scanDepth: null,
    caseSensitive: null,
    matchWholeWords: null,
    useGroupScoring: null,
    automationId: '',
  };
}

async function writeLiveWorld() {
  const worldDir = path.join(state.cfg.sillytavern.dataRoot, 'worlds');
  await fs.mkdir(worldDir, { recursive: true });
  const worldPath = path.join(worldDir, state.cfg.sillytavern.liveWorldName);
  const tempPath = `${worldPath}.tmp`;
  const characterNames = state.characters.map((character) => character.name).filter(Boolean);
  const content = [
    'Live ZealPalace #RPG IRC context mirrored from the SillyTavern bridge.',
    'Use this as recent world state, not as permanent canon unless repeated in play.',
    '',
    recentLines(28) || '(no recent #RPG traffic captured yet)',
  ].join('\n');
  const root = {
    entries: {
      0: liveWorldEntry(
        0,
        'Live #RPG IRC context',
        ['#RPG', 'ZealPalace IRC', 'DungeonMaster', 'sillytavern bridge', ...characterNames.slice(0, 8)],
        content,
        5,
      ),
      1: liveWorldEntry(
        1,
        'SillyTavern bridge commands',
        ['!st', 'sillytavern bridge', 'ZealPalace bridge'],
        'In ZealPalace IRC, !st <character> <message> asks a SillyTavern character to speak in #RPG. Mentions like @Yomiko can also summon a known character. The bridge is explicit-trigger only to avoid bot loops.',
        6,
      ),
    },
  };
  await fs.writeFile(tempPath, `${JSON.stringify(root, null, 2)}\n`);
  await fs.rename(tempPath, worldPath);
}

function scheduleWorldWrite() {
  if (state.worldWriteTimer) return;
  state.worldWriteTimer = setTimeout(async () => {
    state.worldWriteTimer = null;
    try {
      await writeLiveWorld();
    } catch (error) {
      log('live world write failed', error.message);
    }
  }, 3000);
}

async function handleBridgeRequest(character, nick, message) {
  const reply = await generateCharacterReply(character, nick, message);
  const line = `${character.name}/ST: ${reply}`;
  ircSay(line);
  recordIrc(`${character.name}/ST`, reply);
  return reply;
}

async function handleIrcMessage(nick, text) {
  const ignored = new Set((state.cfg.irc.ignoredNicks || []).map((value) => value.toLowerCase()));
  const lowerNick = nick.toLowerCase();
  recordIrc(nick, text);

  if (ignored.has(lowerNick) || lowerNick.startsWith('zealot')) return;

  const trimmed = text.trim();
  if (/^!st\s+sync\b/i.test(trimmed)) {
    await refreshCache();
    ircSay(`[ST] synced ${state.characters.length} characters and ${state.worlds.length} lore entries.`);
    return;
  }

  if (/^!st\s+list\b/i.test(trimmed)) {
    const names = state.characters.map((character) => character.name).slice(0, 12).join(', ');
    ircSay(`[ST] characters: ${names || 'none loaded'}`);
    return;
  }

  const command = trimmed.match(/^!st\s+(\S+)\s+(.+)/i);
  if (command) {
    const character = findCharacter(command[1]);
    if (!character) {
      ircSay(`[ST] unknown character "${command[1]}". Try !st list.`);
      return;
    }
    try {
      await handleBridgeRequest(character, nick, command[2]);
    } catch (error) {
      ircSay(`[ST] ${character.name} cannot reach the model right now (${trimText(error.message, 120)}).`);
    }
    return;
  }

  const mentioned = findMention(trimmed);
  if (mentioned) {
    try {
      await handleBridgeRequest(mentioned, nick, trimmed);
    } catch (error) {
      ircSay(`[ST] ${mentioned.name} cannot reach the model right now (${trimText(error.message, 120)}).`);
    }
  }
}

function parsePrivmsg(line) {
  const match = line.match(/^:([^! ]+)!.* PRIVMSG ([^ ]+) :([\s\S]*)$/);
  if (!match) return null;
  const [, nick, channel, text] = match;
  if (channel !== state.cfg.irc.channel) return null;
  return { nick, text };
}

function connectIrc() {
  const cfg = state.cfg.irc;
  const socket = net.createConnection({ host: cfg.host, port: Number(cfg.port) || 6667 });
  state.irc = socket;
  state.ircReady = false;
  let buffer = '';
  let joined = false;

  function tx(line) {
    socket.write(`${line}\r\n`);
  }

  function join() {
    if (joined) return;
    joined = true;
    tx(`JOIN ${cfg.channel}`);
    state.ircReady = true;
    log(`joined ${cfg.channel} as ${cfg.nick}`);
  }

  socket.on('connect', () => {
    tx(`NICK ${cfg.nick}`);
    tx(`USER ${cfg.nick} 0 * :SillyTavern ZealPalace bridge`);
    setTimeout(join, 1800);
  });

  socket.on('data', (chunk) => {
    buffer += chunk.toString('utf8');
    const lines = buffer.split('\r\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      if (line.startsWith('PING ')) {
        tx(`PONG ${line.slice(5)}`);
        continue;
      }
      if (line.includes(' 001 ')) join();
      const msg = parsePrivmsg(line);
      if (msg) {
        handleIrcMessage(msg.nick, msg.text).catch((error) => log('IRC handler failed', error.message));
      }
    }
  });

  socket.on('error', (error) => {
    log('IRC socket error', error.message);
  });

  socket.on('close', () => {
    state.ircReady = false;
    log('IRC disconnected; reconnecting');
    setTimeout(connectIrc, 8000);
  });
}

function sendJson(res, statusCode, payload, origin = '') {
  const headers = {
    'Content-Type': 'application/json',
    'Cache-Control': 'no-store',
  };
  if (origin) {
    headers['Access-Control-Allow-Origin'] = origin;
    headers['Vary'] = 'Origin';
  }
  res.writeHead(statusCode, headers);
  res.end(`${JSON.stringify(payload)}\n`);
}

async function readBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const raw = Buffer.concat(chunks).toString('utf8');
  return raw ? JSON.parse(raw) : {};
}

function allowedOrigin(req) {
  const origin = req.headers.origin || '';
  if (!origin) return '';
  const allowed = new Set(state.cfg.http.allowedOrigins || []);
  return allowed.has(origin) ? origin : '';
}

function authorized(req) {
  const bearer = String(req.headers.authorization || '').replace(/^Bearer\s+/i, '').trim();
  const header = String(req.headers['x-zeal-bridge-token'] || '').trim();
  return Boolean(state.token && (bearer === state.token || header === state.token));
}

function startHttp() {
  const cfg = state.cfg.http;
  const server = http.createServer(async (req, res) => {
    const origin = allowedOrigin(req);

    if (req.method === 'OPTIONS') {
      res.writeHead(204, {
        'Access-Control-Allow-Origin': origin,
        'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Zeal-Bridge-Token',
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Vary': 'Origin',
      });
      res.end();
      return;
    }

    try {
      const url = new URL(req.url || '/', `http://${req.headers.host || 'localhost'}`);
      if (req.method === 'GET' && url.pathname === '/health') {
        sendJson(res, 200, {
          ok: true,
          ircReady: state.ircReady,
          characters: state.characters.length,
          characterSource: state.characterSource,
          worlds: state.worlds.length,
          recent: state.recent.length,
        }, origin);
        return;
      }
      if (req.method === 'GET' && url.pathname === '/snapshot') {
        sendJson(res, 200, {
          recent: state.recent.slice(-30),
          characters: state.characters.map((character) => character.name),
        }, origin);
        return;
      }
      if (req.method === 'GET' && url.pathname === '/characters') {
        sendJson(res, 200, {
          characters: state.characters.map((character) => ({
            name: character.name,
            file: character.file,
            tags: character.tags,
            slug: character.slug,
            ext: character.ext,
            type: character.type,
            voice: character.voice,
            ircNick: character.ircNick,
            sourceUrl: character.sourceUrl,
          })),
        }, origin);
        return;
      }
      if (!authorized(req)) {
        sendJson(res, 401, { ok: false, error: 'unauthorized' }, origin);
        return;
      }
      if (req.method === 'POST' && url.pathname === '/sync') {
        await refreshCache();
        sendJson(res, 200, { ok: true, characters: state.characters.length, worlds: state.worlds.length }, origin);
        return;
      }
      if (req.method === 'POST' && url.pathname === '/send') {
        const body = await readBody(req);
        const character = findCharacter(body.character || '');
        const text = trimText(body.text, 900);
        if (!character || !text) {
          sendJson(res, 400, { ok: false, error: 'character and text are required' }, origin);
          return;
        }
        ircSay(`${character.name}/ST: ${text}`);
        recordIrc(`${character.name}/ST`, text);
        sendJson(res, 200, { ok: true }, origin);
        return;
      }
      if (req.method === 'POST' && url.pathname === '/ask') {
        const body = await readBody(req);
        const character = findCharacter(body.character || '');
        const text = trimText(body.text, 900);
        if (!character || !text) {
          sendJson(res, 400, { ok: false, error: 'character and text are required' }, origin);
          return;
        }
        const reply = await handleBridgeRequest(character, 'SillyTavern', text);
        sendJson(res, 200, { ok: true, reply }, origin);
        return;
      }
      sendJson(res, 404, { ok: false, error: 'not found' }, origin);
    } catch (error) {
      sendJson(res, 500, { ok: false, error: trimText(error.message, 180) }, origin);
    }
  });

  server.listen(Number(cfg.port) || 8787, cfg.host, () => {
    log(`HTTP bridge listening on ${cfg.host}:${cfg.port}`);
  });
}

async function main() {
  await loadOrCreateConfig();
  await loadOrCreateToken(state.cfg);
  await refreshCache();
  connectIrc();
  startHttp();
}

process.on('SIGINT', () => process.exit(0));
process.on('SIGTERM', () => process.exit(0));

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
