"""Fenêtre principale : panneaux ancrables, menus, raccourcis et cycle de vie du projet."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEvent, QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QImage, QKeySequence, QPixmap
from PySide6.QtWidgets import (QAbstractButton, QApplication, QFileDialog, QInputDialog,
                               QMainWindow, QMessageBox, QToolBar, QWidget)

from remanence.media import intermediaire
from remanence.media.lecteur import LecteurVideo, generer_cache_audio
from remanence.media.proxy import chemin_audio, chemin_proxy, generer_proxy, proxy_utile
from remanence.media.sonde import EXTENSIONS_IMAGES, analyser, detecter_sequence_images
from remanence.projet import edition, serialisation
from remanence.projet.historique import Historique
from remanence.projet.modele import Marqueur, Media, Projet, nouvel_id
from remanence.rendu.couleur import vers_rvb16_apercu, vers_rvba
from remanence.rendu.export import exporter
from remanence.ui import charte
from remanence.ui.apropos import APropos
from remanence.ui.barres import BarreEspaces, BarreTitre
from remanence.ui.composants import Vumetres, etiquette, panneau, panneau_onglets
from remanence.ui.erreurs import afficher_erreur
from remanence.ui.inspecteur import Historique as ListeHistorique
from remanence.ui.inspecteur import Inspecteur, Metadonnees
from remanence.ui.lecture import MoteurLecture
from remanence.ui.medias import PanneauMedias
from remanence.ui.panneau_export import FileExport, FormulaireExport
from remanence.ui.taches import GestionnaireTaches, Tache
from remanence.ui.timeline import Timeline
from remanence.ui.visionneuse import LIBELLES_QUALITE, Visionneuse

INTERVALLE_AUTO_MS = 2 * 60 * 1000
EXTENSIONS_MEDIAS = ("*.mov *.mp4 *.mxf *.mkv *.avi *.webm *.mts *.m2ts *.m4v *.mpg *.mpeg "
                     "*.wav *.aif *.aiff *.mp3 *.flac *.m4a *.dpx *.exr *.tif *.tiff *.png "
                     "*.jpg *.jpeg *.braw *.r3d *.ari")
HAUTEUR_VIGNETTE = 48
BORD = 5
# À augmenter quand les panneaux changent : les dispositions mémorisées avant sont ignorées.
VERSION_DISPOSITION = 2
# Panneaux visibles dans chaque espace de travail.
PANNEAUX_ESPACE = {
    "media": {"medias", "visionneuse", "droite"},
    "montage": {"medias", "visionneuse", "droite", "mixage", "timeline"},
    "export": {"export", "visionneuse", "file_export", "timeline"},
}


def _en_rvb8(image, couleur, largeur: int, hauteur: int) -> np.ndarray:
    rapide = vers_rvb16_apercu(image, couleur, largeur, hauteur)
    if rapide is not None:
        return np.ascontiguousarray((rapide >> 8).astype(np.uint8))
    petite = image.reformat(width=largeur, height=hauteur)
    rvb = vers_rvba(petite, couleur)[..., :3]
    return np.ascontiguousarray((np.clip(rvb, 0, 1) * 255 + 0.5).astype(np.uint8))


def _vignettes(media: Media, nombre: int, annule=None) -> tuple[list[np.ndarray], float]:
    """Vignettes réparties sur tout le média, depuis le proxy s'il existe."""
    v = media.infos.video
    chemin, seq_img = media.chemin, media.infos.sequence_images
    proxy = chemin_proxy(media.infos)
    if proxy.exists():
        chemin, seq_img = str(proxy), None
    infos, index = analyser(chemin, v.cadence if seq_img else None)
    lecteur = LecteurVideo(chemin, index, seq_img, v.cadence)
    try:
        n = max(1, min(nombre, len(index)))
        pas = len(index) / n
        hauteur = HAUTEUR_VIGNETTE
        largeur = max(2, round(v.largeur / v.hauteur * hauteur))
        images = []
        for k in range(n):
            if annule is not None and annule.is_set():
                raise InterruptedError
            images.append(_en_rvb8(lecteur.image(int(k * pas)), v.couleur, largeur, hauteur))
        return images, pas
    finally:
        lecteur.fermer()


def _qimage(rvb: np.ndarray) -> QImage:
    h, l = rvb.shape[:2]
    return QImage(rvb.data, l, h, 3 * l, QImage.Format_RGB888).copy()


