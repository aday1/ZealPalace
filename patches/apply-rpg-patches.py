#!/usr/bin/env python3
"""Apply ZealPalace RPG patches to zealot_rpg.py in repo order."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RPG = ROOT / "zealot_rpg.py"
PATCHES = ROOT / "patches"

for name in ("zealot-rpg-peer-chat.py", "zealot-rpg-terrarium-memory.py"):
    path = PATCHES / name
    if not path.exists():
        print("skip missing", path.name)
        continue
    print("running", name)
    subprocess.check_call([sys.executable, str(path)])

# Default Ollama host: VECTOR (not ZealTower)
text = RPG.read_text(encoding="utf-8")
old = "OLLAMA = os.environ.get('OLLAMA_HOST', 'http://10.13.37.5:11434')"
new = "OLLAMA = os.environ.get('OLLAMA_HOST', 'http://10.13.37.60:11434')"
if old in text:
    text = text.replace(old, new, 1)
    RPG.write_text(text, encoding="utf-8")
    print("ollama default -> VECTOR")

print("done:", RPG)
