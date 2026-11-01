"""Barre du haut (logo, menus, projet, boutons de fenêtre) et navigation du bas (espaces de travail).

La fenêtre n'a pas de cadre Windows : la barre du haut en tient lieu. Le déplacement et le
redimensionnement passent par les fonctions natives (startSystemMove / startSystemResize), ce qui
garde l'ancrage aux bords de l'écran et le double-clic pour agrandir.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QLabel, QMenuBar, QWidget

from remanence.ui import charte
from remanence.ui.composants import bouton_icone, etiquette, poser_icone

HAUTEUR_BARRE = 36


def filet_vertical() -> QWidget:
    f = QWidget()
    f.setFixedSize(1, 16)
    f.setProperty("role", "filet")
    f.setAttribute(Qt.WA_StyledBackground, True)
    return f


class BarreTitre(QWidget):
    """Une seule ligne, tout centré verticalement sur 36 px : logo, menus, projet, fenêtre."""

    def __init__(self, fenetre):
        super().__init__()
        self.fenetre = fenetre
        self.setProperty("role", "barre-haut")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(HAUTEUR_BARRE)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 0, 0)
        lay.setSpacing(0)
        self.symbole = QLabel()
        self.symbole.setAccessibleName("Remanence")
        self.symbole.setFixedWidth(26)
        self.nom = etiquette("Remanence")
        self.nom.setStyleSheet("font-weight: 600;")
        self.menus = QMenuBar()
        self.menus.setNativeMenuBar(False)
        lay.addWidget(self.symbole, 0, Qt.AlignVCenter)
        lay.addWidget(self.nom, 0, Qt.AlignVCenter)
        lay.addSpacing(14)
        lay.addWidget(self.menus, 0, Qt.AlignVCenter)
        lay.addStretch(1)

        self.projet = etiquette("", "info")
        self.projet.setTextFormat(Qt.RichText)
        self.format = etiquette("", "info-valeur")
        self.cadence = etiquette("", "info-valeur")
        for i, w in enumerate((self.projet, self.format, self.cadence)):
            if i:
                lay.addSpacing(12)
                lay.addWidget(filet_vertical(), 0, Qt.AlignVCenter)
                lay.addSpacing(12)
            lay.addWidget(w, 0, Qt.AlignVCenter)
        lay.addSpacing(16)

        self.b_reduire = bouton_icone("minus", "Réduire la fenêtre", variante="fenetre")
        self.b_agrandir = bouton_icone("square", "Agrandir la fenêtre", variante="fenetre",
                                       taille=14)
        self.b_fermer = bouton_icone("x", "Fermer Remanence", variante="fenetre-fermer")
        self.b_reduire.clicked.connect(fenetre.showMinimized)
        self.b_agrandir.clicked.connect(self.basculer_agrandissement)
        self.b_fermer.clicked.connect(fenetre.close)
        for b in (self.b_reduire, self.b_agrandir, self.b_fermer):
            b.setFocusPolicy(Qt.NoFocus)
            lay.addWidget(b, 0, Qt.AlignVCenter)
        self.appliquer_charte()

    def appliquer_charte(self):
        self.symbole.setPixmap(charte.actuelle().symbole(18))

    def afficher_projet(self, nom: str, modifie: bool, largeur: int, hauteur: int, cadence: str):
        c = charte.actuelle()
        etat = f' <span style="color:{c.hex("ink-muted")}">· modifié</span>' if modifie else ""
        self.projet.setText(f'Projet : <span style="color:{c.hex("ink")}">{nom}</span>{etat}')
        self.format.setText(f"{largeur} × {hauteur}")
        self.cadence.setText(f"{cadence} i/s")

    def basculer_agrandissement(self):
        if self.fenetre.isMaximized():
            self.fenetre.showNormal()
        else:
            self.fenetre.showMaximized()

    def etat_fenetre(self, agrandie: bool):
        poser_icone(self.b_agrandir, "copy" if agrandie else "square", 14)
        aide = "Restaurer la fenêtre" if agrandie else "Agrandir la fenêtre"
        self.b_agrandir.setToolTip(aide)
        self.b_agrandir.setAccessibleName(aide)

    # Une zone vide de la barre sert de poignée, comme une barre de titre Windows.

    def _zone_libre(self, pos) -> bool:
        enfant = self.childAt(pos)
        return enfant is None or enfant in (self.nom, self.symbole, self.projet, self.format,
                                            self.cadence)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self._zone_libre(e.position().toPoint()):
            self.fenetre.windowHandle().startSystemMove()
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton and self._zone_libre(e.position().toPoint()):
            self.basculer_agrandissement()


ESPACES = [("media", "Média", "folder", "Média (Maj+1)"),
           ("montage", "Montage", "clapperboard", "Montage (Maj+2)"),
           ("export", "Export", "upload", "Export (Maj+3)")]


class BarreEspaces(QWidget):
    """Navigation du bas, 36 px : espaces de travail centrés, messages à gauche, tâches à droite."""
    espace_choisi = Signal(str)

    def __init__(self, taches: QWidget):
        super().__init__()
        self.setProperty("role", "barre-bas")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(HAUTEUR_BARRE)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(0)
        self.message = etiquette("", "secondaire")
        gauche = QHBoxLayout()
        gauche.addWidget(self.message)
        gauche.addStretch(1)
        lay.addLayout(gauche, 1)
        self.groupe = QButtonGroup(self)
        self.groupe.setExclusive(True)
        self.boutons = {}
        for cle, nom, icone, aide in ESPACES:
            b = bouton_icone(icone, aide, variante="espace", texte=nom, cochable=True, taille=16)
            b.setProperty("espace", cle)
            # Pas de focus clavier : Maj+1, 2, 3 changent d'espace (voir l'info-bulle), et un
            # cadre de focus restait sinon sur le premier bouton.
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, cle=cle: self.espace_choisi.emit(cle))
            self.groupe.addButton(b)
            self.boutons[cle] = b
            lay.addWidget(b)
        droite = QHBoxLayout()
        droite.addStretch(1)
        droite.addWidget(taches)
        lay.addLayout(droite, 1)

    def activer(self, cle: str):
        self.boutons[cle].setChecked(True)
