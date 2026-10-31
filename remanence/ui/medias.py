"""Panneau Médias : liste des médias du projet, import par bouton ou glisser-déposer."""

from __future__ import annotations

from PySide6.QtCore import QMimeData, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QStackedLayout, QStyle,
                               QStyledItemDelegate, QVBoxLayout, QWidget)

from remanence.projet.modele import Media, Projet
from remanence.ui import charte

ROLE_NOM, ROLE_RESUME = Qt.UserRole + 1, Qt.UserRole + 2

MIME_MEDIA = "application/x-remanence-media"


def resume(media: Media) -> str:
    infos = media.infos
    v = infos.video
    morceaux = []
    if v:
        cad = f"{float(v.fraction_cadence):.3f}".rstrip("0").rstrip(".").replace(".", ",")
        morceaux.append(f"{v.largeur}×{v.hauteur} · {cad} i/s · {v.codec_long.split(' (')[0]}")
    elif infos.audio:
        morceaux.append(f"Audio seul · {infos.audio[0].frequence} Hz")
    morceaux.append(f"{infos.duree_s:.1f} s".replace(".", ","))
    if media.hors_ligne:
        morceaux.append("hors ligne")
    return " · ".join(morceaux)


class DelegueMedia(QStyledItemDelegate):
    """Vignette, nom du média en ink, détails techniques en ink-muted."""

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 64)

    def paint(self, p: QPainter, option, index):
        c = charte.actuelle()
        r = option.rect.adjusted(2, 2, -2, -2)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        if option.state & QStyle.State_Selected:
            p.fillRect(r, c.c("accent-soft"))
        elif option.state & QStyle.State_MouseOver:
            p.fillRect(r, c.c("surface-hover"))
        icone = index.data(Qt.DecorationRole)
        vignette = QRectF(r.left() + 6, r.top() + 6, 85, r.height() - 12)
        p.fillRect(vignette, c.c("viewer-bg"))
        if icone:
            pm = icone.pixmap(QSize(170, 96))
            p.drawPixmap(vignette, pm, QRectF(pm.rect()))
        texte = QRectF(vignette.right() + 10, r.top() + 8, r.width() - 110, 20)
        p.setPen(c.c("ink"))
        p.setFont(c.police("body"))
        p.drawText(texte, Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(index.data(ROLE_NOM), Qt.ElideMiddle,
                                              int(texte.width())))
        p.setPen(c.c("ink-muted"))
        p.setFont(c.police("label"))
        bas = texte.translated(0, 22)
        p.drawText(bas, Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(index.data(ROLE_RESUME), Qt.ElideRight,
                                              int(bas.width())))
        if option.state & QStyle.State_HasFocus:
            p.setPen(QPen(c.c("focus"), 2))
            p.drawRect(r.adjusted(1, 1, -1, -1))
        p.restore()


class ListeMedias(QListWidget):
    fichiers_deposes = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setIconSize(QSize(96, 54))
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setSpacing(0)
        self.setMouseTracking(True)
        self.setItemDelegate(DelegueMedia(self))

    def mimeData(self, items):
        d = QMimeData()
        d.setData(MIME_MEDIA, ",".join(i.data(Qt.UserRole) for i in items).encode())
        return d

    def mimeTypes(self):
        return [MIME_MEDIA, "text/uri-list"]

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            self.fichiers_deposes.emit([u.toLocalFile() for u in e.mimeData().urls()])
            e.acceptProposedAction()


class ZoneVide(QLabel):
    """État vide qui accepte aussi le dépôt de fichiers."""
    fichiers_deposes = Signal(list)

    def __init__(self):
        super().__init__("Aucun média dans le projet.\n\nGlissez ici des fichiers ou des dossiers "
                         "depuis l'Explorateur, ou cliquez sur Importer des médias.")
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.setProperty("role", "secondaire")
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.fichiers_deposes.emit([u.toLocalFile() for u in e.mimeData().urls()])


class PanneauMedias(QWidget):
    importer = Signal()
    fichiers_deposes = Signal(list)
    media_selectionne = Signal(object)
    media_active = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bouton_importer = QPushButton("Importer des médias…")
        self.bouton_importer.setToolTip("Ajoute des vidéos, des sons ou des séquences d'images "
                                        "au projet (Ctrl+I). Les fichiers sources ne sont jamais "
                                        "modifiés.")
        self.bouton_importer.clicked.connect(self.importer)
        self.en_cours = QLabel("")
        self.en_cours.setProperty("role", "secondaire")
        self.liste = ListeMedias()
        self.liste.fichiers_deposes.connect(self.fichiers_deposes)
        self.liste.currentItemChanged.connect(self._courant)
        self.liste.itemActivated.connect(lambda i: self.media_active.emit(i.data(Qt.UserRole)))
        self.vide = ZoneVide()
        self.vide.fichiers_deposes.connect(self.fichiers_deposes)
        self._pile = QStackedLayout()
        self._pile.addWidget(self.vide)
        self._pile.addWidget(self.liste)
        haut = QHBoxLayout()
        haut.addWidget(self.bouton_importer)
        haut.addStretch(1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addLayout(haut)
        lay.addWidget(self.en_cours)
        lay.addLayout(self._pile, 1)
        self._vignettes: dict[str, QPixmap] = {}
        self._projet: Projet | None = None
        self.signaler_analyses(0)

    def signaler_analyses(self, n: int):
        self.en_cours.setVisible(n > 0)
        self.en_cours.setText(f"Analyse de {n} fichier{'s' if n > 1 else ''} en cours…")

    def definir_vignette(self, media_id: str, pixmap: QPixmap):
        self._vignettes[media_id] = pixmap
        for i in range(self.liste.count()):
            item = self.liste.item(i)
            if item.data(Qt.UserRole) == media_id:
                item.setIcon(QIcon(pixmap))

    def afficher(self, projet: Projet):
        self._projet = projet
        courant = self.liste.currentItem().data(Qt.UserRole) if self.liste.currentItem() else None
        self.liste.blockSignals(True)
        self.liste.clear()
        for m in projet.medias.values():
            item = QListWidgetItem(m.nom)
            item.setData(Qt.UserRole, m.id)
            item.setData(ROLE_NOM, m.nom)
            item.setData(ROLE_RESUME, resume(m))
            item.setToolTip("\n".join(f"{k} : {v}" for k, v in m.infos.fiche()))
            if m.id in self._vignettes:
                item.setIcon(QIcon(self._vignettes[m.id]))
            self.liste.addItem(item)
            if m.id == courant:
                self.liste.setCurrentItem(item)
        self.liste.blockSignals(False)
        self._pile.setCurrentWidget(self.liste if projet.medias else self.vide)

    def _courant(self, item, _precedent):
        if item is None or self._projet is None:
            self.media_selectionne.emit(None)
            return
        self.media_selectionne.emit(self._projet.medias.get(item.data(Qt.UserRole)))
