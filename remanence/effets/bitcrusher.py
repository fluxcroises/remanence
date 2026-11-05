"""Bitcrusher : moins de bits et moins d'échantillons, le son devient granuleux."""

import numpy as np

from remanence.effets import DescriptionEffet, Parametre


def son(lire, valeurs, graine, frequence):
    bits = int(round(valeurs.get("bits", 16)))
    reduction = max(1, int(round(valeurs.get("reduction", 1))))
    pas = 2.0 ** (bits - 1)

    def lecteur(debut: int, n: int) -> np.ndarray:
        if reduction > 1:
            # Échantillon tenu : aligné sur les positions absolues (même son lu par blocs).
            positions = (np.arange(debut, debut + n) // reduction) * reduction
            a = int(positions[0])
            brut = lire(a, int(positions[-1]) - a + 1)
            x = brut[positions - a]
        else:
            x = lire(debut, n)
        if bits < 16:
            x = np.round(x * pas) / pas
        return x.astype(np.float32)
    return lecteur


DESCRIPTION = DescriptionEffet(
    cle="bitcrusher",
    nom="Bitcrusher",
    famille="Son",
    moteur="audio",
    son=son,
    parametres=[Parametre("bits", "Bits", 1, 16, 6),
                Parametre("reduction", "Réduction", 1, 64, 8, "×")],
)
