# PyInstaller spec for the Windows app. Build with packaging/build.ps1.
from pathlib import Path

ROOT = Path(SPECPATH).parent  # noqa: F821 (SPECPATH is set by PyInstaller)

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    datas=[
        (str(ROOT / "src" / "photoimporter" / "ui" / "icon.png"), "photoimporter/ui"),
        (str(ROOT / "src" / "photoimporter" / "ui" / "fonts"), "photoimporter/ui/fonts"),
    ],
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PhotoImporter",
    icon=str(ROOT / "packaging" / "icon.ico"),
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="PhotoImporter")  # noqa: F821
