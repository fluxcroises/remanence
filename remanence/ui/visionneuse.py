"""Moniteurs source et programme : image en texture OpenGL 16 bits sur fond noir, barre de
défilement, transport et timecode."""

from __future__ import annotations

from fractions import Fraction

import numpy as np
from PySide6.QtCore import QMimeData, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QDrag, QImage, QPainter
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QMenu, QSizePolicy, QToolButton,
                               QVBoxLayout, QWidget)

from remanence.ui import charte
from remanence.ui.composants import ChampTimecode, bouton_icone, poser_icone
from remanence.ui.lecture import QUALITES
from remanence.ui.medias import MIME_MEDIA

try:
    import moderngl
except Exception:
    moderngl = None

SOMMETS = """
#version 330
in vec2 pos;
out vec2 uv;
void main() { uv = vec2(pos.x * 0.5 + 0.5, 0.5 - pos.y * 0.5); gl_Position = vec4(pos, 0.0, 1.0); }
"""
FRAGMENTS = """
#version 330
uniform sampler2D image;
in vec2 uv;
out vec4 couleur;
void main() { couleur = vec4(texture(image, uv).rgb, 1.0); }
"""
LIBELLES_QUALITE = {"Pleine": "Pleine résolution", "1/2": "Proxy 1/2", "1/4": "Proxy 1/4"}
ZOOMS = [("Adapter", None), ("25 %", 0.25), ("50 %", 0.5), ("100 %", 1.0), ("200 %", 2.0)]


