"""Fenêtre principale : panneaux ancrables, menus, raccourcis et cycle de vie du projet."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QImage, QKeySequence, QPixmap
from PySide6.QtWidgets import (QAbstractButton, QApplication, QDockWidget, QFileDialog,
                               QInputDialog, QLabel, QMainWindow, QMessageBox, QWidget)

from remanence.media import intermediaire
from remanence.media.lecteur import LecteurVideo, generer_cache_audio
from remanence.media.proxy import chemin_audio, chemin_proxy, generer_proxy, proxy_utile
from remanence.media.sonde import (EXTENSIONS_IMAGES, MediaIllisible, analyser,
                                   detecter_sequence_images)
from remanence.media.timecode import images_vers_tc
from remanence.projet import edition, serialisation
from remanence.projet.historique import Historique
from remanence.projet.modele import Marqueur, Media, Projet, nouvel_id
from remanence.rendu.couleur import vers_rvba
from remanence.rendu.export import exporter
from remanence.ui.dialogue_export import DialogueExport, DialogueRapport
from remanence.ui.erreurs import afficher_erreur
from remanence.ui.inspecteur import Inspecteur
from remanence.ui.lecture import MoteurLecture
from remanence.ui.medias import PanneauMedias
from remanence.ui.taches import GestionnaireTaches, Tache
from remanence.ui.timeline import Timeline
from remanence.ui.visionneuse import Visionneuse

INTERVALLE_AUTO_MS = 2 * 60 * 1000
EXTENSIONS_MEDIAS = ("*.mov *.mp4 *.mxf *.mkv *.avi *.webm *.mts *.m2ts *.m4v *.mpg *.mpeg "
                     "*.wav *.aif *.aiff *.mp3 *.flac *.m4a *.dpx *.exr *.tif *.tiff *.png "
                     "*.jpg *.jpeg *.braw *.r3d *.ari")


def _vignette(media: Media) -> np.ndarray:
    infos, index = analyser(media.chemin, media.infos.video.cadence
                            if media.infos.sequence_images else None)
    lecteur = LecteurVideo(media.chemin, index, infos.sequence_images, infos.video.cadence)
    try:
        image = lecteur.image(len(index) // 2)
        h = 54
        l = max(2, round(image.width * h / image.height))
        petite = image.reformat(width=l, height=h)
        rvb = vers_rvba(petite, infos.video.couleur)[..., :3]
        return np.ascontiguousarray((np.clip(rvb, 0, 1) * 255 + 0.5).astype(np.uint8))
    finally:
        lecteur.fermer()


class FenetrePrincipale(QMainWindow):
    def __init__(self):
        super().__init__()
        self.projet = Projet.nouveau()
        self.historique = Historique(self.projet)
        self.chemin: Path | None = None
        self.modifie = False
        self._analyses = 0
        self._derniere_auto = None

        self.lecture = MoteurLecture()
        self.taches = GestionnaireTaches()
        self.medias = PanneauMedias()
        self.visionneuse = Visionneuse()
        self.inspecteur = Inspecteur()
        self.timeline = Timeline(self)

        self.setDockNestingEnabled(True)
        self.setCentralWidget(QWidget())
        self.centralWidget().hide()
        self._docks = {}
        for nom, titre, widget in [("medias", "Médias", self.medias),
                                   ("visionneuse", "Visionneuse", self.visionneuse),
                                   ("inspecteur", "Inspecteur", self.inspecteur),
                                   ("timeline", "Timeline", self.timeline)]:
            d = QDockWidget(titre, self)
            d.setObjectName(nom)
            d.setWidget(widget)
            d.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable |
                          QDockWidget.DockWidgetClosable)
            self._docks[nom] = d
        self._disposition_par_defaut()
        self._etat_defaut = self.saveState()

        self.statusBar().addPermanentWidget(self.taches)
        self.message_etat = QLabel("")
        self.statusBar().addWidget(self.message_etat, 1)

        self._actions()
        self._connecter()
        self._afficher_tout()
        self._restaurer_disposition()

        self._minuterie_auto = QTimer(self)
        self._minuterie_auto.timeout.connect(self._sauvegarde_auto)
        self._minuterie_auto.start(INTERVALLE_AUTO_MS)
        self.resize(1500, 900)

    # Disposition

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
        self.resizeDocks([d["medias"], d["visionneuse"], d["inspecteur"]], [320, 820, 320],
                         Qt.Horizontal)
        self.resizeDocks([d["visionneuse"], d["timeline"]], [520, 360], Qt.Vertical)

    def _restaurer_disposition(self):
        etat = QSettings("Remanence", "Remanence").value("disposition")
        if etat is not None:
            self.restoreState(etat)

    def retablir_disposition(self):
        self._disposition_par_defaut()
        self.restoreState(self._etat_defaut)

    # Menus et raccourcis

    def _action(self, menu, texte, fonction, raccourci=None, aide=None):
        a = QAction(texte, self)
        if raccourci:
            a.setShortcuts([QKeySequence(r) for r in
                            (raccourci if isinstance(raccourci, list) else [raccourci])])
        if aide:
            a.setStatusTip(aide)
        a.triggered.connect(fonction)
        if menu is not None:
            menu.addAction(a)
        else:
            self.addAction(a)
        return a

    def _actions(self):
        m = self.menuBar()
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
        self._action(e, "Couper à la tête de lecture", self.couper, ["S", "B"],
                     "Coupe les clips sélectionnés, ou tous ceux sous la tête si rien n'est "
                     "sélectionné.")
        self._action(e, "Supprimer les clips sélectionnés", self.supprimer, ["Del", "Backspace"])
        self._action(e, "Dissocier son et image", self.dissocier, "U")
        self._action(e, "Lier la sélection", self.lier, "Ctrl+L")

        lec = m.addMenu("&Lecture")
        self._action(lec, "Lire / Pause", self._espace, "Space")
        self._action(lec, "Lecture arrière (J)", lambda: self._jkl(-1), "J")
        self._action(lec, "Arrêt (K)", self.lecture_pause, "K")
        self._action(lec, "Lecture avant (L)", lambda: self._jkl(1), "L")
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
        for dock in self._docks.values():
            a.addAction(dock.toggleViewAction())
        a.addSeparator()
        self._action(a, "Revenir à la disposition par défaut", self.retablir_disposition)

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
        self.lecture.image_prete.connect(self._image)
        self.lecture.position_changee.connect(self._position)
        self.lecture.lecture_changee.connect(self.visionneuse.etat_lecture)
        self.lecture.erreur.connect(lambda m, d: self.statusBar().showMessage(
            f"Image impossible à calculer : {m}", 8000))
        v = self.visionneuse
        v.demande_lecture.connect(self.lire_pause)
        v.demande_qualite.connect(self.lecture.definir_qualite)
        v.b_debut.clicked.connect(lambda: self.aller_a(0))
        v.b_fin.clicked.connect(lambda: self.aller_a(max(0, self.projet.sequence.duree() - 1)))
        v.b_prec.clicked.connect(lambda: self._pas(-1))
        v.b_suiv.clicked.connect(lambda: self._pas(1))

    # Affichage de l'état

    def _afficher_tout(self):
        self.medias.afficher(self.projet)
        self.timeline.afficher(self.projet)
        self.lecture.definir_projet(self.projet)
        self._selection(self.timeline.vue.selection)
        self._titre()
        self._position(self.lecture.position)
        self.a_annuler.setEnabled(self.historique.peut_annuler())
        self.a_retablir.setEnabled(self.historique.peut_retablir())
        self.a_annuler.setText(f"Annuler {self.historique.libelle_annuler().lower()}".strip())
        self.a_retablir.setText(f"Rétablir {self.historique.libelle_retablir().lower()}".strip())
        if not self.projet.sequence.duree():
            self.visionneuse.zone.montrer_message(
                "Glissez un média sur la timeline pour le voir ici.")

    def _titre(self):
        nom = self.chemin.stem if self.chemin else "Projet sans titre"
        self.setWindowTitle(f"{nom}{' *' if self.modifie else ''} · Remanence")

    def valider(self, libelle: str):
        """À appeler après toute modification du projet : historique, affichage, aperçu."""
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

    def _image(self, image, f):
        self.visionneuse.zone.montrer(image)

    def _position(self, f: int):
        seq = self.projet.sequence
        self.visionneuse.timecode.setText(images_vers_tc(seq.tc_debut + f, seq.fraction_cadence,
                                                         seq.tc_drop))
        self.visionneuse.info.setText(f"image {f} / {seq.duree()}")
        self.timeline.suivre_tete(f)

    def _cadence(self) -> int:
        return max(1, round(float(self.projet.sequence.fraction_cadence)))

    def _selection(self, ids: set):
        if len(ids) == 1:
            self.inspecteur.clip(self.projet, next(iter(ids)))
        elif ids:
            self.inspecteur.vide()
            self.message_etat.setText(f"{len(ids)} clips sélectionnés")
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

    def _espace(self):
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

    def lecture_pause(self):
        self.lecture.pause()

    def _jkl(self, sens: int):
        v = self.lecture.vitesse
        if v * sens > 0:
            vitesse = max(-8.0, min(8.0, v * 2))
        else:
            vitesse = float(sens)
        self.lecture.lire(vitesse)
        self.statusBar().showMessage(f"Lecture {'avant' if vitesse > 0 else 'arrière'} "
                                     f"×{abs(vitesse):g}" + ("" if vitesse == 1 else ", son coupé"),
                                     2000)

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
            self.statusBar().showMessage(str(e), 5000)
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

    def regler_piste(self, piste_id: str, champ: str, valeur: bool):
        for p in self.projet.sequence.pistes:
            if p.id == piste_id:
                setattr(p, champ, valeur)
        self.valider({"masquee": "Piste masquée", "muette": "Piste muette",
                      "verrouillee": "Verrou de piste"}[champ])

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
        self.valider({"gain": "Niveau", "fondu_entree": "Fondu d'entrée",
                      "fondu_sortie": "Fondu de sortie", "enveloppe": "Enveloppe"}[champ])

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
            self.statusBar().showMessage(str(e), 5000)
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
                    f"{Path(seq_img['motif']).name} contient {seq_img['nombre']} images.\n"
                    "À quelle cadence faut-il la lire ?",
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
                    f"Intermédiaire à cadence fixe ({infos_cfr.video.cadence} i/s) créé depuis "
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
        """Cache audio, proxy et vignette, calculés en arrière-plan après l'import."""
        infos = media.infos
        if infos.audio and not chemin_audio(infos).exists():
            def audio(progression, annule):
                return generer_cache_audio(infos, chemin_audio(infos), progression, annule)

            def audio_pret(_):
                self.timeline.vue.oublier_ondes()
                self.timeline.vue.update()
                self.lecture.definir_projet(self.projet)
            self.taches.lancer(Tache(f"Son de {media.nom}", audio), audio_pret,
                               lambda m, d: self.statusBar().showMessage(
                                   f"Son illisible pour {media.nom} : {m}", 8000))
        if infos.video:
            self.taches.lancer(Tache(f"Vignette de {media.nom}", lambda p, a: _vignette(media)),
                               lambda img: self._poser_vignette(media.id, img))
        if proxy_utile(infos) and not chemin_proxy(infos).exists():
            self.taches.lancer(Tache(f"Proxy de {media.nom}",
                                     lambda p, a: generer_proxy(infos, p, a)),
                               lambda _: self.lecture.definir_projet(self.projet),
                               lambda m, d: self.statusBar().showMessage(
                                   f"Proxy impossible pour {media.nom} : {m}", 8000))

    def _poser_vignette(self, media_id: str, img: np.ndarray):
        h, l = img.shape[:2]
        qimg = QImage(img.data, l, h, 3 * l, QImage.Format_RGB888).copy()
        self.medias.definir_vignette(media_id, QPixmap.fromImage(qimg))

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
                                           f"L'export de « {nom} » a échoué : {m}", det),
            lambda: self.statusBar().showMessage(f"Export de {nom} annulé. Aucun fichier n'a été "
                                                 "laissé à moitié écrit.", 6000))

    # Projet

    def _confirmer_abandon(self) -> bool:
        if not self.modifie:
            return True
        r = QMessageBox.question(
            self, "Modifications non enregistrées",
            "Le projet contient des modifications non enregistrées. Les enregistrer ?",
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
                "enregistré. Ouvrir la sauvegarde automatique ?",
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
                            f"Le projet n'a pas pu être écrit dans « {self.chemin} » : {e}. "
                            "Vérifiez que le disque n'est pas plein ou en lecture seule.")
            return False
        self.modifie = False
        self._titre()
        self.statusBar().showMessage(f"Projet enregistré (version {version.stem.rsplit('_v', 1)[1]})",
                                     4000)
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
        self.message_etat.setText(f"Sauvegarde automatique à {time.strftime('%H:%M')}")

    def closeEvent(self, e):
        if not self._confirmer_abandon():
            e.ignore()
            return
        QSettings("Remanence", "Remanence").setValue("disposition", self.saveState())
        self.taches.tout_annuler()
        self.lecture.fermer()
        self.taches.attendre(3000)
        e.accept()
