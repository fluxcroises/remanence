"""Écran d'accueil, ouvert au lancement : une seule page qui prolonge l'écran de démarrage.

À gauche, l'identité de Remanence (symbole, nom, éclats de l'écran de démarrage) et les deux
actions ; à droite, le format du nouveau projet sur une ligne, les projets récents en grand,
et les fiches de prise en main, qui s'ouvrent dans leur propre fenêtre (`ui/aide.py`).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QPushButton, QSizePolicy,
                               QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from remanence import ANNEE, EDITEUR, __version__
from remanence.config import reglages_interface
from remanence.ui import charte
from remanence.ui.aide import FenetreAide, fiches
from remanence.ui.composants import bouton_icone, etiquette
from remanence.ui.demarrage import eclats

# Format -> (nom affiché, résolutions proposées : la première par défaut).
FORMATS = {
    "16:9": ("16:9", [("Full HD", 1920, 1080), ("4K UHD", 3840, 2160), ("QHD", 2560, 1440),
                      ("HD", 1280, 720)]),
    "4:3": ("4:3", [("HDV", 1440, 1080), ("XGA", 1024, 768), ("SD", 640, 480)]),
    "9:16": ("9:16 vertical", [("Full HD", 1080, 1920), ("HD", 720, 1280)]),
    "1:1": ("1:1 carré", [("Full HD", 1080, 1080), ("4K", 2160, 2160)]),
    "2.39:1": ("2,39:1 scope", [("Full HD", 1920, 804), ("4K UHD", 3840, 1608)]),
}
CADENCES = [("24000/1001", "23,976"), ("24", "24"), ("25", "25"), ("30000/1001", "29,97"),
            ("30", "30"), ("50", "50"), ("60000/1001", "59,94"), ("60", "60")]

CLE_RECENTS = "projets_recents_dates"
CLE_AU_DEMARRAGE = "accueil/au_demarrage"
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
        "octobre", "novembre", "décembre"]


def date_relative(instant: float, maintenant: float | None = None) -> str:
    """« à l'instant », « il y a 5 min », « il y a 2 h », « hier », « il y a 3 jours »,
    puis la date."""
    maintenant = time.time() if maintenant is None else maintenant
    ecart = max(0.0, maintenant - instant)
    jour = time.localtime(instant)
    jours = (time.mktime(time.localtime(maintenant)[:3] + (0, 0, 0, 0, 0, -1))
             - time.mktime(jour[:3] + (0, 0, 0, 0, 0, -1))) / 86400
    if ecart < 60:
        return "à l'instant"
    if ecart < 3600:
        return f"il y a {int(ecart // 60)} min"
    if round(jours) == 0:
        return f"il y a {int(ecart // 3600)} h"
    if round(jours) == 1:
        return "hier"
    if jours < 7:
        return f"il y a {round(jours)} jours"
    return f"{jour.tm_mday} {MOIS[jour.tm_mon - 1]} {jour.tm_year}"


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


class Identite(QWidget):
    """Colonne de gauche : les éclats de l'écran de démarrage jaillissent de son bord droit,
    sous le nom et les deux actions. Elle déplace la fenêtre, qui n'a pas de cadre."""

    def __init__(self):
        super().__init__()
        self.setFixedWidth(300)
        self.setProperty("role", "accueil-identite")
        self.setAttribute(Qt.WA_StyledBackground, True)
        # La gerbe de gauche de l'écran de démarrage, recalée sur ce bord.
        self._eclats = [e for e in eclats() if e[0] < 220]

    def paintEvent(self, e):
        super().paintEvent(e)
        c = charte.actuelle()
        p = QPainter(self)
        haut = self.height() - 380
        for x, y, l, h, ton, opacite in self._eclats:
            p.fillRect(QRectF(x + self.width() - 220, haut + (y - 120), l, h), c.c(ton, opacite))
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.window().windowHandle() is not None:
            self.window().windowHandle().startSystemMove()


