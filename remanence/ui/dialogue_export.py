"""Fenêtres d'export : réglages avant, rapport de conformité après."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
                               QRadioButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from remanence.media.timecode import images_vers_tc
from remanence.projet.modele import Projet
from remanence.rendu.export import FORMATS, Rapport, format_source, media_reference


class DialogueExport(QDialog):
    def __init__(self, projet: Projet, chemin_projet: Path | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Exporter la séquence")
        self.projet = projet
        seq = projet.sequence
        ref = media_reference(projet, seq, 0, max(1, seq.duree()))
        self.format = QComboBox()
        if ref is not None:
            fmt, _ = format_source(ref.infos.video)
            self.format.addItem(f"Comme la source : {fmt.nom}", "source")
        for cle, f in FORMATS.items():
            self.format.addItem(f.nom, cle)
        self.format.setToolTip("« Comme la source » reprend le codec, le profil et la profondeur "
                               "du plan pour qu'il se réintègre au montage sans recalage.")
        self.format.currentIndexChanged.connect(self._extension)

        self.tout = QRadioButton("Toute la séquence")
        self.plage = QRadioButton("Entre les points d'entrée et de sortie (I et O)")
        a_plage = seq.point_entree is not None or seq.point_sortie is not None
        self.plage.setEnabled(a_plage)
        (self.plage if a_plage else self.tout).setChecked(True)
        if not a_plage:
            self.plage.setToolTip("Posez un point d'entrée (I) et de sortie (O) sur la timeline "
                                  "pour exporter une partie seulement.")

        base = (ref.infos.chemin if ref else str(chemin_projet or Path.home() / "export.mov"))
        nom = Path(base).stem + "_remanence"
        dossier = Path(chemin_projet).parent if chemin_projet else Path(base).parent
        self.fichier = QLineEdit(str(dossier / (nom + self._ext())))
        parcourir = QPushButton("Choisir…")
        parcourir.clicked.connect(self._choisir)
        ligne = QHBoxLayout()
        ligne.addWidget(self.fichier, 1)
        ligne.addWidget(parcourir)

        cad = seq.fraction_cadence
        resume = QLabel(f"{seq.largeur} × {seq.hauteur}, {float(cad):.3f} i/s, départ "
                        f"{images_vers_tc(seq.tc_debut, cad, seq.tc_drop)}".replace(".", ",", 1))
        resume.setProperty("role", "secondaire")

        form = QFormLayout()
        form.addRow("Format", self.format)
        form.addRow("Plage", self.tout)
        form.addRow("", self.plage)
        form.addRow("Fichier", ligne)
        form.addRow("Séquence", resume)
        boutons = QDialogButtonBox()
        ok = boutons.addButton("Exporter", QDialogButtonBox.AcceptRole)
        ok.setDefault(True)
        boutons.addButton("Annuler", QDialogButtonBox.RejectRole)
        boutons.accepted.connect(self._valider)
        boutons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        self.erreur = QLabel("")
        self.erreur.setWordWrap(True)
        self.erreur.setVisible(False)
        lay.addWidget(self.erreur)
        lay.addWidget(boutons)
        self.setMinimumWidth(560)

    def _ext(self) -> str:
        cle = self.format.currentData()
        if cle == "source":
            ref = media_reference(self.projet, self.projet.sequence, 0,
                                  max(1, self.projet.sequence.duree()))
            return format_source(ref.infos.video)[0].extension if ref else ".mov"
        return FORMATS[cle].extension

    def _extension(self):
        self.fichier.setText(str(Path(self.fichier.text()).with_suffix(self._ext())))

    def _choisir(self):
        chemin, _ = QFileDialog.getSaveFileName(self, "Fichier exporté", self.fichier.text(),
                                                f"Vidéo (*{self._ext()})")
        if chemin:
            self.fichier.setText(chemin)

    def _valider(self):
        chemin = Path(self.fichier.text())
        if not chemin.parent.exists():
            self.erreur.setText(f"Le dossier « {chemin.parent} » n'existe pas. Choisissez un "
                                "autre emplacement.")
            self.erreur.setVisible(True)
            return
        self.accept()

    def reglages(self) -> dict:
        seq = self.projet.sequence
        r = {"chemin": Path(self.fichier.text()), "cle_format": self.format.currentData()}
        if self.plage.isChecked():
            r["debut"] = seq.point_entree or 0
            r["fin"] = seq.point_sortie if seq.point_sortie is not None else seq.duree()
        else:
            r["debut"], r["fin"] = 0, seq.duree()
        return r


class DialogueRapport(QDialog):
    def __init__(self, rapport: Rapport, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export terminé")
        lay = QVBoxLayout(self)
        titre = QLabel(("Le fichier est conforme : il peut remplacer la source sans recalage."
                        if rapport.conforme else
                        "Le fichier a été écrit, mais il diffère de la source sur les points "
                        "marqués « Écart »."))
        titre.setWordWrap(True)
        titre.setStyleSheet("font-weight: 600;")
        lay.addWidget(titre)
        chemin = QLabel(str(rapport.chemin))
        chemin.setTextInteractionFlags(Qt.TextSelectableByMouse)
        chemin.setProperty("role", "secondaire")
        lay.addWidget(chemin)
        table = QTableWidget(len(rapport.verifications), 4)
        table.setHorizontalHeaderLabels(["Critère", "Attendu", "Obtenu", "Résultat"])
        for i, v in enumerate(rapport.verifications):
            for j, t in enumerate((v.critere, v.attendu, v.obtenu, "Identique" if v.ok else "Écart")):
                item = QTableWidgetItem(t)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                table.setItem(i, j, item)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        lay.addWidget(table)
        details = (f"{rapport.images_recopiees} image(s) recopiée(s) sans réencodage, "
                   f"{rapport.images_calculees} image(s) calculée(s). Son : {rapport.audio}.")
        d = QLabel(details)
        d.setWordWrap(True)
        lay.addWidget(d)
        for a in rapport.avertissements:
            n = QLabel(a)
            n.setWordWrap(True)
            lay.addWidget(n)
        boutons = QDialogButtonBox(QDialogButtonBox.Close)
        boutons.button(QDialogButtonBox.Close).setText("Fermer")
        boutons.rejected.connect(self.accept)
        lay.addWidget(boutons)
        self.resize(720, 360)
