"""La molette fait défiler les panneaux, elle ne change pas un réglage au passage.

Un curseur, un champ numérique ou une liste déroulante ne prend la molette que s'il a le
clavier (après un clic ou Tab) ; sinon elle va au panneau qui le contient, qui défile.
Qt donne le clavier au widget survolé par la molette (WheelFocus) avant tout filtre : ces
widgets passent en StrongFocus dès leur mise en forme.
"""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt
from PySide6.QtWidgets import (QAbstractSlider, QAbstractSpinBox, QComboBox, QScrollBar,
                               QWidget)

REGLAGES = (QAbstractSpinBox, QAbstractSlider, QComboBox)
_filtre = None


class Molette(QObject):
    def eventFilter(self, objet, e):
        genre = e.type()
        # Les barres de défilement restent à part : c'est par elles que les panneaux défilent.
        if not isinstance(objet, REGLAGES) or isinstance(objet, QScrollBar):
            return False
        if genre == QEvent.Polish:
            if objet.focusPolicy() == Qt.WheelFocus:
                objet.setFocusPolicy(Qt.StrongFocus)
        elif genre == QEvent.Wheel and not objet.hasFocus():
            # Qt ne propage pas un événement renvoyé : on remonte soi-même jusqu'au premier
            # parent qui s'en sert (une zone qui défile).
            parent = objet.parentWidget()
            while isinstance(parent, QWidget):
                e.ignore()
                QCoreApplication.sendEvent(parent, e)
                if e.isAccepted():
                    break
                parent = parent.parentWidget()
            return True
        return False


def installer(app):
    """Une fois par application (la fenêtre principale l'appelle)."""
    global _filtre
    if _filtre is None:
        _filtre = Molette(app)
        app.installEventFilter(_filtre)