class FenetrePrincipale(QMainWindow):
    def __init__(self):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint)
        self.projet = Projet.nouveau()
        self.historique = Historique(self.projet)
        self.chemin: Path | None = None
        self.modifie = False
        self._analyses = 0
        self._derniere_sauvegarde: float | None = None
        self._espace = "montage"
        self.setWindowIcon(charte.actuelle().icone_application())
        self.setMouseTracking(True)

        self.lecture = MoteurLecture()
        self.taches = GestionnaireTaches()
        self.medias = PanneauMedias()
        self.visionneuse = Visionneuse()
        self.inspecteur = Inspecteur()
        self.metadonnees = Metadonnees()
        self.liste_historique = ListeHistorique()
        self.timeline = Timeline(self)
        self.vumetres = Vumetres(self.lecture.cretes)
        self.formulaire_export = FormulaireExport()
        self.file_export = FileExport()

        self.setDockNestingEnabled(True)
        self.setCentralWidget(QWidget())
        self.centralWidget().hide()
        self._docks = {}
        d, self.onglets_gauche = panneau_onglets([("Média", self.medias)], "medias", self)
        self._docks["medias"] = d
        d, self.onglets_droite = panneau_onglets(
            [("Inspecteur", self.inspecteur), ("Métadonnées", self.metadonnees),
             ("Historique", self.liste_historique)], "droite", self)
        self._docks["droite"] = d
        self.badge_inspecteur = etiquette("", "badge-accent")
        self.badge_inspecteur.hide()
        self.onglets_droite.ajouter_outil(self.badge_inspecteur)
        d, self.onglets_export = panneau_onglets([("Export", self.formulaire_export)], "export",
                                                 self)
        self._docks["export"] = d
        d, _ = panneau_onglets([("File d'export", self.file_export)], "file_export", self)
        self._docks["file_export"] = d
        d, self._entete_visionneuse = panneau("Programme", self.visionneuse, "visionneuse", self)
        self._docks["visionneuse"] = d
        self._entete_visionneuse.ajouter(self.visionneuse.qualite)
        d, _ = panneau("Mixage", self.vumetres, "mixage", self, titre_visible=False)
        self._docks["mixage"] = d
        d, _ = panneau("Timeline", self.timeline, "timeline", self, titre_visible=False)
        self._docks["timeline"] = d
        self.inspecteur.badge.connect(self._badge)
        self.onglets_droite.onglet_change.connect(lambda _i: self._badge())
        self.inspecteur.setMinimumWidth(320)
        self.medias.setMinimumWidth(260)

        self.barre_titre = BarreTitre(self)
        self.setMenuWidget(self.barre_titre)
        self.barre_espaces = BarreEspaces(self.taches)
        self.barre_bas = QToolBar("Espaces de travail")
        self.barre_bas.setObjectName("barre_espaces")
        self.barre_bas.setMovable(False)
        self.barre_bas.setFloatable(False)
        self.barre_bas.addWidget(self.barre_espaces)
        self.addToolBar(Qt.BottomToolBarArea, self.barre_bas)
        self.barre_espaces.espace_choisi.connect(self.choisir_espace)

        self._appliquer_espace("montage", par_defaut=True)
        self._actions()
        self._connecter()
        self._afficher_tout()
        self._restaurer_disposition()

        self._minuterie_auto = QTimer(self)
        self._minuterie_auto.timeout.connect(self._sauvegarde_auto)
        self._minuterie_auto.start(INTERVALLE_AUTO_MS)
        self._minuterie_etat = QTimer(self)
        self._minuterie_etat.timeout.connect(self._etat_sauvegarde)
        self._minuterie_etat.start(20000)
        self.resize(1600, 1000)

    # Fenêtre sans cadre : bords de redimensionnement et état agrandi

    def changeEvent(self, e):
        if e.type() == QEvent.WindowStateChange:
            agrandie = self.isMaximized() or self.isFullScreen()
            self.setContentsMargins(*(0 if agrandie else BORD,) * 4)
            self.barre_titre.etat_fenetre(agrandie)
        super().changeEvent(e)

    def _bords(self, pos) -> Qt.Edges:
        if self.isMaximized():
            return Qt.Edges()
        bords = Qt.Edges()
        if pos.x() <= BORD:
            bords |= Qt.LeftEdge
        if pos.x() >= self.width() - BORD:
            bords |= Qt.RightEdge
        if pos.y() <= BORD:
            bords |= Qt.TopEdge
        if pos.y() >= self.height() - BORD:
            bords |= Qt.BottomEdge
        return bords

    def mouseMoveEvent(self, e):
        bords = self._bords(e.position().toPoint())
        curseurs = {Qt.LeftEdge: Qt.SizeHorCursor, Qt.RightEdge: Qt.SizeHorCursor,
                    Qt.TopEdge: Qt.SizeVerCursor, Qt.BottomEdge: Qt.SizeVerCursor,
                    Qt.LeftEdge | Qt.TopEdge: Qt.SizeFDiagCursor,
                    Qt.RightEdge | Qt.BottomEdge: Qt.SizeFDiagCursor,
                    Qt.RightEdge | Qt.TopEdge: Qt.SizeBDiagCursor,
                    Qt.LeftEdge | Qt.BottomEdge: Qt.SizeBDiagCursor}
        self.setCursor(curseurs.get(bords, Qt.ArrowCursor))
        super().mouseMoveEvent(e)

    def mousePressEvent(self, e):
        bords = self._bords(e.position().toPoint())
        if e.button() == Qt.LeftButton and bords:
            self.windowHandle().startSystemResize(bords)
            return
        super().mousePressEvent(e)

    # Espaces de travail

    def _disposition(self, espace: str):
        """Disposition par défaut d'un espace : quels panneaux, où, et à quelle taille."""
        d = self._docks
        visibles = PANNEAUX_ESPACE[espace]
        for nom, dock in d.items():
            dock.setFloating(False)
        if espace == "export":
            self.addDockWidget(Qt.LeftDockWidgetArea, d["export"])
            self.addDockWidget(Qt.BottomDockWidgetArea, d["timeline"])
            self.splitDockWidget(d["export"], d["visionneuse"], Qt.Horizontal)
            self.splitDockWidget(d["visionneuse"], d["file_export"], Qt.Horizontal)
            self.resizeDocks([d["export"], d["visionneuse"], d["file_export"]], [340, 900, 360],
                             Qt.Horizontal)
            self.resizeDocks([d["visionneuse"], d["timeline"]], [640, 260], Qt.Vertical)
        else:
            self.addDockWidget(Qt.LeftDockWidgetArea, d["medias"])
            self.addDockWidget(Qt.BottomDockWidgetArea, d["timeline"])
            self.splitDockWidget(d["medias"], d["visionneuse"], Qt.Horizontal)
            self.splitDockWidget(d["visionneuse"], d["droite"], Qt.Horizontal)
            self.splitDockWidget(d["droite"], d["mixage"], Qt.Horizontal)
            if espace == "media":
                self.resizeDocks([d["medias"], d["visionneuse"], d["droite"]], [640, 640, 380],
                                 Qt.Horizontal)
            else:
                self.resizeDocks([d["medias"], d["visionneuse"], d["droite"], d["mixage"]],
                                 [320, 860, 340, 56], Qt.Horizontal)
                self.resizeDocks([d["visionneuse"], d["timeline"]], [520, 420], Qt.Vertical)
        for nom, dock in d.items():
            dock.setVisible(nom in visibles)

    def _appliquer_espace(self, espace: str, par_defaut: bool = False):
        reglages = QSettings("Remanence", "Remanence")
        etat = None if par_defaut else reglages.value(f"disposition/{espace}")
        if etat is None or not self.restoreState(etat, VERSION_DISPOSITION):
            self._disposition(espace)
        # Une disposition mémorisée ne doit jamais faire apparaître un panneau d'un autre espace.
        for nom, dock in self._docks.items():
            if nom not in PANNEAUX_ESPACE[espace]:
                dock.hide()
        if espace == "media":
            self.onglets_droite.choisir(1)
        elif espace == "export":
            self.formulaire_export.actualiser(self.projet, self.chemin)
        self._espace = espace
        self.barre_espaces.activer(espace)

    def choisir_espace(self, espace: str):
        """Change la disposition ; le projet, la sélection et la tête de lecture ne bougent pas."""
        if espace == self._espace:
            return
        QSettings("Remanence", "Remanence").setValue(f"disposition/{self._espace}",
                                                     self.saveState(VERSION_DISPOSITION))
        self._appliquer_espace(espace)

    def _restaurer_disposition(self):
        reglages = QSettings("Remanence", "Remanence")
        espace = reglages.value("espace_actif", "montage")
        if espace in PANNEAUX_ESPACE:
            self._appliquer_espace(espace)

    def retablir_disposition(self):
        reglages = QSettings("Remanence", "Remanence")
        for espace in PANNEAUX_ESPACE:
            reglages.remove(f"disposition/{espace}")
        self._appliquer_espace(self._espace, par_defaut=True)

    # Menus et raccourcis

    def _action(self, menu, texte, fonction, raccourci=None, aide=None):
        a = QAction(texte, self)
        if raccourci:
            a.setShortcuts([QKeySequence(r) for r in
                            (raccourci if isinstance(raccourci, list) else [raccourci])])
        if aide:
            a.setStatusTip(aide)
            a.setToolTip(aide)
        a.triggered.connect(fonction)
        menu.addAction(a)
        return a

    def _actions(self):
        m = self.barre_titre.menus
        f = m.addMenu("&Fichier")
        self._action(f, "Nouveau projet", self.nouveau, "Ctrl+N")
        self._action(f, "Ouvrir un projet…", self.ouvrir, "Ctrl+O")
        self._action(f, "Enregistrer", self.enregistrer, "Ctrl+S",
                     "Enregistre le projet et en garde une version numérotée.")
        self._action(f, "Enregistrer sous…", self.enregistrer_sous, "Ctrl+Shift+S")
        f.addSeparator()
        self._action(f, "Importer des médias…", self.importer, "Ctrl+I")
        self._action(f, "Exporter la séquence…", lambda: self.choisir_espace("export"), "Ctrl+E")
        f.addSeparator()
        self._action(f, "Quitter", self.close, "Ctrl+Q")

        e = m.addMenu("É&dition")
        self.a_annuler = self._action(e, "Annuler", self.annuler, "Ctrl+Z")
        self.a_retablir = self._action(e, "Rétablir", self.retablir, ["Ctrl+Y", "Ctrl+Shift+Z"])

        mo = m.addMenu("&Montage")
        self._action(mo, "Outil de sélection", lambda: self.timeline.choisir_outil("selection"),
                     "V")
        self._action(mo, "Outil de coupe", lambda: self.timeline.choisir_outil("couper"), "C")
        mo.addSeparator()
        self._action(mo, "Couper à la tête de lecture", self.couper, ["S", "B"],
                     "Coupe les clips sélectionnés, ou tous ceux sous la tête si rien n'est "
                     "sélectionné.")
        self._action(mo, "Supprimer les clips sélectionnés", self.supprimer, ["Del", "Backspace"])
        self._action(mo, "Dissocier son et image", self.dissocier, "U")
        self._action(mo, "Lier la sélection", self.lier, "Ctrl+L")
        mo.addSeparator()
        self._action(mo, "Ajouter une piste vidéo", lambda: self.ajouter_piste("video"))
        self._action(mo, "Ajouter une piste audio", lambda: self.ajouter_piste("audio"))
        mo.addSeparator()
        self._action(mo, "Ajouter un marqueur", self.marqueur, "M")

        lec = m.addMenu("&Lecture")
        self._action(lec, "Lire / Pause", self._espace_clavier, "Space")
        self._action(lec, "Lecture arrière", lambda: self._jkl(-1), "J")
        self._action(lec, "Arrêt", self.lecture.pause, "K")
        self._action(lec, "Lecture avant", lambda: self._jkl(1), "L")
        self.a_boucle = self._action(lec, "Lecture en boucle", self._basculer_boucle, "Ctrl+B")
        self.a_boucle.setCheckable(True)
        lec.addSeparator()
        self._action(lec, "Image précédente", lambda: self._pas(-1), "Left")
        self._action(lec, "Image suivante", lambda: self._pas(1), "Right")
        self._action(lec, "Une seconde en arrière", lambda: self._pas(-self._cadence()),
                     "Shift+Left")
        self._action(lec, "Une seconde en avant", lambda: self._pas(self._cadence()),
                     "Shift+Right")
        self._action(lec, "Début de la séquence", lambda: self.aller_a(0), "Home")
        self._action(lec, "Fin de la séquence",
                     lambda: self.aller_a(max(0, self.projet.sequence.duree() - 1)), "End")
        lec.addSeparator()
        self._action(lec, "Point d'entrée", self.point_entree, "I")
        self._action(lec, "Point de sortie", self.point_sortie, "O")
        self._action(lec, "Effacer les points d'entrée et de sortie", self.effacer_points,
                     "Alt+X")

        a = m.addMenu("&Affichage")
        qualite = a.addMenu("Résolution de l'aperçu")
        for cle, nom in LIBELLES_QUALITE.items():
            self._action(qualite, nom,
                         lambda _=False, cle=cle: self.visionneuse.choisir_qualite(cle))
        a.addSeparator()
        for i, (cle, nom) in enumerate((("media", "Média"), ("montage", "Montage"),
                                        ("export", "Export")), 1):
            self._action(a, f"Espace {nom}", lambda _=False, cle=cle: self.choisir_espace(cle),
                         f"Shift+{i}")
        a.addSeparator()
        self.a_barre_espaces = self._action(a, "Barre des espaces de travail",
                                            lambda v: self.barre_bas.setVisible(v))
        self.a_barre_espaces.setCheckable(True)
        self.a_barre_espaces.setChecked(True)
        self._action(a, "Plein écran", self._plein_ecran, "F11")

        fe = m.addMenu("F&enêtre")
        for nom, dock, titre in (("medias", self._docks["medias"], "Média"),
                                 ("visionneuse", self._docks["visionneuse"], "Programme"),
                                 ("droite", self._docks["droite"], "Inspecteur"),
                                 ("mixage", self._docks["mixage"], "Vumètres"),
                                 ("timeline", self._docks["timeline"], "Timeline")):
            act = dock.toggleViewAction()
            act.setText(titre)
            fe.addAction(act)
        fe.addSeparator()
        detacher = fe.addMenu("Détacher un panneau")
        for nom, titre in (("medias", "Média"), ("visionneuse", "Programme"),
                           ("droite", "Inspecteur"), ("timeline", "Timeline")):
            self._action(detacher, titre, lambda _=False, nom=nom: self._docks[nom].setFloating(
                not self._docks[nom].isFloating()))
        fe.addSeparator()
        self._action(fe, "Revenir à la disposition par défaut", self.retablir_disposition)

        ai = m.addMenu("&Aide")
        self._action(ai, "À propos de Remanence", lambda: APropos(self).exec())

    def _plein_ecran(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _connecter(self):
        self.medias.importer.connect(self.importer)
        self.medias.fichiers_deposes.connect(self.importer_chemins)
        self.medias.media_selectionne.connect(self._media_choisi)
        self.medias.media_active.connect(lambda mid: self.poser_medias([mid],
                                                                       self.lecture.position, ""))
        vue = self.timeline.vue
        vue.modifie.connect(self.valider)
        vue.tete_changee.connect(self.aller_a)
        vue.selection_changee.connect(self._selection)
        vue.media_depose.connect(self.poser_medias)
        self.inspecteur.reglage.connect(self._reglage_clip)
        self.liste_historique.aller.connect(self._aller_historique)
        self.formulaire_export.lancer.connect(self._lancer_export)
        self.lecture.image_prete.connect(lambda image, f: self.visionneuse.zone.montrer(image))
        self.lecture.position_changee.connect(self._position)
        self.lecture.lecture_changee.connect(self.visionneuse.etat_lecture)
        self.lecture.erreur.connect(lambda m, d: self.message(f"Image impossible à calculer : {m}",
                                                              8000))
        v = self.visionneuse
        v.demande_lecture.connect(self.lire_pause)
        v.demande_position.connect(self.aller_a)
        v.demande_qualite.connect(self.lecture.definir_qualite)
        v.b_debut.clicked.connect(lambda: self.aller_a(0))
        v.b_fin.clicked.connect(lambda: self.aller_a(max(0, self.projet.sequence.duree() - 1)))
        v.b_prec.clicked.connect(lambda: self._pas(-1))
        v.b_suiv.clicked.connect(lambda: self._pas(1))
        v.b_boucle.toggled.connect(self._boucle)

    # Affichage de l'état

    def message(self, texte: str, duree_ms: int = 5000):
        self.barre_espaces.message.setText(texte)
        QTimer.singleShot(duree_ms, lambda: self.barre_espaces.message.text() == texte
                          and self.barre_espaces.message.setText(""))

    def _afficher_tout(self):
        self.medias.afficher(self.projet)
        self.timeline.afficher(self.projet)
        self.lecture.definir_projet(self.projet)
        self._selection(self.timeline.vue.selection)
        self._titre()
        self._position(self.lecture.position)
        seq = self.projet.sequence
        self.visionneuse.afficher_points(seq)
        self._entete_visionneuse.precision.setText(seq.nom)
        self._boucle(self.visionneuse.b_boucle.isChecked())
        self.liste_historique.afficher(self.historique.libelles(), self.historique.position)
        if self._espace == "export":
            self.formulaire_export.actualiser(self.projet, self.chemin)
        self.a_annuler.setEnabled(self.historique.peut_annuler())
        self.a_retablir.setEnabled(self.historique.peut_retablir())
        self.a_annuler.setText(f"Annuler {self.historique.libelle_annuler().lower()}".strip())
        self.a_retablir.setText(f"Rétablir {self.historique.libelle_retablir().lower()}".strip())
        if not seq.duree():
            self.visionneuse.zone.montrer_message(
                "Glissez un média sur la timeline pour le voir ici.")

    def _titre(self):
        nom = self.chemin.stem if self.chemin else "Sans titre"
        self.setWindowTitle(f"{nom}{' (modifié)' if self.modifie else ''} · Remanence")
        seq = self.projet.sequence
        cad = f"{float(seq.fraction_cadence):.3f}".rstrip("0").rstrip(".").replace(".", ",")
        self.barre_titre.afficher_projet(nom, self.modifie, seq.largeur, seq.hauteur, cad)
        self._etat_sauvegarde()

    def _etat_sauvegarde(self):
        if self._derniere_sauvegarde is None:
            texte = "Projet jamais enregistré"
        else:
            minutes = int((time.time() - self._derniere_sauvegarde) // 60)
            texte = ("Enregistré à l'instant" if minutes < 1
                     else f"Enregistré il y a {minutes} min")
        self.barre_titre.projet.setToolTip(texte)

    def _badge(self, texte: str | None = None):
        if texte is not None:
            self.badge_inspecteur.setText(texte)
        # Le badge décrit le contenu de l'onglet Inspecteur : caché sur les autres onglets.
        self.badge_inspecteur.setVisible(bool(self.badge_inspecteur.text())
                                         and self.onglets_droite.currentIndex() == 0)

    def valider(self, libelle: str):
        """À appeler après toute modification du projet : historique, affichage, aperçu."""
        if self.historique.valider(self.projet, libelle):
            self.modifie = True
        self._afficher_tout()

    def _remplacer_projet(self, projet: Projet):
        hors_ligne = {m.id: m.hors_ligne for m in self.projet.medias.values()}
        for m in projet.medias.values():
            m.hors_ligne = hors_ligne.get(m.id, m.hors_ligne)
        self.projet = projet
        self.modifie = True
        self._afficher_tout()

    def _aller_historique(self, position: int):
        p = self.historique.aller(position)
        if p is not None:
            self._remplacer_projet(p)

    def _position(self, f: int):
        seq = self.projet.sequence
        for champ in (self.visionneuse.timecode, self.timeline.timecode):
            champ.afficher(f, seq.tc_debut, seq.fraction_cadence, seq.tc_drop)
        self.timeline.suivre_tete(f)

    def _cadence(self) -> int:
        return max(1, round(float(self.projet.sequence.fraction_cadence)))

    def _selection(self, ids: set):
        if len(ids) == 1:
            clip_id = next(iter(ids))
            self.inspecteur.clip(self.projet, clip_id)
            _, c = self.projet.sequence.trouver(clip_id)
            media = self.projet.medias.get(c.media_id) if c else None
            if media:
                self.metadonnees.afficher(media)
            if self.onglets_droite.currentIndex() == 1 and self._espace == "montage":
                self.onglets_droite.choisir(0)
        elif ids:
            self.inspecteur.vide()
            self.message(f"{len(ids)} clips sélectionnés", 3000)
        else:
            self.inspecteur.vide()

    def _media_choisi(self, media):
        if media is not None:
            self.metadonnees.afficher(media)
            self.onglets_droite.choisir(1)

    # Lecture

    def aller_a(self, f: int):
        if self.lecture.en_lecture:
            self.lecture.pause()
        self.lecture.aller_a(f)

    def _pas(self, n: int):
        self.aller_a(max(0, self.lecture.position + n))

    def _espace_clavier(self):
        # Espace active le bouton qui a le focus clavier, comme partout ailleurs sous Windows.
        focus = QApplication.focusWidget()
        if isinstance(focus, QAbstractButton) and focus is not self.visionneuse.b_lire:
            focus.click()
        else:
            self.lire_pause()

    def lire_pause(self):
        if self.lecture.en_lecture:
            self.lecture.pause()
        else:
            if self.lecture.position >= self.projet.sequence.duree() - 1:
                self.lecture.aller_a(0)
            self.lecture.lire(1.0)

    def _jkl(self, sens: int):
        v = self.lecture.vitesse
        vitesse = max(-8.0, min(8.0, v * 2)) if v * sens > 0 else float(sens)
        self.lecture.lire(vitesse)
        self.message(f"Lecture {'avant' if vitesse > 0 else 'arrière'} ×{abs(vitesse):g}" +
                     ("" if vitesse == 1 else ", son coupé"), 2000)

    def _basculer_boucle(self):
        self.visionneuse.b_boucle.toggle()

    def _boucle(self, actif: bool):
        self.a_boucle.setChecked(actif)
        seq = self.projet.sequence
        if not actif:
            self.lecture.definir_boucle(None)
            return
        debut = seq.point_entree or 0
        fin = seq.point_sortie if seq.point_sortie is not None else seq.duree()
        self.lecture.definir_boucle((debut, fin))

    def point_entree(self):
        self.projet.sequence.point_entree = self.lecture.position
        self.valider("Point d'entrée")

    def point_sortie(self):
        self.projet.sequence.point_sortie = self.lecture.position + 1
        self.valider("Point de sortie")

    def effacer_points(self):
        self.projet.sequence.point_entree = self.projet.sequence.point_sortie = None
        self.valider("Points effacés")

    def marqueur(self):
        seq = self.projet.sequence
        seq.marqueurs.append(Marqueur(self.lecture.position, f"Marqueur {len(seq.marqueurs) + 1}"))
        self.valider("Marqueur")

    # Montage

    def _tenter(self, libelle: str, operation):
        try:
            operation()
        except edition.EditionImpossible as e:
            self.message(str(e))
            return
        self.valider(libelle)

    def couper(self):
        sel = self.timeline.vue.selection
        self._tenter("Coupe", lambda: edition.couper(self.projet.sequence, self.lecture.position,
                                                     edition.avec_lies(self.projet.sequence, sel)
                                                     if sel else None))

    def supprimer(self):
        sel = set(self.timeline.vue.selection)
        if sel:
            self.timeline.vue.selection = set()
            self._tenter("Suppression", lambda: edition.supprimer(self.projet.sequence, sel))

    def dissocier(self):
        sel = set(self.timeline.vue.selection)
        if sel:
            self._tenter("Dissociation", lambda: edition.dissocier(
                self.projet.sequence, edition.avec_lies(self.projet.sequence, sel)))

    def lier(self):
        sel = set(self.timeline.vue.selection)
        if len(sel) > 1:
            self._tenter("Liaison", lambda: edition.lier(self.projet.sequence, sel))

    def ajouter_piste(self, type_: str):
        edition.ajouter_piste(self.projet.sequence, type_)
        self.valider("Nouvelle piste")

    def supprimer_piste(self, piste_id: str):
        piste = next((p for p in self.projet.sequence.pistes if p.id == piste_id), None)
        if piste is None:
            return
        if piste.clips:
            r = QMessageBox.question(
                self, "Supprimer la piste",
                f"La piste contient {len(piste.clips)} clip(s). La supprimer avec ses clips ? "
                "Vous pourrez l'annuler avec Ctrl+Z.",
                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
            if r != QMessageBox.Yes:
                return
        edition.supprimer_piste(self.projet.sequence, piste_id)
        self.valider("Suppression de piste")

    def regler_piste(self, piste_id: str, champ: str, valeur):
        for p in self.projet.sequence.pistes:
            if p.id == piste_id:
                if getattr(p, champ) == valeur:
                    return
                setattr(p, champ, valeur)
        QTimer.singleShot(0, lambda: self.valider({
            "masquee": "Piste masquée", "muette": "Piste muette", "solo": "Solo de piste",
            "verrouillee": "Verrou de piste", "niveau": "Niveau de piste"}[champ]))

    def deplacer_piste(self, piste_id: str, sens: int):
        edition.deplacer_piste(self.projet.sequence, piste_id, sens)
        self.valider("Ordre des pistes")

    def _reglage_clip(self, clip_id: str, champ: str, valeur):
        _, c = self.projet.sequence.trouver(clip_id)
        if c is None or getattr(c, champ) == valeur:
            return
        if champ in ("fondu_entree", "fondu_sortie"):
            edition.regler_fondu(self.projet.sequence, clip_id,
                                 "entree" if champ == "fondu_entree" else "sortie", valeur)
        else:
            setattr(c, champ, valeur)
        QTimer.singleShot(0, lambda: self.valider({
            "gain": "Niveau", "fondu_entree": "Fondu d'entrée", "fondu_sortie": "Fondu de sortie",
            "enveloppe": "Enveloppe"}[champ]))

    def poser_medias(self, ids: list[str], f: int, piste_id: str):
        seq = self.projet.sequence
        piste = next((p for p in seq.pistes if p.id == piste_id), None)
        position = f
        try:
            for mid in ids:
                media = self.projet.medias.get(mid)
                if media is None:
                    continue
                clips = edition.ajouter_media(self.projet, seq, media, position, piste)
                if clips:
                    position = max(c.fin for c in clips)
        except edition.EditionImpossible as e:
            self.message(str(e))
        self.valider("Ajout à la timeline")
        if len(ids) == 1 and seq.duree() and self.timeline.vue.px_par_image == 6.0:
            self.timeline.tout_voir()

    def annuler(self):
        p = self.historique.annuler()
        if p is not None:
            self._remplacer_projet(p)

    def retablir(self):
        p = self.historique.retablir()
        if p is not None:
            self._remplacer_projet(p)

    # Import

    def importer(self):
        chemins, _ = QFileDialog.getOpenFileNames(
            self, "Importer des médias", "", f"Médias ({EXTENSIONS_MEDIAS});;Tous les fichiers (*)")
        if chemins:
            self.importer_chemins(chemins)

    def importer_chemins(self, chemins: list[str]):
        fichiers: list[Path] = []
        for c in chemins:
            p = Path(c)
            if p.is_dir():
                fichiers += sorted(f for f in p.rglob("*") if f.is_file())
            elif p.exists():
                fichiers.append(p)
        vus_sequences = set()
        deja = {str(Path(m.chemin).resolve()) for m in self.projet.medias.values()}
        for f in fichiers:
            seq_img = detecter_sequence_images(f)
            if seq_img:
                if seq_img["motif"] in vus_sequences:
                    continue
                vus_sequences.add(seq_img["motif"])
                cadence, ok = QInputDialog.getItem(
                    self, "Cadence de la séquence d'images",
                    f"{Path(seq_img['motif']).name} contient {seq_img['nombre']} images.\n"
                    "À quelle cadence faut-il la lire ?",
                    ["24000/1001", "24", "25", "30000/1001", "30", "50", "60"], 1, False)
                if not ok:
                    continue
                self._analyser(str(f), cadence)
            elif f.suffix.lower() in EXTENSIONS_IMAGES and len(fichiers) > 1:
                continue
            elif str(f.resolve()) not in deja:
                self._analyser(str(f), None)

    def _analyser(self, chemin: str, cadence: str | None):
        self._analyses += 1
        self.medias.signaler_analyses(self._analyses)

        def travail(progression, annule):
            infos, _ = analyser(chemin, cadence)
            if infos.video and infos.video.cadence_variable:
                cible = intermediaire.creer_intermediaire(infos, progression, annule)
                infos_cfr, _ = analyser(str(cible))
                infos_cfr.avertissements = [
                    f"Intermédiaire à cadence fixe ({infos_cfr.video.cadence} i/s) créé depuis "
                    f"« {infos.nom} », dont la cadence est variable. La source n'est pas modifiée."]
                infos_cfr.nom = infos.nom
                return infos_cfr
            return infos

        def fin_analyse():
            self._analyses -= 1
            self.medias.signaler_analyses(self._analyses)

        def reussi(infos):
            fin_analyse()
            m = Media(nouvel_id(), infos.chemin, infos)
            self.projet.medias[m.id] = m
            self.valider("Import")
            self._preparer(m)

        def echec(message, detail):
            fin_analyse()
            afficher_erreur(self, "Import impossible", message, detail)

        self.taches.lancer(Tache(f"Analyse de {Path(chemin).name}", travail), reussi, echec,
                           lambda: fin_analyse())

    def _preparer(self, media: Media):
        """Cache audio, proxy, vignette et bande de vignettes, calculés en arrière-plan."""
        infos = media.infos
        if infos.audio and not chemin_audio(infos).exists():
            def audio(progression, annule):
                return generer_cache_audio(infos, chemin_audio(infos), progression, annule)

            def audio_pret(_):
                self.timeline.vue.oublier_ondes()
                self.timeline.vue.update()
                self.lecture.definir_projet(self.projet)
            self.taches.lancer(Tache(f"Son de {media.nom}", audio), audio_pret,
                               lambda m, d: self.message(f"Son illisible pour {media.nom} : {m}",
                                                         8000))
        if not infos.video:
            return
        self.taches.lancer(Tache(f"Vignettes de {media.nom}",
                                 lambda p, a: _vignettes(media, 120, a)),
                           lambda res: self._poser_vignettes(media.id, *res))
        if proxy_utile(infos) and not chemin_proxy(infos).exists():
            self.taches.lancer(Tache(f"Proxy de {media.nom}",
                                     lambda p, a: generer_proxy(infos, p, a)),
                               lambda _: self.lecture.definir_projet(self.projet),
                               lambda m, d: self.message(f"Proxy impossible pour {media.nom} : {m}",
                                                         8000))

    def _poser_vignettes(self, media_id: str, images: list[np.ndarray], pas: float):
        qimages = [_qimage(i) for i in images]
        self.timeline.vue.vignettes[media_id] = (qimages, pas)
        self.timeline.vue.update()
        if qimages:
            milieu = qimages[len(qimages) // 2]
            self.medias.definir_vignette(media_id, QPixmap.fromImage(milieu))

    # Export

    def exporter(self):
        self.choisir_espace("export")

    def _lancer_export(self, r: dict):
        copie = Projet.depuis_dict(self.projet.vers_dict())
        for m in copie.medias.values():
            m.hors_ligne = self.projet.medias[m.id].hors_ligne
        nom = r["chemin"].name
        tache = Tache(f"Export de {nom}", lambda progression, annule: exporter(
            copie, copie.sequence, r["chemin"], r["cle_format"], r["debut"], r["fin"],
            progression, annule))
        ligne = self.file_export.ajouter(nom, r["format"], lambda: tache.annule.set())
        tache.signaux.progression.connect(ligne.progression)

        def termine(rapport):
            ligne.termine(rapport)
            self.message(f"Export de {nom} terminé.", 6000)

        def echec(m, det):
            ligne.echec(m)
            afficher_erreur(self, "Export impossible", f"L'export de « {nom} » a échoué : {m}", det)

        self.taches.lancer(tache, termine, echec, ligne.annule)

    # Projet

    def _confirmer_abandon(self) -> bool:
        if not self.modifie:
            return True
        r = QMessageBox.question(
            self, "Modifications non enregistrées",
            "Le projet contient des modifications non enregistrées. Les enregistrer ?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if r == QMessageBox.Save:
            return self.enregistrer()
        return r == QMessageBox.Discard

    def nouveau(self):
        if not self._confirmer_abandon():
            return
        self.projet = Projet.nouveau()
        self.historique = Historique(self.projet)
        self.chemin = None
        self.modifie = False
        self._derniere_sauvegarde = None
        self.timeline.vue.selection = set()
        self.lecture.aller_a(0)
        self._afficher_tout()

    def ouvrir(self, chemin: str | None = None):
        if not self._confirmer_abandon():
            return
        if not chemin:
            chemin, _ = QFileDialog.getOpenFileName(self, "Ouvrir un projet", "",
                                                    "Projet Remanence (*.remanence)")
        if not chemin:
            return
        chemin = Path(chemin)
        source = chemin
        auto = serialisation.sauvegarde_auto_plus_recente(chemin) if chemin.exists() else None
        if auto is not None:
            r = QMessageBox.question(
                self, "Sauvegarde automatique plus récente",
                f"Une sauvegarde automatique de « {chemin.stem} » est plus récente que le projet "
                "enregistré. Ouvrir la sauvegarde automatique ?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if r == QMessageBox.Yes:
                source = auto
        try:
            projet = serialisation.ouvrir(source)
        except ValueError as e:
            afficher_erreur(self, "Ouverture impossible", str(e))
            return
        self.projet = projet
        self.historique = Historique(projet)
        self.chemin = chemin
        self.modifie = source != chemin
        self._derniere_sauvegarde = chemin.stat().st_mtime if chemin.exists() else None
        self.timeline.vue.selection = set()
        self.lecture.aller_a(0)
        self._afficher_tout()
        self.timeline.tout_voir()
        absents = [m.nom for m in projet.medias.values() if m.hors_ligne]
        if absents:
            QMessageBox.warning(self, "Médias introuvables",
                                "Ces médias ont été déplacés ou renommés, leurs clips sont "
                                "affichés hors ligne :\n\n" + "\n".join(absents))
        for m in projet.medias.values():
            if not m.hors_ligne:
                self._preparer(m)

    def enregistrer(self) -> bool:
        if self.chemin is None:
            return self.enregistrer_sous()
        try:
            version = serialisation.enregistrer(self.projet, self.chemin)
        except OSError as e:
            afficher_erreur(self, "Enregistrement impossible",
                            f"Le projet n'a pas pu être écrit dans « {self.chemin} » : {e}. "
                            "Vérifiez que le disque n'est pas plein ou en lecture seule.")
            return False
        self.modifie = False
        self._derniere_sauvegarde = time.time()
        self._titre()
        self.message(f"Projet enregistré (version {version.stem.rsplit('_v', 1)[1]})", 4000)
        return True

    def enregistrer_sous(self) -> bool:
        chemin, _ = QFileDialog.getSaveFileName(self, "Enregistrer le projet",
                                                str(self.chemin or Path.home() / "projet.remanence"),
                                                "Projet Remanence (*.remanence)")
        if not chemin:
            return False
        self.chemin = Path(chemin).with_suffix(serialisation.EXTENSION)
        return self.enregistrer()

    def _sauvegarde_auto(self):
        if not self.modifie:
            return
        try:
            serialisation.enregistrer_auto(self.projet, self.chemin)
        except OSError:
            return
        self.message(f"Sauvegarde automatique à {time.strftime('%H:%M')}", 4000)

    def closeEvent(self, e):
        if not self._confirmer_abandon():
            e.ignore()
            return
        reglages = QSettings("Remanence", "Remanence")
        reglages.setValue(f"disposition/{self._espace}", self.saveState(VERSION_DISPOSITION))
        reglages.setValue("espace_actif", self._espace)
        self.taches.tout_annuler()
        self.lecture.fermer()
        self.taches.attendre(3000)
        e.accept()
