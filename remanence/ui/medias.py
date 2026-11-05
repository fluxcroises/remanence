"""Panneau Média : chutiers, médias en grille ou en liste, recherche, filtre, survol animé.

Le panneau range et montre ; il ne monte rien. Toute modification du projet (chutiers,
rangement) passe par le signal `modifie`, que la fenêtre enregistre dans l'historique.
"""

from __future__ import annotations

from PySide6.QtCore import QMimeData, QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPainter, QPen
from PySide6.QtWidgets import (QHeaderView, QAbstractItemView, QHBoxLayout, QLineEdit, QListView, QListWidget,
                               QListWidgetItem, QMenu, QSlider, QSplitter, QStackedLayout, QStyle,
                               QStyledItemDelegate, QToolButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from remanence.media.timecode import images_vers_tc
from remanence.projet.modele import Chutier, Media, Projet, nouvel_id
from remanence.ui import charte, focus
from remanence.ui.composants import bouton_icone, etiquette

MIME_MEDIA = "application/x-remanence-media"
ROLE_ID = Qt.UserRole
FILTRES = [("tous", "Tous les types"), ("video", "Vidéo"), ("audio", "Audio seul"),
           ("images", "Séquences d'images")]


def resume(media: Media) -> str:
    infos = media.infos
    v = infos.video
    morceaux = []
    if v:
        cad = f"{float(v.fraction_cadence):.3f}".rstrip("0").rstrip(".").replace(".", ",")
        morceaux.append(f"{v.largeur}×{v.hauteur} · {cad} i/s · {v.codec_long.split(' (')[0]}")
    elif infos.audio:
        morceaux.append(f"Audio seul · {infos.audio[0].frequence} Hz")
    if media.hors_ligne:
        morceaux.append("hors ligne")
    return " · ".join(morceaux)


def duree_tc(media: Media) -> str:
    v = media.infos.video
    if v:
        return images_vers_tc(v.nb_images, v.fraction_cadence, v.tc_drop)
    secondes = int(media.infos.duree_s)
    return f"00:{secondes // 60:02d}:{secondes % 60:02d}:00"


def type_media(media: Media) -> str:
    if media.infos.sequence_images:
        return "images"
    return "video" if media.infos.video else "audio"


class DelegueMedia(QStyledItemDelegate):
    """Grille : vignette 16:9 avec la durée en surimpression et le nom dessous.
    Liste : petite vignette, nom, détails techniques et durée sur une ligne."""

    def __init__(self, panneau: "PanneauMedias"):
        super().__init__(panneau)
        self.panneau = panneau

    def _grille(self) -> bool:
        return self.panneau.vue.viewMode() == QListView.IconMode

    def sizeHint(self, option, index):
        if self._grille():
            l = self.panneau.taille_affichee()
            return QSize(l + 12, round(l * 9 / 16) + 34)
        return QSize(option.rect.width(), 44)

    def _image(self, media_id: str, fraction: float | None) -> QImage | None:
        images = self.panneau.vignettes.get(media_id)
        if not images:
            return None
        if fraction is None:
            return images[len(images) // 2]
        return images[min(len(images) - 1, max(0, int(fraction * len(images))))]

    def paint(self, p: QPainter, option, index):
        c = charte.actuelle()
        media = self.panneau.projet.medias.get(index.data(ROLE_ID)) if self.panneau.projet else None
        if media is None:
            return
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = option.rect.adjusted(3, 3, -3, -3)
        selectionne = bool(option.state & QStyle.State_Selected)
        if selectionne:
            p.fillRect(r, c.c("accent-soft"))
        elif option.state & QStyle.State_MouseOver:
            p.fillRect(r, c.c("surface-hover"))
        survol = self.panneau.survol
        fraction = survol[1] if survol and survol[0] == media.id else None
        if self._grille():
            vignette = QRectF(r.left() + 3, r.top() + 3, r.width() - 6, round((r.width() - 6) * 9 / 16))
            self._peindre_vignette(p, media, vignette, fraction)
            p.setFont(c.police("value", 11))
            texte = duree_tc(media)
            largeur = p.fontMetrics().horizontalAdvance(texte) + 10
            bulle = QRectF(vignette.right() - largeur - 4, vignette.bottom() - 20, largeur, 16)
            p.fillRect(bulle, c.c("bg-app", 0.8))
            p.setPen(c.c("ink"))
            p.drawText(bulle, Qt.AlignCenter, texte)
            p.setFont(c.police("label"))
            nom = QRectF(r.left() + 4, vignette.bottom() + 4, r.width() - 8, 18)
            p.setPen(c.c("ink"))
            p.drawText(nom, Qt.AlignLeft | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(media.nom, Qt.ElideMiddle, int(nom.width())))
        else:
            vignette = QRectF(r.left() + 4, r.top() + 4, 64, 36)
            self._peindre_vignette(p, media, vignette, fraction)
            p.setFont(c.police("body"))
            p.setPen(c.c("ink"))
            zone = QRectF(vignette.right() + 10, r.top() + 3, r.width() - 190, 18)
            p.drawText(zone, Qt.AlignLeft | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(media.nom, Qt.ElideMiddle, int(zone.width())))
            p.setFont(c.police("label"))
            p.setPen(c.c("ink-muted"))
            details = zone.translated(0, 18)
            p.drawText(details, Qt.AlignLeft | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(resume(media), Qt.ElideRight,
                                                  int(details.width())))
            p.setFont(c.police("value", 11))
            p.drawText(QRectF(r.right() - 100, r.top(), 94, r.height()),
                       Qt.AlignRight | Qt.AlignVCenter, duree_tc(media))
        if media.hors_ligne:
            p.setFont(c.police("caption"))
            p.setPen(c.c("danger"))
            p.drawText(r.adjusted(8, 6, -8, -6), Qt.AlignTop | Qt.AlignLeft, "Hors ligne")
        if option.state & QStyle.State_HasFocus and focus.visible(self.panneau.vue):
            p.setPen(QPen(c.c("focus"), 2))
            p.drawRect(r.adjusted(1, 1, -1, -1))
        elif selectionne:
            p.setPen(QPen(c.c("accent"), 1))
            p.drawRect(r.adjusted(0, 0, -1, -1))
        p.restore()

    def _peindre_vignette(self, p: QPainter, media: Media, rect: QRectF, fraction):
        c = charte.actuelle()
        p.fillRect(rect, c.c("viewer-bg"))
        image = self._image(media.id, fraction)
        if image is not None:
            s = min(rect.width() / image.width(), rect.height() / image.height())
            l, h = image.width() * s, image.height() * s
            p.drawImage(QRectF(rect.center().x() - l / 2, rect.center().y() - h / 2, l, h), image)
        else:
            icone = {"video": "film", "audio": "music", "images": "image"}[type_media(media)]
            pm = charte.pixmap_icone(icone, c.hex("ink-muted"), 20)
            p.drawPixmap(int(rect.center().x() - 10), int(rect.center().y() - 10), pm)


class VueMedias(QListWidget):
    """Grille ou liste des médias : glisser vers la timeline ou vers un chutier, survol animé."""
    fichiers_deposes = Signal(list)

    def __init__(self, panneau: "PanneauMedias"):
        super().__init__(panneau)
        self.panneau = panneau
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        # Les mouvements arrivent à la zone d'affichage : c'est elle qui doit les suivre.
        self.viewport().setMouseTracking(True)
        self.setUniformItemSizes(True)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setAccessibleName("Médias du chutier")

    def mimeData(self, items):
        d = QMimeData()
        d.setData(MIME_MEDIA, ",".join(i.data(ROLE_ID) for i in items).encode())
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

    def mouseMoveEvent(self, e):
        # Survol : la position horizontale sur la vignette choisit l'image montrée.
        item = self.itemAt(e.position().toPoint())
        if item is not None and not e.buttons():
            r = self.visualItemRect(item)
            fraction = (e.position().x() - r.left()) / max(1, r.width())
            self.panneau.survol = (item.data(ROLE_ID), min(max(fraction, 0.0), 0.999))
            self.viewport().update(r)
        elif self.panneau.survol is not None:
            self.panneau.survol = None
            self.viewport().update()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self.panneau.survol = None
        self.viewport().update()
        super().leaveEvent(e)


class ArbreChutiers(QTreeWidget):
    """Arborescence des chutiers ; on y dépose des médias pour les ranger."""
    medias_ranges = Signal(list, object)
    fichiers_deposes = Signal(list, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        # Colonne 0 : le nom, seul modifiable ; colonne 1 : le nombre de médias.
        self.setColumnCount(2)
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setEditTriggers(QAbstractItemView.EditKeyPressed | QAbstractItemView.SelectedClicked)
        self.setAccessibleName("Chutiers")
        self.setIndentation(14)

    def _cible(self, pos) -> tuple[bool, str | None]:
        item = self.itemAt(pos)
        return (item is not None, item.data(0, ROLE_ID) if item else None)

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME_MEDIA) or e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        trouve, _ = self._cible(e.position().toPoint())
        if trouve:
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        trouve, chutier = self._cible(e.position().toPoint())
        if not trouve:
            return
        if e.mimeData().hasFormat(MIME_MEDIA):
            ids = bytes(e.mimeData().data(MIME_MEDIA)).decode().split(",")
            self.medias_ranges.emit([i.partition("@")[0] for i in ids], chutier)
        elif e.mimeData().hasUrls():
            self.fichiers_deposes.emit([u.toLocalFile() for u in e.mimeData().urls()], chutier)
        e.acceptProposedAction()


class PanneauMedias(QWidget):
    importer = Signal()
    fichiers_deposes = Signal(list)
    media_selectionne = Signal(object)
    media_active = Signal(str)
    modifie = Signal(str)
    retirer = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.projet: Projet | None = None
        self.vignettes: dict[str, list[QImage]] = {}
        self.survol: tuple[str, float] | None = None
        self.taille_vignette = 150
        self._filtre = "tous"
        self.chutier_courant: str | None = None

        self.recherche = QLineEdit()
        self.recherche.setPlaceholderText("Rechercher dans les médias")
        self.recherche.setClearButtonEnabled(True)
        self.recherche.setAccessibleName("Rechercher dans les médias")
        self.recherche.addAction(charte.actuelle().icone("search", 14), QLineEdit.LeadingPosition)
        self.recherche.textChanged.connect(lambda _t: self._remplir())
        self.b_filtre = bouton_icone("funnel", "Filtrer par type de média")
        self.b_filtre.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.b_filtre)
        self._actions_filtre = {}
        for cle, nom in FILTRES:
            a = menu.addAction(nom, lambda cle=cle: self._filtrer(cle))
            a.setCheckable(True)
            self._actions_filtre[cle] = a
        self._actions_filtre["tous"].setChecked(True)
        self.b_filtre.setMenu(menu)
        haut = QHBoxLayout()
        haut.setContentsMargins(8, 8, 8, 6)
        haut.setSpacing(4)
        haut.addWidget(self.recherche, 1)
        haut.addWidget(self.b_filtre)

        self.arbre = ArbreChutiers()
        self.arbre.currentItemChanged.connect(self._chutier_choisi)
        self.arbre.itemChanged.connect(self._renomme)
        self.arbre.medias_ranges.connect(self.ranger)
        self.arbre.fichiers_deposes.connect(self._deposer_dans)
        self.arbre.setContextMenuPolicy(Qt.CustomContextMenu)
        self.arbre.customContextMenuRequested.connect(self._menu_arbre)

        self.vue = VueMedias(self)
        self.vue.setItemDelegate(DelegueMedia(self))
        self.vue.fichiers_deposes.connect(self.fichiers_deposes)
        self.vue.currentItemChanged.connect(self._courant)
        self.vue.itemActivated.connect(lambda i: self.media_active.emit(i.data(ROLE_ID)))
        self.vue.setContextMenuPolicy(Qt.CustomContextMenu)
        self.vue.customContextMenuRequested.connect(self._menu_vue)
        self.vide = etiquette("", "secondaire")
        self.vide.setAlignment(Qt.AlignCenter)
        self.vide.setWordWrap(True)
        self.vide.setContentsMargins(16, 16, 16, 16)
        self.vide.setAcceptDrops(True)
        self.vide.dragEnterEvent = lambda e: e.acceptProposedAction() if e.mimeData().hasUrls() \
            else None
        self.vide.dropEvent = lambda e: self.fichiers_deposes.emit(
            [u.toLocalFile() for u in e.mimeData().urls()])
        zone = QWidget()
        self._pile = QStackedLayout(zone)
        self._pile.addWidget(self.vide)
        self._pile.addWidget(self.vue)

        separation = self._separation = QSplitter(Qt.Vertical)
        separation.addWidget(self.arbre)
        separation.addWidget(zone)
        separation.setStretchFactor(0, 1)
        separation.setStretchFactor(1, 3)
        separation.setSizes([150, 450])
        separation.setChildrenCollapsible(False)

        self.b_liste = bouton_icone("list", "Afficher en liste", cochable=True)
        self.b_grille = bouton_icone("layout-grid", "Afficher en vignettes", cochable=True)
        self.b_liste.clicked.connect(lambda: self.vue_mode(False))
        self.b_grille.clicked.connect(lambda: self.vue_mode(True))
        b_chutier = bouton_icone("folder-plus", "Nouveau chutier")
        b_chutier.clicked.connect(self.nouveau_chutier)
        b_importer = bouton_icone("plus", "Importer (Ctrl+I)",
                                  texte="Importer")
        b_importer.clicked.connect(self.importer)
        self.b_importer = b_importer
        self.taille = QSlider(Qt.Horizontal)
        self.taille.setRange(110, 260)
        self.taille.setValue(self.taille_vignette)
        self.taille.setFixedWidth(90)
        self.taille.setToolTip("Taille des vignettes")
        self.taille.setAccessibleName("Taille des vignettes")
        self.taille.valueChanged.connect(self._taille)
        bas = QHBoxLayout()
        bas.setContentsMargins(6, 4, 6, 4)
        bas.setSpacing(2)
        for w in (self.b_liste, self.b_grille, b_chutier):
            bas.addWidget(w)
        bas.addStretch(1)
        bas.addWidget(b_importer)
        bas.addSpacing(6)
        bas.addWidget(self.taille)
        barre_bas = QWidget()
        barre_bas.setProperty("role", "pied")
        barre_bas.setAttribute(Qt.WA_StyledBackground, True)
        barre_bas.setLayout(bas)

        self.en_cours = etiquette("", "secondaire")
        self.en_cours.setContentsMargins(10, 0, 10, 4)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addLayout(haut)
        lay.addWidget(self.en_cours)
        lay.addWidget(separation, 1)
        lay.addWidget(barre_bas)
        self.vue_mode(True)
        self.signaler_analyses(0)

    # Affichage

    def vue_mode(self, grille: bool):
        self.vue.setViewMode(QListView.IconMode if grille else QListView.ListMode)
        self.vue.setFlow(QListView.LeftToRight if grille else QListView.TopToBottom)
        self.vue.setWrapping(grille)
        self.vue.setSpacing(2 if grille else 0)
        self.vue.setDragDropMode(QAbstractItemView.DragDrop)
        self.b_grille.setChecked(grille)
        self.b_liste.setChecked(not grille)
        self.taille.setEnabled(grille)
        self.vue.doItemsLayout()

    def _taille(self, v: int):
        self.taille_vignette = v
        self.vue.doItemsLayout()

    def taille_affichee(self) -> int:
        """Largeur des vignettes : celle du curseur, réduite dans un panneau étroit (espace
        Montage) pour en tenir deux par ligne, sans descendre sous 96 px."""
        par_tuile = (self.vue.viewport().width() - 8) // 2 - 12 - 2 * self.vue.spacing()
        return max(96, min(self.taille_vignette, par_tuile))

    def signaler_analyses(self, n: int):
        self.en_cours.setVisible(n > 0)
        self.en_cours.setText(f"Analyse de {n} fichier{'s' if n > 1 else ''} en cours…")

    def definir_vignettes(self, media_id: str, images: list[QImage]):
        self.vignettes[media_id] = images
        self.vue.viewport().update()

    def afficher(self, projet: Projet):
        self.projet = projet
        if self.chutier_courant and not any(c.id == self.chutier_courant for c in projet.chutiers):
            self.chutier_courant = None
        self._remplir_arbre()
        self._remplir()

    def _compte(self, chutier_id: str | None) -> int:
        ids = self.projet.sous_chutiers(chutier_id)
        if chutier_id is None:
            return len(self.projet.medias)
        return sum(1 for m in self.projet.medias.values() if m.chutier in ids)

    def _remplir_arbre(self):
        self.arbre.blockSignals(True)
        self.arbre.clear()
        racine = QTreeWidgetItem(["Médias du projet", str(self._compte(None))])
        racine.setData(0, ROLE_ID, None)
        racine.setToolTip(0, "")
        self.arbre.addTopLevelItem(racine)
        items = {None: racine}
        restants = list(self.projet.chutiers)
        while restants:
            places = [c for c in restants if c.parent in items or
                      not any(x.id == c.parent for x in self.projet.chutiers)]
            if not places:
                break
            for c in places:
                parent = items.get(c.parent, racine)
                item = QTreeWidgetItem([c.nom, str(self._compte(c.id))])
                item.setData(0, ROLE_ID, c.id)
                item.setData(0, Qt.UserRole + 1, c.nom)
                item.setFlags(item.flags() | Qt.ItemIsEditable)
                item.setIcon(0, charte.actuelle().icone("folder", 14))
                parent.addChild(item)
                items[c.id] = item
                restants.remove(c)
        for item in items.values():
            item.setForeground(1, charte.actuelle().c("ink-muted"))
            item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
        self.arbre.expandAll()
        self.arbre.setCurrentItem(items.get(self.chutier_courant, racine))
        self.arbre.blockSignals(False)
        self._lignes_arbre = len(items)
        self._ajuster_arbre()

    def _ajuster_arbre(self):
        lignes = getattr(self, "_lignes_arbre", 1)
        """L'arbre prend la hauteur de ses chutiers (une ligne de marge pour en déposer),
        sans dépasser un tiers du panneau : pas de grande bande vide au-dessus des médias."""
        total = sum(self._separation.sizes())
        if total <= 0:
            return
        hauteur = (lignes + 1) * max(20, self.arbre.sizeHintForRow(0)) + 8
        hauteur = min(hauteur, total // 3)
        self._separation.setSizes([hauteur, total - hauteur])

    def _visible(self, media: Media) -> bool:
        if self.chutier_courant is not None and \
                media.chutier not in self.projet.sous_chutiers(self.chutier_courant):
            return False
        if self._filtre != "tous" and type_media(media) != self._filtre:
            return False
        texte = self.recherche.text().strip().lower()
        return not texte or texte in media.nom.lower()

    def _remplir(self):
        if self.projet is None:
            return
        courant = self.vue.currentItem().data(ROLE_ID) if self.vue.currentItem() else None
        self.vue.blockSignals(True)
        self.vue.clear()
        for m in self.projet.medias.values():
            if not self._visible(m):
                continue
            item = QListWidgetItem(m.nom)
            item.setData(ROLE_ID, m.id)
            # Bulle courte : la fiche complète est dans l'onglet Métadonnées.
            item.setToolTip(m.nom)
            self.vue.addItem(item)
            if m.id == courant:
                self.vue.setCurrentItem(item)
        self.vue.blockSignals(False)
        if self.vue.count():
            self._pile.setCurrentWidget(self.vue)
        else:
            if not self.projet.medias:
                texte = ("Aucun média")
            elif self.recherche.text().strip() or self._filtre != "tous":
                texte = "Aucun résultat"
            else:
                texte = ("Chutier vide")
            self.vide.setText(texte)
            self._pile.setCurrentWidget(self.vide)

    def _filtrer(self, cle: str):
        self._filtre = cle
        for k, a in self._actions_filtre.items():
            a.setChecked(k == cle)
        self.b_filtre.setChecked(cle != "tous")
        self._remplir()

    # Sélection

    def _chutier_choisi(self, item, _precedent):
        self.chutier_courant = item.data(0, ROLE_ID) if item else None
        self._remplir()

    def _courant(self, item, _precedent):
        if item is None or self.projet is None:
            self.media_selectionne.emit(None)
            return
        self.media_selectionne.emit(self.projet.medias.get(item.data(ROLE_ID)))

    def medias_affiches(self) -> list[str]:
        """Les médias montrés, dans l'ordre du panneau (chutier, filtre et recherche)."""
        return [self.vue.item(i).data(ROLE_ID) for i in range(self.vue.count())]

    def medias_choisis(self) -> list[str]:
        return [i.data(ROLE_ID) for i in self.vue.selectedItems()]

    # Chutiers

    def nouveau_chutier(self):
        c = Chutier(nouvel_id(), "Nouveau chutier", self.chutier_courant)
        self.projet.chutiers.append(c)
        self.chutier_courant = c.id
        self.modifie.emit("Nouveau chutier")
        for item in self.arbre.findItems("", Qt.MatchContains | Qt.MatchRecursive):
            if item.data(0, ROLE_ID) == c.id:
                self.arbre.editItem(item)

    def _renomme(self, item, _colonne):
        chutier = next((c for c in self.projet.chutiers if c.id == item.data(0, ROLE_ID)), None)
        nom = item.text(0).strip()
        if chutier is None or not nom or nom == chutier.nom:
            return
        chutier.nom = nom
        self.modifie.emit("Chutier renommé")

    def supprimer_chutier(self, chutier_id: str):
        chutier = next(c for c in self.projet.chutiers if c.id == chutier_id)
        # Rien ne se perd : médias et sous-chutiers remontent d'un cran.
        for m in self.projet.medias.values():
            if m.chutier == chutier_id:
                m.chutier = chutier.parent
        for c in self.projet.chutiers:
            if c.parent == chutier_id:
                c.parent = chutier.parent
        self.projet.chutiers.remove(chutier)
        self.chutier_courant = chutier.parent
        self.modifie.emit("Chutier supprimé")

    def ranger(self, ids: list[str], chutier_id: str | None):
        change = False
        for mid in ids:
            m = self.projet.medias.get(mid)
            if m is not None and m.chutier != chutier_id:
                m.chutier = chutier_id
                change = True
        if change:
            self.modifie.emit("Rangement de médias")

    def _deposer_dans(self, chemins: list[str], chutier_id: str | None):
        self.chutier_courant = chutier_id
        self.fichiers_deposes.emit(chemins)

    def _menu_arbre(self, pos: QPoint):
        item = self.arbre.itemAt(pos)
        chutier = item.data(0, ROLE_ID) if item else None
        menu = QMenu(self)
        menu.addAction("Nouveau chutier", self.nouveau_chutier)
        if chutier is not None:
            menu.addAction("Renommer (F2)", lambda: self.arbre.editItem(item))
            menu.addAction("Supprimer le chutier", lambda: self.supprimer_chutier(chutier))
        menu.exec(self.arbre.viewport().mapToGlobal(pos))

    def _menu_vue(self, pos: QPoint):
        ids = self.medias_choisis()
        if not ids:
            return
        menu = QMenu(self)
        menu.addAction("Ouvrir dans le moniteur source", lambda: self.media_active.emit(ids[0]))
        ranger = menu.addMenu("Ranger dans")
        ranger.addAction("Médias du projet (racine)", lambda: self.ranger(ids, None))
        for c in self.projet.chutiers:
            ranger.addAction(c.nom, lambda cid=c.id: self.ranger(ids, cid))
        menu.addSeparator()
        menu.addAction("Retirer du projet (Suppr)", lambda: self.retirer.emit(ids))
        menu.exec(self.vue.viewport().mapToGlobal(pos))

    def resizeEvent(self, e):
        # Panneau étroit (espace Montage) : le bouton Importer passe en icône seule.
        etroit = self.width() < 300
        self.b_importer.setToolButtonStyle(Qt.ToolButtonIconOnly if etroit
                                           else Qt.ToolButtonTextBesideIcon)
        super().resizeEvent(e)
        # Après la mise en page du séparateur, qui n'a sa taille réelle qu'ensuite.
        QTimer.singleShot(0, self._ajuster_arbre)
        QTimer.singleShot(0, self.vue.doItemsLayout)  # taille des vignettes selon la largeur

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Delete and self.vue.hasFocus() and self.medias_choisis():
            self.retirer.emit(self.medias_choisis())
            return
        super().keyPressEvent(e)

