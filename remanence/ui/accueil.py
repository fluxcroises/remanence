"""Écran d'accueil, ouvert au lancement : nouveau projet, projets récents, prise en main.

Les fiches de prise en main sont des fichiers Markdown de `remanence/ressources/aide`, avec
leurs captures. Les textes détaillés vivent là, pas dans l'interface.
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QImage, QTextBlockFormat, QTextCursor
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog,
                               QGridLayout, QHBoxLayout, QListWidget, QListWidgetItem,
                               QPushButton, QSizePolicy, QStackedWidget, QTextBrowser,
                               QVBoxLayout, QWidget)

from remanence.config import reglages_interface
from remanence.ui.composants import bouton_icone, etiquette

AIDE = Path(__file__).resolve().parents[1] / "ressources" / "aide"

# Format -> (nom affiché, résolutions proposées, la première par défaut).
FORMATS = {
    "16:9": ("Écran large 16:9", [(1920, 1080), (3840, 2160), (2560, 1440), (1280, 720)]),
    "4:3": ("Plein écran 4:3", [(1440, 1080), (1024, 768), (640, 480)]),
    "9:16": ("Portrait 9:16", [(1080, 1920), (720, 1280)]),
    "1:1": ("Carré 1:1", [(1080, 1080), (2160, 2160)]),
    "2.39:1": ("Scope 2,39:1", [(1920, 804), (3840, 1608)]),
}
CADENCES = [("24000/1001", "23,976"), ("24", "24"), ("25", "25"), ("30000/1001", "29,97"),
            ("30", "30"), ("50", "50"), ("60000/1001", "59,94"), ("60", "60")]

CLE_RECENTS = "projets_recents"
CLE_AU_DEMARRAGE = "accueil/au_demarrage"


def recents() -> list[Path]:
    liste = reglages_interface().value(CLE_RECENTS, []) or []
    if isinstance(liste, str):
        liste = [liste]
    return [Path(p) for p in liste if Path(p).exists()]


def retenir(chemin: Path):
    """Le projet ouvert ou enregistré passe en tête des récents (dix au plus)."""
    chemin = Path(chemin)
    liste = [str(chemin)] + [str(p) for p in recents() if p != chemin]
    reglages_interface().setValue(CLE_RECENTS, liste[:10])


def au_demarrage() -> bool:
    return str(reglages_interface().value(CLE_AU_DEMARRAGE, "true")).lower() == "true"


def fiches() -> list[tuple[str, Path]]:
    """(titre, fichier) de chaque fiche, dans l'ordre de leur nom (« 01-… »)."""
    resultat = []
    for f in sorted(AIDE.glob("*.md")):
        premiere = f.read_text(encoding="utf-8").splitlines()[0]
        resultat.append((premiere.lstrip("# ").strip(), f))
    return resultat


