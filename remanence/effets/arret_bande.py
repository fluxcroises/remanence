"""Arrêt de bande : le son ralentit et descend jusqu'à s'arrêter, comme une cassette freinée.

Toutes les « intervalle » secondes (depuis le début du clip), une période tirée (probabilité)
finit par un freinage de « durée » : la vitesse passe de 1 à 0 (la hauteur descend avec
elle) ; le son repart net à la période suivante."""

import numpy as np

from remanence.effets import DescriptionEffet, Parametre
from remanence.rendu.son import echantillons, hasard, lire_positions


def son(lire, valeurs, graine, frequence):
    periode = echantillons(valeurs.get("intervalle", 2) * 1000)
    duree = min(periode, echantillons(valeurs.get("duree", 600)))
    probabilite = valeurs.get("probabilite", 100) / 100
    courbe = max(0.2, valeurs.get("courbe", 1.0))

    def lecteur(debut: int, n: int) -> np.ndarray:
        p = np.arange(debut, debut + n)
        k = p // periode
        depart = k * periode + (periode - duree)
        x = (p - depart).astype(np.float64)
        tires = {int(i): hasard(graine, int(i)) < probabilite for i in np.unique(k)}
        freine = (x >= 0) & np.array([tires[int(i)] for i in k])
        # Vitesse v(u) = (1 - u)^courbe, u = x / durée ; position = intégrale de la vitesse.
        u = np.clip(x / duree, 0, 1)
        parcouru = duree * (1 - (1 - u) ** (courbe + 1)) / (courbe + 1)
        source = np.where(freine, depart + parcouru, p)
        sortie = lire_positions(lire, source)
        # Les dernières millisecondes s'éteignent (la bande est arrêtée).
        gain = np.where(freine, np.clip((1 - u) * 20, 0, 1), 1).astype(np.float32)
        return sortie * gain[:, None]
    return lecteur


DESCRIPTION = DescriptionEffet(
    cle="arret_bande", nom="Arrêt de bande", famille="Son", moteur="audio", son=son,
    parametres=[Parametre("intervalle", "Intervalle", 0.2, 10, 2, "s", 1),
                Parametre("duree", "Durée", 50, 5000, 600, "ms"),
                Parametre("courbe", "Courbe", 0.2, 4, 1, "", 1),
                Parametre("probabilite", "Probabilité", 0, 100, 100, "%")],
)
