"""Fenêtre principale : panneaux ancrables, menus, raccourcis et cycle de vie du projet."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication, QImage, QKeySequence
from PySide6.QtWidgets import (QAbstractButton, QApplication, QDialog, QFileDialog, QInputDialog,
                               QMainWindow, QMessageBox, QSizePolicy, QToolBar, QVBoxLayout,
                               QWidget)

from remanence.config import reglages_interface
from remanence.effets import EFFETS, poser_cle, retirer_cle, valeur_a
from remanence.effets import prereglages
from remanence.media import intermediaire
from remanence.media.lecteur import LecteurVideo, generer_cache_audio
from remanence.media.proxy import chemin_audio, chemin_proxy, generer_proxy, proxy_utile
from remanence.media.sonde import EXTENSIONS_IMAGES, analyser, detecter_sequence_images
from remanence.projet import edition, serialisation
from remanence.projet.historique import Historique
from remanence.projet.modele import Clip, Marqueur, Media, Projet, nouvel_id
from remanence.rendu.couleur import vers_rvb16_apercu, vers_rvba
from remanence.media.timecode import images_vers_tc
from remanence.rendu.export import exporter
from remanence.ui import charte
from remanence.ui.apropos import APropos
from remanence.ui.barres import BarreEspaces, BarreTitre
from remanence.ui.composants import Porte, etiquette, panneau, panneau_onglets
from remanence.ui.dialogue_timecode import DialogueTimecode, preference, timecode_une_heure
from remanence.ui.erreurs import afficher_erreur
from remanence.ui.inspecteur import Historique as ListeHistorique
from remanence.ui.inspecteur import Inspecteur, Metadonnees
from remanence.ui.lecture import MoteurLecture
from remanence.ui.medias import PanneauMedias
from remanence.ui.bibliotheque import PanneauEffets
from remanence.ui.menu_effets import remplir_menu_effets
from remanence.ui.panneau_export import FileExport, FormulaireExport
from remanence.ui.taches import GestionnaireTaches, Tache
from remanence.ui.timeline import Timeline
from remanence.ui.visionneuse import (LIBELLES_QUALITE, Moniteur, ZoneImage, glisser_source,
                                      peindre_cadre_actif)

INTERVALLE_AUTO_MS = 2 * 60 * 1000
EXTENSIONS_MEDIAS = ("*.mov *.mp4 *.mxf *.mkv *.avi *.webm *.mts *.m2ts *.m4v *.mpg *.mpeg "
                     "*.wav *.aif *.aiff *.mp3 *.flac *.m4a *.dpx *.exr *.tif *.tiff *.png "
                     "*.jpg *.jpeg *.braw *.r3d *.ari")
HAUTEUR_VIGNETTE = 48
BORD = 5
# À augmenter quand les panneaux changent : les dispositions mémorisées avant sont ignorées.
VERSION_DISPOSITION = 4
# Panneaux visibles dans chaque espace de travail.
PANNEAUX_ESPACE = {
    "media": {"medias", "source", "droite"},
    "montage": {"medias", "source", "visionneuse", "droite", "timeline"},
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
        self.bibliotheque = PanneauEffets()
        self.visionneuse = Moniteur("programme")
        self.source = Moniteur("source")
        self.source.zone.glissable = True
        self.lecture_source = MoteurLecture()
        self.media_source: Media | None = None
        self._actif = "programme"
        # Piste dont l'inspecteur montre les effets (clic sur son en-tête).
        self._piste_choisie: str | None = None
        self._un_seul = False
        self._double_ecran: QMainWindow | None = None
        # Double écran : None, "panneaux" (comme Resolve) ou "timeline" (timeline seule à côté).
        self._mode_double: str | None = None
        self._barre_espaces_2 = None
        self._docks_ext: dict = {}
        self._programme_externe: QWidget | None = None
        self.inspecteur = Inspecteur()
        self.metadonnees = Metadonnees()
        self.liste_historique = ListeHistorique()
        self.timeline = Timeline(self)
        self.formulaire_export = FormulaireExport()
        self.file_export = FileExport()

        self.setDockNestingEnabled(True)
        self.setCentralWidget(QWidget())
        self.centralWidget().hide()
        self._docks = {}
        d, self.onglets_gauche = panneau_onglets([("Média", self.medias),
                                                  ("Effets", self.bibliotheque)], "medias", self)
        self._docks["medias"] = d
        # Métadonnées et Historique passent sur le second écran en double écran : leurs portes
        # restent ici, vides le temps du double écran.
        self._porte_meta = Porte(self.metadonnees)
        self._porte_histo = Porte(self.liste_historique)
        for w in (self.metadonnees, self.liste_historique):
            w.setProperty("role", "panneau")
            w.setAttribute(Qt.WA_StyledBackground, True)
        d, self.onglets_droite = panneau_onglets(
            [("Inspecteur", self.inspecteur), ("Métadonnées", self._porte_meta),
             ("Historique", self._porte_histo)], "droite", self)
        self._docks["droite"] = d
        self.badge_inspecteur = etiquette("", "badge-accent")
        self.badge_inspecteur.hide()
        # Le badge ne doit pas élargir le panneau : sinon les moniteurs sautent à chaque sélection.
        self.badge_inspecteur.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.onglets_droite.ajouter_outil(self.badge_inspecteur)
        d, self.onglets_export = panneau_onglets([("Export", self.formulaire_export)], "export",
                                                 self)
        self._docks["export"] = d
        d, _ = panneau_onglets([("File d'export", self.file_export)], "file_export", self)
        self._docks["file_export"] = d
        d, self._entete_source = panneau("Source", self.source, "source", self)
        self._docks["source"] = d
        self.source.qualite.hide()
        d, self._entete_visionneuse = panneau("Programme", self.visionneuse, "visionneuse", self)
        self._docks["visionneuse"] = d
        self._entete_visionneuse.ajouter(self.visionneuse.qualite)
        self.duree_source = etiquette("", "info-valeur")
        self._entete_source.ajouter(self.duree_source)
        self.duree_programme = etiquette("", "info-valeur")
        self._entete_visionneuse.ajouter(self.duree_programme)
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
        # Double écran retrouvé au lancement, si le second écran est toujours branché.
        mode = reglages_interface().value("double_ecran/mode", "")
        if mode in ("panneaux", "timeline") and len(QGuiApplication.screens()) > 1:
            QTimer.singleShot(0, lambda: self.choisir_double_ecran(mode))

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
            if not self._est_externe(nom):
                dock.setFloating(False)
        if espace == "export":
            self.addDockWidget(Qt.LeftDockWidgetArea, d["export"])
            self.addDockWidget(Qt.BottomDockWidgetArea, d["timeline"])
            self.splitDockWidget(d["export"], d["visionneuse"], Qt.Horizontal)
            self.splitDockWidget(d["visionneuse"], d["file_export"], Qt.Horizontal)
            self.resizeDocks([d["export"], d["visionneuse"], d["file_export"]], [340, 900, 360],
                             Qt.Horizontal)
            self.resizeDocks([d["visionneuse"], d["timeline"]], [640, 260], Qt.Vertical)
        elif espace == "media" and self._est_externe("medias"):
            self.addDockWidget(Qt.LeftDockWidgetArea, d["source"])
            self.splitDockWidget(d["source"], d["droite"], Qt.Horizontal)
            self.resizeDocks([d["source"], d["droite"]], [1100, 400], Qt.Horizontal)
        elif espace == "media":
            self.addDockWidget(Qt.LeftDockWidgetArea, d["medias"])
            self.splitDockWidget(d["medias"], d["source"], Qt.Horizontal)
            self.splitDockWidget(d["source"], d["droite"], Qt.Horizontal)
            self.resizeDocks([d["medias"], d["source"], d["droite"]], [620, 660, 380],
                             Qt.Horizontal)
        elif self._est_externe("medias"):
            # Double écran façon Resolve : moniteurs, inspecteur et timeline ici.
            self.addDockWidget(Qt.LeftDockWidgetArea, d["source"])
            self.addDockWidget(Qt.BottomDockWidgetArea, d["timeline"])
            self.splitDockWidget(d["source"], d["visionneuse"], Qt.Horizontal)
            self.splitDockWidget(d["visionneuse"], d["droite"], Qt.Horizontal)
            self.resizeDocks([d["source"], d["visionneuse"], d["droite"]], [620, 620, 360],
                             Qt.Horizontal)
            self.resizeDocks([d["visionneuse"], d["timeline"]], [500, 440], Qt.Vertical)
        else:
            self.addDockWidget(Qt.LeftDockWidgetArea, d["medias"])
            self.addDockWidget(Qt.BottomDockWidgetArea, d["timeline"])
            self.splitDockWidget(d["medias"], d["source"], Qt.Horizontal)
            self.splitDockWidget(d["source"], d["visionneuse"], Qt.Horizontal)
            self.splitDockWidget(d["visionneuse"], d["droite"], Qt.Horizontal)
            self.resizeDocks([d["medias"], d["source"], d["visionneuse"], d["droite"]],
                             [300, 480, 480, 340], Qt.Horizontal)
            self.resizeDocks([d["visionneuse"], d["timeline"]], [500, 440], Qt.Vertical)
        for nom, dock in d.items():
            if not self._est_externe(nom):
                dock.setVisible(nom in visibles)

    def _appliquer_espace(self, espace: str, par_defaut: bool = False):
        reglages = reglages_interface()
        etat = None if par_defaut else reglages.value(self._cle_disposition(espace))
        if etat is None or not self.restoreState(etat, VERSION_DISPOSITION):
            self._disposition(espace)
        # Une disposition mémorisée ne doit jamais faire apparaître un panneau d'un autre espace.
        for nom, dock in self._docks.items():
            if nom not in PANNEAUX_ESPACE[espace] and not self._est_externe(nom):
                dock.hide()
        if self._un_seul and espace == "montage":
            self.basculer_un_seul_moniteur()
        if espace == "media":
            self._montrer_metadonnees()
        elif espace == "export":
            self.formulaire_export.actualiser(self.projet, self.chemin)
        self._espace = espace
        self.barre_espaces.activer(espace)
        if self._barre_espaces_2 is not None:
            self._barre_espaces_2.activer(espace)

    def _cle_disposition(self, espace: str) -> str:
        # La disposition façon Resolve n'a pas les mêmes panneaux : elle est retenue à part.
        suffixe = "/double" if self._mode_double == "panneaux" else ""
        return f"disposition/{espace}{suffixe}"

    def _montrer_metadonnees(self):
        if self._mode_double == "panneaux":
            self._docks_ext["metadonnees"].show()
            self._docks_ext["metadonnees"].raise_()
        else:
            self.onglets_droite.choisir(1)

    def focus_initial(self):
        """Le clavier va à la timeline si elle est affichée ; sinon à personne, plutôt qu'au
        premier bouton venu (ou à la liste des médias, qui choisirait le premier média)."""
        if self._docks["timeline"].isVisible():
            self.timeline.vue.setFocus()
        elif QApplication.focusWidget() is not None:
            QApplication.focusWidget().clearFocus()

    def _est_externe(self, nom: str) -> bool:
        externes = {"panneaux": {"medias"}, "timeline": {"timeline"}}.get(self._mode_double, set())
        return nom in externes

    def choisir_espace(self, espace: str):
        """Change la disposition ; le projet, la sélection et la tête de lecture ne bougent pas."""
        if espace == self._espace:
            return
        reglages_interface().setValue(self._cle_disposition(self._espace),
                                      self.saveState(VERSION_DISPOSITION))
        self._appliquer_espace(espace)

    def _restaurer_disposition(self):
        reglages = reglages_interface()
        espace = reglages.value("espace_actif", "montage")
        if espace in PANNEAUX_ESPACE:
            self._appliquer_espace(espace)

    def retablir_disposition(self):
        reglages = reglages_interface()
        for espace in PANNEAUX_ESPACE:
            reglages.remove(f"disposition/{espace}")
            reglages.remove(f"disposition/{espace}/double")
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
                     "")
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
                     "")
        self._action(mo, "Supprimer les clips sélectionnés", self.supprimer, ["Del", "Backspace"])
        self._action(mo, "Dissocier son et image", self.dissocier, "U")
        self._action(mo, "Lier la sélection", self.lier, "G")
        mo.addSeparator()
        self.a_ripple = self._action(mo, "Ripple", self.timeline.b_ripple.toggle, "Ctrl+L",
                                     "")
        self.a_aimant = self._action(mo, "Aimantation", self.timeline.b_aimant.toggle,
                                     ["F8", "N"])
        self.a_fondus = self._action(mo, "Fondus enchaînés automatiques",
                                     self.timeline.b_fondus.toggle)
        for action, bouton in ((self.a_ripple, self.timeline.b_ripple),
                               (self.a_aimant, self.timeline.b_aimant),
                               (self.a_fondus, self.timeline.b_fondus)):
            action.setCheckable(True)
            action.setChecked(bouton.isChecked())
            action.triggered.disconnect()
            action.triggered.connect(lambda _=False, a=action, b=bouton:
                                     b.setChecked(a.isChecked()))
            bouton.toggled.connect(action.setChecked)
        mo.addSeparator()
        self._action(mo, "Insérer depuis la source", lambda: self.monter_source(True), "F9",
                     "")
        self._action(mo, "Écraser depuis la source", lambda: self.monter_source(False), "F10",
                     "")
        mo.addSeparator()
        self._action(mo, "Ajouter une piste vidéo", lambda: self.ajouter_piste("video"))
        self._action(mo, "Ajouter une piste audio", lambda: self.ajouter_piste("audio"))
        mo.addSeparator()
        self._menu_clip_effet = mo.addMenu("Ajouter un clip d'effet")
        self._menu_effet_sequence = mo.addMenu("Ajouter un effet de séquence")
        self._remplir_menus_effets()
        mo.addSeparator()
        self._action(mo, "Ajouter un marqueur", self.marqueur, "M")
        mo.addSeparator()
        self._action(mo, "Timecode de début de la séquence…", self.regler_timecode_debut,
                     aide="")

        lec = m.addMenu("&Lecture")
        self._action(lec, "Lire / Pause", self._espace_clavier, "Space")
        self._action(lec, "Lecture arrière", lambda: self._jkl(-1), "J")
        self._action(lec, "Arrêt", lambda: self._moteur().pause(), "K")
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
        self._action(lec, "Coupe précédente", lambda: self._aller_coupe(-1), "Up")
        self._action(lec, "Coupe suivante", lambda: self._aller_coupe(1), "Down")
        self._action(lec, "Marqueur précédent", lambda: self._aller_marqueur(-1), "Ctrl+Left")
        self._action(lec, "Marqueur suivant", lambda: self._aller_marqueur(1), "Ctrl+Right")
        self._action(lec, "Aller au début", lambda: self._aller_bord(False), "Home")
        self._action(lec, "Aller à la fin", lambda: self._aller_bord(True), "End")
        lec.addSeparator()
        self._action(lec, "Basculer entre source et programme", self.basculer_moniteur, "Q",
                     "")
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
        a.addSeparator()
        self.a_un_seul = self._action(a, "Un seul moniteur", self.basculer_un_seul_moniteur,
                                      "Ctrl+Shift+Q",
                                      "")
        self.a_un_seul.setCheckable(True)
        self.a_programme_externe = self._action(
            a, "Programme en plein écran", self.basculer_programme_externe, "Ctrl+F",
            "")
        double = a.addMenu("Double écran")
        self._groupe_double = QActionGroup(self)
        self.a_doubles = {}
        for mode, texte, aide in (
                (None, "Un seul écran", None),
                ("panneaux", "Panneaux sur le second écran",
                 ""),
                ("timeline", "Timeline sur le second écran",
                 "")):
            act = self._action(double, texte, lambda _=False, mode=mode:
                               self.choisir_double_ecran(mode), aide=aide)
            act.setCheckable(True)
            self._groupe_double.addAction(act)
            self.a_doubles[mode] = act
        self.a_doubles[None].setChecked(True)
        double.addSeparator()
        self.a_echanger = self._action(double, "Échanger les écrans", self.echanger_ecrans,
                                       aide="")
        QGuiApplication.instance().screenAdded.connect(lambda _e: self._ecrans_changes())
        QGuiApplication.instance().screenRemoved.connect(lambda _e: self._ecrans_changes())
        self._ecrans_changes()

        fe = m.addMenu("F&enêtre")
        for nom, dock, titre in (("medias", self._docks["medias"], "Média"),
                                 ("source", self._docks["source"], "Source"),
                                 ("visionneuse", self._docks["visionneuse"], "Programme"),
                                 ("droite", self._docks["droite"], "Inspecteur"),
                                 ("timeline", self._docks["timeline"], "Timeline")):
            act = dock.toggleViewAction()
            act.setText(titre)
            fe.addAction(act)
        fe.addSeparator()
        detacher = fe.addMenu("Détacher un panneau")
        for nom, titre in (("medias", "Média"), ("source", "Source"), ("visionneuse", "Programme"),
                           ("droite", "Inspecteur"), ("timeline", "Timeline")):
            self._action(detacher, titre, lambda _=False, nom=nom: self._docks[nom].setFloating(
                not self._docks[nom].isFloating()))
        fe.addSeparator()
        self._action(fe, "Revenir à la disposition par défaut", self.retablir_disposition)

        ai = m.addMenu("&Aide")
        self._action(ai, "À propos de Remanence", lambda: APropos(self).exec())

    def basculer_un_seul_moniteur(self):
        self._un_seul = self.a_un_seul.isChecked()
        if self._espace == "montage":
            self._docks["source"].setVisible(not self._un_seul or self._actif == "source")
            self._docks["visionneuse"].setVisible(not self._un_seul or self._actif == "programme")

    def _autre_ecran(self):
        for ecran in QGuiApplication.screens():
            if ecran is not self.screen():
                return ecran
        return None

    def _ecrans_changes(self):
        deux = len(QGuiApplication.screens()) > 1
        for mode, act in self.a_doubles.items():
            act.setEnabled(mode is None or deux or self._mode_double == mode)
            act.setToolTip(act.statusTip() if deux or mode is None
                           else "Aucun second écran détecté.")
        self.a_echanger.setEnabled(self._double_ecran is not None and deux)

    def choisir_double_ecran(self, mode: str | None):
        """Un seul écran, panneaux sur le second écran (comme Resolve), ou timeline seule à côté."""
        if mode == self._mode_double:
            return
        if self._mode_double is not None:
            self._quitter_double_ecran()
        if mode is not None:
            self._entrer_double_ecran(mode)
        self.a_doubles[self._mode_double].setChecked(True)
        self._ecrans_changes()

    def _entrer_double_ecran(self, mode: str):
        reglages_interface().setValue(self._cle_disposition(self._espace),
                                      self.saveState(VERSION_DISPOSITION))
        # Fenêtre sans parent : sinon restoreState() de la fenêtre principale retrouverait ses
        # panneaux parmi ses descendants et les rapatrierait au changement d'espace.
        # Sans cadre comme la fenêtre principale ; elle se ferme par Affichage > Double écran.
        fenetre = QMainWindow(None, Qt.Window | Qt.FramelessWindowHint)
        fenetre.setWindowTitle("Remanence · " + ("Panneaux" if mode == "panneaux" else "Timeline"))
        fenetre.setWindowIcon(self.windowIcon())
        fenetre.setCentralWidget(QWidget())
        fenetre.centralWidget().hide()
        fenetre.setDockNestingEnabled(True)
        self._mode_double = mode
        self._double_ecran = fenetre
        if mode == "timeline":
            dock = self._docks["timeline"]
            self.removeDockWidget(dock)
            fenetre.addDockWidget(Qt.BottomDockWidgetArea, dock)
            dock.show()
        else:
            medias = self._docks["medias"]
            self.removeDockWidget(medias)
            fenetre.addDockWidget(Qt.LeftDockWidgetArea, medias)
            medias.show()
            self.onglets_droite.choisir(0)
            for i in (1, 2):
                self.onglets_droite.masquer_onglet(i, True)
            self._docks_ext = {}
            for cle, titre, widget in (("metadonnees", "Métadonnées", self.metadonnees),
                                       ("historique", "Historique", self.liste_historique)):
                d, _ = panneau(titre, Porte(widget), f"{cle}_second_ecran", fenetre)
                fenetre.splitDockWidget(medias, d, Qt.Horizontal) if cle == "metadonnees" \
                    else fenetre.splitDockWidget(self._docks_ext["metadonnees"], d, Qt.Vertical)
                self._docks_ext[cle] = d
            fenetre.resizeDocks([medias, self._docks_ext["metadonnees"]], [1100, 500],
                                Qt.Horizontal)
            # Boutons pour afficher ou masquer chaque panneau du second écran, comme dans Resolve.
            barre = QToolBar("Panneaux")
            barre.setObjectName("panneaux_second_ecran")
            barre.setMovable(False)
            for dock, titre in ((medias, "Média"), (self._docks_ext["metadonnees"], "Métadonnées"),
                                (self._docks_ext["historique"], "Historique")):
                act = dock.toggleViewAction()
                act.setText(titre)
                act.setToolTip(f"Afficher ou masquer le panneau {titre}")
                barre.addAction(act)
                bouton = barre.widgetForAction(act)
                bouton.setProperty("variante", "panneau")
                bouton.setFocusPolicy(Qt.NoFocus)
            fenetre.addToolBar(Qt.TopToolBarArea, barre)
        # Barre des espaces en bas des deux écrans.
        self._barre_espaces_2 = BarreEspaces(QWidget())
        self._barre_espaces_2.espace_choisi.connect(self.choisir_espace)
        bas = QToolBar("Espaces de travail")
        bas.setMovable(False)
        bas.addWidget(self._barre_espaces_2)
        fenetre.addToolBar(Qt.BottomToolBarArea, bas)
        fenetre.closeEvent = lambda e: (e.accept(), self.choisir_double_ecran(None))
        ecran = self._autre_ecran()
        if ecran is not None:
            fenetre.setGeometry(ecran.availableGeometry())
            fenetre.showMaximized()
        else:
            fenetre.resize(1400, 800)
            fenetre.show()
        self._appliquer_espace(self._espace)

    def _quitter_double_ecran(self):
        fenetre, self._double_ecran = self._double_ecran, None
        mode, self._mode_double = self._mode_double, None
        if mode == "timeline":
            dock = self._docks["timeline"]
            fenetre.removeDockWidget(dock)
            self.addDockWidget(Qt.BottomDockWidgetArea, dock)
        else:
            dock = self._docks["medias"]
            fenetre.removeDockWidget(dock)
            self.addDockWidget(Qt.LeftDockWidgetArea, dock)
            self._porte_meta.poser(self.metadonnees)
            self._porte_histo.poser(self.liste_historique)
            for i in (1, 2):
                self.onglets_droite.masquer_onglet(i, False)
            self._docks_ext = {}
        self._barre_espaces_2 = None
        fenetre.closeEvent = lambda e: e.accept()
        fenetre.close()
        fenetre.deleteLater()
        self._appliquer_espace(self._espace)

    def echanger_ecrans(self):
        """Comme le choix de l'écran principal de Resolve : les deux fenêtres changent d'écran."""
        if self._double_ecran is None:
            return
        ecran_principal, ecran_second = self.screen(), self._double_ecran.screen()
        if ecran_principal is ecran_second:
            return
        for fenetre, ecran in ((self, ecran_second), (self._double_ecran, ecran_principal)):
            fenetre.showNormal()
            fenetre.setGeometry(ecran.availableGeometry())
            fenetre.showMaximized()

    def basculer_programme_externe(self):
        if self._programme_externe is not None:
            self._programme_externe.close()
            return
        fenetre = QWidget(None, Qt.Window | Qt.FramelessWindowHint)
        fenetre.setWindowTitle("Remanence · Programme")
        lay = QVBoxLayout(fenetre)
        lay.setContentsMargins(0, 0, 0, 0)
        zone = ZoneImage(fenetre)
        lay.addWidget(zone)
        relais = self.lecture.image_prete.connect(lambda image, f: zone.montrer(image))

        def fermer(e):
            self.lecture.image_prete.disconnect(relais)
            self._programme_externe = None
            e.accept()

        def touche(e):
            if e.key() in (Qt.Key_Escape, Qt.Key_F) or e.matches(QKeySequence.Cancel):
                fenetre.close()
            else:
                self.keyPressEvent(e)
        fenetre.closeEvent = fermer
        fenetre.keyPressEvent = touche
        ecran = self._autre_ecran() or self.screen()
        fenetre.setGeometry(ecran.geometry())
        fenetre.showFullScreen()
        self._programme_externe = fenetre
        self.lecture.rafraichir()

    def _plein_ecran(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _connecter(self):
        self.medias.importer.connect(self.importer)
        self.medias.fichiers_deposes.connect(self.importer_chemins)
        self.medias.media_selectionne.connect(self._media_choisi)
        self.medias.modifie.connect(self.valider)
        self.medias.retirer.connect(self.retirer_medias)
        self.medias.media_active.connect(
            lambda mid: self.charger_source(self.projet.medias[mid]) if mid in self.projet.medias
            else None)
        vue = self.timeline.vue
        vue.modifie.connect(self.valider)
        vue.tete_changee.connect(self.aller_a)
        vue.selection_changee.connect(self._selection)
        vue.media_depose.connect(self.poser_medias)
        self.inspecteur.reglage.connect(self._reglage_clip)
        self.inspecteur.reglage_effet.connect(self.reglage_effet)
        self.inspecteur.ajout_effet.connect(self.ajouter_effet)
        self.inspecteur.enregistrer_prereglage.connect(self.enregistrer_prereglage)
        self.bibliotheque.appliquer.connect(self.appliquer_prereglage)
        self.bibliotheque.personnels_changes.connect(self._remplir_menus_effets)
        vue.prereglage_depose.connect(self._prereglage_depose)
        self.inspecteur.timecode_demande.connect(self.regler_timecode_debut)
        self.liste_historique.aller.connect(self._aller_historique)
        self.formulaire_export.lancer.connect(self._lancer_export)
        for nom, moteur, moniteur in (("programme", self.lecture, self.visionneuse),
                                      ("source", self.lecture_source, self.source)):
            moteur.image_prete.connect(lambda image, f, m=moniteur: m.zone.montrer(image))
            moteur.lecture_changee.connect(moniteur.etat_lecture)
            moteur.erreur.connect(lambda m, d: self.message(f"Image impossible à calculer : {m}",
                                                            8000))
            moniteur.active.connect(lambda nom=nom: self.activer_moniteur(nom))
            moniteur.demande_lecture.connect(lambda nom=nom: self.lire_pause(nom))
            moniteur.demande_vitesse.connect(lambda sens, nom=nom: self._jkl(sens, nom))
            moniteur.demande_position.connect(lambda f, nom=nom: self.aller(nom, f))
            moniteur.demande_entree.connect(lambda nom=nom: self.point_entree(nom))
            moniteur.demande_sortie.connect(lambda nom=nom: self.point_sortie(nom))
            moniteur.demande_aller_entree.connect(lambda nom=nom: self._aller_point(nom, 0))
            moniteur.demande_aller_sortie.connect(lambda nom=nom: self._aller_point(nom, 1))
            moniteur.b_boucle.toggled.connect(lambda v, nom=nom: self._boucle(v, nom))
            moniteur.demande_qualite.connect(lambda cle, m=moteur: m.definir_qualite(cle))
        self.lecture.position_changee.connect(self._position)
        self.lecture_source.position_changee.connect(self._position_source)
        self.source.zone.glisser_depart.connect(self._glisser_source)
        self.timeline.vue.installEventFilter(self)

    def eventFilter(self, objet, e):
        # Travailler dans la timeline rend le programme actif, comme un clic dans son moniteur.
        if objet is self.timeline.vue and e.type() == QEvent.MouseButtonPress:
            self.activer_moniteur("programme")
        return False

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
        self._entete_visionneuse.precision.setText(seq.nom)
        self.duree_programme.setText(images_vers_tc(seq.duree(), seq.fraction_cadence))
        self._boucle(self.visionneuse.b_boucle.isChecked(), "programme")
        if self.media_source is not None:
            self.media_source = self.projet.medias.get(self.media_source.id)
            self._position_source(self.lecture_source.position)
        self.liste_historique.afficher(self.historique.libelles(), self.historique.position)
        if self._espace == "export":
            self.formulaire_export.actualiser(self.projet, self.chemin)
        self.a_annuler.setEnabled(self.historique.peut_annuler())
        self.a_retablir.setEnabled(self.historique.peut_retablir())
        self.a_annuler.setText(f"Annuler {self.historique.libelle_annuler().lower()}".strip())
        self.a_retablir.setText(f"Rétablir {self.historique.libelle_retablir().lower()}".strip())
        if not seq.duree():
            self.visionneuse.zone.montrer_message(
                "Séquence vide")

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

    def valider(self, libelle: str, fusionner: bool = False):
        """À appeler après toute modification du projet : historique, affichage, aperçu."""
        if self.historique.valider(self.projet, libelle, fusionner):
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
        self.visionneuse.afficher_position(f, seq.duree(), seq.tc_debut, seq.fraction_cadence,
                                           seq.tc_drop, seq.point_entree, seq.point_sortie)
        self.timeline.timecode.afficher(f, seq.tc_debut, seq.fraction_cadence, seq.tc_drop)
        self.timeline.suivre_tete(f)
        self.inspecteur.actualiser_temps(f)

    def _position_source(self, f: int):
        m = self.media_source
        if m is None:
            return
        v = m.infos.video
        cadence = v.fraction_cadence if v else self.projet.sequence.fraction_cadence
        self.source.afficher_position(f, m.nb_images(cadence), (v.tc_debut or 0) if v else 0,
                                      cadence, v.tc_drop if v else False, m.point_entree,
                                      m.point_sortie)

    def _cadence(self) -> int:
        return max(1, round(float(self.projet.sequence.fraction_cadence)))

    def _selection(self, ids: set):
        if ids:
            self._piste_choisie = None
        if len(ids) == 1:
            clip_id = next(iter(ids))
            self.inspecteur.clip(self.projet, clip_id)
            _, c = self.projet.sequence.trouver(clip_id)
            media = self.projet.medias.get(c.media_id) if c else None
            if media:
                self.metadonnees.afficher(media)
            self.bibliotheque.marquer_actifs(c.effets if c else [])
            if self.onglets_droite.currentIndex() == 1 and self._espace == "montage":
                self.onglets_droite.choisir(0)
        elif not ids and self._piste_choisie is not None:
            self.inspecteur.piste(self.projet, self._piste_choisie)
        else:
            self.inspecteur.vide(self.projet, len(ids))

    def appliquer_prereglage(self, p, cible: str):
        """Depuis la bibliothèque : cible « selection », « clip_effet » ou « sequence »."""
        seq = self.projet.sequence
        if cible == "clip_effet":
            self.ajouter_clip_effet(p.nouveaux_effets())
            return
        if cible == "sequence":
            self.ajouter_effet("sequence", "", p.nouveaux_effets())
            return
        clips = [c for _, c in seq.tous_les_clips() if c.id in self.timeline.vue.selection
                 and seq.trouver(c.id)[0].type == "video"]
        if not clips and self._piste_choisie is not None:
            self.ajouter_effet("piste", self._piste_choisie, p.nouveaux_effets())
            return
        if not clips:
            self.message("Aucun clip vidéo sélectionné")
            return

        def poser():
            for c in clips:
                for e in p.nouveaux_effets():
                    edition.ajouter_effet(c, e)
        self._tenter(f"Préréglage {p.nom}", poser)

    def _prereglage_depose(self, p, genre: str, cible_id: str, f: int):
        """Préréglage glissé sur la timeline : sur un clip, sur un en-tête de piste, ou dans le
        vide d'une piste vidéo (clip d'effet à cet endroit)."""
        if genre == "vide":
            seq = self.projet.sequence
            clip = edition.ajouter_clip_effet(seq, f, 5 * self._cadence(), p.nouveaux_effets(),
                                              piste_id=cible_id)
            self.valider("Clip d'effet")
            self.timeline.vue._choisir({clip.id})
        else:
            self.ajouter_effet(genre, cible_id, p.nouveaux_effets())
            # Le clip touché passe dans l'inspecteur, avec l'effet qu'il vient de recevoir.
            self.timeline.vue._choisir({cible_id})

    def enregistrer_prereglage(self, effets: list):
        if not effets:
            return
        defaut = EFFETS[effets[0].type].nom if len(effets) == 1 else "Pile d'effets"
        nom, ok = QInputDialog.getText(self, "Enregistrer comme préréglage", "Nom :", text=defaut)
        if not ok or not nom.strip():
            return
        prereglages.enregistrer(nom.strip(), effets)
        self.bibliotheque.recharger()
        self._remplir_menus_effets()
        self.message(f"Préréglage « {nom.strip()} » enregistré", 3000)

    def choisir_piste(self, piste_id: str):
        self.timeline.vue._choisir(set())
        self._piste_choisie = piste_id
        self.inspecteur.piste(self.projet, piste_id)
        self.onglets_droite.choisir(0)

    # Effets

    def _remplir_menus_effets(self):
        """Menus du menu Montage, à refaire quand un préréglage personnel change."""
        self._menu_clip_effet.clear()
        self._menu_effet_sequence.clear()
        remplir_menu_effets(self._menu_clip_effet, self.ajouter_clip_effet)
        remplir_menu_effets(self._menu_effet_sequence,
                            lambda effets: self.ajouter_effet("sequence", "", effets))

    def ajouter_effet(self, genre: str, porteur_id: str, effets: list):
        """genre : "clip", "piste" ou "sequence" ; effets : effets neufs, posés dans l'ordre."""
        seq = self.projet.sequence
        if genre == "sequence":
            porteur = seq
        elif genre == "piste":
            porteur = next((p for p in seq.pistes if p.id == porteur_id), None)
        else:
            porteur = seq.trouver(porteur_id)[1]
        if porteur is None or not effets:
            return

        def poser():
            for e in effets:
                edition.ajouter_effet(porteur, e)
        self._tenter(f"Effet {', '.join(EFFETS[e.type].nom for e in effets)}", poser)

    def ajouter_clip_effet(self, effets: list, debut: int | None = None):
        """Clip d'effet de 5 secondes, à la tête de lecture ou à l'image donnée."""
        seq = self.projet.sequence
        debut = self.lecture.position if debut is None else debut
        clip = edition.ajouter_clip_effet(seq, debut, 5 * self._cadence(), effets)
        self.valider("Clip d'effet")
        self.timeline.vue._choisir({clip.id})

    def reglage_effet(self, effet_id: str, champ: str, valeur):
        porteur, e = edition.trouver_effet(self.projet.sequence, effet_id)
        if e is None:
            return
        nom = EFFETS[e.type].nom if e.type in EFFETS else e.type
        if champ == "retirer":
            porteur.effets.remove(e)
            libelle = f"Effet {nom} retiré"
        elif champ == "reinitialiser":
            e.params = EFFETS[e.type].valeurs()
            e.cles, e.opacite, e.fusion = {}, 1.0, "normal"
            libelle = f"Effet {nom} réinitialisé"
        elif champ in ("actif", "graine", "fusion"):
            if getattr(e, champ) == valeur:
                return
            setattr(e, champ, valeur)
            libelle = f"Effet {nom}"
        else:
            # Temps des images clés : depuis le début du clip, ou de la séquence.
            t = self.lecture.position
            if isinstance(porteur, Clip):
                t = max(0, min(t - porteur.debut, porteur.duree - 1))
            if champ.startswith("cle:"):
                cle = champ[4:]
                if cle in e.cles and any(k[0] == t for k in e.cles[cle]):
                    retirer_cle(e, cle, t)
                    libelle = f"Image clé retirée ({nom})"
                else:
                    poser_cle(e, cle, t, valeur_a(e, cle, t))
                    libelle = f"Image clé ({nom})"
            elif champ.startswith("interp:"):
                cle = champ[7:]
                if valeur == "supprimer":
                    fixe = valeur_a(e, cle, t)
                    e.cles.pop(cle, None)
                    if cle == "opacite":
                        e.opacite = fixe
                    else:
                        e.params[cle] = fixe
                    libelle = f"Animation retirée ({nom})"
                else:
                    for k in e.cles.get(cle, []):
                        k[2] = valeur
                    libelle = f"Interpolation ({nom})"
            elif champ in e.cles:
                # Réglage animé : l'image clé à la tête de lecture prend la valeur.
                poser_cle(e, champ, t, valeur)
                libelle = f"Image clé ({nom})"
            elif champ == "opacite":
                if e.opacite == valeur:
                    return
                e.opacite = valeur
                libelle = f"Effet {nom}"
            else:
                if e.params.get(champ) == valeur:
                    return
                e.params[champ] = valeur
                libelle = f"Effet {nom}"
        # Différé : l'inspecteur est reconstruit, le réglage qui a parlé ne doit pas disparaître
        # pendant son propre signal.
        QTimer.singleShot(0, lambda: self.valider(libelle))

    def _media_choisi(self, media):
        if media is not None:
            self.metadonnees.afficher(media)
            self._montrer_metadonnees()
            self.charger_source(media)

    def charger_source(self, media: Media):
        """Affiche le média dans le moniteur source, avec ses points d'entrée et de sortie."""
        if self.media_source is not None and self.media_source.id == media.id:
            return
        mini = Projet.nouveau()
        mini.medias[media.id] = media
        try:
            edition.ajouter_media(mini, mini.sequence, media, 0)
        except edition.EditionImpossible as e:
            self.message(str(e))
            return
        self.media_source = media
        self.lecture_source.pause()
        self.lecture_source.definir_projet(mini)
        self.lecture_source.aller_a(media.point_entree or 0)
        self._entete_source.precision.setText(media.nom)
        v = media.infos.video
        cadence = v.fraction_cadence if v else self.projet.sequence.fraction_cadence
        self.duree_source.setText(images_vers_tc(media.nb_images(cadence), cadence))
        self.source.zone.taille_reference = (v.largeur, v.hauteur) if v else None
        if not v:
            self.source.zone.montrer_message("Média audio")
        self._position_source(self.lecture_source.position)
        self.activer_moniteur("source")

    # Lecture : chaque commande s'adresse au moniteur actif (source ou programme).

    def activer_moniteur(self, nom: str):
        if nom == "source" and self.media_source is None:
            return
        self._actif = nom
        peindre_cadre_actif(self._entete_source, nom == "source")
        peindre_cadre_actif(self._entete_visionneuse, nom == "programme")
        if self._un_seul and self._espace == "montage":
            self._docks["source"].setVisible(nom == "source")
            self._docks["visionneuse"].setVisible(nom == "programme")

    def basculer_moniteur(self):
        self.activer_moniteur("source" if self._actif == "programme" else "programme")

    def _moteur(self, nom: str | None = None) -> MoteurLecture:
        return self.lecture_source if (nom or self._actif) == "source" else self.lecture

    def _duree(self, nom: str) -> int:
        if nom == "source":
            m = self.media_source
            return m.nb_images(self.projet.sequence.fraction_cadence) if m else 0
        return self.projet.sequence.duree()

    def _points(self, nom: str) -> tuple[int | None, int | None]:
        if nom == "source":
            m = self.media_source
            return (m.point_entree, m.point_sortie) if m else (None, None)
        return self.projet.sequence.point_entree, self.projet.sequence.point_sortie

    def aller(self, nom: str, f: int):
        moteur = self._moteur(nom)
        if moteur.en_lecture:
            moteur.pause()
        moteur.aller_a(max(0, min(f, max(0, self._duree(nom) - 1))))

    def aller_a(self, f: int):
        """Place la tête du programme (timeline)."""
        moteur = self.lecture
        if moteur.en_lecture:
            moteur.pause()
        moteur.aller_a(max(0, f))

    def _pas(self, n: int):
        self.aller(self._actif, self._moteur().position + n)

    def _aller_bord(self, fin: bool):
        self.aller(self._actif, self._duree(self._actif) - 1 if fin else 0)

    def _aller_vers(self, positions: list[int], sens: int):
        """Tête du programme à la position suivante (sens 1) ou précédente (sens -1)."""
        f = self.lecture.position
        candidats = [x for x in positions if (x > f if sens > 0 else x < f)]
        if candidats:
            self.activer_moniteur("programme")
            self.aller_a(min(candidats) if sens > 0 else max(candidats))

    def _aller_coupe(self, sens: int):
        self._aller_vers(edition.coupes(self.projet.sequence), sens)

    def _aller_marqueur(self, sens: int):
        self._aller_vers([m.position for m in self.projet.sequence.marqueurs], sens)

    def _aller_point(self, nom: str, i: int):
        point = self._points(nom)[i]
        if point is not None:
            self.aller(nom, point if i == 0 else point - 1)

    def _espace_clavier(self):
        # Espace active le bouton qui a le focus clavier, comme partout ailleurs sous Windows.
        focus = QApplication.focusWidget()
        if isinstance(focus, QAbstractButton) and focus not in (self.visionneuse.b_lire,
                                                                self.source.b_lire):
            focus.click()
        else:
            self.lire_pause()

    def lire_pause(self, nom: str | None = None):
        nom = nom or self._actif
        moteur = self._moteur(nom)
        if moteur.en_lecture:
            moteur.pause()
            return
        # Un seul moniteur joue à la fois, comme dans les logiciels de montage.
        self._moteur("programme" if nom == "source" else "source").pause()
        if moteur.position >= self._duree(nom) - 1:
            moteur.aller_a(0)
        moteur.lire(1.0)

    def _jkl(self, sens: int, nom: str | None = None):
        nom = nom or self._actif
        moteur = self._moteur(nom)
        self._moteur("programme" if nom == "source" else "source").pause()
        v = moteur.vitesse
        vitesse = max(-8.0, min(8.0, v * 2)) if v * sens > 0 else float(sens)
        moteur.lire(vitesse)
        self.message(f"Lecture {'avant' if vitesse > 0 else 'arrière'} ×{abs(vitesse):g}" +
                     ("" if vitesse == 1 else ", son coupé"), 2000)

    def _basculer_boucle(self):
        moniteur = self.source if self._actif == "source" else self.visionneuse
        moniteur.b_boucle.toggle()

    def _boucle(self, actif: bool, nom: str = "programme"):
        if nom == "programme":
            self.a_boucle.setChecked(actif)
        moteur = self._moteur(nom)
        if not actif:
            moteur.definir_boucle(None)
            return
        entree, sortie = self._points(nom)
        moteur.definir_boucle((entree or 0, sortie if sortie is not None else self._duree(nom)))

    def point_entree(self, nom: str | None = None):
        nom = nom or self._actif
        f = self._moteur(nom).position
        if nom == "source" and self.media_source is not None:
            self.media_source.point_entree = f
            if self.media_source.point_sortie is not None and self.media_source.point_sortie <= f:
                self.media_source.point_sortie = None
            self.valider("Point d'entrée de la source")
        elif nom == "programme":
            self.projet.sequence.point_entree = f
            self.valider("Point d'entrée")

    def point_sortie(self, nom: str | None = None):
        nom = nom or self._actif
        f = self._moteur(nom).position + 1
        if nom == "source" and self.media_source is not None:
            self.media_source.point_sortie = f
            if (self.media_source.point_entree or 0) >= f:
                self.media_source.point_entree = None
            self.valider("Point de sortie de la source")
        elif nom == "programme":
            self.projet.sequence.point_sortie = f
            self.valider("Point de sortie")

    def effacer_points(self):
        if self._actif == "source" and self.media_source is not None:
            self.media_source.point_entree = self.media_source.point_sortie = None
            self.valider("Points de la source effacés")
        else:
            self.projet.sequence.point_entree = self.projet.sequence.point_sortie = None
            self.valider("Points effacés")

    # Monter depuis la source

    def monter_source(self, inserer: bool):
        """F9 insère, F10 écrase : la partie choisie de la source va à la tête du programme."""
        m = self.media_source
        if m is None:
            self.message("Aucun média dans le moniteur source.")
            return
        seq = self.projet.sequence
        entree, sortie = m.plage_source(seq.fraction_cadence)
        f = self.lecture.position
        operation = edition.inserer_media if inserer else edition.ajouter_media
        clips = []
        vierge = not seq.reglee

        def faire():
            clips.extend(operation(self.projet, seq, m, f, None, entree, sortie - entree))
        self._tenter("Insertion depuis la source" if inserer else "Écrasement depuis la source",
                     faire)
        if clips:
            if vierge and seq.reglee:
                self._timecode_nouvelle_sequence("Insertion depuis la source" if inserer
                                                 else "Écrasement depuis la source")
            self.aller_a(max(c.fin for c in clips))
            self.activer_moniteur("programme")

    def _glisser_source(self):
        m = self.media_source
        if m is not None:
            entree, sortie = m.plage_source(self.projet.sequence.fraction_cadence)
            glisser_source(self.source.zone, m.id, entree, sortie)

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

    def retirer_medias(self, ids: list[str]):
        """Retire des médias du projet ; ceux qui servent encore sur la timeline restent."""
        utilises = [self.projet.medias[i] for i in ids
                    if i in self.projet.medias and self.projet.clips_du_media(i)]
        libres = [i for i in ids if i in self.projet.medias and
                  self.projet.medias[i] not in utilises]
        for i in libres:
            del self.projet.medias[i]
            if self.media_source is not None and self.media_source.id == i:
                self.media_source = None
                self.lecture_source.pause()
                self.source.zone.montrer_message("Aucun média")
                self._entete_source.precision.setText("")
                self.activer_moniteur("programme")
        if libres:
            self.valider("Retrait de médias")
        if utilises:
            noms = "\n".join(f"{m.nom} ({self.projet.clips_du_media(m.id)} clip(s))"
                             for m in utilises)
            QMessageBox.information(self, "Médias encore utilisés",
                                    "Médias utilisés sur la timeline, non retirés :\n\n" + noms)

    def supprimer(self):
        if self.medias.vue.hasFocus():
            self.retirer_medias(self.medias.medias_choisis())
            return
        sel = set(self.timeline.vue.selection)
        if sel:
            self.timeline.vue.selection = set()
            if self.timeline.vue.ripple:
                self._tenter("Suppression ripple",
                             lambda: edition.supprimer_ripple(self.projet.sequence, sel))
            else:
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
                f"Supprimer la piste et ses {len(piste.clips)} clip(s) ?",
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
            "verrouillee": "Verrou de piste", "niveau": "Niveau de piste",
            "nom": "Piste renommée", "hauteur": "Hauteur de piste"}[champ]))

    def piste_exclusive(self, piste_id: str, champ: str):
        """Ctrl+clic sur M ou S : la piste garde l'état, les autres pistes audio le perdent.
        Si elle était déjà la seule, tout est rétabli."""
        audio = [p for p in self.projet.sequence.pistes if p.type == "audio"]
        cible = next(p for p in audio if p.id == piste_id)
        seule = getattr(cible, champ) and not any(getattr(p, champ) for p in audio
                                                  if p is not cible)
        for p in audio:
            setattr(p, champ, False if seule else p is cible)
        QTimer.singleShot(0, lambda: self.valider("Solo de piste" if champ == "solo"
                                                  else "Piste muette"))

    def deplacer_piste(self, piste_id: str, sens: int):
        edition.deplacer_piste(self.projet.sequence, piste_id, sens)
        self.valider("Ordre des pistes")

    def _reglage_clip(self, clip_id: str, champ: str, valeur):
        _, c = self.projet.sequence.trouver(clip_id)
        if champ == "reinitialiser":
            if c is not None:
                c.gain, c.fondu_entree, c.fondu_sortie = 1.0, 0, 0
                QTimer.singleShot(0, lambda: self.valider("Réinitialisation du clip"))
            return
        if c is None or getattr(c, champ) == valeur:
            return
        if champ in ("fondu_entree", "fondu_sortie"):
            edition.regler_fondu(self.projet.sequence, clip_id,
                                 "entree" if champ == "fondu_entree" else "sortie", valeur)
        else:
            setattr(c, champ, valeur)
        QTimer.singleShot(0, lambda: self.valider({
            "gain": "Niveau", "fondu_entree": "Fondu d'entrée", "fondu_sortie": "Fondu de sortie",
            "enveloppe": "Enveloppe", "fusion": "Mode de fusion"}[champ]))

    def poser_medias(self, ids: list[str], f: int, piste_id: str):
        seq = self.projet.sequence
        vierge = not seq.reglee
        piste = next((p for p in seq.pistes if p.id == piste_id), None)
        position = f
        try:
            for element in ids:
                mid, _, plage = element.partition("@")
                media = self.projet.medias.get(mid)
                if media is None:
                    continue
                entree, duree = 0, None
                if plage:
                    a, b = (int(x) for x in plage.split(":"))
                    entree, duree = a, b - a
                clips = edition.ajouter_media(self.projet, seq, media, position, piste, entree,
                                              duree)
                if clips:
                    position = max(c.fin for c in clips)
        except edition.EditionImpossible as e:
            self.message(str(e))
        self.valider("Ajout à la timeline")
        if vierge and seq.reglee:
            self._timecode_nouvelle_sequence("Ajout à la timeline")
        if len(ids) == 1 and seq.duree() and self.timeline.vue.px_par_image == 6.0:
            self.timeline.tout_voir()

    # Timecode de début de la séquence

    def _timecode_premier_clip(self) -> int | None:
        """Timecode de la séquence qui fait correspondre le premier clip à sa source."""
        seq = self.projet.sequence
        clips = sorted((c for p in seq.pistes_video for c in p.clips), key=lambda c: c.debut)
        for c in clips:
            m = self.projet.medias.get(c.media_id)
            if m and m.infos.video:
                if m.infos.video.tc_debut is None:
                    return None
                return max(0, m.infos.video.tc_debut + c.entree - c.debut)
        return None

    def _timecode_nouvelle_sequence(self, libelle: str):
        """Premier média posé : propose le timecode de début (ou applique le choix retenu).
        Différé : la boîte ne doit pas s'ouvrir pendant le glisser-déposer qui a posé le clip."""
        def proposer():
            seq = self.projet.sequence
            choix = preference()
            tc_clip = self._timecode_premier_clip()
            if choix == "heure":
                seq.tc_debut = timecode_une_heure(seq)
            elif choix == "clip":
                if tc_clip is not None:
                    seq.tc_debut = tc_clip
            else:
                d = DialogueTimecode(seq, tc_clip, True, self)
                if d.exec() != QDialog.Accepted:
                    return
                seq.tc_debut = d.valeur()
            # Même libellé : le timecode fait partie de la pose du premier clip (un seul Ctrl+Z).
            self.valider(libelle, fusionner=True)
        QTimer.singleShot(0, proposer)

    def regler_timecode_debut(self):
        seq = self.projet.sequence
        d = DialogueTimecode(seq, self._timecode_premier_clip(), False, self)
        if d.exec() == QDialog.Accepted and d.valeur() != seq.tc_debut:
            seq.tc_debut = d.valeur()
            self.valider("Timecode de début")

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
                    "Cadence :",
                    ["24000/1001", "24", "25", "30000/1001", "30", "50", "60"], 1, False)
                if not ok:
                    continue
                self._analyser(str(f), cadence)
            elif f.suffix.lower() in EXTENSIONS_IMAGES and len(fichiers) > 1:
                continue
            elif str(f.resolve()) not in deja:
                self._analyser(str(f), None)

    def _analyser(self, chemin: str, cadence: str | None):
        chutier = self.medias.chutier_courant
        self._analyses += 1
        self.medias.signaler_analyses(self._analyses)

        def travail(progression, annule):
            infos, _ = analyser(chemin, cadence)
            if infos.video and infos.video.cadence_variable:
                cible = intermediaire.creer_intermediaire(infos, progression, annule)
                infos_cfr, _ = analyser(str(cible))
                infos_cfr.avertissements = [
                    f"Intermédiaire à cadence fixe ({infos_cfr.video.cadence} i/s)."]
                infos_cfr.nom = infos.nom
                return infos_cfr
            return infos

        def fin_analyse():
            self._analyses -= 1
            self.medias.signaler_analyses(self._analyses)

        def reussi(infos):
            fin_analyse()
            m = Media(nouvel_id(), infos.chemin, infos)
            if any(c.id == chutier for c in self.projet.chutiers):
                m.chutier = chutier
            self.projet.medias[m.id] = m
            self.valider("Import de médias", fusionner=True)
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
            self.medias.definir_vignettes(media_id, qimages)

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
            "Enregistrer les modifications ?",
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
                "Ouvrir la sauvegarde automatique ?",
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
                                "Médias introuvables, clips hors ligne :\n\n" + "\n".join(absents))
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
                            f"Écriture impossible dans « {self.chemin} » : {e}")
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
        reglages = reglages_interface()
        reglages.setValue(self._cle_disposition(self._espace), self.saveState(VERSION_DISPOSITION))
        reglages.setValue("espace_actif", self._espace)
        reglages.setValue("double_ecran/mode", self._mode_double or "")
        if self._double_ecran is not None:
            self.choisir_double_ecran(None)
        if self._programme_externe is not None:
            self._programme_externe.close()
        self.taches.tout_annuler()
        self.bibliotheque.fermer()
        self.lecture.fermer()
        self.lecture_source.fermer()
        self.taches.attendre(3000)
        e.accept()
