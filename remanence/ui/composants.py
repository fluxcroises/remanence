"""Composants de la charte reproduits en widgets Qt : en-tête de panneau, timecode,
ligne de réglage, vumètres, boutons à icône."""

from __future__ import annotations

import math
from fractions import Fraction

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (QDockWidget, QHBoxLayout, QLabel, QLineEdit, QSizePolicy, QSlider,
                               QStackedWidget, QToolButton, QWidget)
from shiboken6 import isValid

from remanence.media.timecode import images_vers_tc, tc_vers_images
from remanence.ui import charte

_boutons_icones: dict[int, tuple[QToolButton, str, int]] = {}


def poser_icone(bouton, nom: str, taille: int = 16):
    """Pose une icône Lucide, recolorée automatiquement au changement de thème."""
    _boutons_icones[id(bouton)] = (bouton, nom, taille)
    bouton.setIcon(charte.actuelle().icone(nom, taille))
    bouton.setIconSize(QSize(taille, taille))


def rafraichir_icones():
    for cle, (bouton, nom, taille) in list(_boutons_icones.items()):
        if isValid(bouton):
            bouton.setIcon(charte.actuelle().icone(nom, taille))
        else:
            del _boutons_icones[cle]


def bouton_icone(nom: str, aide: str, variante: str = "discret", taille: int = 16,
                 texte: str = "", cochable: bool = False) -> QToolButton:
    """Bouton à icône : l'info-bulle et le nom accessible disent ce qu'il fait."""
    b = QToolButton()
    b.setProperty("variante", variante)
    poser_icone(b, nom, taille)
    b.setToolTip(aide)
    b.setAccessibleName(aide.split(" (")[0])
    b.setCheckable(cochable)
    if texte:
        b.setText(texte)
        b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    return b


ROLES_CAPTION = ("section", "badge", "badge-accent")


def etiquette(texte: str, role: str = "") -> QLabel:
    l = QLabel(texte)
    if role:
        l.setProperty("role", role)
    if role in ROLES_CAPTION:
        # Capitales espacées du style caption : la feuille de style Qt ne sait pas les faire.
        l.setFont(charte.actuelle().police("caption"))
    if role.startswith("badge"):
        l.setFixedHeight(20)
    return l


class BarreTitrePanneau(QWidget):
    """Barre de titre de 36 px. QDockWidget se règle sur la taille suggérée de sa barre de titre,
    pas sur sa hauteur fixe : sans cette correction, le contenu recouvrait le bas de la barre."""

    def sizeHint(self) -> QSize:
        return QSize(super().sizeHint().width(), 36)

    def minimumSizeHint(self) -> QSize:
        return QSize(super().minimumSizeHint().width(), 36)


class EnTetePanneau(BarreTitrePanneau):
    """Barre de titre d'un panneau ancrable : titre, précision, outils, bouton Détacher."""

    def __init__(self, dock: QDockWidget, titre: str):
        super().__init__(dock)
        self.setProperty("role", "entete")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(36)
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(12, 0, 6, 0)
        self._lay.setSpacing(8)
        self.titre = etiquette(titre)
        self.titre.setStyleSheet("font-weight: 500;")
        self.precision = etiquette("", "secondaire")
        self._lay.addWidget(self.titre)
        self._lay.addWidget(self.precision)
        self._lay.addStretch(1)
        self._outils = QHBoxLayout()
        self._outils.setSpacing(4)
        self._lay.addLayout(self._outils)
        detacher = bouton_icone("picture-in-picture-2", f"Détacher le panneau {titre} "
                                                        "(ou double-clic sur son titre)")
        detacher.clicked.connect(lambda: dock.setFloating(not dock.isFloating()))
        self._lay.addWidget(detacher)

    def ajouter(self, widget: QWidget):
        self._outils.addWidget(widget)


