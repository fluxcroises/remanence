"""Inversion par fragments : des morceaux du son, tirés au hasard, joués à l'envers."""

import numpy as np

from remanence.effets import DescriptionEffet, Parametre
from remanence.rendu.son import echantillons, hasard, lire_positions


def son(lire, valeurs, graine, frequence):
    fragment = echantillons(valeurs.get("fragment", 150))
    probabilite = valeurs.get("probabilite", 50) / 100

    def lecteur(debut: int, n: int) -> np.ndarray:
        p = np.arange(debut, debut + n)
        k = p // fragment
        tires = {int(i): hasard(graine, int(i)) < probabilite for i in np.unique(k)}
        inverse = np.array([tires[int(i)] for i in k])
        source = np.where(inverse, k * fragment + (fragment - 1 - (p - k * fragment)), p)
        return lire_positions(lire, source.astype(np.float64))
    return lecteur


DESCRIPTION = DescriptionEffet(
    cle="inversion_fragments", nom="Inversion par fragments", famille="Son", moteur="audio",
    son=son,
    parametres=[Parametre("fragment", "Fragment", 10, 2000, 150, "ms"),
                Parametre("probabilite", "Probabilité", 0, 100, 50, "%")],
)
