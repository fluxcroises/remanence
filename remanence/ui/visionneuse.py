"""Visionneuse : image en texture OpenGL 16 bits, sur fond noir, avec le transport."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QImage, QPainter
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QHBoxLayout, QMenu, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from remanence.media.timecode import images_vers_tc
from remanence.ui import charte
from remanence.ui.composants import ChampTimecode, bouton_icone, etiquette, poser_icone
from remanence.ui.lecture import QUALITES

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


class ZoneImage(QOpenGLWidget):
    """Affiche la dernière image reçue, centrée sans déformation.

    Sans OpenGL 3.3 (pilote ancien, bureau à distance), l'image passe par QPainter.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._image: np.ndarray | None = None
        self._a_envoyer = False
        self._ctx = None
        self._texture = None
        self._echec_gl = moderngl is None
        self._message = "Glissez un média sur la timeline pour le voir ici."
        self.setMinimumSize(320, 180)
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

    def _rect_image(self, largeur: float, hauteur: float) -> QRectF:
        h, l = self._image.shape[:2]
        s = min(largeur / l, hauteur / h)
        return QRectF((largeur - l * s) / 2, (hauteur - h * s) / 2, l * s, h * s)

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
        r = self._rect_image(lp, hp)
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


class Visionneuse(QWidget):
    demande_position = Signal(int)
    demande_lecture = Signal()
    demande_qualite = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.zone = ZoneImage(self)
        cadre = QWidget()
        cadre.setProperty("role", "noir")
        cadre.setAttribute(Qt.WA_StyledBackground, True)
        lc = QVBoxLayout(cadre)
        lc.setContentsMargins(16, 16, 16, 16)
        lc.addWidget(self.zone)
        self._cadre = cadre

        self.points = etiquette("E –  ·  S –", "etat")
        self.points.setToolTip("Points d'entrée (I) et de sortie (O) de la séquence.")
        self.points.setFixedWidth(240)
        self.b_debut = bouton_icone("skip-back", "Aller au début (Origine)")
        self.b_prec = bouton_icone("chevron-left", "Image précédente (flèche gauche)")
        self.b_lire = bouton_icone("play", "Lire ou mettre en pause (Espace). J, K et L "
                                           "pilotent la lecture arrière, l'arrêt et la lecture avant.",
                                   variante="panneau")
        self.b_lire.setFixedSize(40, 32)
        self.b_lire.setProperty("variante", "lecture")
        self.b_suiv = bouton_icone("chevron-right", "Image suivante (flèche droite)")
        self.b_fin = bouton_icone("skip-forward", "Aller à la fin (Fin)")
        self.b_boucle = bouton_icone("repeat", "Lire en boucle entre les points d'entrée et de "
                                               "sortie, ou sur toute la séquence (Ctrl+B)",
                                     cochable=True)
        for b in (self.b_debut, self.b_prec, self.b_suiv, self.b_fin, self.b_boucle):
            b.setFixedSize(32, 28)
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
        transport.setContentsMargins(12, 0, 12, 0)
        transport.setSpacing(6)
        transport.addWidget(self.points)
        transport.addStretch(1)
        for b in (self.b_debut, self.b_prec, self.b_lire, self.b_suiv, self.b_fin, self.b_boucle):
            transport.addWidget(b)
        transport.addStretch(1)
        transport.addWidget(self.timecode)
        barre = QWidget()
        barre.setProperty("role", "pied")
        barre.setAttribute(Qt.WA_StyledBackground, True)
        barre.setFixedHeight(48)
        barre.setLayout(transport)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(cadre, 1)
        lay.addWidget(barre)
        self.b_lire.clicked.connect(lambda: self.demande_lecture.emit())

    def choisir_qualite(self, cle: str, emettre: bool = True):
        self.qualite.setText(LIBELLES_QUALITE[cle])
        self._qualite = cle
        if emettre:
            self.demande_qualite.emit(cle)

    def etat_lecture(self, lecture: bool):
        poser_icone(self.b_lire, "pause" if lecture else "play")
        self.b_lire.setAccessibleName("Pause" if lecture else "Lire")

    def afficher_points(self, seq):
        cad = seq.fraction_cadence

        def tc(f):
            return "–" if f is None else images_vers_tc(seq.tc_debut + f, cad, seq.tc_drop)
        self.points.setText(f"E {tc(seq.point_entree)}  ·  S {tc(seq.point_sortie)}")
