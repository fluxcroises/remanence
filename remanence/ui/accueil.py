"""Écran d'accueil, ouvert au lancement, sur le modèle de celui de Vegas Pro : nouveau projet,
projets récents, prise en main.

Les fiches de prise en main sont des fichiers Markdown de `remanence/ressources/aide`, avec
leurs captures. Les textes détaillés vivent là, pas dans l'interface. Le bandeau est une image
datamoshée par Remanence (`scripts/captures_aide.py` la refait).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPainter
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog,
                               QGridLayout, QHBoxLayout, QHeaderView, QLabel, QPushButton,
                               QScrollArea, QSizePolicy, QStackedWidget,
                               QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from remanence.config import reglages_interface
from remanence.ui import charte
from remanence.ui.charte import pixmap_icone
from remanence.ui.aide import FenetreAide, fiches
from remanence.ui.composants import bouton_icone, etiquette

RESSOURCES = Path(__file__).resolve().parents[1] / "ressources"
BANDEAU = RESSOURCES / "accueil" / "bandeau.png"

# Format -> (nom affiché, icône, résolutions proposées : la première par défaut).
FORMATS = {
    "16:9": ("Écran large (16:9)", "monitor",
             [("Full HD", 1920, 1080), ("4K UHD", 3840, 2160), ("QHD", 2560, 1440),
              ("HD", 1280, 720)]),
    "4:3": ("Plein écran (4:3)", "tv-minimal",
            [("HDV", 1440, 1080), ("XGA", 1024, 768), ("SD", 640, 480)]),
    "9:16": ("Portrait (9:16)", "smartphone",
             [("Full HD", 1080, 1920), ("HD", 720, 1280)]),
    "1:1": ("Carré (1:1)", "square", [("Full HD", 1080, 1080), ("4K", 2160, 2160)]),
    "2.39:1": ("Scope (2,39:1)", "rectangle-horizontal",
               [("Full HD", 1920, 804), ("4K UHD", 3840, 1608)]),
}
CADENCES = [("24000/1001", "23,976p"), ("24", "24p"), ("25", "25p"), ("30000/1001", "29,97p"),
            ("30", "30p"), ("50", "50p"), ("60000/1001", "59,94p"), ("60", "60p")]

CLE_RECENTS = "projets_recents_dates"
CLE_AU_DEMARRAGE = "accueil/au_demarrage"
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
        "octobre", "novembre", "décembre"]


def date_longue(instant: float) -> str:
    """« mardi 30 juin 2026 22:53:31 »."""
    t = time.localtime(instant)
    return f"{JOURS[t.tm_wday]} {t.tm_mday} {MOIS[t.tm_mon - 1]} {t.tm_year} " \
           f"{time.strftime('%H:%M:%S', t)}"


def _recents_bruts() -> list[list]:
    try:
        liste = json.loads(reglages_interface().value(CLE_RECENTS, "[]") or "[]")
    except ValueError:
        return []
    return [e for e in liste if isinstance(e, list) and len(e) == 2]


def recents() -> list[tuple[Path, float]]:
    """(projet, dernière ouverture), du plus récent au plus ancien ; les fichiers disparus
    sont oubliés."""
    return [(Path(p), float(t)) for p, t in _recents_bruts() if Path(p).exists()]


def retenir(chemin: Path):
    """Le projet ouvert ou enregistré passe en tête des récents (dix au plus)."""
    chemin = Path(chemin)
    liste = [[str(chemin), time.time()]] + [[str(p), t] for p, t in recents() if p != chemin]
    reglages_interface().setValue(CLE_RECENTS, json.dumps(liste[:10]))


def au_demarrage() -> bool:
    return str(reglages_interface().value(CLE_AU_DEMARRAGE, "true")).lower() == "true"


def icone_tuile(nom: str, taille: int) -> QIcon:
    """Icône d'une tuile : grise au repos, claire au survol, sur le mauve quand choisie."""
    c = charte.actuelle()
    icone = QIcon()
    for mode, etat, couleur in [(QIcon.Normal, QIcon.Off, "ink-muted"),
                                (QIcon.Active, QIcon.Off, "ink"),
                                (QIcon.Normal, QIcon.On, "on-accent"),
                                (QIcon.Active, QIcon.On, "on-accent")]:
        icone.addPixmap(pixmap_icone(nom, c.hex(couleur), taille), mode, etat)
    return icone


