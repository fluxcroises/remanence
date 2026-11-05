"""Moniteurs source et programme : image en texture OpenGL 16 bits sur fond noir, barre de
défilement, transport et timecode."""

from __future__ import annotations

import copy
import math
from fractions import Fraction

import numpy as np
from PySide6.QtCore import QMimeData, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QDrag, QImage, QPainter, QPainterPath, QPen, QPolygonF, QTransform
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QMenu, QSizePolicy, QToolButton,
                               QVBoxLayout, QWidget)

from remanence.effets.masques import contour
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
# Avant / après : mode 1, volet (l'avant à gauche du trait) ; mode 2, côte à côte (l'avant
# à gauche). LUT d'affichage : texture 3D, le rouge sur x, échantillonnée au centre des cases.
FRAGMENTS = """
#version 330
uniform sampler2D image;
uniform sampler2D avant;
uniform sampler3D lut;
uniform int mode;
uniform float volet;
uniform float trait;
uniform vec3 couleur_trait;
uniform int a_lut;
uniform float lut_n;
uniform vec3 lut_min;
uniform vec3 lut_max;
in vec2 uv;
out vec4 couleur;

vec3 lire() {
    if (mode == 1) {
        return uv.x < volet ? texture(avant, uv).rgb : texture(image, uv).rgb;
    }
    if (mode == 2) {
        return uv.x < 0.5 ? texture(avant, vec2(uv.x * 2.0, uv.y)).rgb
                          : texture(image, vec2(uv.x * 2.0 - 1.0, uv.y)).rgb;
    }
    return texture(image, uv).rgb;
}

void main() {
    vec3 c = lire();
    if (a_lut == 1) {
        vec3 t = clamp((c - lut_min) / max(lut_max - lut_min, vec3(1e-6)), 0.0, 1.0);
        c = texture(lut, t * (lut_n - 1.0) / lut_n + 0.5 / lut_n).rgb;
    }
    if (mode == 1 && abs(uv.x - volet) < trait) {
        c = couleur_trait;
    }
    couleur = vec4(c, 1.0);
}
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
        # Avant / après : l'image sans effets, et la façon de la montrer.
        self._avant: np.ndarray | None = None
        self.comparaison = "apres"
        self.volet = 0.5
        self._en_volet = False
        self.lut = None
        self._lut_a_envoyer = False
        self._texture_lut = None
        self._texture_avant = None
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
        self.calque: CalqueMasques | None = None
        # Calque des vecteurs de mouvement (espace Datamosh).
        self.vecteurs = None
        # Cadre et poignées de la transformation du clip choisi.
        self.transformation = None
        self.setMinimumSize(160, 90)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    @property
    def rendu_gpu(self) -> bool:
        return self._ctx is not None and not self._echec_gl

    def montrer(self, image):
        """Une image, ou (après, avant) pour un volet ou un côte à côte."""
        if isinstance(image, tuple):
            self._image, self._avant = image
        else:
            self._image, self._avant = image, None
        self._a_envoyer = True
        self._message = ""
        self.update()
        for calque in self._calques():
            if calque.isVisible():
                calque.update()

    def _calques(self) -> list:
        return [c for c in (self.calque, self.vecteurs, self.transformation)
                if c is not None]

    def resizeEvent(self, e):
        super().resizeEvent(e)
        for calque in self._calques():
            calque.setGeometry(self.rect())

    def definir_lut(self, lut):
        """LUT d'affichage (rendu.lut.Lut) ou None."""
        self.lut = lut
        self._lut_a_envoyer = True
        self.update()

    @property
    def mode_comparaison(self) -> int:
        if self._avant is None or self._image is None or self._avant.shape != self._image.shape:
            return 0
        return {"volet": 1, "cote": 2}.get(self.comparaison, 0)

    def montrer_message(self, texte: str):
        self._image = None
        self._message = texte
        self.update()

    def definir_zoom(self, zoom: float | None):
        self.zoom = zoom
        self._decalage = QPointF(0, 0)
        self.update()
        for calque in self._calques():
            calque.update()

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
        if self.mode_comparaison == 2:
            l *= 2  # côte à côte : deux images dans la largeur
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
            if self._avant is not None:
                dtype_avant = "nu2" if self._avant.dtype == np.uint16 else "f2"
                ha, la = self._avant.shape[:2]
                if self._texture_avant is None or self._texture_avant.size != (la, ha) or \
                        self._texture_avant.dtype != dtype_avant:
                    if self._texture_avant is not None:
                        self._texture_avant.release()
                    self._texture_avant = self._ctx.texture((la, ha), 3, dtype=dtype_avant)
                    self._texture_avant.filter = (moderngl.LINEAR, moderngl.LINEAR)
                self._texture_avant.write(np.ascontiguousarray(self._avant).tobytes())
            self._a_envoyer = False
        if self._lut_a_envoyer:
            if self._texture_lut is not None:
                self._texture_lut.release()
                self._texture_lut = None
            if self.lut is not None:
                n = self.lut.taille
                self._texture_lut = self._ctx.texture3d((n, n, n), 3, self.lut.table.tobytes(),
                                                        dtype="f4")
                self._texture_lut.filter = (moderngl.LINEAR, moderngl.LINEAR)
                self._texture_lut.repeat_x = self._texture_lut.repeat_y = False
                self._texture_lut.repeat_z = False
            self._lut_a_envoyer = False
        r = self._rect_image(lp, hp, ratio)
        self._ctx.viewport = (int(r.x()), int(hp - r.y() - r.height()), int(r.width()),
                              int(r.height()))
        mode = self.mode_comparaison
        self._texture.use(0)
        if self._texture_avant is not None:
            self._texture_avant.use(1)
        if self._texture_lut is not None:
            self._texture_lut.use(2)
        trait = charte.actuelle().c("accent")
        for nom, valeur in (("image", 0), ("avant", 1), ("lut", 2), ("mode", mode),
                            ("volet", float(self.volet)),
                            ("trait", ratio / max(1.0, r.width())),
                            ("couleur_trait", (trait.redF(), trait.greenF(), trait.blueF())),
                            ("a_lut", int(self._texture_lut is not None))):
            if nom in self._prog:
                self._prog[nom].value = valeur
        if self.lut is not None:
            for nom, valeur in (("lut_n", float(self.lut.taille)), ("lut_min", self.lut.minimum),
                                ("lut_max", self.lut.maximum)):
                if nom in self._prog:
                    self._prog[nom].value = tuple(valeur) if nom != "lut_n" else valeur
        self._vao.render(moderngl.TRIANGLE_STRIP)

    def _peindre_qpainter(self):
        c = charte.actuelle()
        p = QPainter(self)
        p.fillRect(self.rect(), c.c("viewer-bg"))
        if self._image is not None:
            rgb = np.clip(self.image_affichee() * 255.0 + 0.5, 0, 255).astype(np.uint8)
            rgb = np.ascontiguousarray(rgb)
            h, l = rgb.shape[:2]
            qimg = QImage(rgb.data, l, h, 3 * l, QImage.Format_RGB888)
            p.drawImage(self._rect_image(self.width(), self.height()), qimg)
        elif self._message:
            p.setPen(c.c("ink-muted"))
            p.drawText(self.rect().adjusted(24, 0, -24, 0), Qt.AlignCenter | Qt.TextWordWrap,
                       self._message)
        p.end()

    def image_affichee(self) -> np.ndarray:
        """Ce que montre le moniteur, calculé sur le processeur (sans OpenGL, et pour les
        tests) : comparaison avant / après, puis LUT."""
        def flottant(image):
            if image.dtype == np.uint16:
                return image.astype(np.float32) / 65535.0
            return image.astype(np.float32)
        apres = flottant(self._image)
        mode = self.mode_comparaison
        if mode == 1:
            avant = flottant(self._avant)
            limite = int(round(self.volet * apres.shape[1]))
            apres = apres.copy()
            apres[:, :limite] = avant[:, :limite]
        elif mode == 2:
            apres = np.concatenate([flottant(self._avant), apres], axis=1)
        if self.lut is not None:
            from remanence.rendu.lut import appliquer
            apres = appliquer(apres, self.lut)
        return apres

    # Souris : déplacer l'image zoomée, glisser la source vers la timeline, ou tirer le volet.

    def _deplacer_volet(self, pos: QPointF):
        r = self._rect_image(self.width(), self.height())
        if r.width() > 0:
            self.volet = min(1.0, max(0.0, (pos.x() - r.x()) / r.width()))
            self.update()

    def mousePressEvent(self, e):
        if self.mode_comparaison == 1 and e.button() == Qt.LeftButton:
            self._en_volet = True
            self._deplacer_volet(e.position())
            return
        self._clic = e.position()
        self._decalage_depart = QPointF(self._decalage)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._en_volet:
            self._deplacer_volet(e.position())
            return
        if self._clic is None or not e.buttons() & Qt.LeftButton:
            return
        delta = e.position() - self._clic
        if self.zoom is not None:
            self._decalage = self._decalage_depart + delta
            self.update()
            for calque in self._calques():
                calque.update()
        elif self.glissable and delta.manhattanLength() > 10:
            self._clic = None
            self.glisser_depart.emit()

    def mouseReleaseEvent(self, e):
        self._en_volet = False
        self._clic = None
        super().mouseReleaseEvent(e)


