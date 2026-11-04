"""Repère du clavier seulement quand on se déplace au clavier, comme :focus-visible sur le web.

Qt donne le clavier au widget cliqué, et la feuille de style l'encadrait à chaque clic. Ici, un
widget ne reçoit la propriété `focus_clavier` (que la feuille de style rend visible) que s'il a
eu le clavier par Tab, Maj+Tab ou un raccourci, juste après une touche ; un clic de souris
ne montre rien, ni l'ouverture d'une fenêtre (Qt y donne le clavier au premier bouton en se
disant venu de Tab).
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QWidget

PROPRIETE = "focus_clavier"
RAISONS_CLAVIER = (Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason)
_filtre = None


def marquer(widget: QWidget, oui: bool):
    if bool(widget.property(PROPRIETE)) == oui:
        return
    widget.setProperty(PROPRIETE, oui)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def visible(widget: QWidget) -> bool:
    """Le widget a le clavier, et on y est venu au clavier : le repère doit se voir."""
    return widget.hasFocus() and bool(widget.property(PROPRIETE))


class FocusClavier(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.au_clavier = False  # la dernière action était une touche (et non un clic)

    def eventFilter(self, objet, e):
        genre = e.type()
        if genre == QEvent.KeyPress:
            self.au_clavier = True
        elif genre in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick):
            self.au_clavier = False
        elif genre == QEvent.FocusIn and isinstance(objet, QWidget):
            marquer(objet, self.au_clavier and e.reason() in RAISONS_CLAVIER)
        elif genre == QEvent.FocusOut and isinstance(objet, QWidget):
            marquer(objet, False)
        return False


def installer(app):
    """Une fois par application (la fenêtre principale l'appelle)."""
    global _filtre
    if _filtre is None:
        _filtre = FocusClavier(app)
        app.installEventFilter(_filtre)
