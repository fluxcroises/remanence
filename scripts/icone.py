"""Fabrique remanence/ressources/remanence.ico, l'icône du programme Windows, depuis l'icône
de l'application (le symbole sur fond arrondi, `charte.icone_application`).

    .venv\\Scripts\\python.exe scripts\\icone.py

Une icône Windows à plusieurs tailles (16 à 256 px), chacune en PNG dans le fichier .ico : Qt
n'écrit qu'une taille par fichier, l'en-tête est donc écrit ici.
"""

import os
import struct
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

TAILLES = (16, 24, 32, 48, 64, 128, 256)
SORTIE = RACINE / "remanence" / "ressources" / "remanence.ico"


def png(icone, taille: int) -> bytes:
    image = icone.pixmap(QSize(taille, taille)).toImage().scaled(taille, taille)
    tampon = QByteArray()
    flux = QBuffer(tampon)
    flux.open(QIODevice.WriteOnly)
    image.save(flux, "PNG")
    return bytes(tampon.data())


def main():
    app = QApplication([])  # noqa: F841  (les pixmaps demandent une application Qt)
    from remanence.ui import charte
    icone = charte.actuelle().icone_application()
    images = [png(icone, t) for t in TAILLES]
    entete = struct.pack("<HHH", 0, 1, len(images))
    position = 6 + 16 * len(images)
    entrees = b""
    for taille, donnees in zip(TAILLES, images):
        cote = 0 if taille >= 256 else taille  # 0 veut dire 256 dans le format ICO
        entrees += struct.pack("<BBBBHHII", cote, cote, 0, 0, 1, 32, len(donnees), position)
        position += len(donnees)
    SORTIE.write_bytes(entete + entrees + b"".join(images))
    print(f"{SORTIE.name} : {len(images)} tailles, {SORTIE.stat().st_size} octets")


if __name__ == "__main__":
    main()
