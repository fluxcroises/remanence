"""Espace Export : réglages du rendu et file des exports en cours ou terminés."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLineEdit,
                               QProgressBar, QPushButton, QRadioButton, QScrollArea, QVBoxLayout,
                               QWidget)

from remanence.media.timecode import images_vers_tc
from remanence.projet.modele import Projet
from remanence.rendu.export import FORMATS, Rapport, format_source, media_reference
from remanence.ui.composants import etiquette
from remanence.ui.dialogue_export import DialogueRapport


class FormulaireExport(QWidget):
    """Format, plage et fichier ; le bouton principal lance l'export dans la file."""
    lancer = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.projet: Projet | None = None
        self.chemin_projet: Path | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(12)
        lay.addWidget(etiquette("Format", "section"))
        self.format = QComboBox()

        self.format.currentIndexChanged.connect(self._extension)
        lay.addWidget(self.format)
        lay.addWidget(etiquette("Plage", "section"))
        self.tout = QRadioButton("Toute la séquence")
        self.plage = QRadioButton("Entre les points E et S")
        lay.addWidget(self.tout)
        lay.addWidget(self.plage)
        lay.addWidget(etiquette("Fichier", "section"))
        self.fichier = QLineEdit()
        self.fichier.setAccessibleName("Fichier exporté")
        parcourir = QPushButton("Choisir…")
        parcourir.clicked.connect(self._choisir)
        ligne = QHBoxLayout()
        ligne.addWidget(self.fichier, 1)
        ligne.addWidget(parcourir)
        lay.addLayout(ligne)
        self.resume = etiquette("", "secondaire")
        self.resume.setWordWrap(True)
        lay.addWidget(self.resume)
        self.erreur = etiquette("", "erreur")
        self.erreur.setWordWrap(True)
        self.erreur.hide()
        lay.addWidget(self.erreur)
        lay.addStretch(1)
        self.bouton = QPushButton("Exporter")
        self.bouton.setProperty("variante", "principal")
        self.bouton.setToolTip("Exporter (Ctrl+Entrée)")
        self.bouton.clicked.connect(self._valider)
        lay.addWidget(self.bouton)

    def actualiser(self, projet: Projet, chemin_projet: Path | None):
        """Remet les choix à jour pour la séquence courante, sans effacer un fichier déjà saisi."""
        self.projet, self.chemin_projet = projet, chemin_projet
        seq = projet.sequence
        ref = media_reference(projet, seq, 0, max(1, seq.duree()))
        choix = self.format.currentData()
        self.format.blockSignals(True)
        self.format.clear()
        if ref is not None:
            fmt, _ = format_source(ref.infos.video)
            self.format.addItem(f"Comme la source : {fmt.nom}", "source")
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
        if not self.fichier.text():
            base = ref.infos.chemin if ref else str(chemin_projet or Path.home() / "export.mov")
            dossier = Path(chemin_projet).parent if chemin_projet else Path(base).parent
            self.fichier.setText(str(dossier / (Path(base).stem + "_remanence" + self._ext())))
            self.fichier.setCursorPosition(0)
        else:
            self._extension()
        cad = seq.fraction_cadence
        self.resume.setText(
            f"Séquence : {seq.largeur} × {seq.hauteur}, "
            f"{float(cad):.3f}".replace(".", ",", 1) + f" i/s, départ "
            f"{images_vers_tc(seq.tc_debut, cad, seq.tc_drop)}")
        self.bouton.setEnabled(seq.duree() > 0)
        self.bouton.setToolTip("" if seq.duree() else "Timeline vide")

    def _ext(self) -> str:
        cle = self.format.currentData()
        if cle in (None, "source"):
            ref = media_reference(self.projet, self.projet.sequence, 0,
                                  max(1, self.projet.sequence.duree())) if self.projet else None
            return format_source(ref.infos.video)[0].extension if ref else ".mov"
        return FORMATS[cle].extension

    def _extension(self):
        if self.fichier.text():
            self.fichier.setText(str(Path(self.fichier.text()).with_suffix(self._ext())))

    def _choisir(self):
        chemin, _ = QFileDialog.getSaveFileName(self, "Fichier exporté", self.fichier.text(),
                                                f"Vidéo (*{self._ext()})")
        if chemin:
            self.fichier.setText(chemin)

    def _valider(self):
        chemin = Path(self.fichier.text())
        if not chemin.parent.exists():
            self.erreur.setText(f"Dossier introuvable : « {chemin.parent} »")
            self.erreur.show()
            return
        self.erreur.hide()
        seq = self.projet.sequence
        r = {"chemin": chemin, "cle_format": self.format.currentData() or "source",
             "format": self.format.currentText()}
        if self.plage.isChecked():
            r["debut"] = seq.point_entree or 0
            r["fin"] = seq.point_sortie if seq.point_sortie is not None else seq.duree()
        else:
            r["debut"], r["fin"] = 0, seq.duree()
        self.lancer.emit(r)


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
        self.nom = etiquette(nom)
        self.nom.setStyleSheet("font-weight: 500;")
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
