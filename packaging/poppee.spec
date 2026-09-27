# -*- mode: python -*-
# PyInstaller spec: `pyinstaller packaging/poppee.spec` (run `python packaging/make_icons.py` first).
#
#   Windows: dist/poppee/{poppee.exe (console CLI), poppee-tray.exe (no console)}
#   macOS:   dist/Poppee.app (menu-bar only app, no Dock icon)
#   Linux:   dist/poppee/poppee
import re
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
VERSION = re.search(
    r'__version__ = "([^"]+)"', (ROOT / "src" / "poppee" / "__init__.py").read_text()
).group(1)
ICONS = ROOT / "build" / "icons"

if sys.platform == "win32":
    hidden, icon = ["pystray._win32"], ICONS / "poppee.ico"
elif sys.platform == "darwin":
    hidden, icon = ["pystray._darwin"], ICONS / "poppee.icns"
else:
    hidden, icon = ["pystray._xorg", "pystray._appindicator", "pystray._gtk"], None
icon = str(icon) if icon and icon.exists() else None

a = Analysis(
    [str(ROOT / "packaging" / "poppee_entry.py")],
    pathex=[str(ROOT / "src")],
    hiddenimports=hidden,
    excludes=["pytest", "IPython"],
)
pyz = PYZ(a.pure)


def make_exe(name, console):
    return EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=name,
        console=console,
        icon=icon,
        upx=False,
    )


if sys.platform == "darwin":
    exe = make_exe("Poppee", console=False)
    coll = COLLECT(exe, a.binaries, a.datas, name="Poppee", upx=False)
    app = BUNDLE(
        coll,
        name="Poppee.app",
        icon=icon,
        bundle_identifier="io.github.poppee",
        version=VERSION,
        info_plist={
            "CFBundleShortVersionString": VERSION,
            "LSUIElement": True,
            "NSHighResolutionCapable": True,
        },
    )
elif sys.platform == "win32":
    cli = make_exe("poppee", console=True)
    gui = make_exe("poppee-tray", console=False)
    coll = COLLECT(cli, gui, a.binaries, a.datas, name="poppee", upx=False)
else:
    cli = make_exe("poppee", console=True)
    coll = COLLECT(cli, a.binaries, a.datas, name="poppee", upx=False)
