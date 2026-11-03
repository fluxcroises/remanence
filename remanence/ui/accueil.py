"""Écran d'accueil, ouvert au lancement : une seule page qui prolonge l'écran de démarrage.

Sur un fond de points ondulants : à gauche, l'identité de Remanence et les deux actions ; à
droite, trois volets dépliables (nouveau projet, récents, prise en main). Les fiches de prise
en main s'ouvrent dans leur propre fenêtre (`ui/aide.py`).
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

from PySide6.QtCore import QPointF, QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QPushButton, QScrollArea,
                               QSizePolicy, QToolButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from remanence import EDITEUR, __version__
from remanence.config import reglages_interface
from remanence.ui import charte
from remanence.ui.aide import FenetreAide, fiches
from remanence.ui.composants import bouton_icone, etiquette, poser_icone

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


class Volet(QWidget):
    """Section dépliable de l'accueil : un titre bien visible, son état retenu."""

    def __init__(self, titre: str, cle: str, contenu: QWidget, etire: int = 0):
        super().__init__()
        self.cle = cle
        self.etire = etire
        self.setProperty("role", "volet")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 10, 0, 10)
        lay.setSpacing(10)
        self.titre = QToolButton()
        self.titre.setProperty("variante", "volet")
        self.titre.setText(titre)
        self.titre.setCheckable(True)
        self.titre.setCursor(Qt.PointingHandCursor)
        self.titre.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.titre.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.titre.setAccessibleName(titre)
        lay.addWidget(self.titre)
        self.corps = contenu
        lay.addWidget(contenu, 1)
        ouvert = not reglages_interface().value(f"accueil/replie/{cle}", False, type=bool)
        self.titre.setChecked(ouvert)
        self._montrer(ouvert)
        self.titre.toggled.connect(self._basculer)

    def ouvert(self) -> bool:
        return self.titre.isChecked()

    def _montrer(self, ouvert: bool):
        self.corps.setVisible(ouvert)
        poser_icone(self.titre, "chevron-down" if ouvert else "chevron-right", 16)
        # Replié, le volet ne prend que la hauteur de son titre.
        parent = self.parentWidget()
        if parent is not None and parent.layout() is not None:
            parent.layout().setStretchFactor(self, self.etire if ouvert else 0)

    def _basculer(self, ouvert: bool):
        self._montrer(ouvert)
        reglages_interface().setValue(f"accueil/replie/{self.cle}", not ouvert)


class FondOndes(QWidget):
    """Fond de l'accueil : une nappe de points vue en perspective, qui ondule lentement."""

    COLONNES, RANGEES = 72, 26

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._t = 0.0
        self._horloge = QTimer(self)
        self._horloge.setInterval(40)
        self._horloge.timeout.connect(self._avancer)

    def showEvent(self, e):
        self._horloge.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self._horloge.stop()
        super().hideEvent(e)

    def _avancer(self):
        self._t += 0.04
        self.update()

    def paintEvent(self, _e):
        c = charte.actuelle()
        p = QPainter(self)
        p.fillRect(self.rect(), c.c("bg-app"))
        p.setRenderHint(QPainter.Antialiasing)
        l, h = self.width(), self.height()
        horizon = h * 0.45
        t = self._t
        # Du fond vers l'avant : les points proches, plus gros, passent devant.
        for r in range(self.RANGEES - 1, -1, -1):
            z = r / (self.RANGEES - 1)
            echelle = 1 / (0.6 + 1.6 * z)
            points = QPolygonF()
            for k in range(self.COLONNES):
                x = k / (self.COLONNES - 1) * 2 - 1
                y = (math.sin(x * 3.1 + t) * math.cos(z * 4.2 - t * 0.6) * 0.16
                     + math.sin((x + z) * 6.0 - t * 1.3) * 0.04)
                points.append(QPointF(l / 2 + x * l * 0.9 * echelle,
                                      horizon + (0.5 - y) * h * echelle * 0.6))
            p.setPen(QPen(c.c("accent", 0.14 + 0.5 * (1 - z)), 1.0 + 2.4 * (1 - z),
                          Qt.SolidLine, Qt.RoundCap))
            p.drawPoints(points)
        p.end()