class Accueil(QDialog):
    """resultat : ("nouveau", largeur, hauteur, cadence, tc_une_heure), ("auto",),
    ("ouvrir", chemin) ou None."""

    def __init__(self, parent=None, onglet: str = "nouveau"):
        super().__init__(parent)
        self.setWindowTitle("Remanence")
        self.resize(980, 640)
        self.resultat = None
        racine = QHBoxLayout(self)
        racine.setContentsMargins(0, 0, 0, 0)
        racine.setSpacing(0)

        cote = QWidget()
        cote.setProperty("role", "panneau-accueil")
        cote.setAttribute(Qt.WA_StyledBackground, True)
        cote.setFixedWidth(200)
        lay_cote = QVBoxLayout(cote)
        lay_cote.setContentsMargins(0, 16, 0, 12)
        lay_cote.setSpacing(2)
        self.pages = QStackedWidget()
        self._groupe = QButtonGroup(self)
        self._boutons = {}
        for i, (cle, nom, icone, page) in enumerate((
                ("nouveau", "Nouveau projet", "plus", self._page_nouveau()),
                ("ouvrir", "Ouvrir un projet", "folder", self._page_ouvrir()),
                ("aide", "Prise en main", "info", self._page_aide()))):
            b = bouton_icone(icone, nom, variante="accueil", texte=nom, cochable=True, taille=18)
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.clicked.connect(lambda _=False, i=i: self.pages.setCurrentIndex(i))
            b.setFocusPolicy(Qt.TabFocus)
            self._groupe.addButton(b)
            self._boutons[cle] = b
            lay_cote.addWidget(b)
            self.pages.addWidget(page)
        lay_cote.addStretch(1)
        self.au_demarrage = QCheckBox("Afficher au démarrage")
        self.au_demarrage.setChecked(au_demarrage())
        self.au_demarrage.toggled.connect(
            lambda v: reglages_interface().setValue(CLE_AU_DEMARRAGE, "true" if v else "false"))
        marge = QHBoxLayout()
        marge.setContentsMargins(14, 0, 14, 0)
        marge.addWidget(self.au_demarrage)
        lay_cote.addLayout(marge)
        racine.addWidget(cote)
        racine.addWidget(self.pages, 1)
        self.choisir(onglet)
        self._creer_bouton.setFocus()

    def choisir(self, onglet: str):
        b = self._boutons.get(onglet, self._boutons["nouveau"])
        b.setChecked(True)
        self.pages.setCurrentIndex(list(self._boutons).index(
            onglet if onglet in self._boutons else "nouveau"))

    # Nouveau projet

    def _page_nouveau(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(16)
        lay.addWidget(etiquette("Nouveau projet", "dialogue"))
        tuiles = QHBoxLayout()
        tuiles.setSpacing(8)
        self._formats = QButtonGroup(page)
        for cle, nom in [("auto", "D'après le premier média")] + \
                [(c, v[0]) for c, v in FORMATS.items()]:
            b = QPushButton(nom)
            b.setProperty("variante", "format")
            b.setCheckable(True)
            b.setMinimumHeight(56)
            b.setProperty("format", cle)
            self._formats.addButton(b)
            tuiles.addWidget(b, 1)
        self._formats.buttons()[0].setChecked(True)
        self._formats.buttonClicked.connect(lambda _b: self._format_change())
        lay.addLayout(tuiles)

        grille = QGridLayout()
        grille.setHorizontalSpacing(12)
        grille.setVerticalSpacing(10)
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
        for ligne, (nom, champ) in enumerate((("Résolution", self.resolution),
                                              ("Cadence", self.cadence),
                                              ("Timecode de début", self.timecode))):
            libelle = etiquette(nom, "libelle")
            libelle.setFixedWidth(140)
            grille.addWidget(libelle, ligne, 0)
            grille.addWidget(champ, ligne, 1)
        grille.setColumnStretch(1, 1)
        lay.addLayout(grille)
        self._note_auto = etiquette("Taille, cadence et timecode du premier média posé",
                                    "secondaire")
        lay.addWidget(self._note_auto)
        lay.addStretch(1)
        bas = QHBoxLayout()
        bas.addStretch(1)
        creer = QPushButton("Créer le projet")
        creer.setProperty("variante", "principal")
        creer.setDefault(True)
        creer.clicked.connect(self._creer)
        self._creer_bouton = creer
        bas.addWidget(creer)
        lay.addLayout(bas)
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
        for l, h in ([] if auto else FORMATS[cle][1]):
            self.resolution.addItem(f"{l} × {h}", (l, h))

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
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(12)
        lay.addWidget(etiquette("Ouvrir un projet", "dialogue"))
        self.liste_recents = QListWidget()
        self.liste_recents.setAccessibleName("Projets récents")
        self.liste_recents.setIconSize(QSize(18, 18))
        for chemin in recents():
            date = time.strftime("%d/%m/%Y %H:%M", time.localtime(chemin.stat().st_mtime))
            item = QListWidgetItem(f"{chemin.stem}\n{chemin.parent} · {date}")
            item.setData(Qt.UserRole, str(chemin))
            item.setToolTip(str(chemin))
            self.liste_recents.addItem(item)
        if not self.liste_recents.count():
            vide = QListWidgetItem("Aucun projet récent")
            vide.setFlags(Qt.NoItemFlags)
            self.liste_recents.addItem(vide)
        self.liste_recents.itemActivated.connect(self._ouvrir_item)
        self.liste_recents.itemDoubleClicked.connect(self._ouvrir_item)
        lay.addWidget(self.liste_recents, 1)
        bas = QHBoxLayout()
        parcourir = QPushButton("Parcourir…")
        parcourir.clicked.connect(self._parcourir)
        bas.addWidget(parcourir)
        bas.addStretch(1)
        ouvrir = QPushButton("Ouvrir")
        ouvrir.setProperty("variante", "principal")
        ouvrir.clicked.connect(lambda: self._ouvrir_item(self.liste_recents.currentItem()))
        bas.addWidget(ouvrir)
        lay.addLayout(bas)
        return page

    def _ouvrir_item(self, item):
        if item is None or not item.data(Qt.UserRole):
            return
        self.resultat = ("ouvrir", item.data(Qt.UserRole))
        self.accept()

    def _parcourir(self):
        chemin, _ = QFileDialog.getOpenFileName(self, "Ouvrir un projet", "",
                                                "Projet Remanence (*.remanence)")
        if chemin:
            self.resultat = ("ouvrir", chemin)
            self.accept()

    # Prise en main

    def _page_aide(self) -> QWidget:
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.liste_fiches = QListWidget()
        self.liste_fiches.setAccessibleName("Fiches")
        self.liste_fiches.setFixedWidth(240)
        self.lecteur = QTextBrowser()
        self.lecteur.setAccessibleName("Fiche")
        self.lecteur.setOpenExternalLinks(False)
        self.lecteur.setSearchPaths([str(AIDE)])
        self.lecteur.document().setDocumentMargin(24)
        for titre, chemin in fiches():
            item = QListWidgetItem(titre)
            item.setData(Qt.UserRole, str(chemin))
            self.liste_fiches.addItem(item)
        self.liste_fiches.currentItemChanged.connect(self._lire)
        self.pages.currentChanged.connect(
            lambda i: self._lire(self.liste_fiches.currentItem()) if i == 2 else None)
        lay.addWidget(self.liste_fiches)
        lay.addWidget(self.lecteur, 1)
        if self.liste_fiches.count():
            self.liste_fiches.setCurrentRow(0)
        return page

    def _lire(self, item, _avant=None):
        if item is None:
            return
        chemin = Path(item.data(Qt.UserRole))
        self.lecteur.document().setBaseUrl(QUrl.fromLocalFile(str(chemin.parent) + "/"))
        self.lecteur.setMarkdown(chemin.read_text(encoding="utf-8"))
        # Le Markdown de Qt colle les paragraphes : un peu d'air entre les blocs.
        # Les captures prennent au plus la largeur du texte.
        doc = self.lecteur.document()
        largeur = max(360, self.lecteur.viewport().width() - 2 * doc.documentMargin() - 8)
        curseur = QTextCursor(doc)
        bloc = doc.begin()
        while bloc.isValid():
            forme = bloc.blockFormat()
            forme.setBottomMargin(10 if bloc.textList() is None else 4)
            forme.setLineHeight(130, QTextBlockFormat.ProportionalHeight.value)
            curseur.setPosition(bloc.position())
            curseur.setBlockFormat(forme)
            it = bloc.begin()
            while not it.atEnd():
                fragment = it.fragment()
                image = fragment.charFormat().toImageFormat()
                if image.isValid():
                    taille = QImage(str(AIDE / image.name())).size()
                    if taille.width() > largeur:
                        image.setWidth(largeur)
                        image.setHeight(taille.height() * largeur / taille.width())
                        curseur.setPosition(fragment.position())
                        curseur.setPosition(fragment.position() + fragment.length(),
                                            QTextCursor.KeepAnchor)
                        curseur.setCharFormat(image)
                it += 1
            bloc = bloc.next()
        self.lecteur.verticalScrollBar().setValue(0)

