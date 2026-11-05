"""Onglet Effets : les préréglages en tuiles, à glisser sur un clip, une piste ou la timeline.

Chaque tuile montre le rendu du préréglage sur une image de démonstration, calculé par la carte
graphique ; au survol, la vignette s'anime. Fiche de la charte : EffectPreset.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QMimeData, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPainter, QPainterPath
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QInputDialog, QLineEdit,
                               QListView, QListWidget, QListWidgetItem, QMenu, QMessageBox,
                               QStyle, QStyledItemDelegate, QToolButton, QVBoxLayout, QWidget)

from remanence.effets import EFFETS, FAMILLES, FAMILLES_SON
from remanence.effets import prereglages as pr
from remanence.moteurs.codec import prerendu
from remanence.rendu import son as son_
from remanence.rendu.gpu import RenduGPU, gpu_demande
from remanence.ui import charte
from remanence.ui.composants import bouton_icone, etiquette

LARGEUR_VIGNETTE, HAUTEUR_VIGNETTE = 160, 90
IMAGES_ANIMATION = 24
ROLE_INDEX = Qt.UserRole


def image_demo(numero: int, largeur: int = 256, hauteur: int = 144) -> np.ndarray:
    """Image de démonstration, H×L×4 float32 : barres de couleur, dégradé, zone claire et un
    disque blanc qui traverse l'image au fil des numéros (pour que le tri et les bandes se
    voient)."""
    y, x = np.mgrid[0:hauteur, 0:largeur].astype(np.float32)
    barres = np.array([[0.85, 0.85, 0.85], [0.9, 0.85, 0.1], [0.1, 0.8, 0.85], [0.1, 0.75, 0.2],
                       [0.8, 0.15, 0.75], [0.85, 0.15, 0.1], [0.15, 0.2, 0.8]], np.float32)
    image = np.empty((hauteur, largeur, 4), np.float32)
    image[..., :3] = barres[np.minimum((x / largeur * len(barres)).astype(int), len(barres) - 1)]
    bas = y > hauteur * 0.66
    image[bas, :3] = (x[bas] / largeur)[:, None]
    cx = (numero % IMAGES_ANIMATION) / IMAGES_ANIMATION * largeur * 1.2 - largeur * 0.1
    disque = (x - cx) ** 2 + (y - hauteur * 0.4) ** 2 < (hauteur * 0.16) ** 2
    image[disque, :3] = 1.0
    image[..., 3] = 1.0
    return image


class DelegueTuile(QStyledItemDelegate):
    """Tuile surface-raised, arrondi radius-md, vignette sur viewer-bg, nom, puis l'effet en
    label ink-muted ; bordure accent si le préréglage est celui du clip sélectionné."""

    def __init__(self, panneau: "PanneauEffets"):
        super().__init__(panneau)
        self.panneau = panneau

    def sizeHint(self, option, index):
        return QSize(LARGEUR_VIGNETTE + 12, HAUTEUR_VIGNETTE + 52)

    def paint(self, p: QPainter, option, index):
        c = charte.actuelle()
        preset = self.panneau.prereglages[index.data(ROLE_INDEX)]
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(option.rect).adjusted(4, 4, -4, -4)
        rayon = c.px("radius-md")
        forme = QPainterPath()
        forme.addRoundedRect(r, rayon, rayon)
        fond = "surface-hover" if option.state & QStyle.State_MouseOver else "surface-raised"
        p.fillPath(forme, c.c(fond))
        vignette = QRectF(r.left() + 6, r.top() + 6, r.width() - 12, HAUTEUR_VIGNETTE)
        p.fillRect(vignette, c.c("viewer-bg"))
        image = self.panneau.vignette(index.data(ROLE_INDEX))
        if image is not None:
            p.drawImage(vignette, image)
        p.setPen(c.c("ink"))
        p.setFont(c.police("heading", 13))
        texte = QRectF(vignette.left(), vignette.bottom() + 4, vignette.width(), 18)
        p.drawText(texte, Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(preset.nom, Qt.ElideRight, int(texte.width())))
        p.setPen(c.c("ink-muted"))
        p.setFont(c.police("label"))
        meta = QRectF(texte.left(), texte.bottom(), texte.width(), 16)
        p.drawText(meta, Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(preset.description, Qt.ElideRight, int(meta.width())))
        actif = preset.nom in self.panneau.actifs
        if actif or option.state & QStyle.State_Selected or option.state & QStyle.State_HasFocus:
            p.setPen(c.c("accent" if actif else "focus"))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), rayon, rayon)
        p.restore()


class VueTuiles(QListWidget):
    def __init__(self, panneau: "PanneauEffets"):
        super().__init__(panneau)
        self.panneau = panneau
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setUniformItemSizes(True)
        self.setSpacing(2)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.viewport().setMouseTracking(True)
        self.setAccessibleName("Préréglages d'effets")

    def mimeTypes(self):
        return [pr.MIME_PREREGLAGE]

    def mimeData(self, items):
        d = QMimeData()
        if items:
            d.setData(pr.MIME_PREREGLAGE,
                      pr.vers_mime(self.panneau.prereglages[items[0].data(ROLE_INDEX)]))
        return d

    def mouseMoveEvent(self, e):
        item = self.itemAt(e.position().toPoint())
        self.panneau.survoler(item.data(ROLE_INDEX) if item else None)
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self.panneau.survoler(None)
        super().leaveEvent(e)


class PanneauEffets(QWidget):
    """Bibliothèque d'effets. appliquer(préréglage, cible) ; cible « selection »,
    « clip_effet » ou « sequence »."""
    appliquer = Signal(object, str)
    personnels_changes = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.prereglages: list[pr.Prereglage] = []
        self.actifs: set[str] = set()
        self._vignettes: dict[int, QImage] = {}
        self._animations_codec: dict[int, list] = {}
        self._ondes: dict[int, np.ndarray] = {}
        self._gpu: RenduGPU | None = None
        self._gpu_essaye = False
        self._survole: int | None = None
        self._numero = 0
        self._famille = ""
        self._minuterie = QTimer(self)
        self._minuterie.setInterval(80)
        self._minuterie.timeout.connect(self._animer)

        self.recherche = QLineEdit()
        self.recherche.setPlaceholderText("Rechercher un effet")
        self.recherche.setClearButtonEnabled(True)
        self.recherche.setAccessibleName("Rechercher un effet")
        self.recherche.addAction(charte.actuelle().icone("search", 14), QLineEdit.LeadingPosition)
        self.recherche.textChanged.connect(lambda _t: self._remplir())
        self.b_filtre = bouton_icone("funnel", "Filtrer par famille")
        self.b_filtre.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.b_filtre)
        self._actions_filtre = {}
        for famille in ["", *FAMILLES, *FAMILLES_SON, pr.FAMILLE_PERSONNELS]:
            a = menu.addAction(famille or "Toutes les familles",
                               lambda famille=famille: self._filtrer(famille))
            a.setCheckable(True)
            self._actions_filtre[famille] = a
        self._actions_filtre[""].setChecked(True)
        self.b_filtre.setMenu(menu)
        haut = QHBoxLayout()
        haut.setContentsMargins(8, 8, 8, 6)
        haut.setSpacing(4)
        haut.addWidget(self.recherche, 1)
        haut.addWidget(self.b_filtre)

        self.vue = VueTuiles(self)
        self.vue.setItemDelegate(DelegueTuile(self))
        self.vue.itemActivated.connect(
            lambda item: self.appliquer.emit(self.prereglages[item.data(ROLE_INDEX)], "selection"))
        self.vue.setContextMenuPolicy(Qt.CustomContextMenu)
        self.vue.customContextMenuRequested.connect(self._menu)
        self.vide = etiquette("Aucun résultat", "secondaire")
        self.vide.setAlignment(Qt.AlignCenter)
        self.vide.hide()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addLayout(haut)
        lay.addWidget(self.vue, 1)
        lay.addWidget(self.vide, 1)
        self.recharger()

    # Contenu

    def recharger(self):
        """Relit les préréglages (après l'ajout ou la suppression d'un préréglage personnel)."""
        self.prereglages = pr.tous()
        self._vignettes.clear()
        self._animations_codec.clear()
        self._ondes.clear()
        self._remplir()

    def _filtrer(self, famille: str):
        self._famille = famille
        for f, a in self._actions_filtre.items():
            a.setChecked(f == famille)
        self.b_filtre.setProperty("variante", "discret")
        self._remplir()

    def _remplir(self):
        texte = self.recherche.text().strip().lower()
        self.vue.clear()
        for i, p in enumerate(self.prereglages):
            if self._famille and p.famille != self._famille:
                continue
            if texte and texte not in (p.nom + " " + p.description + " " + p.famille).lower():
                continue
            item = QListWidgetItem()
            item.setData(ROLE_INDEX, i)
            item.setToolTip(f"{p.nom} · {p.famille}")
            self.vue.addItem(item)
        rien = self.vue.count() == 0
        self.vue.setVisible(not rien)
        self.vide.setVisible(rien)

    def marquer_actifs(self, effets: list):
        """Bordure accent sur les tuiles dont le préréglage est exactement celui du clip."""
        self.actifs = {p.nom for p in self.prereglages if p.correspond(effets)}
        self.vue.viewport().update()

    # Vignettes

    def _rendu(self) -> RenduGPU | None:
        if not self._gpu_essaye:
            self._gpu_essaye = True
            if gpu_demande():
                try:
                    self._gpu = RenduGPU()
                except Exception:
                    self._gpu = None
        return self._gpu

    def _codec(self, i: int) -> list[np.ndarray] | None:
        """Préréglage codec : toute l'animation passée une fois par le moteur Bavure."""
        effets = self.prereglages[i].nouveaux_effets()
        if not any(EFFETS[e.type].codec for e in effets):
            return None
        if i not in self._animations_codec:
            # Une coupe à mi-chemin (second plan : l'image en miroir), pour que la suppression
            # d'images clés ait un raccord où baver.
            images = []
            for n in range(IMAGES_ANIMATION):
                rvb = np.clip(image_demo(n)[..., :3], 0, 1)
                if n >= IMAGES_ANIMATION // 2:
                    rvb = rvb[::-1, ::-1]
                images.append(np.ascontiguousarray((rvb * 255 + 0.5).astype(np.uint8)))
            self._animations_codec[i] = prerendu.apercu(images, effets)
        return self._animations_codec[i]

    def est_audio(self, i: int) -> bool:
        effets = self.prereglages[i].effets
        return bool(effets) and all(e["type"] in EFFETS and EFFETS[e["type"]].audio
                                    for e in effets)

    def _onde(self, i: int) -> np.ndarray:
        """Préréglage audio : le motif de démonstration passé par ses effets (calculé une
        fois)."""
        if i not in self._ondes:
            demo = son_.son_demo()

            def lire(a: int, n: int) -> np.ndarray:
                sortie = np.zeros((n, 2), np.float32)
                b, c = max(0, a), min(len(demo), a + n)
                if c > b:
                    sortie[b - a:c - a] = demo[b:c]
                return sortie
            for e in self.prereglages[i].nouveaux_effets():
                lire = EFFETS[e.type].son(lire, e.params, e.graine, son_.FREQUENCE)
            self._ondes[i] = lire(0, len(demo))[:, 0]
        return self._ondes[i]

    def _calculer_onde(self, i: int, numero: int) -> QImage:
        """Vignette d'un effet audio : la forme d'onde du son traité ; au survol, une tête de
        lecture la parcourt."""
        c = charte.actuelle()
        largeur, hauteur = 256, 144
        image = QImage(largeur, hauteur, QImage.Format_RGB888)
        # Comme un clip audio de la timeline : l'onde claire sur le fond des clips audio.
        image.fill(c.c("clip-audio"))
        onde = self._onde(i)
        colonnes = np.array_split(onde, largeur)
        p = QPainter(image)
        p.setPen(c.c("ink"))
        milieu = hauteur / 2
        for x, col in enumerate(colonnes):
            if len(col):
                haut, bas = float(col.max()), float(col.min())
                p.drawLine(x, round(milieu - haut * milieu * 0.9), x,
                           round(milieu - bas * milieu * 0.9))
        if numero > 6:
            xt = (numero - 6) * 6 % largeur
            p.fillRect(QRectF(xt, 0, 2, hauteur), c.c("playhead"))
        p.end()
        return image

    def _calculer(self, i: int, numero: int) -> QImage:
        if self.est_audio(i):
            return self._calculer_onde(i, numero)
        codec = self._codec(i)
        if codec is not None:
            rvb = np.ascontiguousarray(codec[numero % IMAGES_ANIMATION])
            h, l = rvb.shape[:2]
            return QImage(rvb.data, l, h, 3 * l, QImage.Format_RGB888).copy()
        image = image_demo(numero)
        g = self._rendu()
        if g is not None:
            # Le contexte de la visionneuse vit dans le même fil : le nôtre n'est actif que le
            # temps du calcul, puis le précédent revient.
            with g.ctx:
                image = g.traiter(image, self.prereglages[i].nouveaux_effets(), numero)
        rvb = np.ascontiguousarray((np.clip(image[..., :3], 0.0, 1.0) * 255 + 0.5).astype(np.uint8))
        h, l = rvb.shape[:2]
        return QImage(rvb.data, l, h, 3 * l, QImage.Format_RGB888).copy()

    def vignette(self, i: int) -> QImage:
        if i == self._survole:
            return self._image_survol
        if i not in self._vignettes:
            self._vignettes[i] = self._calculer(i, 6)
        return self._vignettes[i]

    def survoler(self, i: int | None):
        if i == self._survole:
            return
        self._survole = i
        if i is None:
            self._minuterie.stop()
        else:
            self._numero = 6
            self._image_survol = self._calculer(i, self._numero)
            self._minuterie.start()
        self.vue.viewport().update()

    def _animer(self):
        if self._survole is None:
            return
        self._numero += 1
        self._image_survol = self._calculer(self._survole, self._numero)
        self.vue.viewport().update()

    def fermer(self):
        self._minuterie.stop()
        if self._gpu is not None:
            self._gpu.fermer()
            self._gpu = None

    # Menu

    def _menu(self, pos):
        item = self.vue.itemAt(pos)
        if item is None:
            return
        p = self.prereglages[item.data(ROLE_INDEX)]
        menu = QMenu(self)
        menu.addAction("Appliquer aux clips sélectionnés", lambda: self.appliquer.emit(p, "selection"))
        if not self.est_audio(item.data(ROLE_INDEX)):
            menu.addAction("Clip d'effet à la tête de lecture",
                           lambda: self.appliquer.emit(p, "clip_effet"))
            menu.addAction("Effet de séquence", lambda: self.appliquer.emit(p, "sequence"))
        if not p.fourni:
            menu.addSeparator()
            menu.addAction("Renommer…", lambda: self._renommer(p))
            menu.addAction("Supprimer", lambda: self._supprimer(p))
        menu.exec(self.vue.viewport().mapToGlobal(pos))

    def _renommer(self, p: pr.Prereglage):
        nom, ok = QInputDialog.getText(self, "Renommer le préréglage", "Nom :", text=p.nom)
        if ok and nom.strip() and nom.strip() != p.nom:
            pr.renommer(p.nom, nom.strip())
            self.recharger()
            self.personnels_changes.emit()

    def _supprimer(self, p: pr.Prereglage):
        r = QMessageBox.question(self, "Supprimer le préréglage", f"Supprimer « {p.nom} » ?",
                                 QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if r == QMessageBox.Yes:
            pr.supprimer(p.nom)
            self.recharger()
            self.personnels_changes.emit()