class Accueil(QDialog):
    """resultat : ("nouveau", largeur, hauteur, cadence, tc_une_heure), ("auto",),
    ("ouvrir", chemin) ou None."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        # Modale pour la fenêtre principale seulement : la prise en main reste utilisable.
        self.setWindowModality(Qt.WindowModal)
        self.setWindowTitle("Remanence")
        self.setProperty("role", "accueil")
        self.resize(980, 640)
        self.resultat = None
        racine = QHBoxLayout(self)
        racine.setContentsMargins(1, 1, 1, 1)
        racine.setSpacing(0)
        racine.addWidget(self._colonne_identite())
        racine.addWidget(self._contenu(), 1)
        self._creer_bouton.setFocus()

    # À gauche : identité et actions

    def _colonne_identite(self) -> QWidget:
        colonne = Identite()
        lay = QVBoxLayout(colonne)
        lay.setContentsMargins(28, 32, 28, 20)
        lay.setSpacing(0)
        nom = QHBoxLayout()
        nom.setSpacing(12)
        symbole = QLabel()
        symbole.setPixmap(charte.actuelle().symbole(40))
        symbole.setAccessibleName("Remanence")
        nom.addWidget(symbole)
        titre = QLabel("Remanence")
        # La feuille de style l'emporte sur setFont : la police du titre passe par elle.
        titre.setStyleSheet("QLabel { %s font-size: 26px; letter-spacing: -0.5px; }"
                            % charte.actuelle().css_police("display"))
        nom.addWidget(titre)
        nom.addStretch(1)
        lay.addLayout(nom)
        lay.addSpacing(6)
        lay.addWidget(etiquette(f"Version {__version__} · © {ANNEE} {EDITEUR}", "secondaire"))
        lay.addSpacing(32)
        self._creer_bouton = QPushButton("Nouveau projet")
        self._creer_bouton.setProperty("variante", "principal")
        self._creer_bouton.setDefault(True)
        self._creer_bouton.clicked.connect(self._creer)
        ouvrir = QPushButton("Ouvrir…")
        ouvrir.clicked.connect(self._parcourir)
        for b in (self._creer_bouton, ouvrir):
            b.setFixedWidth(200)
            lay.addWidget(b)
            lay.addSpacing(8)
        lay.addStretch(1)
        self.au_demarrage = QCheckBox("Afficher au démarrage")
        self.au_demarrage.setChecked(au_demarrage())
        self.au_demarrage.toggled.connect(
            lambda v: reglages_interface().setValue(CLE_AU_DEMARRAGE, "true" if v else "false"))
        lay.addWidget(self.au_demarrage)
        return colonne

    # À droite : nouveau projet, récents, prise en main

    def _contenu(self) -> QWidget:
        page = QWidget()
        page.setProperty("role", "panneau")
        page.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(page)
        lay.setContentsMargins(28, 12, 12, 24)
        lay.setSpacing(0)
        haut = QHBoxLayout()
        haut.addStretch(1)
        fermer = bouton_icone("x", "Fermer (Échap)", variante="fenetre-fermer")
        fermer.clicked.connect(self.reject)
        haut.addWidget(fermer)
        lay.addLayout(haut)

        marge = QVBoxLayout()
        marge.setContentsMargins(0, 0, 16, 0)
        marge.setSpacing(10)
        marge.addWidget(etiquette("Nouveau projet", "section"))
        marge.addLayout(self._ligne_format())
        marge.addSpacing(18)
        marge.addWidget(etiquette("Récents", "section"))
        marge.addWidget(self._liste_recents(), 1)
        marge.addSpacing(18)
        marge.addWidget(etiquette("Prise en main", "section"))
        marge.addLayout(self._fiches())
        lay.addLayout(marge, 1)
        return page

    def _ligne_format(self) -> QGridLayout:
        grille = QGridLayout()
        grille.setHorizontalSpacing(8)
        grille.setVerticalSpacing(4)
        self.format = QComboBox()
        self.format.setAccessibleName("Format")
        self.format.addItem("D'après le média", "auto")
        for cle, (nom, _r) in FORMATS.items():
            self.format.addItem(nom, cle)
        self.format.currentIndexChanged.connect(lambda _i: self._format_change())
        self.resolution = QComboBox()
        self.resolution.setAccessibleName("Résolution")
        self.cadence = QComboBox()
        self.cadence.setAccessibleName("Cadence")
        for cle, nom in CADENCES:
            self.cadence.addItem(f"{nom} i/s", cle)
        self.cadence.setCurrentIndex(2)
        self.timecode = QComboBox()
        self.timecode.setAccessibleName("Timecode de début")
        self.timecode.addItem("01:00:00:00", True)
        self.timecode.addItem("00:00:00:00", False)
        for colonne, (nom, champ, etire) in enumerate((
                ("Format", self.format, 3), ("Résolution", self.resolution, 4),
                ("Cadence", self.cadence, 2), ("Timecode", self.timecode, 2))):
            grille.addWidget(etiquette(nom, "libelle"), 0, colonne)
            grille.addWidget(champ, 1, colonne)
            grille.setColumnStretch(colonne, etire)
        self._format_change()
        return grille

    def format_choisi(self) -> str:
        return self.format.currentData()

    def _format_change(self):
        cle = self.format_choisi()
        auto = cle == "auto"
        for champ in (self.resolution, self.cadence, self.timecode):
            champ.setEnabled(not auto)
        self.resolution.clear()
        if auto:
            self.resolution.addItem("Celle du premier média", None)
        for nom, l, h in ([] if auto else FORMATS[cle][1]):
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

    def _liste_recents(self) -> QTreeWidget:
        self.liste_recents = QTreeWidget()
        self.liste_recents.setAccessibleName("Projets récents")
        self.liste_recents.setHeaderHidden(True)
        self.liste_recents.setColumnCount(3)
        self.liste_recents.setRootIsDecorated(False)
        self.liste_recents.setIndentation(0)
        self.liste_recents.setProperty("role", "liste-plate")
        entete = self.liste_recents.header()
        entete.setStretchLastSection(False)
        entete.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        entete.setSectionResizeMode(1, QHeaderView.Stretch)
        entete.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        gris = charte.actuelle().c("ink-muted")
        for chemin, instant in recents():
            item = QTreeWidgetItem([chemin.stem, str(chemin.parent), date_relative(instant)])
            item.setData(0, Qt.UserRole, str(chemin))
            item.setToolTip(0, str(chemin))
            item.setToolTip(2, time.strftime("%d/%m/%Y %H:%M", time.localtime(instant)))
            item.setForeground(1, gris)
            item.setForeground(2, gris)
            item.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)
            self.liste_recents.addTopLevelItem(item)
        if not self.liste_recents.topLevelItemCount():
            vide = QTreeWidgetItem(["Aucun projet récent", "", ""])
            vide.setFlags(Qt.NoItemFlags)
            self.liste_recents.addTopLevelItem(vide)
        self.liste_recents.itemActivated.connect(lambda item, _c: self._ouvrir_item(item))
        return self.liste_recents

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

    def _fiches(self) -> QGridLayout:
        """Une étiquette par fiche ; elle ouvre la fenêtre de prise en main, à part."""
        grille = QGridLayout()
        grille.setSpacing(6)
        self.boutons_fiches: list[QPushButton] = []
        for i, (titre, _chemin, _image) in enumerate(fiches()):
            b = QPushButton(titre)
            b.setProperty("variante", "fiche")
            b.setCursor(Qt.PointingHandCursor)
            b.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            b.setToolTip(titre)
            b.clicked.connect(lambda _=False, i=i: FenetreAide.ouvrir(i))
            grille.addWidget(b, i // 2, i % 2)
            self.boutons_fiches.append(b)
        for colonne in range(2):
            grille.setColumnStretch(colonne, 1)
        return grille
