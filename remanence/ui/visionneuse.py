"""Visionneuse : image en texture OpenGL 16 bits flottants, timecode et transport."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from remanence.ui import theme

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
        self._ctx.clear(0.08, 0.08, 0.08)
        h, l = self._image.shape[:2]
        if self._a_envoyer:
            # uint16 normalisé par la carte (aperçu rapide) ou float16 (image composée).
            dtype = "nu2" if self._image.dtype == np.uint16 else "f2"
            if self._texture is None or self._texture.size != (l, h) or                     self._texture.dtype != dtype:
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
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(20, 20, 20))
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
            p.setPen(QColor(theme.TEXTE_SECONDAIRE))
            p.drawText(self.rect(), Qt.AlignCenter | Qt.TextWordWrap, self._message)
        p.end()


class Visionneuse(QWidget):
    demande_position = Signal(int)
    demande_lecture = Signal()
    demande_qualite = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.zone = ZoneImage(self)
        self.timecode = QLabel("00:00:00:00")
        self.timecode.setProperty("role", "timecode")
        self.timecode.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.timecode.setToolTip("Timecode de la tête de lecture, calé sur celui de la séquence.")
        self.info = QLabel("")
        self.info.setProperty("role", "secondaire")

        self.b_debut = QPushButton("Début")
        self.b_prec = QPushButton("Image −1")
        self.b_lire = QPushButton("Lire")
        self.b_lire.setCheckable(True)
        self.b_suiv = QPushButton("Image +1")
        self.b_fin = QPushButton("Fin")
        for b, aide in [(self.b_debut, "Aller au début (Origine)"),
                        (self.b_prec, "Reculer d'une image (flèche gauche)"),
                        (self.b_lire, "Lire ou mettre en pause (Espace). J, K et L pilotent "
                                      "la lecture arrière, l'arrêt et la lecture avant."),
                        (self.b_suiv, "Avancer d'une image (flèche droite)"),
                        (self.b_fin, "Aller à la fin (Fin)")]:
            b.setToolTip(aide)
            b.setFocusPolicy(Qt.TabFocus)
        self.qualite = QComboBox()
        self.qualite.addItems(["Pleine", "1/2", "1/4"])
        self.qualite.setCurrentText("1/2")
        self.qualite.setToolTip("Résolution de l'aperçu. En 1/2 et 1/4, la lecture utilise les "
                                "proxies quand ils existent. L'export est toujours en pleine "
                                "résolution.")
        self.qualite.currentTextChanged.connect(self.demande_qualite)

        transport = QHBoxLayout()
        transport.addWidget(self.timecode)
        transport.addSpacing(12)
        for b in (self.b_debut, self.b_prec, self.b_lire, self.b_suiv, self.b_fin):
            transport.addWidget(b)
        transport.addStretch(1)
        transport.addWidget(self.info)
        transport.addWidget(QLabel("Aperçu"))
        transport.addWidget(self.qualite)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addWidget(self.zone, 1)
        lay.addLayout(transport)
        self.b_lire.clicked.connect(lambda: self.demande_lecture.emit())

    def etat_lecture(self, lecture: bool):
        self.b_lire.setChecked(lecture)
        self.b_lire.setText("Pause" if lecture else "Lire")
