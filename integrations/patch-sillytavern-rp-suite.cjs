const fs = require('fs');

const target = process.argv[2];
if (!target) {
  console.error('usage: node patch-sillytavern-rp-suite.cjs /path/to/index.js');
  process.exit(2);
}

let text = fs.readFileSync(target, 'utf8');

const marker = 'zealpalace-irc-bridge-v1';
if (text.includes(marker)) {
  console.log('bridge UI patch already present');
  process.exit(0);
}

const helper = `

// ${marker}
const BRIDGE_URL_KEY = 'zealpalaceBridgeUrl';
const BRIDGE_TOKEN_KEY = 'zealpalaceBridgeToken';

function bridgeBaseUrl() {
    return localStorage.getItem(BRIDGE_URL_KEY) || 'http://100.91.133.101:8787';
}

function bridgeToken() {
    return localStorage.getItem(BRIDGE_TOKEN_KEY) || '';
}

function setBridgeToken() {
    const token = prompt('ZealPalace bridge token');
    if (token) {
        localStorage.setItem(BRIDGE_TOKEN_KEY, token.trim());
        globalThis.toastr?.success?.('ZealPalace bridge token saved locally.');
    }
}

async function bridgeFetch(path, body = null, auth = true) {
    const headers = { 'Content-Type': 'application/json' };
    if (auth && bridgeToken()) headers.Authorization = \`Bearer \${bridgeToken()}\`;
    const response = await fetch(\`\${bridgeBaseUrl()}\${path}\`, {
        method: body ? 'POST' : 'GET',
        headers,
        body: body ? JSON.stringify(body) : undefined,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) {
        throw new Error(data.error || \`Bridge HTTP \${response.status}\`);
    }
    return data;
}

async function bridgeStatus() {
    try {
        const data = await bridgeFetch('/health', null, false);
        globalThis.toastr?.info?.(\`Zeal bridge: IRC \${data.ircReady ? 'online' : 'offline'}, \${data.characters} chars, \${data.worlds} lore entries.\`);
    } catch (error) {
        globalThis.toastr?.error?.(\`Zeal bridge unavailable: \${error.message}\`);
    }
}

async function bridgeSync() {
    try {
        const data = await bridgeFetch('/sync', {});
        globalThis.toastr?.success?.(\`Synced \${data.characters} characters and \${data.worlds} lore entries.\`);
    } catch (error) {
        globalThis.toastr?.error?.(\`Bridge sync failed: \${error.message}\`);
    }
}

function currentComposerText() {
    const input =
        document.querySelector('#send_textarea') ||
        document.querySelector('#send_textarea textarea') ||
        document.querySelector('textarea');
    return input?.value?.trim() || '';
}

async function bridgeSendCurrent({ ask = false } = {}) {
    const character = getCharName();
    const text = currentComposerText() || prompt(\`Text to send as \${character} into ZealPalace #RPG\`);
    if (!text) return;
    try {
        const data = await bridgeFetch(ask ? '/ask' : '/send', { character, text });
        if (data.reply) putInComposer(data.reply, true);
        globalThis.toastr?.success?.(\`\${character} sent to ZealPalace #RPG.\`);
    } catch (error) {
        globalThis.toastr?.error?.(\`ZealPalace bridge send failed: \${error.message}\`);
    }
}
`;

text = text.replace('\nfunction pick(list) {', `${helper}\nfunction pick(list) {`);

text = text.replace(
  "makeButton('Stage Glow', 'Toggle the ZealPalace visual chrome.', () => document.body.classList.toggle('zealpalace-theme-active')),",
  [
    "makeButton('Stage Glow', 'Toggle the ZealPalace visual chrome.', () => document.body.classList.toggle('zealpalace-theme-active')),",
    "        makeButton('IRC Status', 'Check the ZealPalace IRC bridge.', () => bridgeStatus()),",
    "        makeButton('IRC Sync', 'Refresh bridge character and lore cache.', () => bridgeSync()),",
    "        makeButton('IRC Send', 'Send composer text as this character into #RPG.', () => bridgeSendCurrent({ ask: false })),",
    "        makeButton('IRC Ask', 'Ask this character to answer in #RPG via the bridge model.', () => bridgeSendCurrent({ ask: true })),",
    "        makeButton('IRC Token', 'Save the bridge token locally in this browser.', () => setBridgeToken()),",
  ].join('\n')
);

text = text.replace(
  "SlashCommandParser.addCommandObject(SlashCommand.fromProps({\n        name: 'zeal-cosplay',",
  `SlashCommandParser.addCommandObject(SlashCommand.fromProps({
        name: 'zeal-rpg-status',
        callback: () => {
            bridgeStatus();
            return 'Checking ZealPalace IRC bridge status...';
        },
        returns: ARGUMENT_TYPE.STRING,
        helpString: 'Checks the ZealPalace IRC bridge.',
    }));

    SlashCommandParser.addCommandObject(SlashCommand.fromProps({
        name: 'zeal-rpg-sync',
        callback: () => {
            bridgeSync();
            return 'Syncing ZealPalace IRC bridge lore and characters...';
        },
        returns: ARGUMENT_TYPE.STRING,
        helpString: 'Refreshes the ZealPalace IRC bridge cache.',
    }));

    SlashCommandParser.addCommandObject(SlashCommand.fromProps({
        name: 'zeal-rpg-send',
        callback: () => {
            bridgeSendCurrent({ ask: false });
            return 'Sending current composer text into ZealPalace #RPG...';
        },
        returns: ARGUMENT_TYPE.STRING,
        helpString: 'Sends current composer text as the active character into ZealPalace #RPG.',
    }));

    SlashCommandParser.addCommandObject(SlashCommand.fromProps({
        name: 'zeal-rpg-ask',
        callback: () => {
            bridgeSendCurrent({ ask: true });
            return 'Asking active character to speak in ZealPalace #RPG...';
        },
        returns: ARGUMENT_TYPE.STRING,
        helpString: 'Asks the active character to answer in ZealPalace #RPG through the bridge.',
    }));

    SlashCommandParser.addCommandObject(SlashCommand.fromProps({
        name: 'zeal-cosplay',`
);

fs.writeFileSync(target, text);
console.log('patched ZealPalace RP Suite bridge controls');
