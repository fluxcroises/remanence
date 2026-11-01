"""Mode expert : l'éditeur du script JavaScript d'un effet Script FFglitch."""

from __future__ import annotations

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QInputDialog,
                               QPlainTextEdit, QPushButton, QVBoxLayout)

from remanence.moteurs.codec import scripts
from remanence.ui import charte


class EditeurScript(QDialog):
    def __init__(self, texte: str, nom: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Script FFglitch · {nom}")
        self.resize(760, 620)
        self.nom = nom
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(10)
        self.texte = QPlainTextEdit(texte)
        self.texte.setAccessibleName("Script")
        # IBM Plex Mono, comme les valeurs de l'interface (la feuille de style l'emporte sur
        # setFont).
        self.texte.setStyleSheet("QPlainTextEdit { %s }" % charte.actuelle().css_police("value"))
        self.texte.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.texte.setTabStopDistance(self.texte.fontMetrics().horizontalAdvance(" ") * 2)
        lay.addWidget(self.texte, 1)
        bas = QHBoxLayout()
        garder = QPushButton("Enregistrer dans la bibliothèque…")
        garder.clicked.connect(self._enregistrer)
        bas.addWidget(garder)
        bas.addStretch(1)
        boutons = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Cancel)
        boutons.button(QDialogButtonBox.Apply).setText("Appliquer")
        boutons.button(QDialogButtonBox.Apply).setDefault(True)
        boutons.button(QDialogButtonBox.Apply).clicked.connect(self.accept)
        boutons.rejected.connect(self.reject)
        bas.addWidget(boutons)
        lay.addLayout(bas)
        QShortcut(QKeySequence("Ctrl+Return"), self, self.accept)

    def contenu(self) -> str:
        return self.texte.toPlainText()

    def _enregistrer(self):
        nom, ok = QInputDialog.getText(self, "Enregistrer le script", "Nom", text=self.nom)
        if ok and nom.strip():
            scripts.enregistrer(nom.strip(), self.contenu())
            self.nom = nom.strip()
            self.setWindowTitle(f"Script FFglitch · {self.nom}")
