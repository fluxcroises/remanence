"""Fenêtres d'export : réglages avant, rapport de conformité après."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHeaderView, QLabel, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from remanence.rendu.export import Rapport


class DialogueRapport(QDialog):
    def __init__(self, rapport: Rapport, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export terminé")
        lay = QVBoxLayout(self)
        titre = QLabel(("Le fichier est conforme : il peut remplacer la source sans recalage."
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
        details = (f"{rapport.images_recopiees} image(s) recopiée(s) sans réencodage, "
                   f"{rapport.images_calculees} image(s) calculée(s). Son : {rapport.audio}.")
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
