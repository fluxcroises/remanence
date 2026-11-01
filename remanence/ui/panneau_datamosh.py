"""Espace Datamosh : la structure de compression du clip choisi, et ses vecteurs de mouvement
posés sur l'image du programme."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from remanence.moteurs.codec.analyse import Analyse
from remanence.ui import charte
from remanence.ui.composants import bouton_icone, etiquette


class BandeImages(QWidget):
    """Une barre par image du clip, haute comme son poids compressé : images clés en mauve
    plein, images P en gris ; une image clé supprimée n'a que son contour."""
    image_cliquee = Signal(int)
    cle_basculee = Signal(int)

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(64)
        self.setMouseTracking(True)
        self.analyse: Analyse | None = None
        self.supprimees: set[int] = set()
        self.tete: int | None = None

    def _largeur(self) -> float:
        return self.width() / max(1, len(self.analyse.tailles)) if self.analyse else 1.0

    def paintEvent(self, _e):
        c = charte.actuelle()
        p = QPainter(self)
        p.fillRect(self.rect(), c.c("viewer-bg"))
        if self.analyse is None:
            p.end()
            return
        tailles = np.asarray(self.analyse.tailles, np.float64)
        haut = max(1.0, float(np.percentile(tailles, 99)))
        w = self._largeur()
        h = self.height() - 4
        ecart = 1 if w >= 4 else 0
        for t, (genre, taille) in enumerate(zip(self.analyse.types, tailles)):
            barre = max(2.0, min(1.0, taille / haut) * h)
            r = QRectF(t * w, self.height() - barre, max(1.0, w - ecart), barre)
            if genre == "I" and t in self.supprimees:
                p.setPen(QPen(c.c("accent"), 1))
                p.setBrush(Qt.NoBrush)
                p.drawRect(r.adjusted(0.5, 0.5, -0.5, -0.5))
            else:
                p.fillRect(r, c.c("accent" if genre == "I" else "ink-muted"))
        if self.tete is not None and 0 <= self.tete < len(tailles):
            x = (self.tete + 0.5) * w
            p.setPen(QPen(c.c("playhead"), 1))
            p.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        p.end()

    def _image_a(self, x: float) -> int | None:
        if self.analyse is None:
            return None
        t = int(x / self._largeur())
        return t if 0 <= t < len(self.analyse.tailles) else None

    def mousePressEvent(self, e):
        t = self._image_a(e.position().x())
        if t is not None and e.button() == Qt.LeftButton:
            self.image_cliquee.emit(t)

    def mouseDoubleClickEvent(self, e):
        t = self._image_a(e.position().x())
        if t is not None and self.analyse.types[t] == "I":
            self.cle_basculee.emit(t)

    def mouseMoveEvent(self, e):
        t = self._image_a(e.position().x())
        if t is None:
            self.setToolTip("")
            return
        genre = self.analyse.types[t]
        ko = self.analyse.tailles[t] / 1024
        etat = " supprimée" if genre == "I" and t in self.supprimees else ""
        self.setToolTip(f"Image {t} · {genre}{etat} · {ko:.1f} ko".replace(".", ","))


class PanneauDatamosh(QWidget):
    """Structure de compression du clip choisi."""
    image_cliquee = Signal(int)       # image depuis le début du clip
    cle_basculee = Signal(int)        # double-clic sur une image clé
    vecteurs_bascules = Signal(bool)

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 10)
        lay.setSpacing(6)
        haut = QHBoxLayout()
        haut.setSpacing(8)
        self.titre = etiquette("", "libelle")
        self.infos = etiquette("", "valeur")
        self.bouton_vecteurs = bouton_icone("move", "Vecteurs de mouvement sur le programme",
                                            cochable=True, taille=16)
        self.bouton_vecteurs.toggled.connect(self.vecteurs_bascules)
        haut.addWidget(self.titre)
        haut.addStretch(1)
        haut.addWidget(self.infos)
        haut.addWidget(self.bouton_vecteurs)
        lay.addLayout(haut)
        self.bande = BandeImages()
        self.bande.image_cliquee.connect(self.image_cliquee)
        self.bande.cle_basculee.connect(self.cle_basculee)
        lay.addWidget(self.bande, 1)
        self.afficher(None, None)

    def afficher(self, nom: str | None, analyse: Analyse | None, supprimees=(),
                 en_cours: bool = False):
        self.bande.analyse = analyse
        self.bande.supprimees = set(supprimees)
        if nom is None:
            self.titre.setText("Aucun clip vidéo sélectionné")
            self.infos.setText("")
        elif analyse is None:
            self.titre.setText(nom)
            self.infos.setText("Analyse…" if en_cours else "")
        else:
            self.titre.setText(nom)
            n_i = analyse.types.count("I")
            n_s = len([t for t in self.bande.supprimees if analyse.types[t:t + 1] == ["I"]])
            texte = f"{len(analyse.types)} images · I : {n_i}"
            if n_s:
                texte += f" (dont {n_s} supprimée{'s' if n_s > 1 else ''})"
            texte += f" · P : {analyse.types.count('P')} · {analyse.moteur}"
            self.infos.setText(texte)
        self.bande.update()

    def suivre(self, t: int | None):
        self.bande.tete = t
        self.bande.update()


class CalqueVecteurs(QWidget):
    """Vecteurs de mouvement de l'image en cours, posés sur le programme. Laisse passer la
    souris."""

    def __init__(self, zone):
        super().__init__(zone)
        self.zone = zone
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.vecteurs: np.ndarray | None = None
        # Place du média dans l'image de la séquence, en fractions : x, y, largeur, hauteur.
        self.cadre = (0.0, 0.0, 1.0, 1.0)
        self.taille_media = (1, 1)
        self.hide()

    def montrer(self, vecteurs: np.ndarray | None, taille_media=(1, 1), cadre=(0, 0, 1, 1)):
        self.vecteurs = vecteurs
        self.taille_media = taille_media
        self.cadre = cadre
        self.setGeometry(self.zone.rect())
        self.setVisible(vecteurs is not None)
        self.raise_()
        self.update()

    def paintEvent(self, _e):
        if self.vecteurs is None or not len(self.vecteurs) or self.zone._image is None:
            return
        r = self.zone._rect_image(self.zone.width(), self.zone.height())
        cx, cy, cw, ch = self.cadre
        lm, hm = self.taille_media
        sx, sy = r.width() * cw / lm, r.height() * ch / hm
        ox, oy = r.x() + r.width() * cx, r.y() + r.height() * cy
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        couleur = charte.actuelle().c("focus")
        p.setPen(QPen(couleur, 1))
        lignes = self.vecteurs
        if len(lignes) > 6000:  # au-delà, l'image devient illisible
            lignes = lignes[:: len(lignes) // 6000 + 1]
        for x, y, dx, dy in lignes:
            a = QPointF(ox + (x - dx) * sx, oy + (y - dy) * sy)
            b = QPointF(ox + x * sx, oy + y * sy)
            p.drawLine(a, b)
            p.drawEllipse(b, 1.2, 1.2)
        p.end()