class CalqueMasques(QWidget):
    """Contours des masques de l'effet en cours de modification, posés sur l'image. Poignées :
    les quatre coins d'un rectangle ou d'une ellipse, les points d'une forme libre. Glisser
    dedans déplace le masque ; double-clic sur une forme libre : un point de plus ; clic droit
    sur un point : le retirer. Inactif, il laisse passer la souris vers l'image."""
    modifie = Signal(str, list)  # identifiant du masque, nouveaux points

    RAYON = 6

    def __init__(self, zone: "ZoneImage"):
        super().__init__(zone)
        self.zone = zone
        self.masques: list = []
        self._prise = None
        # Masques d'un effet de clip transformé : de l'image du clip (en fraction) vers celle
        # de la séquence. Les masques suivent l'image déplacée, tournée, réduite.
        self.carte = QTransform()
        self.setMouseTracking(True)
        self.montrer_masques(None)

    def en_prise(self) -> bool:
        """Vrai pendant qu'un masque est tiré à la souris."""
        return self._prise is not None

    def montrer_masques(self, masques: list | None, carte: QTransform | None = None):
        """masques : ceux de l'effet modifié (copiés), None pour cacher le calque ; carte : la
        transformation du clip (voir `carte_normalisee`)."""
        self.carte = carte if carte is not None else QTransform()
        self.masques = copy.deepcopy(masques) if masques else []
        actif = masques is not None
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not actif)
        self.setVisible(actif)
        self.setGeometry(self.zone.rect())
        self.update()

    def _rect(self) -> QRectF | None:
        if self.zone._image is None:
            return None
        return self.zone._rect_image(self.zone.width(), self.zone.height())

    def _total(self, r: QRectF) -> QTransform:
        return self.carte * QTransform(r.width(), 0, 0, r.height(), r.x(), r.y())

    def _ecran(self, r: QRectF, pt) -> QPointF:
        return self._total(r).map(QPointF(pt[0], pt[1]))

    def _image(self, r: QRectF, pos: QPointF) -> list[float]:
        q = self._total(r).inverted()[0].map(pos)
        return [q.x(), q.y()]

    @staticmethod
    def _poignees(m) -> list:
        if m.forme == "courbe":
            return m.points
        (ax, ay), (bx, by) = m.points
        return [[ax, ay], [bx, ay], [bx, by], [ax, by]]

    def _chemin(self, r: QRectF, m) -> QPainterPath:
        # Tracé dans l'image du clip, puis porté à l'écran (rotation comprise).
        chemin = QPainterPath()
        if m.forme == "courbe":
            sommets = contour(m.points)
            chemin.addPolygon(QPolygonF([QPointF(x, y) for x, y in sommets]))
            chemin.closeSubpath()
        else:
            zone = QRectF(QPointF(*m.points[0]), QPointF(*m.points[1])).normalized()
            if m.forme == "ellipse":
                chemin.addEllipse(zone)
            else:
                chemin.addRect(zone)
        return self._total(r).map(chemin)

    def paintEvent(self, _e):
        r = self._rect()
        if r is None:
            return
        c = charte.actuelle()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        for m in self.masques:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(c.c("accent" if m.actif else "ink-muted"), 1.5,
                          Qt.DashLine if m.inverse else Qt.SolidLine))
            p.drawPath(self._chemin(r, m))
            p.setPen(QPen(c.c("bg-app"), 1))
            p.setBrush(c.c("ink"))
            for pt in self._poignees(m):
                e = self._ecran(r, pt)
                p.drawRect(QRectF(e.x() - 3.5, e.y() - 3.5, 7, 7))
        p.end()

    def _trouver(self, pos: QPointF):
        r = self._rect()
        if r is None:
            return None
        for m in reversed(self.masques):
            for i, pt in enumerate(self._poignees(m)):
                e = self._ecran(r, pt)
                if abs(e.x() - pos.x()) <= self.RAYON and abs(e.y() - pos.y()) <= self.RAYON:
                    return m, i
        for m in reversed(self.masques):
            if self._chemin(r, m).contains(pos):
                return m, -1
        return None

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._prise is None:
            trouve = self._trouver(pos)
            self.setCursor(Qt.ArrowCursor if trouve is None else
                           Qt.SizeAllCursor if trouve[1] < 0 else Qt.CrossCursor)
            return
        m, i, depart, points = self._prise
        r = self._rect()
        a, b = self._image(r, depart), self._image(r, pos)
        dx, dy = b[0] - a[0], b[1] - a[1]
        if i < 0:
            m.points = [[x + dx, y + dy] for x, y in points]
        elif m.forme == "courbe":
            m.points = [list(p) for p in points]
            m.points[i] = [points[i][0] + dx, points[i][1] + dy]
        else:
            # Coins 0 à 3 : (a.x, a.y), (b.x, a.y), (b.x, b.y), (a.x, b.y).
            (ax, ay), (bx, by) = points
            if i in (0, 3):
                ax += dx
            else:
                bx += dx
            if i in (0, 1):
                ay += dy
            else:
                by += dy
            m.points = [[ax, ay], [bx, by]]
        self.update()

    def mousePressEvent(self, e):
        trouve = self._trouver(e.position())
        if trouve is None:
            return
        m, i = trouve
        if e.button() == Qt.RightButton:
            if m.forme == "courbe" and i >= 0 and len(m.points) > 3:
                del m.points[i]
                self.modifie.emit(m.id, m.points)
            return
        if e.button() == Qt.LeftButton:
            self._prise = (m, i, e.position(), copy.deepcopy(m.points))

    def mouseReleaseEvent(self, e):
        if self._prise is None:
            return
        m, _, depart, _ = self._prise
        self._prise = None
        if (e.position() - depart).manhattanLength() > 0:
            self.modifie.emit(m.id, m.points)

    def mouseDoubleClickEvent(self, e):
        """Forme libre : un point de plus sur le côté le plus proche."""
        r = self._rect()
        if r is None:
            return
        pos = self._image(r, e.position())
        for m in reversed(self.masques):
            if m.forme != "courbe":
                continue
            n = len(m.points)
            meilleur, rang = None, 0
            for k in range(n):
                (x0, y0), (x1, y1) = m.points[k], m.points[(k + 1) % n]
                d = math.dist(pos, [(x0 + x1) / 2, (y0 + y1) / 2])
                if meilleur is None or d < meilleur:
                    meilleur, rang = d, k + 1
            m.points.insert(rang, pos)
            self.modifie.emit(m.id, m.points)
            return


