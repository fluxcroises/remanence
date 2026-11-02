"""Fenêtre de prise en main : les fiches à gauche, la fiche choisie à droite. Elle reste
ouverte à côté de Remanence pendant qu'on travaille (Aide > Prise en main, F1, ou une carte
de l'écran d'accueil).

Les fiches sont des fichiers Markdown de `remanence/ressources/aide`, avec leurs captures
(refaites par `scripts/captures_aide.py`).
"""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QImage, QTextBlockFormat, QTextCursor
from PySide6.QtWidgets import QHBoxLayout, QListWidget, QListWidgetItem, QTextBrowser, QWidget

from remanence.ui import charte

AIDE = Path(__file__).resolve().parents[1] / "ressources" / "aide"


def fiches() -> list[tuple[str, Path, Path | None]]:
    """(titre, fichier, première capture) de chaque fiche, dans l'ordre de leur nom."""
    resultat = []
    for f in sorted(AIDE.glob("*.md")):
        texte = f.read_text(encoding="utf-8")
        titre = texte.splitlines()[0].lstrip("# ").strip()
        image = re.search(r"!\[[^\]]*\]\(([^)]+)\)", texte)
        resultat.append((titre, f, AIDE / image.group(1) if image else None))
    return resultat


def afficher_fiche(lecteur: QTextBrowser, chemin: Path):
    """La fiche dans le lecteur. Le Markdown de Qt colle les paragraphes et montre les images
    à leur taille : un peu d'air entre les blocs, captures ramenées à la largeur du texte."""
    doc = lecteur.document()
    doc.setBaseUrl(QUrl.fromLocalFile(str(chemin.parent) + "/"))
    lecteur.setMarkdown(chemin.read_text(encoding="utf-8"))
    largeur = max(360, lecteur.viewport().width() - 2 * doc.documentMargin() - 8)
    curseur = QTextCursor(doc)
    bloc = doc.begin()
    while bloc.isValid():
        forme = bloc.blockFormat()
        forme.setBottomMargin(10 if bloc.textList() is None else 4)
        forme.setLineHeight(130, QTextBlockFormat.ProportionalHeight.value)
        curseur.setPosition(bloc.position())
        curseur.setBlockFormat(forme)
        it = bloc.begin()
        while not it.atEnd():
            fragment = it.fragment()
            image = fragment.charFormat().toImageFormat()
            if image.isValid():
                taille = QImage(str(AIDE / image.name())).size()
                if taille.width() > largeur:
                    image.setWidth(largeur)
                    image.setHeight(taille.height() * largeur / taille.width())
                    curseur.setPosition(fragment.position())
                    curseur.setPosition(fragment.position() + fragment.length(),
                                        QTextCursor.KeepAnchor)
                    curseur.setCharFormat(image)
            it += 1
        bloc = bloc.next()
    lecteur.verticalScrollBar().setValue(0)


class FenetreAide(QWidget):
    """Une seule fenêtre pour toute la session (`ouvrir`)."""

    _instance: "FenetreAide | None" = None

    def __init__(self):
        super().__init__(None, Qt.Window)
        self.setWindowTitle("Prise en main · Remanence")
        self.setWindowIcon(charte.actuelle().icone_application())
        self.setProperty("role", "panneau")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.resize(980, 720)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.liste = QListWidget()
        self.liste.setAccessibleName("Fiches")
        self.liste.setFixedWidth(260)
        self.lecteur = QTextBrowser()
        self.lecteur.setAccessibleName("Fiche")
        self.lecteur.setOpenExternalLinks(False)
        self.lecteur.setSearchPaths([str(AIDE)])
        self.lecteur.document().setDocumentMargin(28)
        self._fiches = fiches()
        for titre, chemin, _image in self._fiches:
            item = QListWidgetItem(titre)
            item.setData(Qt.UserRole, str(chemin))
            self.liste.addItem(item)
        self.liste.currentRowChanged.connect(self._lire)
        lay.addWidget(self.liste)
        lay.addWidget(self.lecteur, 1)

    def _lire(self, i: int):
        if 0 <= i < len(self._fiches):
            afficher_fiche(self.lecteur, self._fiches[i][1])

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # Les captures suivent la largeur du texte.
        self._lire(self.liste.currentRow())

    @classmethod
    def ouvrir(cls, fiche: int = 0) -> "FenetreAide":
        if cls._instance is None:
            cls._instance = FenetreAide()
        f = cls._instance
        f.show()
        f.raise_()
        f.activateWindow()
        if f.liste.currentRow() != fiche:
            f.liste.setCurrentRow(fiche)
        else:
            f._lire(fiche)
        return f
