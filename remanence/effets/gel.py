"""Gel : un instant du son tenu, comme une image figée.

Toutes les « intervalle » secondes (depuis le début du clip), une période tirée (probabilité)
finit par un gel : pendant « durée », le grain de son qui la précède est rejoué en boucle, avec
un fondu sur ses bords pour qu'il chante au lieu de claquer."""

import numpy as np

from remanence.effets import DescriptionEffet, Parametre
from remanence.rendu.son import echantillons, hasard, lire_positions


def son(lire, valeurs, graine, frequence):
    periode = echantillons(valeurs.get("intervalle", 3) * 1000)
    duree = min(periode, echantillons(valeurs.get("duree", 400)))
    grain = max(8, echantillons(valeurs.get("grain", 40)))
    probabilite = valeurs.get("probabilite", 100) / 100
    fondu = max(1, grain // 8)

    def lecteur(debut: int, n: int) -> np.ndarray:
        p = np.arange(debut, debut + n)
        k = p // periode
        depart = k * periode + (periode - duree)  # début du gel dans la période
        x = p - depart
        tires = {int(i): hasard(graine, int(i)) < probabilite for i in np.unique(k)}
        gele = (x >= 0) & np.array([tires[int(i)] for i in k])
        o = np.where(gele, x % grain, 0)
        source = np.where(gele, depart - grain + o, p)
        sortie = lire_positions(lire, source.astype(np.float64))
        # Fondu aux bords du grain, seulement pendant le gel.
        bord = np.minimum(o, grain - 1 - o)
        gain = np.where(gele, np.clip((bord + 1) / fondu, 0, 1), 1).astype(np.float32)
        return sortie * gain[:, None]
    return lecteur


DESCRIPTION = DescriptionEffet(
    cle="gel", nom="Gel", famille="Son", moteur="audio", neutre=lambda v: v.get("probabilite", 100) <= 0, son=son,
    prereglages={"Note tenue": {"intervalle": 3, "duree": 800, "grain": 60},
                 "Glace fine": {"intervalle": 1, "duree": 300, "grain": 20},
                 "Bourdon": {"intervalle": 4, "duree": 2500, "grain": 120}},
    parametres=[Parametre("intervalle", "Intervalle", 0.2, 10, 3, "s", 1),
                Parametre("duree", "Durée", 20, 5000, 400, "ms"),
                Parametre("grain", "Grain", 5, 300, 40, "ms"),
                Parametre("probabilite", "Probabilité", 0, 100, 100, "%")],
)
