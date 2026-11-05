"""Espace Export : réglages du rendu et file des exports en cours ou terminés."""

from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLineEdit,
                               QProgressBar, QPushButton, QRadioButton, QScrollArea, QSizePolicy,
                               QVBoxLayout,
                               QWidget)

from remanence.config import reglages_interface
from remanence.media.timecode import images_vers_tc
from remanence.projet.modele import Projet
from remanence.rendu import nommage
from remanence.rendu.export import FORMATS, Rapport, format_source, media_reference
from remanence.ui.composants import etiquette
from remanence.ui.dialogue_export import DialogueRapport


class FormulaireExport(QWidget):
    """Format, plage, dossier et modèle de nom ; le bouton principal lance l'export (ou un
    export par plan) dans la file."""
    lancer = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.projet: Projet | None = None
        self.chemin_projet: Path | None = None
        # Fichiers promis à des exports en attente : la version suivante les saute.
        self._reserves: set[Path] = set()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(12)
        lay.addWidget(etiquette("Format", "section"))
        self.format = QComboBox()
        self.format.currentIndexChanged.connect(lambda _i: self._apercu())
        lay.addWidget(self.format)
        lay.addWidget(etiquette("Plage", "section"))
        self.tout = QRadioButton("Toute la séquence")
        self.plage = QRadioButton("Entre les points E et S")
        lay.addWidget(self.tout)
        lay.addWidget(self.plage)
        self.par_plan = QCheckBox("Un fichier par plan")
        self.par_plan.setToolTip("Un fichier par clip de la piste vidéo du bas")
        self.par_plan.toggled.connect(lambda _v: self._apercu())
        lay.addWidget(self.par_plan)
        lay.addWidget(etiquette("Dossier", "section"))
        self.dossier = QLineEdit()
        self.dossier.setAccessibleName("Dossier d'export")
        # Le bout du chemin compte plus que son début : la fin reste visible.
        self.dossier.textChanged.connect(self._fin_du_chemin)
        self.dossier.textChanged.connect(lambda _t: self._apercu())
        parcourir = QPushButton("Choisir…")
        parcourir.clicked.connect(self._choisir)
        ligne = QHBoxLayout()
        ligne.addWidget(self.dossier, 1)
        ligne.addWidget(parcourir)
        lay.addLayout(ligne)
        lay.addWidget(etiquette("Nom", "section"))
        self.modele = QLineEdit(str(reglages_interface().value("export/modele",
                                                               nommage.MODELE_DEFAUT)))
        self.modele.setAccessibleName("Modèle de nom")
        self.modele.textChanged.connect(lambda _t: self._apercu())
        lay.addWidget(self.modele)
        lay.addWidget(etiquette(" · ".join("{" + v + "}" for v in nommage.VARIABLES),
                                "secondaire"))
        self.nom_final = etiquette("", "valeur")
        self.nom_final.setWordWrap(True)
        lay.addWidget(self.nom_final)
        self.resume = etiquette("", "secondaire")
        self.resume.setWordWrap(True)
        lay.addWidget(self.resume)
        self.erreur = etiquette("", "erreur")
        self.erreur.setWordWrap(True)
        self.erreur.hide()
        lay.addWidget(self.erreur)
        lay.addSpacing(8)
        self.bouton = QPushButton("Exporter")
        self.bouton.setProperty("variante", "principal")
        self.bouton.setToolTip("Exporter (Ctrl+Entrée)")
        self.bouton.clicked.connect(self._valider)
        lay.addWidget(self.bouton)
        lay.addStretch(1)

    def _fin_du_chemin(self, texte: str):
        self.dossier.setToolTip(texte)
        if not self.dossier.hasFocus():
            QTimer.singleShot(0, lambda: self.dossier.end(False))

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, lambda: self.dossier.end(False))

    def actualiser(self, projet: Projet, chemin_projet: Path | None):
        """Remet les choix à jour pour la séquence courante, sans effacer un dossier choisi."""
        self.projet, self.chemin_projet = projet, chemin_projet
        seq = projet.sequence
        ref = media_reference(projet, seq, 0, max(1, seq.duree()))
        choix = self.format.currentData()
        self.format.blockSignals(True)
        self.format.clear()
        if ref is not None:
            fmt, _ = format_source(ref.infos.video)
            self.format.addItem(f"Comme la source : {fmt.nom}", "source")
        for cle, f in FORMATS.items():
            self.format.addItem(f.nom, cle)
        i = self.format.findData(choix)
        if i < 0:
            i = 0 if ref is not None else self.format.findData("prores_hq")
        self.format.setCurrentIndex(max(0, i))
        self.format.blockSignals(False)
        a_plage = seq.point_entree is not None or seq.point_sortie is not None
        self.plage.setEnabled(a_plage)
        if not a_plage:
            self.tout.setChecked(True)
        elif not self.tout.isChecked():
            self.plage.setChecked(True)
        if not self.dossier.text():
            if chemin_projet:
                self.dossier.setText(str(Path(chemin_projet).parent))
            else:
                self.dossier.setText(str(Path(ref.infos.chemin).parent) if ref
                                     else str(Path.home()))
        cad = seq.fraction_cadence
        self.resume.setText(
            f"Séquence : {seq.largeur} × {seq.hauteur}, "
            f"{float(cad):.3f}".replace(".", ",", 1) + f" i/s, départ "
            f"{images_vers_tc(seq.tc_debut, cad, seq.tc_drop)}")
        self.bouton.setEnabled(seq.duree() > 0)
        self.bouton.setToolTip("" if seq.duree() else "Timeline vide")
        self._apercu()

    def _ext(self) -> str:
        cle = self.format.currentData()
        if cle in (None, "source"):
            ref = media_reference(self.projet, self.projet.sequence, 0,
                                  max(1, self.projet.sequence.duree())) if self.projet else None
            return format_source(ref.infos.video)[0].extension if ref else ".mov"
        return FORMATS[cle].extension

    def _choisir(self):
        dossier = QFileDialog.getExistingDirectory(self, "Dossier d'export", self.dossier.text())
        if dossier:
            self.dossier.setText(dossier)

    def _plans(self) -> list[tuple[int, int, str]]:
        """(début, fin, nom du plan) de chaque fichier à écrire."""
        seq = self.projet.sequence
        if self.plage.isChecked():
            debut = seq.point_entree or 0
            fin = seq.point_sortie if seq.point_sortie is not None else seq.duree()
        else:
            debut, fin = 0, seq.duree()
        if self.par_plan.isChecked() and seq.pistes_video:
            plans = []
            for c in seq.pistes_video[-1].clips:
                media = self.projet.medias.get(c.media_id)
                a, b = max(debut, c.debut), min(fin, c.fin)
                if media is not None and b > a:
                    plans.append((a, b, Path(media.chemin).stem))
            if plans:
                return plans
        ref = media_reference(self.projet, seq, debut, max(debut + 1, fin))
        return [(debut, fin, Path(ref.chemin).stem if ref else seq.nom)]

    def _valeurs(self, plan: str) -> dict:
        cle = self.format.currentData() or "source"
        return {"plan": plan, "sequence": self.projet.sequence.nom,
                "projet": Path(self.chemin_projet).stem if self.chemin_projet else "Sans titre",
                "format": cle}

    def _apercu(self):
        if self.projet is None or not self.projet.sequence.duree():
            self.nom_final.setText("")
            return
        plans = self._plans()
        chemin = nommage.nommer(self.modele.text(), self._valeurs(plans[0][2]),
                                Path(self.dossier.text()), self._ext(), self._reserves)
        suite = f" (+{len(plans) - 1})" if len(plans) > 1 else ""
        self.nom_final.setText(chemin.name + suite)

    def _valider(self):
        dossier = Path(self.dossier.text())
        if not dossier.is_dir():
            self.erreur.setText(f"Dossier introuvable : « {dossier} »")
            self.erreur.show()
            return
        self.erreur.hide()
        reglages_interface().setValue("export/modele", self.modele.text())
        seq = self.projet.sequence
        for debut, fin, plan in self._plans():
            chemin = nommage.nommer(self.modele.text(), self._valeurs(plan), dossier,
                                    self._ext(), self._reserves)
            self._reserves.add(chemin)
            self.lancer.emit({"chemin": chemin, "cle_format": self.format.currentData() or "source",
                              "format": self.format.currentText(), "debut": debut, "fin": fin,
                              "plan": plan, "tc": seq.tc_debut + debut,
                              "cadence": seq.cadence})
        self._apercu()


