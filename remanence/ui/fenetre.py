"""Fenêtre principale : panneaux ancrables, menus, raccourcis et cycle de vie du projet."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QImage, QKeySequence, QPixmap
from PySide6.QtWidgets import (QAbstractButton, QApplication, QFileDialog, QInputDialog,
                               QMainWindow, QMessageBox, QToolBar, QVBoxLayout, QWidget)

from remanence.config import reglages_interface
from remanence.media import intermediaire
from remanence.media.lecteur import LecteurVideo, generer_cache_audio
from remanence.media.proxy import chemin_audio, chemin_proxy, generer_proxy, proxy_utile
from remanence.media.sonde import EXTENSIONS_IMAGES, analyser, detecter_sequence_images
from remanence.projet import edition, serialisation
from remanence.projet.historique import Historique
from remanence.projet.modele import Marqueur, Media, Projet, nouvel_id
from remanence.rendu.couleur import vers_rvb16_apercu, vers_rvba
from remanence.media.timecode import images_vers_tc
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
from remanence.ui.visionneuse import (LIBELLES_QUALITE, Moniteur, ZoneImage, glisser_source,
                                      peindre_cadre_actif)

INTERVALLE_AUTO_MS = 2 * 60 * 1000
EXTENSIONS_MEDIAS = ("*.mov *.mp4 *.mxf *.mkv *.avi *.webm *.mts *.m2ts *.m4v *.mpg *.mpeg "
                     "*.wav *.aif *.aiff *.mp3 *.flac *.m4a *.dpx *.exr *.tif *.tiff *.png "
                     "*.jpg *.jpeg *.braw *.r3d *.ari")
HAUTEUR_VIGNETTE = 48
BORD = 5
# À augmenter quand les panneaux changent : les dispositions mémorisées avant sont ignorées.
VERSION_DISPOSITION = 3
# Panneaux visibles dans chaque espace de travail.
PANNEAUX_ESPACE = {
    "media": {"medias", "source", "droite"},
    "montage": {"medias", "source", "visionneuse", "droite", "mixage", "timeline"},
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
        self.visionneuse = Moniteur("programme")
        self.source = Moniteur("source")
        self.source.zone.glissable = True
        self.lecture_source = MoteurLecture()
        self.media_source: Media | None = None
        self._actif = "programme"
        self._un_seul = False
        self._double_ecran: QMainWindow | None = None
        self._programme_externe: QWidget | None = None
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
        elif espace == "media":
            self.addDockWidget(Qt.LeftDockWidgetArea, d["medias"])
            self.splitDockWidget(d["medias"], d["source"], Qt.Horizontal)
            self.splitDockWidget(d["source"], d["droite"], Qt.Horizontal)
            self.resizeDocks([d["medias"], d["source"], d["droite"]], [620, 660, 380],
                             Qt.Horizontal)
        else:
            self.addDockWidget(Qt.LeftDockWidgetArea, d["medias"])
            self.addDockWidget(Qt.BottomDockWidgetArea, d["timeline"])
            self.splitDockWidget(d["medias"], d["source"], Qt.Horizontal)
            self.splitDockWidget(d["source"], d["visionneuse"], Qt.Horizontal)
            self.splitDockWidget(d["visionneuse"], d["droite"], Qt.Horizontal)
            self.splitDockWidget(d["droite"], d["mixage"], Qt.Horizontal)
            self.resizeDocks([d["medias"], d["source"], d["visionneuse"], d["droite"],
                              d["mixage"]], [300, 470, 470, 320, 56], Qt.Horizontal)
            self.resizeDocks([d["visionneuse"], d["timeline"]], [500, 440], Qt.Vertical)
        for nom, dock in d.items():
            if not self._est_externe(nom):
                dock.setVisible(nom in visibles)

    def _appliquer_espace(self, espace: str, par_defaut: bool = False):
        reglages = reglages_interface()
        etat = None if par_defaut else reglages.value(f"disposition/{espace}")
        if etat is None or not self.restoreState(etat, VERSION_DISPOSITION):
            self._disposition(espace)
        # Une disposition mémorisée ne doit jamais faire apparaître un panneau d'un autre espace.
        for nom, dock in self._docks.items():
            if nom not in PANNEAUX_ESPACE[espace] and not self._est_externe(nom):
                dock.hide()
        if self._un_seul and espace == "montage":
            self.basculer_un_seul_moniteur()
        if espace == "media":
            self.onglets_droite.choisir(1)
        elif espace == "export":
            self.formulaire_export.actualiser(self.projet, self.chemin)
        self._espace = espace
        self.barre_espaces.activer(espace)

    def _est_externe(self, nom: str) -> bool:
        return self._double_ecran is not None and nom in ("timeline", "mixage")

    def choisir_espace(self, espace: str):
        """Change la disposition ; le projet, la sélection et la tête de lecture ne bougent pas."""
        if espace == self._espace:
            return
        reglages_interface().setValue(f"disposition/{self._espace}",
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
        self._action(mo, "Insérer depuis la source", lambda: self.monter_source(True), "F9",
                     "Pose la partie choisie de la source à la tête de lecture et pousse la suite.")
        self._action(mo, "Écraser depuis la source", lambda: self.monter_source(False), "F10",
                     "Pose la partie choisie de la source à la tête de lecture, par-dessus.")
        mo.addSeparator()
        self._action(mo, "Ajouter une piste vidéo", lambda: self.ajouter_piste("video"))
        self._action(mo, "Ajouter une piste audio", lambda: self.ajouter_piste("audio"))
        mo.addSeparator()
        self._action(mo, "Ajouter un marqueur", self.marqueur, "M")

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
        self._action(lec, "Aller au début", lambda: self._aller_bord(False), "Home")
        self._action(lec, "Aller à la fin", lambda: self._aller_bord(True), "End")
        lec.addSeparator()
        self._action(lec, "Basculer entre source et programme", self.basculer_moniteur, "Q",
                     "Les commandes de lecture s'adressent au moniteur actif, souligné en mauve.")
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
                                      "Ne montre que le moniteur actif, en grand ; Q bascule.")
        self.a_un_seul.setCheckable(True)
        self.a_programme_externe = self._action(
            a, "Programme en plein écran", self.basculer_programme_externe, "Ctrl+F",
            "Montre le programme en plein écran, sur le second écran s'il y en a un. Échap ferme.")
        self.a_double_ecran = self._action(a, "Double écran", self.basculer_double_ecran,
                                           aide="Envoie la timeline et les vumètres sur le "
                                                "second écran, comme dans DaVinci Resolve.")
        self.a_double_ecran.setCheckable(True)
        QGuiApplication.instance().screenAdded.connect(lambda _e: self._ecrans_changes())
        QGuiApplication.instance().screenRemoved.connect(lambda _e: self._ecrans_changes())
        self._ecrans_changes()

        fe = m.addMenu("F&enêtre")
        for nom, dock, titre in (("medias", self._docks["medias"], "Média"),
                                 ("source", self._docks["source"], "Source"),
                                 ("visionneuse", self._docks["visionneuse"], "Programme"),
                                 ("droite", self._docks["droite"], "Inspecteur"),
                                 ("mixage", self._docks["mixage"], "Vumètres"),
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
        self.a_double_ecran.setEnabled(deux or self._double_ecran is not None)
        self.a_double_ecran.setText("Double écran" if deux
                                    else "Double écran (aucun second écran détecté)")

    def basculer_double_ecran(self, actif: bool | None = None):
        """La timeline et les vumètres passent dans une fenêtre sur le second écran."""
        actif = self.a_double_ecran.isChecked() if actif is None else actif
        if actif and self._double_ecran is None:
            # Fenêtre sans parent : sinon restoreState() de la fenêtre principale retrouverait la
            # timeline parmi ses descendants et la rapatrierait au changement d'espace.
            fenetre = QMainWindow()
            fenetre.setWindowTitle("Remanence · Timeline")
            fenetre.setWindowIcon(self.windowIcon())
            fenetre.setCentralWidget(QWidget())
            fenetre.centralWidget().hide()
            for nom, zone in (("timeline", Qt.BottomDockWidgetArea),
                              ("mixage", Qt.RightDockWidgetArea)):
                dock = self._docks[nom]
                self.removeDockWidget(dock)
                fenetre.addDockWidget(zone, dock)
                dock.show()
            fenetre.closeEvent = lambda e: (e.accept(), self.basculer_double_ecran(False))
            ecran = self._autre_ecran()
            if ecran is not None:
                fenetre.setGeometry(ecran.availableGeometry())
                fenetre.showMaximized()
            else:
                fenetre.resize(1400, 500)
                fenetre.show()
            self._double_ecran = fenetre
        elif not actif and self._double_ecran is not None:
            fenetre, self._double_ecran = self._double_ecran, None
            for nom in ("timeline", "mixage"):
                dock = self._docks[nom]
                fenetre.removeDockWidget(dock)
                self.addDockWidget(Qt.BottomDockWidgetArea, dock)
            fenetre.closeEvent = lambda e: e.accept()
            fenetre.close()
            fenetre.deleteLater()
            self._appliquer_espace(self._espace, par_defaut=True)
        self.a_double_ecran.setChecked(self._double_ecran is not None)
        self._ecrans_changes()

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
        self.medias.media_active.connect(
            lambda mid: self.charger_source(self.projet.medias[mid]) if mid in self.projet.medias
            else None)
        vue = self.timeline.vue
        vue.modifie.connect(self.valider)
        vue.tete_changee.connect(self.aller_a)
        vue.selection_changee.connect(self._selection)
        vue.media_depose.connect(self.poser_medias)
        self.inspecteur.reglage.connect(self._reglage_clip)
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
        self.visionneuse.afficher_position(f, seq.duree(), seq.tc_debut, seq.fraction_cadence,
                                           seq.tc_drop, seq.point_entree, seq.point_sortie)
        self.timeline.timecode.afficher(f, seq.tc_debut, seq.fraction_cadence, seq.tc_drop)
        self.timeline.suivre_tete(f)

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
            self.source.zone.montrer_message("Média audio : pas d'image à afficher.")
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
            self.message("Choisissez d'abord un média : il s'affiche dans le moniteur source.")
            return
        seq = self.projet.sequence
        entree, sortie = m.plage_source(seq.fraction_cadence)
        f = self.lecture.position
        operation = edition.inserer_media if inserer else edition.ajouter_media
        clips = []

        def faire():
            clips.extend(operation(self.projet, seq, m, f, None, entree, sortie - entree))
        self._tenter("Insertion depuis la source" if inserer else "Écrasement depuis la source",
                     faire)
        if clips:
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
        reglages = reglages_interface()
        reglages.setValue(f"disposition/{self._espace}", self.saveState(VERSION_DISPOSITION))
        reglages.setValue("espace_actif", self._espace)
        if self._double_ecran is not None:
            self.basculer_double_ecran(False)
        if self._programme_externe is not None:
            self._programme_externe.close()
        self.taches.tout_annuler()
        self.lecture.fermer()
        self.lecture_source.fermer()
        self.taches.attendre(3000)
        e.accept()
