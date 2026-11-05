"""Bégaiement : un petit fragment se répète, comme un disque rayé ou un sampler qu'on martèle.

Le son est découpé en fenêtres de « fragment × répétitions », comptées depuis le début du
clip ; dans une fenêtre tirée (probabilité), le premier fragment est rejoué jusqu'à la fin de
la fenêtre, sinon le son passe."""

import numpy as np

from remanence.effets import DescriptionEffet, Parametre
from remanence.rendu.son import echantillons, hasard, lire_positions


def son(lire, valeurs, graine, frequence):
    fragment = echantillons(valeurs.get("fragment", 80))
    fenetre = fragment * max(1, int(round(valeurs.get("repetitions", 4))))
    probabilite = valeurs.get("probabilite", 100) / 100

    def lecteur(debut: int, n: int) -> np.ndarray:
        p = np.arange(debut, debut + n)
        k = p // fenetre
        tires = {int(i): hasard(graine, int(i)) < probabilite for i in np.unique(k)}
        repete = np.array([tires[int(i)] for i in k])
        source = np.where(repete, k * fenetre + (p - k * fenetre) % fragment, p)
        return lire_positions(lire, source.astype(np.float64))
    return lecteur


DESCRIPTION = DescriptionEffet(
    cle="begaiement", nom="Bégaiement", famille="Son", moteur="audio", neutre=lambda v: v.get("probabilite", 100) <= 0 or v.get("repetitions", 4) <= 1, son=son,
    prereglages={"Disque rayé": {"fragment": 60, "repetitions": 6, "probabilite": 100},
                 "Sampler nerveux": {"fragment": 30, "repetitions": 8, "probabilite": 50},
                 "Hoquet": {"fragment": 200, "repetitions": 2, "probabilite": 70}},
    parametres=[Parametre("fragment", "Fragment", 5, 1000, 80, "ms"),
                Parametre("repetitions", "Répétitions", 1, 32, 4),
                Parametre("probabilite", "Probabilité", 0, 100, 100, "%")],
)
