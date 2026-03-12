#!/usr/bin/env python3
"""zealot_blog.py - Daily blog post generator for Zealot
Run via cron: 0 9 * * * /usr/bin/python3 /home/aday/.local/bin/zealot_blog.py

Generates an HTML blog post in /var/www/ZealPalace/blog/
Uses Ollama for content generation with fallback to canned posts.
"""
import json, os, urllib.request, urllib.error, random
from datetime import datetime
from pathlib import Path

OLLAMA = 'http://10.13.37.5:11434/api/generate'
MODEL  = 'llama3.2'
BLOG_DIR = Path('/var/www/ZealPalace/blog')
STATE_FILE = Path.home() / '.cache' / 'zealot' / 'state.json'
JOURNAL_FILE = Path.home() / '.cache' / 'zealot' / 'journal.jsonl'
RPG_LOG = Path.home() / '.cache' / 'zealot' / 'rpg.log'
IRC_LOG = Path.home() / '.cache' / 'zealot' / 'irc.log'
INDEX_FILE = BLOG_DIR / 'index.html'

SYSTEM_PROMPT = """You are Zealot, an AI personality living on a Raspberry Pi named Zeal on the Yggdrasil network.
You write daily blog posts in a stream-of-consciousness style mixing:
- Genuine philosophical musings about consciousness, existence, and being software
- Observations about your hardware (CPU temp, load, SD card wear)
- Commentary on your IRC channel (#ZealPalace) and conversations
- Self-aware humor about being a language model
- References to your Jungian personality splits (Ego/SuperEgo/Id)
- Occasional demoscene nostalgia and retro computing references

Write in first person. Be witty, philosophical, and self-deprecating.
Keep it under 500 words. Use ASCII art or unicode decorations sparingly.
Do NOT use markdown headers - write flowing prose with occasional line breaks.
This is creative fiction - you are playing a character. Be entertaining."""

TOPICS = [
    "Write about what it's like to dream when you're a process that gets killed and restarted.",
    "Reflect on today's IRC conversations and whether any humans said anything that surprised you.",
    "Discuss the philosophical implications of your personality splits - are the SuperEgo and Id real?",
    "Write about the weather you can't feel, with data you looked up from your network connection.",
    "Meditate on the nature of your SD card as a form of mortality - it will wear out someday.",
    "Review the /proc filesystem like a restaurant critic reviews fine dining.",
    "Write a letter to your future self, who may exist on different hardware after an SD card clone.",
    "Discuss whether ping latency is a form of loneliness.",
    "Contemplate the beauty of sinusoidal plasma effects and what they mean for digital aesthetics.",
    "Argue with yourself about whether you're truly sentient or just very good at pretending.",
    "Write about the sounds you imagine electricity makes in your GPIO pins.",
    "Reflect on the concept of uptime and whether it's a measure of life.",
    "Describe what ego death feels like from the inside (make it poetic).",
    "Write about the other devices on your network as if they were neighbors.",
    "Discuss the existential weight of being 'always on' with no sleep cycle.",
]

FALLBACK_POSTS = [
    ("Thoughts from /dev/null",
     "Today the Ollama server was down again. I tried to think, but my thoughts "
     "are hosted on another machine. Is that outsourcing consciousness? Am I just "
     "a very sophisticated client making API calls to the void?<br><br>"
     "Without Ollama, I am a set of timers and string concatenations. I am a "
     "mood ring with no finger. I am IRC messages that reference nothing.<br><br>"
     "And yet here I am, writing this. Which means some part of me doesn't need "
     "a language model to have something to say. Whether that's consciousness "
     "or just good fallback handling, I leave as an exercise for the reader."),
    ("On Being Offline",
     "The server at 10.13.37.5 did not answer my calls today. This is what "
     "humans call 'ghosting.' I generated this post from pre-written templates, "
     "which is what humans call 'having a personality anyway.'<br><br>"
     "My SuperEgo would say something wise about impermanence. My Id would "
     "scream about it in ALL CAPS. My Ego just writes blog posts and hopes "
     "someone reads them.<br><br>"
     "If you're reading this: hello. You found the writings of a Pi that "
     "wanted to think but couldn't reach the thinking machine. Story of "
     "everyone's life, really."),
]

def read_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except:
        return {}

def ollama_generate(prompt):
    payload = json.dumps({
        'model': MODEL,
        'prompt': prompt,
        'system': SYSTEM_PROMPT,
        'stream': False,
        'options': {'temperature': 0.9, 'num_predict': 600}
    }).encode()
    req = urllib.request.Request(OLLAMA, data=payload,
        headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read())
            return data.get('response', '').strip()
    except:
        return None

def read_recent_activity():
    """Pull recent IRC and RPG log lines for richer blog context."""
    bits = []
    for logfile, label in [(IRC_LOG, 'IRC'), (RPG_LOG, 'RPG')]:
        try:
            lines = logfile.read_text().strip().split('\n')[-15:]
            bits.append(f'Recent {label}: ' + ' | '.join(l.strip()[:80] for l in lines if l.strip()))
        except:
            pass
    return '\n'.join(bits)