class ZoneImage(QOpenGLWidget):
    """Affiche la dernière image reçue, sans déformation : ajustée à la zone ou à un zoom fixe
    (100 % = un pixel de la séquence par pixel d'écran), déplaçable à la souris quand elle dépasse.

    Sans OpenGL 3.3 (pilote ancien, bureau à distance), l'image passe par QPainter.
    """
    glisser_depart = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._image: np.ndarray | None = None
        self._a_envoyer = False
        self._ctx = None
        self._texture = None
        self._echec_gl = moderngl is None
        self._message = ""
        self.zoom: float | None = None
        self.taille_reference: tuple[int, int] | None = None
        self._decalage = QPointF(0, 0)
        self._clic = None
        self.glissable = False
        self.setMinimumSize(160, 90)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    @property
    def rendu_gpu(self) -> bool:
        return self._ctx is not None and not self._echec_gl

    def montrer(self, image: np.ndarray):
        self._image = image
        self._a_envoyer = True
        self._message = ""
        self.update()

    def montrer_message(self, texte: str):
        self._image = None
        self._message = texte
        self.update()

    def definir_zoom(self, zoom: float | None):
        self.zoom = zoom
        self._decalage = QPointF(0, 0)
        self.update()

    def initializeGL(self):
        if self._echec_gl:
            return
        try:
            self._ctx = moderngl.create_context()
            self._prog = self._ctx.program(vertex_shader=SOMMETS, fragment_shader=FRAGMENTS)
            quad = np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype="f4")
            self._vbo = self._ctx.buffer(quad.tobytes())
            self._vao = self._ctx.vertex_array(self._prog, [(self._vbo, "2f", "pos")])
        except Exception:
            self._ctx = None
            self._echec_gl = True

    def _rect_image(self, largeur: float, hauteur: float, ratio: float = 1.0) -> QRectF:
        h, l = self._image.shape[:2]
        if self.zoom is None:
            s = min(largeur / l, hauteur / h)
        else:
            reference = self.taille_reference[0] if self.taille_reference else l
            s = self.zoom * reference / l * ratio
        x = (largeur - l * s) / 2 + self._decalage.x() * ratio
        y = (hauteur - h * s) / 2 + self._decalage.y() * ratio
        return QRectF(x, y, l * s, h * s)

    def paintGL(self):
        if self._echec_gl or self._ctx is None or self._image is None:
            self._peindre_qpainter()
            return
        ratio = self.devicePixelRatioF()
        lp, hp = int(self.width() * ratio), int(self.height() * ratio)
        fbo = self._ctx.detect_framebuffer(self.defaultFramebufferObject())
        fbo.use()
        self._ctx.viewport = (0, 0, lp, hp)
        fond = charte.actuelle().c("viewer-bg")
        self._ctx.clear(fond.redF(), fond.greenF(), fond.blueF())
        h, l = self._image.shape[:2]
        if self._a_envoyer:
            # uint16 normalisé par la carte (aperçu rapide) ou float16 (image composée).
            dtype = "nu2" if self._image.dtype == np.uint16 else "f2"
            if self._texture is None or self._texture.size != (l, h) or \
                    self._texture.dtype != dtype:
                if self._texture is not None:
                    self._texture.release()
                self._texture = self._ctx.texture((l, h), 3, dtype=dtype)
                self._texture.filter = (moderngl.LINEAR, moderngl.LINEAR)
            self._texture.write(self._image.tobytes())
            self._a_envoyer = False
        r = self._rect_image(lp, hp, ratio)
        self._ctx.viewport = (int(r.x()), int(hp - r.y() - r.height()), int(r.width()),
                              int(r.height()))
        self._texture.use(0)
        self._vao.render(moderngl.TRIANGLE_STRIP)

    def _peindre_qpainter(self):
        c = charte.actuelle()
        p = QPainter(self)
        p.fillRect(self.rect(), c.c("viewer-bg"))
        if self._image is not None:
            if self._image.dtype == np.uint16:
                rgb = (self._image >> 8).astype(np.uint8)
            else:
                rgb = np.clip(self._image.astype(np.float32) * 255.0 + 0.5, 0, 255).astype(np.uint8)
            rgb = np.ascontiguousarray(rgb)
            h, l = rgb.shape[:2]
            qimg = QImage(rgb.data, l, h, 3 * l, QImage.Format_RGB888)
            p.drawImage(self._rect_image(self.width(), self.height()), qimg)
        elif self._message:
            p.setPen(c.c("ink-muted"))
            p.drawText(self.rect().adjusted(24, 0, -24, 0), Qt.AlignCenter | Qt.TextWordWrap,
                       self._message)
        p.end()

    # Souris : déplacer l'image zoomée, ou glisser la source vers la timeline.

    def mousePressEvent(self, e):
        self._clic = e.position()
        self._decalage_depart = QPointF(self._decalage)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._clic is None or not e.buttons() & Qt.LeftButton:
            return
        delta = e.position() - self._clic
        if self.zoom is not None:
            self._decalage = self._decalage_depart + delta
            self.update()
        elif self.glissable and delta.manhattanLength() > 10:
            self._clic = None
            self.glisser_depart.emit()

    def mouseReleaseEvent(self, e):
        self._clic = None
        super().mouseReleaseEvent(e)


class BarreDefilement(QWidget):
    """Fine barre sous l'image : toute la durée, la zone entre E et S teintée, la tête de
    lecture. Un clic ou un glisser déplace la tête."""
    position_demandee = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(14)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Cliquez ou glissez pour vous déplacer dans le média.")
        self.duree = 0
        self.position = 0
        self.entree: int | None = None
        self.sortie: int | None = None

    def definir(self, duree: int, position: int, entree: int | None, sortie: int | None):
        self.duree, self.position, self.entree, self.sortie = duree, position, entree, sortie
        self.update()

    def _x(self, f: float) -> float:
        return 8 + (self.width() - 16) * f / max(1, self.duree)

    def paintEvent(self, _e):
        c = charte.actuelle()
        p = QPainter(self)
        p.fillRect(self.rect(), c.c("surface"))
        milieu = self.height() / 2
        p.fillRect(QRectF(8, milieu - 1, self.width() - 16, 2), c.c("line"))
        if self.duree and (self.entree is not None or self.sortie is not None):
            a = self._x(self.entree or 0)
            b = self._x(self.sortie if self.sortie is not None else self.duree)
            p.fillRect(QRectF(a, 2, max(1.0, b - a), self.height() - 4), c.c("surface-hover"))
            p.fillRect(QRectF(a, milieu - 1, max(1.0, b - a), 2), c.c("ink-muted"))
            p.fillRect(QRectF(a, 2, 1, self.height() - 4), c.c("ink-muted"))
            p.fillRect(QRectF(b - 1, 2, 1, self.height() - 4), c.c("ink-muted"))
        if self.duree:
            x = self._x(self.position)
            p.fillRect(QRectF(x - 1, 1, 2, self.height() - 2), c.c("playhead"))
        p.end()

    def _aller(self, x: float):
        if self.duree:
            f = round((x - 8) / max(1, self.width() - 16) * self.duree)
            self.position_demandee.emit(max(0, min(self.duree - 1, f)))

    def mousePressEvent(self, e):
        self._aller(e.position().x())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._aller(e.position().x())


