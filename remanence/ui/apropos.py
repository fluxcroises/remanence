"""Fenêtre À propos : version, nature du logiciel et licences de tout ce qu'il embarque."""

from __future__ import annotations

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QTextBrowser,
                               QVBoxLayout)

from remanence import __version__
from remanence.ui import charte
from remanence.ui.charte import RACINE
from remanence.ui.composants import etiquette


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
        texte = etiquette("Logiciel libre, distribué en code source, sans but commercial. "
                          "Il repose sur les projets libres listés ci-dessous.", "")
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
        lay.addWidget(boutons)
        self.resize(720, 520)
