"""Fabrique les images de l'installateur (Inno Setup) aux couleurs de la charte, dans
build/installateur : le grand panneau des pages d'accueil et de fin (fond de l'application,
symbole de Remanence) et la petite image en haut à droite des autres pages (l'icône de
l'application). En BMP 24 bits, à plusieurs tailles pour les écrans agrandis.

    .venv\\Scripts\\python.exe scripts\\images_installateur.py
"""

import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, QSize, Qt  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

SORTIE = RACINE / "build" / "installateur"
# Tailles d'Inno Setup à 100, 150 et 200 % : grand panneau, petite image.
GRANDES = ((164, 314), (246, 459), (328, 628))
PETITES = (55, 83, 110)


def grande(c, largeur: int, hauteur: int) -> QImage:
    image = QImage(largeur, hauteur, QImage.Format_RGB888)
    image.fill(c.c("bg-app"))
    p = QPainter(image)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    cote = round(largeur * 0.5)
    symbole = c.symbole(cote)
    p.drawPixmap(QRectF((largeur - cote) / 2, hauteur * 0.32, cote, cote), symbole,
                 QRectF(symbole.rect()))
    p.end()
    return image


def petite(c, cote: int) -> QImage:
    image = QImage(cote, cote, QImage.Format_RGB888)
    image.fill(Qt.white)  # le haut des pages de l'assistant est blanc
    p = QPainter(image)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    icone = c.icone_application().pixmap(QSize(cote, cote))
    p.drawPixmap(QRectF(0, 0, cote, cote), icone, QRectF(icone.rect()))
    p.end()
    return image


def main():
    app = QApplication([])  # noqa: F841  (les pixmaps demandent une application Qt)
    from remanence.ui import charte
    charte.charger_polices()
    c = charte.definir("dark")
    SORTIE.mkdir(parents=True, exist_ok=True)
    for l, h in GRANDES:
        grande(c, l, h).save(str(SORTIE / f"panneau_{l}.bmp"), "BMP")
    for cote in PETITES:
        petite(c, cote).save(str(SORTIE / f"icone_{cote}.bmp"), "BMP")
    print(f"Images de l'installateur : {SORTIE}")


if __name__ == "__main__":
    main()