class Accueil(QDialog):
    """resultat : ("nouveau", largeur, hauteur, cadence, tc_une_heure), ("auto",),
    ("ouvrir", chemin) ou None."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        # Modale pour la fenêtre principale seulement : la prise en main reste utilisable.
        self.setWindowModality(Qt.WindowModal)
        self.setWindowTitle("Remanence")
        self.setProperty("role", "accueil")
        self.resize(1040, 680)
        self.resultat = None
        self.fond = FondOndes(self)
        racine = QHBoxLayout(self)
        racine.setContentsMargins(1, 1, 1, 1)
        racine.setSpacing(0)
        racine.addWidget(self._colonne_identite())
        racine.addWidget(self._contenu(), 1)
        self._creer_bouton.setFocus()

    def resizeEvent(self, e):
        self.fond.setGeometry(self.rect().adjusted(1, 1, -1, -1))
        self.fond.lower()
        super().resizeEvent(e)

    def showEvent(self, e):
        # Centré sur l'écran de la fenêtre principale : au lancement, elle n'a pas encore sa
        # taille finale, et Qt plaçait l'accueil trop haut.
        parent = self.parentWidget()
        ecran = (parent.screen() if parent is not None else self.screen()).availableGeometry()
        self.move(ecran.center() - self.rect().center())
        super().showEvent(e)

    def mousePressEvent(self, e):
        # Sans cadre : la fenêtre se déplace en la tirant par le fond.
        if e.button() == Qt.LeftButton and self.windowHandle() is not None:
            self.windowHandle().startSystemMove()

    # À gauche : identité et actions

    def _colonne_identite(self) -> QWidget:
        colonne = QWidget()
        colonne.setFixedWidth(300)
        lay = QVBoxLayout(colonne)
        lay.setContentsMargins(32, 36, 28, 24)
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
        lay.addWidget(etiquette(f"Version {__version__}", "secondaire"))
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
        logo = charte.actuelle().logo_famille(28)
        if logo is not None:
            famille = QLabel()
            famille.setPixmap(logo)
            famille.setAccessibleName("Creative Orbit")
            famille.setToolTip(f"Creative Orbit · {EDITEUR}")
            lay.addWidget(famille)
            lay.addSpacing(20)
        self.au_demarrage = QCheckBox("Afficher au démarrage")
        self.au_demarrage.setChecked(au_demarrage())
        self.au_demarrage.toggled.connect(
            lambda v: reglages_interface().setValue(CLE_AU_DEMARRAGE, "true" if v else "false"))
        lay.addWidget(self.au_demarrage)
        return colonne

    # À droite : nouveau projet, récents, prise en main

    def _contenu(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(28, 12, 12, 20)
        lay.setSpacing(0)
        haut = QHBoxLayout()
        haut.addStretch(1)
        fermer = bouton_icone("x", "Fermer (Échap)", variante="fenetre-fermer")
        fermer.clicked.connect(self.reject)
        haut.addWidget(fermer)
        lay.addLayout(haut)

        colonne = QWidget()
        volets = QVBoxLayout(colonne)
        volets.setContentsMargins(0, 0, 16, 0)
        volets.setSpacing(0)
        format_ = QWidget()
        format_.setLayout(self._ligne_format())
        self.volets = [Volet("Nouveau projet", "nouveau", format_),
                       Volet("Récents", "recents", self._liste_recents(), 1),
                       Volet("Prise en main", "prise_en_main", self._fiches())]
        for v in self.volets:
            volets.addWidget(v, v.etire if v.ouvert() else 0)
        volets.addStretch(0)
        lay.addWidget(colonne, 1)
        return page

    def _ligne_format(self) -> QGridLayout:
        grille = QGridLayout()
        grille.setContentsMargins(0, 0, 0, 0)
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
            self.cadence.addItem(f"{nom} i/s", cle)
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
            self.resolution.addItem(f"{nom} ({l} × {h})", (l, h))

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
        self.liste_recents.setProperty("fond", "transparent")
        self.liste_recents.setMinimumHeight(120)
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

    def _fiches(self) -> QWidget:
        """Une carte par fiche, sa première capture en vignette, sur une rangée qui défile.
        Elle ouvre la fenêtre de prise en main, à part."""
        rangee = QWidget()
        lay = QHBoxLayout(rangee)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.boutons_fiches: list[QToolButton] = []
        vignette = QSize(176, 99)
        for i, (titre, _chemin, image) in enumerate(fiches()):
            b = QToolButton()
            b.setProperty("variante", "fiche")
            b.setText(titre)
            b.setToolTip(titre)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setFixedSize(vignette.width() + 18, vignette.height() + 48)
            if image is not None and image.exists():
                pm = QPixmap(str(image)).scaled(vignette * 2, Qt.KeepAspectRatioByExpanding,
                                                Qt.SmoothTransformation)
                pm = pm.copy((pm.width() - vignette.width() * 2) // 2, 0,
                             vignette.width() * 2, vignette.height() * 2)
                pm.setDevicePixelRatio(2.0)
                b.setIcon(QIcon(pm))
                b.setIconSize(vignette)
            b.clicked.connect(lambda _=False, i=i: FenetreAide.ouvrir(i))
            lay.addWidget(b)
            self.boutons_fiches.append(b)
        lay.addStretch(1)
        defile = QScrollArea()
        defile.setWidget(rangee)
        defile.setWidgetResizable(True)
        defile.setFrameShape(QScrollArea.NoFrame)
        defile.setProperty("fond", "transparent")
        defile.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        defile.setFixedHeight(vignette.height() + 48 + 14)
        return defile
