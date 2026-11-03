"""Écran d'accueil, ouvert au lancement : une seule page qui prolonge l'écran de démarrage.

Sur un fond de points ondulants : à gauche, l'identité de Remanence et les deux actions ; à
droite, trois volets en accordéon (nouveau projet, récents, prise en main), un seul ouvert. Les fiches de prise
en main s'ouvrent dans leur propre fenêtre (`ui/aide.py`).
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

from PySide6.QtCore import (QEasingCurve, QPointF, QRectF, QSize, Qt, QTimer,
                            QVariantAnimation)
from PySide6.QtGui import QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QGridLayout,
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
CLE_VOLET = "accueil/volet"
TAILLE_MAX = 16777215
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


def _icone_format(cle: str) -> QIcon:
    """Un cadre aux proportions du format, gris au repos, mauve quand la tuile est choisie."""
    l, h = FORMATS[cle][1][0][1:]
    boite_l, boite_h = 44, 32
    echelle = min((boite_l - 4) / l, (boite_h - 4) / h)
    cadre = QRectF(0, 0, l * echelle, h * echelle)
    cadre.moveCenter(QPointF(boite_l / 2, boite_h / 2))
    c = charte.actuelle()
    icone = QIcon()
    for mode, etat, couleur in [(QIcon.Normal, QIcon.Off, "ink-muted"),
                                (QIcon.Active, QIcon.Off, "ink"),
                                (QIcon.Normal, QIcon.On, "accent"),
                                (QIcon.Active, QIcon.On, "accent")]:
        pm = QPixmap(boite_l * 2, boite_h * 2)
        pm.setDevicePixelRatio(2.0)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(c.c(couleur), 1.5))
        p.drawRoundedRect(cadre.adjusted(0.75, 0.75, -0.75, -0.75), 2, 2)
        p.end()
        icone.addPixmap(pm, mode, etat)
    return icone


class Volet(QWidget):
    """Volet de l'accueil : un titre bien visible et son contenu. Un seul est ouvert à la fois
    et prend toute la hauteur ; les autres ne montrent que leur titre (`Accueil.ouvrir_volet`)."""

    def __init__(self, titre: str, contenu: QWidget):
        super().__init__()
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

    def ouvert(self) -> bool:
        return self.titre.isChecked()

    def marquer(self, ouvert: bool):
        self.titre.setChecked(ouvert)
        poser_icone(self.titre, "chevron-down" if ouvert else "chevron-right", 16)


class FondOndes(QWidget):
    """Fond de l'accueil : une nappe de points vue en perspective, qui ondule lentement."""

    COLONNES, RANGEES = 72, 26

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self._t = 0.0
        self._image: QPixmap | None = None
        self._horloge = QTimer(self)
        self._horloge.setInterval(40)
        self._horloge.timeout.connect(self._avancer)

    def showEvent(self, e):
        self._horloge.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self._horloge.stop()
        super().hideEvent(e)

    def pause(self, oui: bool):
        """Arrêtée pendant le glissement d'un volet : chaque pas redessinait toute la fenêtre."""
        if oui:
            self._horloge.stop()
        elif self.isVisible():
            self._horloge.start()

    def resizeEvent(self, e):
        self._image = None
        super().resizeEvent(e)

    def _avancer(self):
        self._t += 0.04
        self._image = None
        self.update()

    def paintEvent(self, _e):
        # Les volets sont transparents : chacun de leurs dessins redessine le fond. La nappe
        # n'est donc calculée qu'une fois par pas de l'horloge.
        if self._image is None or self._image.size() != self.size() * self.devicePixelRatioF():
            self._image = self._dessiner()
        p = QPainter(self)
        p.drawPixmap(0, 0, self._image)
        p.end()

    def _dessiner(self) -> QPixmap:
        c = charte.actuelle()
        ratio = self.devicePixelRatioF()
        image = QPixmap(self.size() * ratio)
        image.setDevicePixelRatio(ratio)
        image.fill(c.c("bg-app"))
        p = QPainter(image)
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
        return image


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
        nouveau = QPushButton("Nouveau projet")
        nouveau.clicked.connect(self._vers_nouveau_projet)
        ouvrir = QPushButton("Ouvrir…")
        ouvrir.clicked.connect(self._parcourir)
        for b in (nouveau, ouvrir):
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

    def _vers_nouveau_projet(self):
        self.ouvrir_volet(0)
        self._creer_bouton.setFocus()

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
        self._pile_volets = QVBoxLayout(colonne)
        self._pile_volets.setContentsMargins(0, 0, 16, 0)
        self._pile_volets.setSpacing(0)
        self.volets = [Volet("Nouveau projet", self._nouveau_projet()),
                       Volet("Récents", self._liste_recents()),
                       Volet("Prise en main", self._fiches())]
        for i, v in enumerate(self.volets):
            self._pile_volets.addWidget(v)
            v.titre.clicked.connect(lambda _=False, i=i: self.ouvrir_volet(i))
        self._pile_volets.addStretch(0)
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(260)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.valueChanged.connect(self._glisser)
        self._animation.finished.connect(self._fin_glisser)
        self._ouvert = -1
        self._fermant = -1
        self.ouvrir_volet(int(reglages_interface().value(CLE_VOLET, 1)), anime=False)
        lay.addWidget(colonne, 1)
        return page

    def ouvrir_volet(self, i: int, anime: bool = True):
        """Ouvre le volet i en entier ; celui qui était ouvert se replie en glissant."""
        i = max(0, min(len(self.volets) - 1, i))
        if self._animation.state() == QVariantAnimation.Running:
            self._animation.stop()
            self._fin_glisser()
        for k, v in enumerate(self.volets):
            v.marquer(k == i)
        if i == self._ouvert:
            return
        reglages_interface().setValue(CLE_VOLET, i)
        avant, self._ouvert = self._ouvert, i
        if not anime or avant < 0 or not self.isVisible():
            for k, v in enumerate(self.volets):
                v.corps.setVisible(k == i)
                v.corps.setMaximumHeight(TAILLE_MAX)
                self._pile_volets.setStretchFactor(v, 1 if k == i else 0)
            return
        self._fermant = avant
        self._hauteur = self.volets[avant].corps.height()
        nouveau = self.volets[i].corps
        nouveau.setMaximumHeight(0)
        nouveau.show()
        self._pile_volets.setStretchFactor(self.volets[i], 1)
        self.fond.pause(True)
        self._animation.start()

    def _glisser(self, x: float):
        h = round(self._hauteur * x)
        self.volets[self._ouvert].corps.setMaximumHeight(h)
        if self._fermant >= 0:
            self.volets[self._fermant].corps.setMaximumHeight(max(0, self._hauteur - h))

    def _fin_glisser(self):
        if self._fermant >= 0:
            ferme = self.volets[self._fermant]
            ferme.corps.hide()
            ferme.corps.setMaximumHeight(TAILLE_MAX)
            self._pile_volets.setStretchFactor(ferme, 0)
            self._fermant = -1
        self.volets[self._ouvert].corps.setMaximumHeight(TAILLE_MAX)
        self.fond.pause(False)


    def _nouveau_projet(self) -> QWidget:
        """Le format en tuiles (le dessin de chaque tuile a ses proportions), puis résolution,
        cadence et timecode, et le bouton qui crée le projet."""
        volet = QWidget()
        lay = QVBoxLayout(volet)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)
        tuiles = QHBoxLayout()
        tuiles.setSpacing(8)
        self._groupe_format = QButtonGroup(self)
        self.tuiles_format: dict[str, QToolButton] = {}
        for cle, nom in [("auto", "D'après le média")] + [(k, v[0]) for k, v in FORMATS.items()]:
            b = QToolButton()
            b.setProperty("variante", "format")
            b.setText(nom)
            b.setAccessibleName(f"Format {nom}")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.setFixedHeight(84)
            b.setIcon(charte.actuelle().icone("film", 28) if cle == "auto" else _icone_format(cle))
            b.setIconSize(QSize(44, 32))
            b.clicked.connect(lambda _=False, cle=cle: self.choisir_format(cle))
            self._groupe_format.addButton(b)
            self.tuiles_format[cle] = b
            tuiles.addWidget(b)
        lay.addLayout(tuiles)

        grille = QGridLayout()
        grille.setContentsMargins(0, 0, 0, 0)
        grille.setHorizontalSpacing(8)
        grille.setVerticalSpacing(4)
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
                ("Résolution", self.resolution, 4), ("Cadence", self.cadence, 2),
                ("Timecode", self.timecode, 2))):
            grille.addWidget(etiquette(nom, "libelle"), 0, colonne)
            grille.addWidget(champ, 1, colonne)
            grille.setColumnStretch(colonne, etire)
        lay.addLayout(grille)

        self._creer_bouton = QPushButton("Créer le projet")
        self._creer_bouton.setProperty("variante", "principal")
        self._creer_bouton.setDefault(True)
        self._creer_bouton.setFixedWidth(200)
        self._creer_bouton.clicked.connect(self._creer)
        lay.addWidget(self._creer_bouton)
        lay.addStretch(1)
        self.choisir_format("auto")
        return volet

    def choisir_format(self, cle: str):
        self._format = cle
        self.tuiles_format[cle].setChecked(True)
        auto = cle == "auto"
        for champ in (self.resolution, self.cadence, self.timecode):
            champ.setEnabled(not auto)
        self.resolution.clear()
        if auto:
            self.resolution.addItem("Celle du premier média", None)
        for nom, l, h in ([] if auto else FORMATS[cle][1]):
            self.resolution.addItem(f"{nom} ({l} × {h})", (l, h))

    def format_choisi(self) -> str:
        return self._format

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
        """Une carte par fiche, sa première capture en vignette, en grille. Elle ouvre la
        fenêtre de prise en main, à part."""
        grille_w = QWidget()
        grille = QGridLayout(grille_w)
        grille.setContentsMargins(0, 0, 0, 0)
        grille.setSpacing(10)
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
            grille.addWidget(b, i // 3, i % 3)
            self.boutons_fiches.append(b)
        # Les cartes gardent leur taille : pendant le glissement du volet, elles sont coupées
        # au lieu d'être écrasées (la feuille de style l'emporte sur setFixedSize).
        rangees = (len(self.boutons_fiches) + 2) // 3
        grille_w.setMinimumHeight(rangees * (vignette.height() + 48) + (rangees - 1) * 10)
        grille.setRowStretch(grille.rowCount(), 1)
        grille.setColumnStretch(3, 1)
        defile = QScrollArea()
        defile.setWidget(grille_w)
        defile.setWidgetResizable(True)
        defile.setFrameShape(QScrollArea.NoFrame)
        defile.setProperty("fond", "transparent")
        defile.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        return defile