def carte_normalisee(matrice, largeur: int, hauteur: int) -> QTransform:
    """Une matrice de `transformation.matrice` (pixels de la séquence) en QTransform, de
    l'image du clip vers celle de la séquence, en fractions de l'image."""
    n = np.diag([1 / largeur, 1 / hauteur, 1.0]) @ matrice @ np.diag([largeur, hauteur, 1.0])
    return QTransform(n[0, 0], n[1, 0], n[0, 1], n[1, 1], n[0, 2], n[1, 2])


class CalqueTransformation(QWidget):
    """Cadre de l'image du clip transformé, posé sur le programme. Glisser dedans : la
    position ; un coin : la taille (Maj : largeur et hauteur séparées) ; la poignée ronde
    au-dessus : la rotation (Maj : par pas de 15°). `glisse` donne les réglages pendant le
    geste (aperçu), `relache` à la fin (une action de l'historique)."""
    glisse = Signal(dict)
    relache = Signal(dict)

    RAYON = 7
    ECART_ROTATION = 26

    def __init__(self, zone: "ZoneImage"):
        super().__init__(zone)
        self.zone = zone
        self.valeurs: dict | None = None
        self.taille = (1, 1)
        self._prise = None
        self.setMouseTracking(True)
        self.montrer(None)

    def en_prise(self) -> bool:
        return self._prise is not None

    def montrer(self, valeurs: dict | None, largeur: int = 1, hauteur: int = 1):
        """valeurs : réglages de la transformation à la tête de lecture, cadre compris ;
        None cache le calque. largeur, hauteur : la séquence."""
        if self._prise is not None and valeurs is not None:
            return  # pendant un geste, le calque garde ses propres valeurs
        self.valeurs = dict(valeurs) if valeurs is not None else None
        self.taille = (max(1, largeur), max(1, hauteur))
        actif = valeurs is not None
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not actif)
        self.setVisible(actif)
        self.setGeometry(self.zone.rect())
        self.update()

    def _ecran_seq(self) -> QTransform | None:
        """Des pixels de la séquence vers l'écran."""
        if self.zone._image is None:
            return None
        r = self.zone._rect_image(self.zone.width(), self.zone.height())
        l, h = self.taille
        return QTransform(r.width() / l, 0, 0, r.height() / h, r.x(), r.y())

    def _points(self, valeurs: dict):
        """Coins à l'écran, centre de l'image transformée, milieu du bord haut et poignée de
        rotation."""
        from remanence.effets import transformation
        e = self._ecran_seq()
        if e is None:
            return None
        l, h = self.taille
        m = transformation.matrice(valeurs, l, h)

        def vers(x, y):
            q = m @ [x, y, 1.0]
            return e.map(QPointF(q[0], q[1]))
        coins = [vers(x, y) for x, y in transformation.coins(valeurs, l, h)]
        centre = vers(l / 2, h / 2)
        haut = (coins[0] + coins[1]) / 2
        bas = (coins[3] + coins[2]) / 2
        # La poignée de rotation, au-dessus du bord haut, quel que soit l'angle.
        dx, dy = haut.x() - bas.x(), haut.y() - bas.y()
        n = math.hypot(dx, dy) or 1.0
        rotation = QPointF(haut.x() + dx / n * self.ECART_ROTATION,
                           haut.y() + dy / n * self.ECART_ROTATION)
        return coins, centre, haut, rotation

    def paintEvent(self, _e):
        if self.valeurs is None:
            return
        pts = self._points(self.valeurs)
        if pts is None:
            return
        coins, centre, haut, rotation = pts
        c = charte.actuelle()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(c.c("accent"), 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawPolygon(QPolygonF(coins))
        p.drawLine(haut, rotation)
        p.drawLine(centre - QPointF(5, 0), centre + QPointF(5, 0))
        p.drawLine(centre - QPointF(0, 5), centre + QPointF(0, 5))
        p.setPen(QPen(c.c("bg-app"), 1))
        p.setBrush(c.c("ink"))
        for pt in coins:
            p.drawRect(QRectF(pt.x() - 4, pt.y() - 4, 8, 8))
        p.drawEllipse(rotation, 4.5, 4.5)
        p.end()

    def _trouver(self, pos: QPointF) -> str | None:
        pts = self._points(self.valeurs) if self.valeurs is not None else None
        if pts is None:
            return None
        coins, _, _, rotation = pts
        if (pos - rotation).manhattanLength() <= self.RAYON * 1.5:
            return "rotation"
        for i, pt in enumerate(coins):
            if abs(pt.x() - pos.x()) <= self.RAYON and abs(pt.y() - pos.y()) <= self.RAYON:
                return f"coin{i}"
        if QPolygonF(coins).containsPoint(pos, Qt.OddEvenFill):
            return "dedans"
        return None

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton or self.valeurs is None:
            return
        quoi = self._trouver(e.position())
        if quoi is not None:
            self._prise = (quoi, e.position(), dict(self.valeurs))

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._prise is None:
            quoi = self._trouver(pos)
            self.setCursor(Qt.ArrowCursor if quoi is None else Qt.SizeAllCursor
                           if quoi == "dedans" else Qt.CrossCursor)
            return
        self.valeurs = {**self.valeurs, **self.nouvelles(pos, e.modifiers())}
        self.update()
        self.glisse.emit(self._reglages())

    def mouseReleaseEvent(self, e):
        if self._prise is None:
            return
        depart = self._prise[1]
        reglages = self._reglages()
        self._prise = None
        if (e.position() - depart).manhattanLength() > 0:
            self.relache.emit(reglages)

    def _reglages(self) -> dict:
        quoi = self._prise[0] if self._prise else ""
        cles = {"dedans": ("x", "y"), "rotation": ("rotation",)}.get(
            quoi, ("taille", "largeur", "hauteur"))
        return {k: self.valeurs[k] for k in cles}

    def nouvelles(self, pos: QPointF, modificateurs=Qt.NoModifier) -> dict:
        """Les réglages du geste en cours, le pointeur en pos."""
        quoi, depart, v0 = self._prise
        inverse = self._ecran_seq().inverted()[0]
        a, b = inverse.map(depart), inverse.map(pos)  # pixels de la séquence
        l, h = self.taille
        if quoi == "dedans":
            return {"x": max(-200.0, min(200.0, v0["x"] + (b.x() - a.x()) / l * 100)),
                    "y": max(-200.0, min(200.0, v0["y"] + (b.y() - a.y()) / h * 100))}
        centre = QPointF(l / 2 + v0["x"] / 100 * l, h / 2 + v0["y"] / 100 * h)
        u, w = a - centre, b - centre
        if quoi == "rotation":
            angle = math.degrees(math.atan2(w.y(), w.x()) - math.atan2(u.y(), u.x()))
            if angle > 180:
                angle -= 360
            elif angle < -180:
                angle += 360
            nouvelle = v0["rotation"] - angle
            if modificateurs & Qt.ShiftModifier:
                nouvelle = round(nouvelle / 15) * 15
            return {"rotation": max(-720.0, min(720.0, nouvelle))}
        if modificateurs & Qt.ShiftModifier:
            # Dans les axes de l'image : largeur et hauteur séparées.
            r = math.radians(v0["rotation"])
            ca, sa = math.cos(r), math.sin(r)

            def locale(q):
                return ca * q.x() - sa * q.y(), sa * q.x() + ca * q.y()
            (ux, uy), (wx, wy) = locale(u), locale(w)
            fx = abs(wx / ux) if abs(ux) > 1e-6 else 1.0
            fy = abs(wy / uy) if abs(uy) > 1e-6 else 1.0
            return {"largeur": min(1000.0, v0["largeur"] * fx),
                    "hauteur": min(1000.0, v0["hauteur"] * fy)}
        n0 = math.hypot(u.x(), u.y())
        f = math.hypot(w.x(), w.y()) / n0 if n0 > 1e-6 else 1.0
        return {"taille": min(1000.0, v0["taille"] * f)}


class BarreDefilement(QWidget):
    """Fine barre sous l'image : toute la durée, la zone entre E et S teintée, la tête de
    lecture. Un clic ou un glisser déplace la tête."""
    position_demandee = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(14)
        self.setCursor(Qt.PointingHandCursor)

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
        self.zoom.setToolTip("Zoom de l'image")
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
        self.b_prec = b("rewind", "Lecture arrière (J)")
        self.b_prec.clicked.connect(lambda: self.demande_vitesse.emit(-1))
        self.b_lire = bouton_icone("play", "Lire ou mettre en pause (Espace)", variante="lecture")
        self.b_lire.setFixedSize(40, 32)
        self.b_lire.clicked.connect(lambda: self.demande_lecture.emit())
        self.b_suiv = b("fast-forward", "Lecture avant (L)")
        self.b_suiv.clicked.connect(lambda: self.demande_vitesse.emit(1))
        self.b_sortie = b(None, "Marquer le point de sortie (O)", self.demande_sortie, "]")
        self.b_aller_sortie = b("arrow-right-to-line", "Aller au point de sortie",
                                self.demande_aller_sortie)
        self.b_boucle = bouton_icone("repeat", "Boucle (Ctrl+B)", cochable=True)
        self.b_boucle.setFixedSize(30, 28)
        self.timecode = ChampTimecode(15)
        self.timecode.position_demandee.connect(self.demande_position)

        self.qualite = QToolButton()
        self.qualite.setProperty("variante", "badge")
        self.qualite.setPopupMode(QToolButton.InstantPopup)
        self.qualite.setToolTip("Résolution de l'aperçu")
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

    def ajouter_ligne(self, widget: QWidget):
        """Une rangée sous le transport (les poses rapides de l'espace Cut)."""
        self.layout().addWidget(widget)

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

