# Construction de Remanence.exe par PyInstaller (Construire.bat) : un dossier dist\Remanence
# qui contient Remanence.exe et tout ce qu'il lui faut (Python, Qt, FFmpeg, ressources).
#
# Les fichiers lus par l'appli à côté de son code (charte, polices, icônes, aide, scripts)
# gardent leur place relative : remanence\ressources, UI\charte. FFglitch n'est pas inclus : il
# est proposé au premier lancement et s'installe dans dist\Remanence\outils.

import os
import sys

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
    (chemin("NOTES_DE_VERSION.md"), "."),
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


# Ce que Remanence n'utilise pas, retiré du dossier livré : Qt Quick, QML, PDF et clavier virtuel
# (entraînés par des greffons de PySide6), les variantes de PortAudio pour d'autres machines et
# pour ASIO (le SDK ASIO a sa propre licence).
RETIRES = ("Qt6Pdf", "Qt6Qml", "Qt6Quick", "Qt6VirtualKeyboard", "qtvirtualkeyboard",
           "platforminputcontexts", "qpdf", "qmltooling", os.sep + "qml" + os.sep)


def garde(entree):
    nom = entree[0]
    if any(r in nom for r in RETIRES):
        return False
    if "_sounddevice_data" in nom and nom.endswith((".dll", ".dylib")):
        return nom.endswith("libportaudio64bit.dll")
    return True


a.binaries = [e for e in a.binaries if garde(e)]
a.datas = [e for e in a.datas if garde(e)]
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


# Licences à côté de Remanence.exe : LICENCES.md, les textes GNU du projet, et les fichiers de
# licence de chaque paquet livré (tels que les paquets les fournissent).
def copier_licences():
    import importlib.metadata as md
    import shutil
    livre = os.path.join(DISTPATH, "Remanence")  # noqa: F821
    dossier = os.path.join(livre, "licences")
    shutil.rmtree(dossier, ignore_errors=True)
    os.makedirs(dossier)
    shutil.copy(chemin("LICENCES.md"), livre)
    shutil.copy(chemin("NOTES_DE_VERSION.md"), livre)
    ressources = chemin("remanence", "ressources")
    for source in (os.path.join(ressources, "licences"),):
        for nom in os.listdir(source):
            shutil.copy(os.path.join(source, nom), dossier)
    for nom in ("OFL-IBM-Plex.txt",):
        shutil.copy(os.path.join(ressources, "polices", nom), dossier)
    shutil.copy(os.path.join(ressources, "icones", "LICENCE-Lucide.txt"), dossier)
    licence_python = os.path.join(sys.base_prefix, "LICENSE.txt")
    if os.path.exists(licence_python):  # Python et ce qu'il embarque (OpenSSL, libffi…)
        os.makedirs(os.path.join(dossier, "python"), exist_ok=True)
        shutil.copy(licence_python, os.path.join(dossier, "python", "LICENSE.txt"))
    paquets = ("av", "numpy", "moderngl", "glcontext", "sounddevice", "cffi", "pycparser",
               "opencv-contrib-python-headless", "mido", "python-rtmidi", "OpenTimelineIO",
               "otio-cmx3600-adapter", "otio-fcp-adapter", "setuptools", "packaging",
               "pyinstaller", "PySide6", "shiboken6")
    for paquet in paquets:
        distribution = md.distribution(paquet)
        for f in distribution.files or []:
            texte = str(f).upper()
            if (any(k in texte for k in ("LICEN", "COPYING", "NOTICE"))
                    and not texte.endswith((".PY", ".PYC")) and "_VENDOR" not in texte):
                cible = os.path.join(dossier, paquet, os.path.basename(str(f)))
                os.makedirs(os.path.dirname(cible), exist_ok=True)
                shutil.copy(f.locate(), cible)


copier_licences()
