"""Titres simples : un texte en IBM Plex, dessiné par Qt sur une image transparente de la taille
de la séquence, puis posé comme une couche (effets, fondus et modes de fusion compris).

La taille du texte est une part de la hauteur de l'image et sa position une part de la largeur
et de la hauteur : l'aperçu en demi-résolution et l'export se ressemblent. Rendu en 16 bits
par canal, alpha prémultiplié, gardé en mémoire pour les images suivantes.
"""

from __future__ import annotations

import json
from functools import lru_cache

import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter

POLICES = {"sans": "IBM Plex Sans", "mono": "IBM Plex Mono"}
GRAISSES = {300: "Léger", 400: "Normal", 600: "Demi-gras", 700: "Gras"}
ALIGNEMENTS = {"gauche": "À gauche", "centre": "Au centre", "droite": "À droite"}
POIDS_QT = {300: QFont.Light, 400: QFont.Normal, 600: QFont.DemiBold, 700: QFont.Bold}


def nouveau_titre(texte: str = "Titre") -> dict:
    return {"texte": texte, "police": "sans", "graisse": 600, "taille": 10.0, "x": 50.0,
            "y": 50.0, "alignement": "centre", "couleur": [1.0, 1.0, 1.0]}


def rendre(titre: dict, largeur: int, hauteur: int) -> np.ndarray:
    """Le titre sur fond transparent : H × L × 4 float32, alpha prémultiplié."""
    return _rendre(json.dumps(titre, sort_keys=True), largeur, hauteur)


@lru_cache(maxsize=16)
def _rendre(cle: str, largeur: int, hauteur: int) -> np.ndarray:
    t = {**nouveau_titre(), **json.loads(cle)}
    image = QImage(largeur, hauteur, QImage.Format_RGBA64_Premultiplied)
    image.fill(Qt.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    police = QFont(POLICES.get(t["police"], POLICES["sans"]))
    police.setPixelSize(max(1, round(t["taille"] / 100 * hauteur)))
    police.setWeight(POIDS_QT.get(int(t["graisse"]), QFont.DemiBold))
    p.setFont(police)
    r, v, b = (max(0.0, min(1.0, float(x))) for x in t["couleur"])
    couleur = QColor()
    couleur.setRgbF(r, v, b, 1.0)
    p.setPen(couleur)
    lignes = str(t["texte"]).split("\n")
    mesure = QFontMetricsF(police)
    pas = mesure.lineSpacing()
    largeur_texte = max((mesure.horizontalAdvance(ligne) for ligne in lignes), default=0.0)
    haut = pas * len(lignes)
    x = t["x"] / 100 * largeur
    y = t["y"] / 100 * hauteur - haut / 2
    alignement = t["alignement"]
    gauche = x if alignement == "gauche" else x - largeur_texte if alignement == "droite" \
        else x - largeur_texte / 2
    drapeau = {"gauche": Qt.AlignLeft, "droite": Qt.AlignRight}.get(alignement, Qt.AlignHCenter)
    for i, ligne in enumerate(lignes):
        p.drawText(QRectF(gauche, y + i * pas, largeur_texte, pas), drapeau | Qt.AlignVCenter,
                   ligne)
    p.end()
    brut = np.frombuffer(image.constBits(), np.uint16)
    pixels = brut.reshape(hauteur, image.bytesPerLine() // 8, 4)[:, :largeur]
    return (pixels.astype(np.float32) / 65535.0).copy()
