"""Menu des effets par famille, puis préréglage ; partagé par la timeline, l'inspecteur et le
menu Montage."""

from __future__ import annotations

from PySide6.QtWidgets import QMenu

from remanence.effets import EFFETS, FAMILLES


def remplir_menu_effets(menu: QMenu, choisir):
    """choisir(cle, prereglage) ; prereglage None : valeurs par défaut."""
    for famille in FAMILLES:
        descriptions = sorted((d for d in EFFETS.values() if d.famille == famille),
                              key=lambda d: d.nom)
        if not descriptions:
            continue
        sous = menu.addMenu(famille)
        for d in descriptions:
            m = sous.addMenu(d.nom)
            m.addAction("Par défaut", lambda d=d: choisir(d.cle, None))
            m.addSeparator()
            for nom in d.prereglages:
                m.addAction(nom, lambda d=d, nom=nom: choisir(d.cle, nom))
