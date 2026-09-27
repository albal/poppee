"""Render the application icon into .ico / .icns / .png for PyInstaller."""

import sys
from pathlib import Path

from poppee.icon import render_icon

out = Path(sys.argv[1] if len(sys.argv) > 1 else "build/icons")
out.mkdir(parents=True, exist_ok=True)
img = render_icon(0, size=512)
img.save(out / "poppee.png")
img.save(out / "poppee.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)])
img.save(out / "poppee.icns")
print(f"icons written to {out}")
