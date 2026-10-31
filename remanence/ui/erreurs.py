"""Message d'erreur qui dit quoi faire, avec le détail technique copiable."""

from __future__ import annotations

import datetime
import traceback

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QPushButton, QVBoxLayout)

from remanence.config import dossier_donnees


def journaliser(detail: str):
    try:
        with open(dossier_donnees() / "journal.txt", "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}]\n{detail}\n")
    except OSError:
        pass


def afficher_erreur(parent, titre: str, message: str, detail: str | None = None):
    detail = detail or traceback.format_exc()
    journaliser(f"{titre} : {message}\n{detail}")
    d = QDialog(parent)
    d.setWindowTitle(titre)
    lay = QVBoxLayout(d)
    texte = QLabel(message)
    texte.setWordWrap(True)
    texte.setMinimumWidth(420)
    lay.addWidget(texte)
    boutons = QDialogButtonBox()
    copier = QPushButton("Copier le détail")
    copier.setToolTip("Copie le détail technique dans le presse-papiers, pour un rapport de bogue.")

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
