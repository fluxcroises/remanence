"""Fenêtre principale : panneaux ancrables, menus, raccourcis et cycle de vie du projet."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QImage, QKeySequence, QPixmap
from PySide6.QtWidgets import (QAbstractButton, QApplication, QButtonGroup, QFileDialog,
                               QHBoxLayout, QInputDialog, QLabel, QMainWindow, QMenuBar,
                               QMessageBox, QPushButton, QToolBar, QWidget)

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
from remanence.ui.composants import Vumetres, bouton_icone, etiquette, panneau, rafraichir_icones
from remanence.ui.dialogue_export import DialogueExport, DialogueRapport
from remanence.ui.erreurs import afficher_erreur
from remanence.ui.inspecteur import Inspecteur
from remanence.ui.lecture import MoteurLecture
from remanence.ui.medias import PanneauMedias
from remanence.ui.taches import GestionnaireTaches, Tache
from remanence.ui.timeline import Timeline
from remanence.ui.visionneuse import LIBELLES_QUALITE, Visionneuse

INTERVALLE_AUTO_MS = 2 * 60 * 1000
EXTENSIONS_MEDIAS = ("*.mov *.mp4 *.mxf *.mkv *.avi *.webm *.mts *.m2ts *.m4v *.mpg *.mpeg "
                     "*.wav *.aif *.aiff *.mp3 *.flac *.m4a *.dpx *.exr *.tif *.tiff *.png "
                     "*.jpg *.jpeg *.braw *.r3d *.ari")
HAUTEUR_VIGNETTE = 48


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


class BarreHaut(QWidget):
    """Logo, menus, nom du projet, panneaux à afficher, et le bouton principal Exporter."""

    def __init__(self, fenetre: "FenetrePrincipale"):
        super().__init__()
        self.setProperty("role", "barre-haut")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(charte.actuelle().px("toolbar-h"))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(12)
        self.symbole = QLabel()
        self.symbole.setAccessibleName("Remanence")
        self.nom = etiquette("Remanence")
        self.nom.setStyleSheet("font-weight: 600;")
        self.menus = QMenuBar()
        self.menus.setNativeMenuBar(False)
        self.titre = etiquette("")
        self.titre.setStyleSheet("font-weight: 600;")
        self.etat = etiquette("", "secondaire")
        lay.addWidget(self.symbole)
        lay.addWidget(self.nom)
        lay.addWidget(self.menus)
        lay.addStretch(1)
        lay.addWidget(self.titre)
        lay.addWidget(self.etat)
        lay.addStretch(1)
        self.boutons_panneaux = QHBoxLayout()
        self.boutons_panneaux.setSpacing(4)
        lay.addLayout(self.boutons_panneaux)
        self.exporter = QPushButton("Exporter")
        self.exporter.setProperty("variante", "principal")
        self.exporter.setToolTip("Exporter la séquence (Ctrl+E)")
        self.exporter.clicked.connect(fenetre.exporter)
        lay.addWidget(self.exporter)
        self.appliquer_charte()

    def appliquer_charte(self):
        self.symbole.setPixmap(charte.actuelle().symbole(18))


class BarreBas(QWidget):
    """État technique à gauche, espaces de travail au centre, sauvegarde et tâches à droite."""

    def __init__(self, fenetre: "FenetrePrincipale"):
        super().__init__()
        self.setProperty("role", "barre-bas")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(charte.actuelle().px("toolbar-h"))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 12, 0)
        self.etat = etiquette("", "etat")
        self.message = etiquette("", "secondaire")
        self.message.hide()
        gauche = QHBoxLayout()
        gauche.addWidget(self.etat)
        gauche.addWidget(self.message)
        gauche.addStretch(1)
        lay.addLayout(gauche, 1)
        self.espaces = QButtonGroup(self)
        centre = QHBoxLayout()
        centre.setSpacing(4)
        for cle, nom, aide in (("medias", "Médias", "Espace de travail pour trier et examiner "
                                                   "les médias"),
                               ("montage", "Montage", "Espace de travail pour monter la séquence")):
            b = QPushButton(nom)
            b.setProperty("variante", "onglet")
            b.setCheckable(True)
            b.setToolTip(aide)
            b.setProperty("espace", cle)
            self.espaces.addButton(b)
            centre.addWidget(b)
        self.espaces.buttons()[1].setChecked(True)
        lay.addLayout(centre)
        droite = QHBoxLayout()
        droite.addStretch(1)
        droite.addWidget(fenetre.taches)
        self.sauvegarde = etiquette("Jamais enregistré", "secondaire")
        droite.addWidget(self.sauvegarde)
        lay.addLayout(droite, 1)
        self._minuterie = QTimer(self)
        self._minuterie.timeout.connect(lambda: (self.message.hide(), self.etat.show()))
        self._minuterie.setSingleShot(True)

    def afficher_message(self, texte: str, duree_ms: int = 5000):
        self.message.setText(texte)
        self.etat.hide()
        self.message.show()
        self._minuterie.start(duree_ms)


class FenetrePrincipale(QMainWindow):
    def __init__(self):
        super().__init__()
        self.projet = Projet.nouveau()
        self.historique = Historique(self.projet)
        self.chemin: Path | None = None
        self.modifie = False
        self._analyses = 0
        self._derniere_sauvegarde: float | None = None
        self._espace = "montage"
        self.setWindowIcon(charte.actuelle().icone_application())

        self.lecture = MoteurLecture()
        self.taches = GestionnaireTaches()
        self.medias = PanneauMedias()
        self.visionneuse = Visionneuse()
        self.inspecteur = Inspecteur()
        self.timeline = Timeline(self)
        self.vumetres = Vumetres(self.lecture.cretes)

        self.setDockNestingEnabled(True)
        self.setCentralWidget(QWidget())
        self.centralWidget().hide()
        self._docks = {}
        self._entetes = {}
        for nom, titre, widget in [("medias", "Médias", self.medias),
                                   ("visionneuse", "Programme", self.visionneuse),
                                   ("inspecteur", "Inspecteur", self.inspecteur),
                                   ("mixage", "Mixage", self.vumetres),
                                   ("timeline", "Timeline", self.timeline)]:
            d, entete = panneau(titre, widget, nom, self, titre_visible=nom != "mixage")
            self._docks[nom] = d
            self._entetes[nom] = entete
        self._entetes["visionneuse"].ajouter(self.visionneuse.qualite)
        self.inspecteur.setMinimumWidth(320)
        self.medias.setMinimumWidth(280)
        self.badge_inspecteur = etiquette("", "badge-accent")
        self.badge_inspecteur.hide()
        self._entetes["inspecteur"].ajouter(self.badge_inspecteur)
        self.inspecteur.badge.connect(self._badge)

        self.barre_haut = BarreHaut(self)
        self.setMenuWidget(self.barre_haut)
        self.barre_bas = BarreBas(self)
        bas = QToolBar("Barre d'état")
        bas.setObjectName("barre_bas")
        bas.setMovable(False)
        bas.setFloatable(False)
        bas.toggleViewAction().setVisible(False)
        bas.addWidget(self.barre_bas)
        self.addToolBar(Qt.BottomToolBarArea, bas)
        self.barre_bas.espaces.buttonClicked.connect(
            lambda b: self.choisir_espace(b.property("espace")))

        self._disposition_par_defaut()
        self._etat_defaut = self.saveState()
        self._actions()
        for nom, icone, aide in (("medias", "app-window", "Afficher ou masquer le panneau Médias"),
                                 ("inspecteur", "sliders-horizontal",
                                  "Afficher ou masquer l'inspecteur"),
                                 ("mixage", "audio-lines", "Afficher ou masquer les vumètres")):
            b = bouton_icone(icone, aide, variante="panneau", texte=self._docks[nom].windowTitle(),
                             cochable=True)
            b.setChecked(True)
            b.toggled.connect(self._docks[nom].setVisible)
            self._docks[nom].visibilityChanged.connect(
                lambda v, b=b, d=self._docks[nom]: b.setChecked(not d.isHidden()))
            self.barre_haut.boutons_panneaux.addWidget(b)
        self._connecter()
        self._afficher_tout()
        self._restaurer_disposition()

        self._minuterie_auto = QTimer(self)
        self._minuterie_auto.timeout.connect(self._sauvegarde_auto)
        self._minuterie_auto.start(INTERVALLE_AUTO_MS)
        self._minuterie_etat = QTimer(self)
        self._minuterie_etat.timeout.connect(self._etat_sauvegarde)
        self._minuterie_etat.start(20000)
        QTimer.singleShot(0, self._etat_technique)
        self.resize(1600, 1000)

    # Disposition et espaces de travail

    def _disposition_par_defaut(self):
        d = self._docks
        for dock in d.values():
            dock.setFloating(False)
            dock.show()
        self.addDockWidget(Qt.LeftDockWidgetArea, d["medias"])
        self.addDockWidget(Qt.RightDockWidgetArea, d["inspecteur"])
        self.addDockWidget(Qt.BottomDockWidgetArea, d["timeline"])
        self.splitDockWidget(d["medias"], d["visionneuse"], Qt.Horizontal)
        self.splitDockWidget(d["visionneuse"], d["inspecteur"], Qt.Horizontal)
        self.splitDockWidget(d["inspecteur"], d["mixage"], Qt.Horizontal)
        self.resizeDocks([d["medias"], d["visionneuse"], d["inspecteur"], d["mixage"]],
                         [340, 820, 340, 56], Qt.Horizontal)
        self.resizeDocks([d["visionneuse"], d["timeline"]], [520, 400], Qt.Vertical)

    def _disposition_medias(self):
        self._disposition_par_defaut()
        d = self._docks
        self.resizeDocks([d["medias"], d["visionneuse"], d["inspecteur"], d["mixage"]],
                         [720, 560, 380, 56], Qt.Horizontal)
        self.resizeDocks([d["visionneuse"], d["timeline"]], [700, 220], Qt.Vertical)

    def choisir_espace(self, espace: str):
        if espace == self._espace:
            return
        reglages = QSettings("Remanence", "Remanence")
        reglages.setValue(f"espace/{self._espace}", self.saveState())
        self._espace = espace
        etat = reglages.value(f"espace/{espace}")
        if etat is not None:
            self.restoreState(etat)
        elif espace == "medias":
            self._disposition_medias()
        else:
            self._disposition_par_defaut()
        for b in self.barre_bas.espaces.buttons():
            b.setChecked(b.property("espace") == espace)

    def _restaurer_disposition(self):
        etat = QSettings("Remanence", "Remanence").value("disposition")
        if etat is not None:
            self.restoreState(etat)

    def retablir_disposition(self):
        reglages = QSettings("Remanence", "Remanence")
        reglages.remove("espace/medias")
        reglages.remove("espace/montage")
        if self._espace == "medias":
            self._disposition_medias()
        else:
            self._disposition_par_defaut()
            self.restoreState(self._etat_defaut)

    def changer_theme(self, theme: str):
        QSettings("Remanence", "Remanence").setValue("theme", theme)
        charte.definir(theme)
        QApplication.instance().setStyleSheet(charte.actuelle().feuille())
        rafraichir_icones()
        self.barre_haut.appliquer_charte()
        self.visionneuse.timecode.appliquer_charte()
        self.timeline.timecode.appliquer_charte()
        self.setWindowIcon(charte.actuelle().icone_application())
        self._afficher_tout()

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
        m = self.barre_haut.menus
        f = m.addMenu("&Fichier")
        self._action(f, "Nouveau projet", self.nouveau, "Ctrl+N")
        self._action(f, "Ouvrir un projet…", self.ouvrir, "Ctrl+O")
        self._action(f, "Enregistrer", self.enregistrer, "Ctrl+S",
                     "Enregistre le projet et en garde une version numérotée.")
        self._action(f, "Enregistrer sous…", self.enregistrer_sous, "Ctrl+Shift+S")
        f.addSeparator()
        self._action(f, "Importer des médias…", self.importer, "Ctrl+I")
        self._action(f, "Exporter la séquence…", self.exporter, "Ctrl+E")
        f.addSeparator()
        self._action(f, "Quitter", self.close, "Ctrl+Q")

        e = m.addMenu("É&dition")
        self.a_annuler = self._action(e, "Annuler", self.annuler, "Ctrl+Z")
        self.a_retablir = self._action(e, "Rétablir", self.retablir, ["Ctrl+Y", "Ctrl+Shift+Z"])
        e.addSeparator()
        self._action(e, "Outil de sélection", lambda: self.timeline.choisir_outil("selection"), "V")
        self._action(e, "Outil de coupe", lambda: self.timeline.choisir_outil("couper"), "C")

        c = m.addMenu("&Clip")
        self._action(c, "Couper à la tête de lecture", self.couper, ["S", "B"],
                     "Coupe les clips sélectionnés, ou tous ceux sous la tête si rien n'est "
                     "sélectionné.")
        self._action(c, "Supprimer les clips sélectionnés", self.supprimer, ["Del", "Backspace"])
        self._action(c, "Dissocier son et image", self.dissocier, "U")
        self._action(c, "Lier la sélection", self.lier, "Ctrl+L")

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
        self._action(lec, "Ajouter un marqueur", self.marqueur, "M")

        a = m.addMenu("&Affichage")
        themes = a.addMenu("Thème")
        groupe = QActionGroup(self)
        for cle, nom in charte.THEMES.items():
            act = self._action(themes, nom, lambda _=False, cle=cle: self.changer_theme(cle))
            act.setCheckable(True)
            act.setChecked(charte.actuelle().theme == cle)
            groupe.addAction(act)
        qualite = a.addMenu("Résolution de l'aperçu")
        for cle, nom in LIBELLES_QUALITE.items():
            self._action(qualite, nom, lambda _=False, cle=cle: self.visionneuse.choisir_qualite(cle))
        a.addSeparator()
        self._action(a, "Espace Médias", lambda: self.choisir_espace("medias"), "Alt+1")
        self._action(a, "Espace Montage", lambda: self.choisir_espace("montage"), "Alt+2")

        fe = m.addMenu("F&enêtre")
        for dock in self._docks.values():
            fe.addAction(dock.toggleViewAction())
        fe.addSeparator()
        self._action(fe, "Revenir à la disposition par défaut", self.retablir_disposition)

        ai = m.addMenu("&Aide")
        self._action(ai, "À propos de Remanence", lambda: APropos(self).exec())

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
        self.lecture.image_prete.connect(lambda image, f: self.visionneuse.zone.montrer(image))
        self.lecture.position_changee.connect(self._position)
        self.lecture.lecture_changee.connect(self.visionneuse.etat_lecture)
        self.lecture.erreur.connect(lambda m, d: self.message(f"Image impossible à calculer : {m}",
                                                              8000))
        v = self.visionneuse
        v.demande_lecture.connect(self.lire_pause)
        v.demande_position.connect(self.aller_a)
        v.demande_qualite.connect(self._qualite)
        v.b_debut.clicked.connect(lambda: self.aller_a(0))
        v.b_fin.clicked.connect(lambda: self.aller_a(max(0, self.projet.sequence.duree() - 1)))
        v.b_prec.clicked.connect(lambda: self._pas(-1))
        v.b_suiv.clicked.connect(lambda: self._pas(1))
        v.b_boucle.toggled.connect(self._boucle)

    # Affichage de l'état

    def message(self, texte: str, duree_ms: int = 5000):
        self.barre_bas.afficher_message(texte, duree_ms)

    def _afficher_tout(self):
        self.medias.afficher(self.projet)
        self.timeline.afficher(self.projet)
        self.lecture.definir_projet(self.projet)
        self._selection(self.timeline.vue.selection)
        self._titre()
        self._position(self.lecture.position)
        seq = self.projet.sequence
        self.visionneuse.afficher_points(seq)
        self._entetes["visionneuse"].precision.setText(seq.nom)
        self._boucle(self.visionneuse.b_boucle.isChecked())
        self.a_annuler.setEnabled(self.historique.peut_annuler())
        self.a_retablir.setEnabled(self.historique.peut_retablir())
        self.a_annuler.setText(f"Annuler {self.historique.libelle_annuler().lower()}".strip())
        self.a_retablir.setText(f"Rétablir {self.historique.libelle_retablir().lower()}".strip())
        if not seq.duree():
            self.visionneuse.zone.montrer_message(
                "Glissez un média sur la timeline pour le voir ici.")
        self._etat_technique()

    def _titre(self):
        nom = self.chemin.stem if self.chemin else "Projet sans titre"
        self.setWindowTitle(f"{nom}{' (modifié)' if self.modifie else ''} · Remanence")
        self.barre_haut.titre.setText(f"{nom} · {self.projet.sequence.nom}")
        self.barre_haut.etat.setText("Modifié" if self.modifie else "")
        self._etat_sauvegarde()

    def _etat_sauvegarde(self):
        if self._derniere_sauvegarde is None:
            texte = "Jamais enregistré"
        else:
            minutes = int((time.time() - self._derniere_sauvegarde) // 60)
            texte = ("Enregistré à l'instant" if minutes < 1
                     else f"Enregistré il y a {minutes} min")
        self.barre_bas.sauvegarde.setText(texte)

    def _etat_technique(self):
        seq = self.projet.sequence
        cad = f"{float(seq.fraction_cadence):.3f}".rstrip("0").rstrip(".").replace(".", ",")
        rendu = "OpenGL" if self.visionneuse.zone.rendu_gpu else "Rendu logiciel"
        qualite = LIBELLES_QUALITE[self.visionneuse._qualite]
        self.barre_bas.etat.setText(f"{rendu} · {qualite} · {cad} i/s · "
                                    f"{seq.largeur} × {seq.hauteur}")

    def _qualite(self, cle: str):
        self.lecture.definir_qualite(cle)
        self._etat_technique()

    def _badge(self, texte: str):
        self.badge_inspecteur.setText(texte)
        self.badge_inspecteur.setVisible(bool(texte))

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

    def _position(self, f: int):
        seq = self.projet.sequence
        for champ in (self.visionneuse.timecode, self.timeline.timecode):
            champ.afficher(f, seq.tc_debut, seq.fraction_cadence, seq.tc_drop)
        self.timeline.suivre_tete(f)

    def _cadence(self) -> int:
        return max(1, round(float(self.projet.sequence.fraction_cadence)))

    def _selection(self, ids: set):
        if len(ids) == 1:
            self.inspecteur.clip(self.projet, next(iter(ids)))
        elif ids:
            self.inspecteur.vide()
            self.message(f"{len(ids)} clips sélectionnés", 3000)
        else:
            self.inspecteur.vide()

    def _media_choisi(self, media):
        if media is not None:
            self.inspecteur.fiche_media(media)

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
        seq = self.projet.sequence
        if seq.duree() == 0:
            QMessageBox.information(self, "Rien à exporter",
                                    "La timeline est vide. Glissez un média sur la timeline avant "
                                    "d'exporter.")
            return
        d = DialogueExport(self.projet, self.chemin, self)
        if d.exec() != DialogueExport.Accepted:
            return
        r = d.reglages()
        copie = Projet.depuis_dict(self.projet.vers_dict())
        for m in copie.medias.values():
            m.hors_ligne = self.projet.medias[m.id].hors_ligne
        nom = r["chemin"].name

        def travail(progression, annule):
            return exporter(copie, copie.sequence, r["chemin"], r["cle_format"], r["debut"],
                            r["fin"], progression, annule)

        self.taches.lancer(
            Tache(f"Export de {nom}", travail),
            lambda rapport: DialogueRapport(rapport, self).exec(),
            lambda m, det: afficher_erreur(self, "Export impossible",
                                           f"L'export de « {nom} » a échoué : {m}", det),
            lambda: self.message(f"Export de {nom} annulé. Aucun fichier n'a été laissé à moitié "
                                 "écrit.", 6000))

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
        reglages.setValue("disposition", self.saveState())
        reglages.setValue(f"espace/{self._espace}", self.saveState())
        self.taches.tout_annuler()
        self.lecture.fermer()
        self.taches.attendre(3000)
        e.accept()
