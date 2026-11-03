"""Menu des effets par famille, puis préréglage, et les préréglages personnels ; partagé par la
timeline, l'inspecteur et le menu Montage."""

from __future__ import annotations

from PySide6.QtWidgets import QMenu

from remanence.effets import EFFETS, FAMILLES, nouvel_effet
from remanence.effets import prereglages as prereglages_


def remplir_menu_effets(menu: QMenu, appliquer):
    """appliquer(effets) reçoit une liste d'effets neufs (plusieurs pour une pile)."""
    for famille in FAMILLES:
        descriptions = sorted((d for d in EFFETS.values() if d.famille == famille),
                              key=lambda d: d.nom)
        if not descriptions:
            continue
        sous = menu.addMenu(famille)
        # Deux niveaux seulement : les préréglages sont dans la bibliothèque d'effets.
        for d in descriptions:
            sous.addAction(d.nom, lambda d=d: appliquer([nouvel_effet(d.cle)]))
    perso = prereglages_.personnels()
    if perso:
        menu.addSeparator()
        sous = menu.addMenu(prereglages_.FAMILLE_PERSONNELS)
        for p in perso:
            sous.addAction(p.nom, lambda p=p: appliquer(p.nouveaux_effets()))