def tuile(texte: str, icone: str, variante: str, taille: int = 28) -> QToolButton:
    b = QToolButton()
    b.setProperty("variante", variante)
    b.setText(texte)
    b.setIcon(icone_tuile(icone, taille))
    b.setIconSize(QSize(taille, taille))
    b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
    b.setCheckable(True)
    b.setAccessibleName(texte)
    b.setFocusPolicy(Qt.TabFocus)
    return b


class Image(QWidget):
    """Image qui remplit le cadre en gardant ses proportions (rognée au besoin), assombrie
    si demandé (fond de la prise en main)."""

    def __init__(self, chemin: Path | None, assombrir: float = 0.0, hauteur: int | None = None):
        super().__init__()
        self.image = QImage(str(chemin)) if chemin is not None and chemin.exists() else QImage()
        self.assombrir = assombrir
        if hauteur:
            self.setFixedHeight(hauteur)

    def paintEvent(self, _e):
        p = QPainter(self)
        c = charte.actuelle()
        p.fillRect(self.rect(), c.c("viewer-bg"))
        if not self.image.isNull():
            r = self.rect()
            s = max(r.width() / self.image.width(), r.height() / self.image.height())
            l, h = r.width() / s, r.height() / s
            source = QRectF((self.image.width() - l) / 2, (self.image.height() - h) / 2, l, h)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.drawImage(QRectF(r), self.image, source)
        if self.assombrir:
            p.fillRect(self.rect(), c.c("bg-app", self.assombrir))
        p.end()


class Carte(QWidget):
    """Carte d'une fiche : capture en vignette, titre, « Remanence »."""
    choisie = Signal()

    def __init__(self, titre: str, image: Path | None):
        super().__init__()
        self.setFixedSize(220, 152)
        self.setCursor(Qt.PointingHandCursor)
        self.setProperty("role", "carte-fiche")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAccessibleName(titre)
        self.setFocusPolicy(Qt.TabFocus)
        self.setAttribute(Qt.WA_Hover, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 10)
        lay.setSpacing(2)
        lay.addWidget(Image(image, hauteur=92))
        nom = etiquette(titre, "titre-carte")
        nom.setWordWrap(True)
        for w in (nom, etiquette("Remanence", "secondaire")):
            marge = QHBoxLayout()
            marge.setContentsMargins(10, 0, 10, 0)
            marge.addWidget(w)
            lay.addLayout(marge)
        lay.addStretch(1)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.choisie.emit()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.choisie.emit()
        else:
            super().keyPressEvent(e)


