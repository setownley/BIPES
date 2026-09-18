"""Static checks for the BIPES Games toolbox and embedded Frogger source."""

import json
from pathlib import Path


root = Path(__file__).resolve().parents[2]
source = (root / "ui" / "core" / "games.js").read_text(encoding="utf-8")

menu_line = next(line for line in source.splitlines() if "var gameBlocks =" in line)
assert "play_invaders_standalone" in menu_line
assert "play_snake_standalone" in menu_line
assert "play_defender_standalone" in menu_line
assert "play_frogger_standalone" in menu_line
assert "'play_invaders'," not in menu_line
assert "'play_snake'," not in menu_line
assert "'play_defender'," not in menu_line

assert "var retiredGameBlocks = ['play_invaders', 'play_snake', 'play_defender'];" in source
assert "oldBlocks[ob].parentNode.removeChild(oldBlocks[ob]);" in source
assert "appendField('Frogger')" in source
assert 'media/frogger.svg' in source

start = source.index("    var FROGGER_SRC = [")
start = source.index("\n", start) + 1
end = source.index("    ].join('\\n');", start)
frogger_lines = []
for line in source[start:end].splitlines():
    encoded = line.strip()
    if encoded.endswith(","):
        encoded = encoded[:-1]
    frogger_lines.append(json.loads(encoded))

frogger_source = "\n".join(frogger_lines)
compile(frogger_source, "frogger-generated.py", "exec")
assert frogger_source.startswith("def _play_frogger(")
assert "Game(oled, btn, x0, y0, led).run()" in frogger_source

print("ALL PASS")
