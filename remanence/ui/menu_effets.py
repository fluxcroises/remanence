"""Menu des effets par famille, puis préréglage, et les préréglages personnels ; partagé par la
timeline, l'inspecteur et le menu Montage."""

from __future__ import annotations

from PySide6.QtWidgets import QMenu

from remanence.effets import EFFETS, FAMILLES, FAMILLES_SON, nouvel_effet
from remanence.effets import prereglages as prereglages_


def remplir_menu_effets(menu: QMenu, appliquer, son: bool = False):
    """appliquer(effets) reçoit une liste d'effets neufs (plusieurs pour une pile). son : les
    effets audio (clips et pistes audio), sinon les effets vidéo."""
    for famille in (FAMILLES_SON if son else FAMILLES):
        descriptions = sorted((d for d in EFFETS.values() if d.famille == famille),
                              key=lambda d: d.nom)
        if not descriptions:
            continue
        sous = menu.addMenu(famille)
        # Deux niveaux seulement : les préréglages sont dans la bibliothèque d'effets.
        for d in descriptions:
            sous.addAction(d.nom, lambda d=d: appliquer([nouvel_effet(d.cle)]))
    # Préréglages personnels : ceux dont les effets vont sur ce genre de porteur.
    perso = [p for p in prereglages_.personnels()
             if all(e["type"] in EFFETS and EFFETS[e["type"]].audio == son for e in p.effets)]
    if perso:
        menu.addSeparator()
        sous = menu.addMenu(prereglages_.FAMILLE_PERSONNELS)
        for p in perso:
            sous.addAction(p.nom, lambda p=p: appliquer(p.nouveaux_effets()))
