"""Fenêtre À propos : version, nature du logiciel et licences de tout ce qu'il embarque."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QTextBrowser,
                               QVBoxLayout)

from remanence import EDITEUR, __version__
from remanence.ui import charte
from remanence.ui.charte import RACINE
from remanence.ui.composants import etiquette


def dossier_licences() -> Path:
    """Les textes des licences : à côté de Remanence.exe dans le programme construit, sinon
    ceux du projet (GPL, LGPL ; les autres sont dans les paquets installés)."""
    if getattr(sys, "frozen", False):
        livre = Path(sys.executable).parent / "licences"
        if livre.is_dir():
            return livre
    return RACINE / "remanence" / "ressources" / "licences"


class APropos(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("À propos de Remanence")
        c = charte.actuelle()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 16)
        lay.setSpacing(12)
        haut = QHBoxLayout()
        symbole = QLabel()
        symbole.setPixmap(c.symbole(48))
        haut.addWidget(symbole)
        titres = QVBoxLayout()
        titres.setSpacing(2)
        titres.addWidget(etiquette("Remanence", "dialogue"))
        titres.addWidget(etiquette(f"Version {__version__} · Montage et datamosh", "secondaire"))
        haut.addLayout(titres, 1)
        lay.addLayout(haut)
        texte = etiquette(f"Édité par {EDITEUR}. Logiciel libre.", "")
        texte.setWordWrap(True)
        lay.addWidget(texte)
        licences = QTextBrowser()
        licences.setOpenExternalLinks(True)
        fichier = RACINE / "LICENCES.md"
        licences.setMarkdown(fichier.read_text(encoding="utf-8") if fichier.exists()
                             else "Le fichier LICENCES.md est introuvable.")
        lay.addWidget(licences, 1)
        boutons = QDialogButtonBox(QDialogButtonBox.Close)
        boutons.button(QDialogButtonBox.Close).setText("Fermer")
        boutons.rejected.connect(self.accept)
        textes = boutons.addButton("Textes des licences", QDialogButtonBox.ActionRole)
        textes.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(dossier_licences()))))
        lay.addWidget(boutons)
        self.resize(720, 520)