def montrer_dans_explorateur(chemin: Path):
    """L'explorateur de Windows ouvert sur le dossier, le fichier choisi ; une séquence
    d'images (pas de fichier unique) : le dossier seul."""
    if chemin.is_file():
        subprocess.Popen(["explorer", "/select,", str(chemin)])
    else:
        dossier = chemin if chemin.is_dir() else chemin.parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(dossier)))


class LigneExport(QWidget):
    """Un rendu dans la file : nom, format, progression, puis résultat et rapport."""

    def __init__(self, nom: str, format_: str, annuler):
        super().__init__()
        self.setProperty("role", "entete-piste")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(4)
        haut = QHBoxLayout()
        # Un nom long se coupe (« … ») au lieu de pousser le bouton hors du panneau.
        self._nom_complet = nom
        self.nom = etiquette(nom)
        self.nom.setStyleSheet("font-weight: 500;")
        self.nom.setToolTip(nom)
        self.nom.setMinimumWidth(40)
        self.nom.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        haut.addWidget(self.nom, 1)
        self.bouton = QPushButton("Annuler")
        self.bouton.setProperty("variante", "discret")
        self.bouton.clicked.connect(annuler)
        haut.addWidget(self.bouton)
        lay.addLayout(haut)
        lay.addWidget(etiquette(format_, "libelle"))
        self.barre = QProgressBar()
        self.barre.setRange(0, 1000)
        lay.addWidget(self.barre)
        self.etat = etiquette("En attente", "libelle")
        lay.addWidget(self.etat)
        self._rapport: Rapport | None = None

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.nom.setText(self.nom.fontMetrics().elidedText(
            self._nom_complet, Qt.ElideMiddle, max(0, self.nom.width())))

    def progression(self, v: float):
        self.barre.setValue(int(v * 1000))
        self.etat.setText(f"En cours : {round(v * 100)} %")

    def termine(self, rapport: Rapport):
        self._rapport = rapport
        self.barre.setValue(1000)
        if rapport.conforme:
            self.etat.setText("Terminé : conforme à la source")
            self.etat.setProperty("role", "succes")
        else:
            self.etat.setText("Terminé avec des écarts")
            self.etat.setProperty("role", "avertissement")
        self.etat.style().polish(self.etat)
        self._bouton("Voir le rapport", lambda: DialogueRapport(rapport, self).exec())
        # Le fichier obtenu : son dossier (fichier choisi dans l'explorateur) et la lecture.
        chemin = Path(rapport.chemin)
        bas = QHBoxLayout()
        bas.setSpacing(6)
        dossier = QPushButton("Ouvrir le dossier")
        dossier.setProperty("variante", "discret")
        dossier.clicked.connect(lambda: montrer_dans_explorateur(chemin))
        bas.addWidget(dossier)
        if chemin.is_file():
            lire = QPushButton("Lire")
            lire.setProperty("variante", "discret")
            lire.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(chemin))))
            bas.addWidget(lire)
        bas.addStretch(1)
        self.layout().addLayout(bas)

    def echec(self, message: str):
        self.etat.setText(f"Erreur : {message}")
        self.etat.setProperty("role", "erreur")
        self.etat.style().polish(self.etat)
        self.bouton.hide()

    def annule(self):
        self.etat.setText("Annulé")
        self.bouton.hide()

    def _bouton(self, texte, action):
        self.bouton.setText(texte)
        try:
            self.bouton.clicked.disconnect()
        except RuntimeError:
            pass
        self.bouton.clicked.connect(action)
        self.bouton.show()


class FileExport(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        defil = QScrollArea()
        defil.setWidgetResizable(True)
        defil.setFrameShape(QScrollArea.NoFrame)
        contenu = QWidget()
        contenu.setProperty("role", "panneau")
        contenu.setAttribute(Qt.WA_StyledBackground, True)
        self._liste = QVBoxLayout(contenu)
        self._liste.setContentsMargins(8, 8, 8, 8)
        self._liste.setSpacing(6)
        self._vide = etiquette("Aucun export", "secondaire")
        self._vide.setWordWrap(True)
        self._liste.addWidget(self._vide)
        self._liste.addStretch(1)
        defil.setWidget(contenu)
        lay.addWidget(defil)

    def ajouter(self, nom: str, format_: str, annuler) -> LigneExport:
        self._vide.hide()
        ligne = LigneExport(nom, format_, annuler)
        self._liste.insertWidget(0, ligne)
        return ligne
