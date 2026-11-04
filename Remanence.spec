# Construction de Remanence.exe par PyInstaller (Construire.bat) : un dossier dist\Remanence
# qui contient Remanence.exe et tout ce qu'il lui faut (Python, Qt, FFmpeg, ressources).
#
# Les fichiers lus par l'appli à côté de son code (charte, polices, icônes, aide, scripts)
# gardent leur place relative : remanence\ressources, UI\charte. FFglitch n'est pas inclus : il
# est proposé au premier lancement et s'installe dans dist\Remanence\outils.

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata
from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct,
                                                 StringTable, VarFileInfo, VarStruct,
                                                 VSVersionInfo)

RACINE = SPECPATH  # noqa: F821  (fourni par PyInstaller)


def chemin(*morceaux):
    return os.path.join(RACINE, *morceaux)


def version_remanence():
    espace = {}
    with open(chemin("remanence", "__init__.py"), encoding="utf-8") as f:
        exec(f.read(), espace)
    return espace["__version__"], espace["EDITEUR"]


VERSION, EDITEUR = version_remanence()
nombres = tuple(int(x) for x in VERSION.split(".")) + (0,) * (4 - len(VERSION.split(".")))

datas = [
    (chemin("remanence", "ressources"), os.path.join("remanence", "ressources")),
    (chemin("UI", "charte", "tokens.json"), os.path.join("UI", "charte")),
    (chemin("UI", "charte", "assets", "Logos"), os.path.join("UI", "charte", "assets", "Logos")),
    (chemin("LICENCES.md"), "."),
]
# OpenTimelineIO trouve ses formats (EDL, FCP XML) par les métadonnées des paquets.
for paquet in ("opentimelineio", "otio-cmx3600-adapter", "otio-fcp-adapter"):
    datas += copy_metadata(paquet)
for paquet in ("opentimelineio", "otio_cmx3600_adapter", "otio_fcp_adapter"):
    datas += collect_data_files(paquet)

# Les effets sont chargés par pkgutil (un module par effet) : PyInstaller ne les voit pas
# dans les imports, il faut les lui nommer. Idem pour le contexte OpenGL de moderngl.
hiddenimports = (collect_submodules("remanence") + collect_submodules("glcontext")
                 + collect_submodules("otio_cmx3600_adapter")
                 + collect_submodules("otio_fcp_adapter") + ["mido.backends.rtmidi"])

excludes = ["tkinter", "pytest", "_pytest", "IPython", "matplotlib",
            "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
            "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtCharts", "PySide6.QtMultimedia"]

a = Analysis(  # noqa: F821
    [chemin("scripts", "remanence_exe.py")],
    pathex=[RACINE],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

infos = VSVersionInfo(
    ffi=FixedFileInfo(filevers=nombres, prodvers=nombres),
    kids=[StringFileInfo([StringTable("040C04B0", [
        StringStruct("CompanyName", EDITEUR),
        StringStruct("FileDescription", "Remanence"),
        StringStruct("FileVersion", VERSION),
        StringStruct("ProductName", "Remanence"),
        StringStruct("ProductVersion", VERSION),
        StringStruct("LegalCopyright", f"© 2026 {EDITEUR}"),
        StringStruct("OriginalFilename", "Remanence.exe")])]),
        VarFileInfo([VarStruct("Translation", [0x040C, 1200])])])

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Remanence",
    icon=chemin("remanence", "ressources", "remanence.ico"),
    version=infos,
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Remanence", upx=False)  # noqa: F821
