"""Message d'erreur qui dit quoi faire, avec le détail technique copiable."""

from __future__ import annotations

import traceback

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QPushButton, QVBoxLayout)

from remanence import journal


def afficher_erreur(parent, titre: str, message: str, detail: str | None = None):
    detail = detail or traceback.format_exc()
    journal.erreur(titre, message, detail)
    d = QDialog(parent)
    d.setWindowTitle(titre)
    lay = QVBoxLayout(d)
    texte = QLabel(message)
    texte.setWordWrap(True)
    texte.setMinimumWidth(420)
    lay.addWidget(texte)
    boutons = QDialogButtonBox()
    copier = QPushButton("Copier le détail")


    def _copier():
        QGuiApplication.clipboard().setText(f"{titre}\n{message}\n\n{detail}")
        copier.setText("Détail copié")
    copier.clicked.connect(_copier)
    fermer = boutons.addButton("Fermer", QDialogButtonBox.AcceptRole)
    boutons.addButton(copier, QDialogButtonBox.ActionRole)
    boutons.accepted.connect(d.accept)
    fermer.setDefault(True)
    lay.addWidget(boutons)
    d.exec()