def panneau(titre: str, contenu: QWidget, nom: str, parent,
            titre_visible: bool = True) -> tuple[QDockWidget, EnTetePanneau | None]:
    """Panneau ancrable. Sans titre visible (timeline, vumètres), il n'a pas de barre du tout :
    on le détache depuis le menu Fenêtre."""
    d = QDockWidget(titre, parent)
    d.setObjectName(nom)
    d.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable |
                  QDockWidget.DockWidgetClosable)
    entete = EnTetePanneau(d, titre) if titre_visible else None
    d.setTitleBarWidget(entete if entete is not None else QWidget(d))
    contenu.setProperty("role", "panneau")
    contenu.setAttribute(Qt.WA_StyledBackground, True)
    d.setWidget(contenu)
    return d, entete


class ChampTimecode(QStackedWidget):
    """Timecode HH:MM:SS:II, images en accent. Un clic (ou Entrée) permet de taper une
    position ; « +12 » ou « -12 » déplace d'autant d'images."""
    position_demandee = Signal(int)

    def __init__(self, taille_px: int = 15, parent=None):
        super().__init__(parent)
        self._taille = taille_px
        self.affichage = QLabel()
        self.affichage.setTextFormat(Qt.RichText)
        self.affichage.setFocusPolicy(Qt.StrongFocus)
        self.affichage.setToolTip("Cliquez pour taper une position, ou +12 et -12 pour "
                                  "avancer ou reculer de 12 images.")
        self.affichage.setAccessibleName("Timecode de la tête de lecture")
        self.saisie = QLineEdit()
        self.saisie.setProperty("role", "timecode")
        self.addWidget(self.affichage)
        self.addWidget(self.saisie)
        self._images = 0
        self._tc_debut = 0
        self._cadence = Fraction(24)
        self._drop = False
        self.affichage.mousePressEvent = lambda e: self._editer()
        self.affichage.keyPressEvent = self._touche
        self.saisie.returnPressed.connect(self._valider)
        self.saisie.editingFinished.connect(lambda: self.setCurrentWidget(self.affichage))
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.appliquer_charte()

    def appliquer_charte(self):
        c = charte.actuelle()
        self.affichage.setFont(c.police("timecode", self._taille))
        self.saisie.setFont(c.police("timecode", self._taille))
        self.afficher(self._images, self._tc_debut, self._cadence, self._drop)
        self.setFixedWidth(round(self._taille * 7.6))

    def afficher(self, images: int, tc_debut: int, cadence: Fraction, drop: bool):
        self._images, self._tc_debut, self._cadence, self._drop = images, tc_debut, cadence, drop
        tc = images_vers_tc(tc_debut + images, cadence, drop)
        self.affichage.setText(charte.texte_timecode(tc, charte.actuelle()))

    def text(self) -> str:
        return images_vers_tc(self._tc_debut + self._images, self._cadence, self._drop)

    def _touche(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._editer()
        else:
            QLabel.keyPressEvent(self.affichage, e)

    def _editer(self):
        self.saisie.setText(images_vers_tc(self._tc_debut + self._images, self._cadence,
                                           self._drop))
        self.setCurrentWidget(self.saisie)
        self.saisie.setFocus()
        self.saisie.selectAll()

    def _valider(self):
        texte = self.saisie.text().strip().replace(" ", "")
        try:
            if texte[:1] in "+-" and texte[1:].isdigit():
                cible = self._images + int(texte)
            elif texte.isdigit() and len(texte) <= 8:
                # Saisie rapide : 1000012 vaut 01:00:00:12, comme dans les logiciels de montage.
                texte = texte.zfill(8)
                cible = tc_vers_images(f"{texte[0:2]}:{texte[2:4]}:{texte[4:6]}:{texte[6:8]}",
                                       self._cadence)[0] - self._tc_debut
            else:
                cible = tc_vers_images(texte, self._cadence)[0] - self._tc_debut
        except ValueError:
            self.saisie.selectAll()
            return
        self.setCurrentWidget(self.affichage)
        self.affichage.setFocus()
        self.position_demandee.emit(max(0, cible))


class LigneParametre(QWidget):
    """Ligne de l'inspecteur : libellé, curseur, valeur saisissable avec son unité.
    Double-clic sur le libellé : retour à la valeur par défaut."""
    valeur_finale = Signal(float)

    def __init__(self, libelle: str, minimum: float, maximum: float, valeur: float,
                 unite: str, defaut: float, decimales: int = 0, aide: str = ""):
        super().__init__()
        self._min, self._max, self._defaut = minimum, maximum, defaut
        self._decimales, self._unite = decimales, unite
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.libelle = etiquette(libelle, "libelle")
        self.libelle.setFixedWidth(100)
        self.libelle.setToolTip((aide + " " if aide else "") +
                                "Double-cliquez sur le libellé pour revenir à la valeur par défaut.")
        self.libelle.mouseDoubleClickEvent = lambda e: self._poser(self._defaut, True)
        self.curseur = QSlider(Qt.Horizontal)
        self.curseur.setRange(0, 1000)
        self.curseur.setAccessibleName(libelle)
        self.champ = QLineEdit()
        self.champ.setFixedWidth(80)
        self.champ.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.champ.setFont(charte.actuelle().police("value"))
        self.champ.setAccessibleName(f"{libelle}, valeur")
        lay.addWidget(self.libelle)
        lay.addWidget(self.curseur, 1)
        lay.addWidget(self.champ)
        self.curseur.valueChanged.connect(lambda v: self._afficher(self._de_curseur(v)))
        self.curseur.sliderReleased.connect(lambda: self.valeur_finale.emit(self.valeur))
        self.curseur.actionTriggered.connect(
            lambda a: QTimer.singleShot(0, lambda: None if self.curseur.isSliderDown()
                                        else self.valeur_finale.emit(self.valeur)))
        self.champ.editingFinished.connect(self._saisie)
        self.valeur = valeur
        self._poser(valeur, False)

    def _de_curseur(self, v: int) -> float:
        return self._min + (self._max - self._min) * v / 1000

    def _texte(self, v: float) -> str:
        nombre = f"{v:.{self._decimales}f}".replace(".", ",")
        return f"{nombre} {self._unite}" if self._unite else nombre

    def _afficher(self, v: float):
        self.valeur = v
        self.champ.setText(self._texte(v))

    def _poser(self, v: float, emettre: bool):
        v = max(self._min, min(self._max, v))
        self.curseur.blockSignals(True)
        self.curseur.setValue(round((v - self._min) / max(1e-9, self._max - self._min) * 1000))
        self.curseur.blockSignals(False)
        self._afficher(v)
        if emettre:
            self.valeur_finale.emit(v)

    def _saisie(self):
        texte = self.champ.text().replace(self._unite, "").replace(" ", "").replace(",", ".")
        try:
            self._poser(float(texte.strip()), True)
        except ValueError:
            self._afficher(self.valeur)


class Vumetres(QWidget):
    """Crêtes gauche et droite en dBFS, avec retombée de 24 dB par seconde."""
    PLANCHER = -60.0

    def __init__(self, source, parent=None):
        super().__init__(parent)
        self._source = source
        self._niveaux = [self.PLANCHER, self.PLANCHER]
        self.setMinimumWidth(64)
        self.setMaximumWidth(64)
        self.setToolTip("Niveau de crête du son lu, en décibels. Au-dessus de 0, le son sature.")
        self.setAccessibleName("Vumètres")
        self._minuterie = QTimer(self)
        self._minuterie.timeout.connect(self._actualiser)
        self._minuterie.start(33)

    def _actualiser(self):
        cretes = self._source()
        change = False
        for i in range(2):
            db = 20 * math.log10(max(cretes[i], 1e-6)) if cretes else self.PLANCHER
            nouveau = max(db, self._niveaux[i] - 24 * 0.033, self.PLANCHER)
            if abs(nouveau - self._niveaux[i]) > 0.05:
                self._niveaux[i] = nouveau
                change = True
        if change:
            self.update()

    def texte(self) -> str:
        m = max(self._niveaux)
        if m <= self.PLANCHER + 0.5:
            return "−∞"
        return f"{m:.1f}".replace(".", ",").replace("-", "−")

    def paintEvent(self, _e):
        """Deux barres (gauche, droite), l'échelle en dB à côté, la crête en haut, L et R en bas."""
        c = charte.actuelle()
        p = QPainter(self)
        p.fillRect(self.rect(), c.c("surface"))
        p.setPen(c.c("ink-muted"))
        p.setFont(c.police("value", 10))
        p.drawText(QRectF(0, 4, self.width(), 14), Qt.AlignHCenter, self.texte())
        haut, bas = 24, self.height() - 22
        hauteur = max(10, bas - haut)
        largeur = 7
        x0 = 8
        seuil_jaune = (-6 - self.PLANCHER) / -self.PLANCHER
        seuil_rouge = (-1 - self.PLANCHER) / -self.PLANCHER
        for i, db in enumerate(self._niveaux):
            x = x0 + i * (largeur + 3)
            p.fillRect(QRectF(x, haut, largeur, hauteur), c.c("bg-app"))
            frac = (db - self.PLANCHER) / -self.PLANCHER
            for debut, fin, couleur in ((0, min(frac, seuil_jaune), "accent-2"),
                                        (seuil_jaune, min(frac, seuil_rouge), "warning"),
                                        (seuil_rouge, min(frac, 1.0), "danger")):
                if fin > debut:
                    y1 = haut + hauteur * (1 - fin)
                    p.fillRect(QRectF(x, y1, largeur, hauteur * (fin - debut)), c.c(couleur))
            p.drawText(QRectF(x - 2, bas + 4, largeur + 4, 14), Qt.AlignHCenter, "LR"[i])
        # Échelle : graduations lisibles tant que la hauteur le permet.
        echelle_x = x0 + 2 * (largeur + 3) + 3
        dernier = -100.0
        for db in (0, -6, -12, -18, -24, -36, -48, -60):
            y = haut + hauteur * (-db / -self.PLANCHER)
            if y - dernier < 12:
                continue
            dernier = y
            p.fillRect(QRectF(echelle_x, y, 3, 1), c.c("ink-faint"))
            p.drawText(QRectF(echelle_x + 7, y - 7, self.width() - echelle_x - 7, 14),
                       Qt.AlignLeft | Qt.AlignVCenter, str(db).replace("-", "\u2212"))
        p.end()



class PanneauOnglets(QStackedWidget):
    """Contenu d'un panneau à onglets ; la barre d'onglets sert de titre au panneau ancrable."""
    onglet_change = Signal(int)

    def __init__(self, dock: QDockWidget, onglets: list[tuple[str, QWidget]]):
        super().__init__()
        self.entete = BarreTitrePanneau(dock)
        self.entete.setProperty("role", "onglets")
        self.entete.setAttribute(Qt.WA_StyledBackground, True)
        self.entete.setFixedHeight(36)
        lay = QHBoxLayout(self.entete)
        lay.setContentsMargins(4, 0, 6, 0)
        lay.setSpacing(0)
        self.boutons: list[QToolButton] = []
        for i, (nom, widget) in enumerate(onglets):
            b = QToolButton()
            b.setText(nom)
            b.setProperty("variante", "onglet")
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.clicked.connect(lambda _=False, i=i: self.choisir(i))
            lay.addWidget(b)
            self.boutons.append(b)
            widget.setProperty("role", "panneau")
            widget.setAttribute(Qt.WA_StyledBackground, True)
            self.addWidget(widget)
        lay.addStretch(1)
        self._outils = QHBoxLayout()
        self._outils.setSpacing(4)
        lay.addLayout(self._outils)
        detacher = bouton_icone("picture-in-picture-2", "Détacher le panneau (ou double-clic "
                                                        "sur sa barre d'onglets)")
        detacher.clicked.connect(lambda: dock.setFloating(not dock.isFloating()))
        lay.addWidget(detacher)
        dock.setTitleBarWidget(self.entete)
        dock.setWidget(self)
        self.choisir(0)

    def ajouter_outil(self, widget: QWidget):
        self._outils.addWidget(widget)

    def choisir(self, i: int):
        self.setCurrentIndex(i)
        self.boutons[i].setChecked(True)
        self.onglet_change.emit(i)


def panneau_onglets(onglets: list[tuple[str, QWidget]], nom: str,
                    parent) -> tuple[QDockWidget, PanneauOnglets]:
    d = QDockWidget(onglets[0][0], parent)
    d.setObjectName(nom)
    d.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable |
                  QDockWidget.DockWidgetClosable)
    return d, PanneauOnglets(d, onglets)