class Accueil(QDialog):
    """resultat : ("nouveau", largeur, hauteur, cadence, tc_une_heure), ("auto",),
    ("ouvrir", chemin) ou None."""

    def __init__(self, parent=None, onglet: str = "nouveau"):
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        # Modale pour la fenêtre principale seulement : la prise en main reste utilisable.
        self.setWindowModality(Qt.WindowModal)
        self.setWindowTitle("Remanence")
        self.setProperty("role", "accueil")
        self.resize(940, 660)
        self.resultat = None
        racine = QVBoxLayout(self)
        racine.setContentsMargins(1, 0, 1, 1)
        racine.setSpacing(0)
        racine.addWidget(self._barre_titre())

        milieu = QHBoxLayout()
        milieu.setContentsMargins(4, 0, 4, 0)
        milieu.setSpacing(4)
        cote = QVBoxLayout()
        cote.setSpacing(4)
        self.pages = QStackedWidget()
        self.pages.setProperty("role", "accueil-page")
        self.pages.setAttribute(Qt.WA_StyledBackground, True)
        self._boutons: dict[str, QToolButton] = {}
        groupe = QButtonGroup(self)
        for i, (cle, nom, icone, page) in enumerate((
                ("nouveau", "Nouveau projet", "file", self._page_nouveau()),
                ("ouvrir", "Ouvrir un projet", "folder", self._page_ouvrir()),
                ("aide", "Prise en main", "graduation-cap", self._page_aide()))):
            b = tuile(nom, icone, "accueil-onglet")
            b.setFixedSize(110, 84)
            b.clicked.connect(lambda _=False, i=i: self.pages.setCurrentIndex(i))
            groupe.addButton(b)
            self._boutons[cle] = b
            cote.addWidget(b)
            self.pages.addWidget(page)
        cote.addStretch(1)
        milieu.addLayout(cote)
        milieu.addWidget(self.pages, 1)
        racine.addLayout(milieu, 1)

        bas = QHBoxLayout()
        bas.setContentsMargins(14, 8, 14, 8)
        self.au_demarrage = QCheckBox("Afficher l'écran d'accueil au démarrage")
        self.au_demarrage.setChecked(au_demarrage())
        self.au_demarrage.toggled.connect(
            lambda v: reglages_interface().setValue(CLE_AU_DEMARRAGE, "true" if v else "false"))
        bas.addWidget(self.au_demarrage)
        bas.addStretch(1)
        racine.addLayout(bas)
        self.choisir(onglet)
        self._creer_bouton.setFocus()

    def _barre_titre(self) -> QWidget:
        barre = QWidget()
        barre.setFixedHeight(48)
        lay = QHBoxLayout(barre)
        lay.setContentsMargins(48, 0, 4, 0)
        lay.addStretch(1)
        symbole = QLabel()
        symbole.setPixmap(charte.actuelle().symbole(26))
        symbole.setAccessibleName("Remanence")
        lay.addWidget(symbole)
        lay.addSpacing(8)
        lay.addWidget(etiquette("Remanence", "titre-accueil"))
        lay.addStretch(1)
        fermer = bouton_icone("x", "Fermer (Échap)", variante="fenetre-fermer")
        fermer.clicked.connect(self.reject)
        lay.addWidget(fermer)
        barre.mousePressEvent = self._deplacer
        return barre

    def _deplacer(self, e):
        """La barre de titre déplace la fenêtre, qui n'a pas de cadre."""
        if e.button() == Qt.LeftButton and self.windowHandle() is not None:
            self.windowHandle().startSystemMove()

    def choisir(self, onglet: str):
        cle = onglet if onglet in self._boutons else "nouveau"
        self._boutons[cle].setChecked(True)
        self.pages.setCurrentIndex(list(self._boutons).index(cle))

    # Nouveau projet

    def _page_nouveau(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 14)
        lay.setSpacing(12)
        lay.addWidget(Image(BANDEAU, hauteur=250))
        tuiles = QHBoxLayout()
        tuiles.setContentsMargins(4, 0, 4, 0)
        tuiles.setSpacing(4)
        self._formats = QButtonGroup(page)
        for cle, nom, icone in [("auto", "D'après le média", "film")] + \
                [(c, v[0], v[1]) for c, v in FORMATS.items()]:
            b = tuile(nom, icone, "accueil-format", 26)
            b.setProperty("format", cle)
            b.setMinimumHeight(74)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self._formats.addButton(b)
            tuiles.addWidget(b)
        self._formats.buttons()[0].setChecked(True)
        self._formats.buttonClicked.connect(lambda _b: self._format_change())
        lay.addLayout(tuiles)

        bloc = QVBoxLayout()
        bloc.setContentsMargins(14, 0, 14, 0)
        bloc.setSpacing(8)
        bloc.addWidget(etiquette("Créer un nouveau projet", "titre-section"))
        grille = QGridLayout()
        grille.setHorizontalSpacing(12)
        grille.setVerticalSpacing(6)
        self.resolution = QComboBox()
        self.resolution.setAccessibleName("Résolution")
        self.cadence = QComboBox()
        self.cadence.setAccessibleName("Fréquence image")
        for cle, nom in CADENCES:
            self.cadence.addItem(nom, cle)
        self.cadence.setCurrentIndex(2)
        self.timecode = QComboBox()
        self.timecode.setAccessibleName("Timecode de début")
        self.timecode.addItem("01:00:00:00", True)
        self.timecode.addItem("00:00:00:00", False)
        for ligne, (nom, champ) in enumerate((("Résolution :", self.resolution),
                                              ("Fréquence image :", self.cadence),
                                              ("Timecode de début :", self.timecode))):
            libelle = etiquette(nom, "")
            libelle.setFixedWidth(130)
            grille.addWidget(libelle, ligne, 0)
            grille.addWidget(champ, ligne, 1)
        grille.setColumnStretch(1, 1)
        bloc.addLayout(grille)
        self._note_auto = etiquette("Taille, cadence et timecode du premier média posé",
                                    "secondaire")
        bloc.addWidget(self._note_auto)
        boutons = QHBoxLayout()
        boutons.addSpacing(142)
        creer = QPushButton("Créer un projet")
        creer.setProperty("variante", "principal")
        creer.setDefault(True)
        creer.clicked.connect(self._creer)
        self._creer_bouton = creer
        boutons.addWidget(creer)
        boutons.addStretch(1)
        bloc.addLayout(boutons)
        lay.addLayout(bloc)
        lay.addStretch(1)
        self._format_change()
        return page

    def format_choisi(self) -> str:
        return self._formats.checkedButton().property("format")

    def _format_change(self):
        cle = self.format_choisi()
        auto = cle == "auto"
        for champ in (self.resolution, self.cadence, self.timecode):
            champ.setEnabled(not auto)
        self._note_auto.setVisible(auto)
        self.resolution.clear()
        for nom, l, h in ([] if auto else FORMATS[cle][2]):
            self.resolution.addItem(f"{nom} ({l} × {h})", (l, h))

    def _creer(self):
        cle = self.format_choisi()
        if cle == "auto":
            self.resultat = ("auto",)
        else:
            l, h = self.resolution.currentData()
            self.resultat = ("nouveau", l, h, self.cadence.currentData(),
                             self.timecode.currentData())
        self.accept()

    # Ouvrir un projet

    def _page_ouvrir(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(8)
        lay.addWidget(etiquette("Ouverture d'un projet existant", "titre-section"))
        parcourir = QPushButton("Parcourir…")
        parcourir.setFixedWidth(130)
        parcourir.clicked.connect(self._parcourir)
        lay.addWidget(parcourir)
        lay.addSpacing(8)
        lay.addWidget(etiquette("Projets récents", "titre-section"))
        self.liste_recents = QTreeWidget()
        self.liste_recents.setAccessibleName("Projets récents")
        self.liste_recents.setHeaderHidden(True)
        self.liste_recents.setColumnCount(2)
        self.liste_recents.setRootIsDecorated(False)
        self.liste_recents.setIndentation(0)
        self.liste_recents.setProperty("role", "liste-plate")
        entete = self.liste_recents.header()
        entete.setStretchLastSection(False)
        entete.setSectionResizeMode(0, QHeaderView.Stretch)
        entete.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        for chemin, instant in recents():
            item = QTreeWidgetItem([chemin.stem, date_longue(instant)])
            item.setData(0, Qt.UserRole, str(chemin))
            item.setToolTip(0, str(chemin))
            item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
            self.liste_recents.addTopLevelItem(item)
        if not self.liste_recents.topLevelItemCount():
            vide = QTreeWidgetItem(["Aucun projet récent", ""])
            vide.setFlags(Qt.NoItemFlags)
            self.liste_recents.addTopLevelItem(vide)
        self.liste_recents.itemActivated.connect(lambda item, _c: self._ouvrir_item(item))
        lay.addWidget(self.liste_recents, 1)
        return page

    def _ouvrir_item(self, item):
        if item is None or not item.data(0, Qt.UserRole):
            return
        self.resultat = ("ouvrir", item.data(0, Qt.UserRole))
        self.accept()

    def _parcourir(self):
        chemin, _ = QFileDialog.getOpenFileName(self, "Ouvrir un projet", "",
                                                "Projet Remanence (*.remanence)")
        if chemin:
            self.resultat = ("ouvrir", chemin)
            self.accept()

    # Prise en main : les fiches en cartes ; un clic ouvre la fenêtre de prise en main

    def _page_aide(self) -> QWidget:
        fond = Image(BANDEAU, assombrir=0.72)
        lay_fond = QVBoxLayout(fond)
        lay_fond.setContentsMargins(0, 0, 0, 0)
        defil = QScrollArea()
        defil.setWidgetResizable(True)
        defil.setFrameShape(QScrollArea.NoFrame)
        defil.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget "
                            "{ background: transparent; }")
        cartes = QWidget()
        grille = QGridLayout(cartes)
        grille.setContentsMargins(24, 20, 24, 20)
        grille.setSpacing(14)
        self.cartes: list[Carte] = []
        self._fiches = fiches()
        for i, (titre, _chemin, image) in enumerate(self._fiches):
            carte = Carte(titre, image)
            carte.choisie.connect(lambda i=i: self.ouvrir_fiche(i))
            grille.addWidget(carte, i // 3, i % 3, Qt.AlignCenter)
            self.cartes.append(carte)
        defil.setWidget(cartes)
        lay_fond.addWidget(defil)

        return fond

    def ouvrir_fiche(self, i: int):
        """La fiche dans la fenêtre de prise en main, qui reste ouverte à côté."""
        FenetreAide.ouvrir(i)