class Moniteur(QWidget):
    """Un moniteur : image, barre de défilement, transport, timecode.

    Il ne lit rien lui-même : ses boutons émettent des demandes, la fenêtre les adresse au
    moteur de lecture de la source ou du programme.
    """
    demande_position = Signal(int)
    demande_lecture = Signal()
    demande_vitesse = Signal(int)
    demande_entree = Signal()
    demande_sortie = Signal()
    demande_aller_entree = Signal()
    demande_aller_sortie = Signal()
    demande_qualite = Signal(str)
    active = Signal()

    def __init__(self, nom: str, parent=None):
        super().__init__(parent)
        self.nom = nom
        self.zone = ZoneImage(self)
        cadre = QWidget()
        cadre.setProperty("role", "noir")
        cadre.setAttribute(Qt.WA_StyledBackground, True)
        lc = QVBoxLayout(cadre)
        lc.setContentsMargins(12, 12, 12, 12)
        lc.addWidget(self.zone)
        self.defilement = BarreDefilement()
        self.defilement.position_demandee.connect(self.demande_position)

        self.zoom = QComboBox()
        for libelle, valeur in ZOOMS:
            self.zoom.addItem(libelle, valeur)
        self.zoom.setToolTip("Taille de l'image : ajustée au moniteur, ou à un zoom fixe. "
                             "Glissez l'image pour la déplacer quand elle dépasse.")
        self.zoom.setAccessibleName(f"Zoom du moniteur {nom}")
        self.zoom.currentIndexChanged.connect(lambda _i: self.zone.definir_zoom(
            self.zoom.currentData()))
        self.zoom.setFixedWidth(104)

        def b(icone, aide, signal=None, texte=""):
            bouton = bouton_icone(icone, aide) if icone else QToolButton()
            if not icone:
                bouton.setText(texte)
                bouton.setProperty("variante", "discret")
                bouton.setToolTip(aide)
                bouton.setAccessibleName(aide.split(" (")[0])
            bouton.setFixedSize(30, 28)
            if signal is not None:
                bouton.clicked.connect(lambda: signal.emit())
            return bouton

        self.b_aller_entree = b("arrow-left-to-line", "Aller au point d'entrée",
                                self.demande_aller_entree)
        self.b_entree = b(None, "Marquer le point d'entrée (I)", self.demande_entree, "[")
        self.b_prec = b("rewind", "Lecture arrière (J), répétez pour accélérer")
        self.b_prec.clicked.connect(lambda: self.demande_vitesse.emit(-1))
        self.b_lire = bouton_icone("play", "Lire ou mettre en pause (Espace)", variante="lecture")
        self.b_lire.setFixedSize(40, 32)
        self.b_lire.clicked.connect(lambda: self.demande_lecture.emit())
        self.b_suiv = b("fast-forward", "Lecture avant (L), répétez pour accélérer")
        self.b_suiv.clicked.connect(lambda: self.demande_vitesse.emit(1))
        self.b_sortie = b(None, "Marquer le point de sortie (O)", self.demande_sortie, "]")
        self.b_aller_sortie = b("arrow-right-to-line", "Aller au point de sortie",
                                self.demande_aller_sortie)
        self.b_boucle = bouton_icone("repeat", "Lire en boucle entre les points d'entrée et de "
                                               "sortie (Ctrl+B)", cochable=True)
        self.b_boucle.setFixedSize(30, 28)
        self.timecode = ChampTimecode(15)
        self.timecode.position_demandee.connect(self.demande_position)

        self.qualite = QToolButton()
        self.qualite.setProperty("variante", "badge")
        self.qualite.setPopupMode(QToolButton.InstantPopup)
        self.qualite.setToolTip("Résolution de l'aperçu. En 1/2 et 1/4, la lecture utilise les "
                                "proxies quand ils existent. L'export est toujours en pleine "
                                "résolution.")
        menu = QMenu(self.qualite)
        for cle in QUALITES:
            menu.addAction(LIBELLES_QUALITE[cle], lambda cle=cle: self.choisir_qualite(cle))
        self.qualite.setMenu(menu)
        self.choisir_qualite("1/2", emettre=False)

        transport = QHBoxLayout()
        transport.setContentsMargins(10, 0, 10, 0)
        transport.setSpacing(4)
        gauche = QHBoxLayout()
        gauche.addWidget(self.zoom)
        gauche.addStretch(1)
        transport.addLayout(gauche, 1)
        for w in (self.b_aller_entree, self.b_entree, self.b_prec, self.b_lire, self.b_suiv,
                  self.b_sortie, self.b_aller_sortie):
            transport.addWidget(w)
        droite = QHBoxLayout()
        droite.addSpacing(8)
        droite.addWidget(self.b_boucle)
        droite.addStretch(1)
        droite.addWidget(self.timecode)
        transport.addLayout(droite, 1)
        barre = QWidget()
        barre.setProperty("role", "pied")
        barre.setAttribute(Qt.WA_StyledBackground, True)
        barre.setFixedHeight(44)
        barre.setLayout(transport)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(cadre, 1)
        lay.addWidget(self.defilement)
        lay.addWidget(barre)
        for w in (self.zone, self.defilement, barre):
            w.installEventFilter(self)

    def eventFilter(self, objet, e):
        # Tout clic dans le moniteur le rend actif pour les raccourcis de lecture.
        if e.type() == e.Type.MouseButtonPress:
            self.active.emit()
        return False

    def choisir_qualite(self, cle: str, emettre: bool = True):
        self.qualite.setText(LIBELLES_QUALITE[cle])
        self._qualite = cle
        if emettre:
            self.demande_qualite.emit(cle)

    @property
    def qualite_choisie(self) -> str:
        return self._qualite

    def etat_lecture(self, lecture: bool):
        poser_icone(self.b_lire, "pause" if lecture else "play")
        self.b_lire.setAccessibleName("Pause" if lecture else "Lire")

    def afficher_position(self, f: int, duree: int, tc_debut: int, cadence: Fraction, drop: bool,
                          entree: int | None, sortie: int | None):
        self.timecode.afficher(f, tc_debut, cadence, drop)
        self.defilement.definir(duree, f, entree, sortie)


def glisser_source(widget: QWidget, media_id: str, entree: int, sortie: int):
    """Glisser l'image source vers la timeline : seule la partie entre E et S est posée."""
    donnees = QMimeData()
    donnees.setData(MIME_MEDIA, f"{media_id}@{entree}:{sortie}".encode())
    glisser = QDrag(widget)
    glisser.setMimeData(donnees)
    glisser.exec(Qt.CopyAction)


def peindre_cadre_actif(widget: QWidget, actif: bool):
    """Repère du moniteur actif : un filet mauve sous son en-tête (ce qu'on pilote au clavier)."""
    widget.setProperty("actif", actif)
    widget.style().unpolish(widget)
    widget.style().polish(widget)