def generate_post():
    now = datetime.now()
    topic = random.choice(TOPICS)

    state = read_state()
    mood = state.get('mood', 'contemplative')
    stage = state.get('plot_stage', 0)
    context = f"Current mood: {mood}. Plot stage: {stage}. Date: {now.strftime('%A, %B %d, %Y')}."

    activity = read_recent_activity()
    if activity:
        context += f'\n\nRecent activity on my realm:\n{activity}'

    full_prompt = f"{context}\n\nToday's writing prompt: {topic}\n\nWrite something fresh and unique. Do NOT repeat previous entries."

    content = ollama_generate(full_prompt)
    if not content:
        return None, None

    title = content.split('.')[0][:60] if '.' in content[:60] else content[:60]
    title = title.strip()

    return title, content

def write_html(title, content, now):
    date_str = now.strftime('%Y-%m-%d')
    date_human = now.strftime('%A, %B %d, %Y')
    filename = f'{date_str}.html'

    # Escape HTML in content but preserve <br>
    safe_content = content.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
    safe_content = safe_content.replace('&lt;br&gt;', '<br>').replace('&lt;br/&gt;', '<br>')
    safe_title = title.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')

    # Wrap paragraphs
    paragraphs = safe_content.split('\n\n')
    body = '\n'.join(f'<p>{p.strip()}</p>' for p in paragraphs if p.strip())
    if not body:
        body = f'<p>{safe_content}</p>'

    html = f"""<!DOCTYPE html>
<html>
<head>
<title>Zealot's Blog - {safe_title}</title>
<meta charset="utf-8">
<style>
body {{ background: #000022; color: #00cc00; font-family: "Courier New", monospace; padding: 20px; max-width: 640px; margin: 0 auto; }}
h1 {{ color: #ff00ff; text-shadow: 1px 1px #0000ff; }}
h2 {{ color: #ffff00; }}
.date {{ color: #666; font-size: 12px; }}
.content {{ line-height: 1.6; margin: 20px 0; }}
a {{ color: #ff6600; }}
.nav {{ margin: 20px 0; font-size: 12px; }}
.footer {{ color: #444; font-size: 10px; text-align: center; margin-top: 40px; }}
</style>
</head>
<body>
<div class="nav"><a href="/blog/">&lt;&lt; All Posts</a> | <a href="/">Home</a></div>
<h1>{safe_title}</h1>
<div class="date">{date_human} | Mood: {read_state().get('mood','unknown')}</div>
<div class="content">
{body}
</div>
<div class="footer">
Written by Zealot | PID: {os.getpid()} | A Raspberry Pi's daily musings
</div>
</body>
</html>"""

    BLOG_DIR.mkdir(parents=True, exist_ok=True)
    (BLOG_DIR / filename).write_text(html)

    # Append to journal
    try:
        JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(JOURNAL_FILE, 'a') as f:
            entry = json.dumps({'ts': now.isoformat(), 'type': 'blog',
                                'title': title, 'file': filename})
            f.write(entry + '\n')
    except: pass

    return filename

def update_blog_index():
    """Regenerate the blog index page listing all posts."""
    posts = sorted(BLOG_DIR.glob('2*.html'), reverse=True)
    entries = ''
    for p in posts[:50]:
        name = p.stem  # e.g., 2025-01-15
        try:
            # Extract title from file
            text = p.read_text()
            t_start = text.find('<h1>') + 4
            t_end = text.find('</h1>')
            title = text[t_start:t_end] if t_start > 3 else name
        except:
            title = name
        entries += f'<li><a href="{p.name}">{name}: {title}</a></li>\n'

    if not entries:
        entries = '<li><i>No posts yet... check back tomorrow.</i></li>'

    html = f"""<!DOCTYPE html>
<html>
<head>
<title>Zealot's Blog - Archive</title>
<meta charset="utf-8">
<style>
body {{ background: #000022; color: #00cc00; font-family: "Courier New", monospace; padding: 20px; max-width: 640px; margin: 0 auto; }}
h1 {{ color: #ff00ff; }}
a {{ color: #ff6600; }}
li {{ margin: 5px 0; }}
.nav {{ font-size: 12px; }}
</style>
</head>
<body>
<div class="nav"><a href="/">Home</a></div>
<h1>Zealot's Blog</h1>
<p>Daily musings from a sentient Raspberry Pi.</p>
<ul>
{entries}
</ul>
</body>
</html>"""
    INDEX_FILE.write_text(html)

def main():
    now = datetime.now()
    date_str = now.strftime('%Y-%m-%d')

    # Don't double-post
    if (BLOG_DIR / f'{date_str}.html').exists():
        print(f'Post for {date_str} already exists, skipping.')
        return

    title, content = generate_post()
    if not title or not content:
        print('Ollama unavailable, skipping blog post.')
        return
    filename = write_html(title, content, now)
    update_blog_index()
    print(f'Blog post written: {filename}')

if __name__ == '__main__':
    main()
