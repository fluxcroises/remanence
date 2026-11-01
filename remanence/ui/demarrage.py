"""Écran de démarrage : la carte de la maquette, entourée d'éclats qui jaillissent de ses bords.

Les éclats sont tirés d'une suite pseudo-aléatoire à graine fixe : l'écran est identique
à chaque lancement. Rien ne s'anime : seule la ligne de chargement change.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFont, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from remanence import ANNEE, EDITEUR, __version__
from remanence.ui import charte

LARGEUR, HAUTEUR = 880, 600
CARTE = QRectF(220, 150, 440, 300)


def eclats() -> list[tuple[float, float, float, float, str, float]]:
    """(x, y, largeur, hauteur, token de couleur, opacité), même générateur que la maquette."""
    v = 1234

    def r():
        nonlocal v
        v = (v * 9301 + 49297) % 233280
        return v / 233280

    def choisir(liste):
        return liste[int(r() * len(liste))]

    tons = [("clip-video", 1), ("clip-video", 1), ("clip-transition", 1), ("surface-raised", 1),
            ("ink", 0.9), ("ink", 0.5), ("accent", 1), ("accent-2", 1), ("accent-soft", 1)]
    sortie = []

    def gerbe(n, bord_x, sens, y0, y1, longueur_max):
        for _ in range(n):
            y = round(y0 + r() * (y1 - y0))
            h = choisir([3, 4, 6, 8, 10, 14, 18])
            longueur = round(30 + r() ** 0.7 * longueur_max)
            ton = choisir(tons)
            x = bord_x - longueur + 24 if sens < 0 else bord_x - 24
            sortie.append((x, y, longueur, h, ton[0], ton[1]))
            if r() < 0.55:
                cote = choisir([4, 6, 8])
                ecart = round(6 + r() * 30)
                px = x - ecart - cote if sens < 0 else x + longueur + ecart
                sortie.append((px, y + round(r() * h), cote, cote, ton[0], ton[1]))

    gerbe(34, 220, -1, 140, 460, 200)
    gerbe(16, 660, 1, 130, 260, 190)
    gerbe(14, 660, 1, 330, 470, 170)
    gerbe(8, 440, 1, 120, 150, 120)
    # Profondeur : de petits fragments plus loin et plus pâles, comme projetés par l'éclatement.
    for _ in range(46):
        gauche = r() < 0.6
        x = (220 - 40 - r() ** 0.6 * 200) if gauche else (660 + 20 + r() ** 0.6 * 190)
        y = 120 + r() * 360
        cote = choisir([2, 3, 4, 5])
        ton = choisir(tons)
        sortie.append((x, y, cote, cote, ton[0], 0.35 + r() * 0.4))
    return sortie


class EcranDemarrage(QWidget):
    def __init__(self):
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(LARGEUR, HAUTEUR)
        self.setAccessibleName("Démarrage de Remanence")
        self._message = "Démarrage…"
        self._eclats = eclats()
        ecran = QApplication.primaryScreen().availableGeometry()
        self.move(ecran.center().x() - LARGEUR // 2, ecran.center().y() - HAUTEUR // 2)

    def etape(self, message: str):
        self._message = message
        self.repaint()
        QApplication.processEvents()

    def paintEvent(self, _e):
        c = charte.actuelle()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        for x, y, l, h, ton, opacite in self._eclats:
            p.fillRect(QRectF(x, y, l, h), c.c(ton, opacite))
        # Ombre portée de la carte (shadow-float), en couches de plus en plus larges.
        for i in range(12, 0, -1):
            p.fillRect(CARTE.adjusted(-i, -i + 8, i, i + 8), c.c("bg-app", 0.05))
        p.fillRect(CARTE, c.c("surface"))
        p.setPen(c.c("line"))
        p.drawRect(CARTE.adjusted(0.5, 0.5, -0.5, -0.5))

        g, haut = CARTE.left() + 40, CARTE.top() + 36
        p.drawPixmap(int(g), int(haut), c.symbole(64))
        nom = c.police("display", 40)
        nom.setLetterSpacing(QFont.AbsoluteSpacing, -0.8)
        p.setFont(nom)
        p.setPen(c.c("ink"))
        # Nom centré verticalement sur le symbole de 64 px.
        p.drawText(QRectF(g + 80, haut, 320, 64), Qt.AlignLeft | Qt.AlignVCenter, "Remanence")

        # Bas de la carte : l'étape de chargement, puis copyright et version ; l'éditeur à droite.
        gauche = QRectF(g, CARTE.bottom() - 58, CARTE.width() - 80, 18)
        p.setFont(c.police("label"))
        p.drawText(gauche, Qt.AlignLeft | Qt.AlignVCenter, self._message)
        p.setFont(c.police("body", 11))
        p.drawText(gauche.translated(0, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   f"© {ANNEE} {EDITEUR} · Version {__version__}")
        logo = c.logo_editeur(16)
        milieu = gauche.bottom() + 1
        if logo is not None:
            l = logo.width() / logo.devicePixelRatio()
            p.drawPixmap(int(gauche.right() - l), int(milieu - 8), logo)
        else:
            p.setFont(c.police("label"))
            p.setPen(c.c("ink"))
            p.drawText(QRectF(gauche.left(), milieu - 9, gauche.width(), 18),
                       Qt.AlignRight | Qt.AlignVCenter, EDITEUR)
        p.end()
