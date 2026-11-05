"""Effets audio : une chaîne de lecteurs.

Un lecteur rend les échantillons stéréo d'une plage quelconque : `lire(début, n)` -> (n, 2)
float32, positions comptées depuis le début du porteur (le clip, ou la séquence pour un effet
de piste), zéro en dehors. Chaque effet audio (`DescriptionEffet.son`) reçoit le lecteur de
l'étape précédente et rend un nouveau lecteur. Un effet calcule le son d'une position à partir
de cette position seulement (pas de mémoire de ce qu'il a joué juste avant) : la lecture depuis
le milieu, l'export par blocs et deux exports successifs donnent les mêmes échantillons.

Chaque image du porteur est calculée avec ses propres réglages (images clés et modulateurs
compris), quelle que soit la taille des blocs lus ; l'opacité de l'effet devient son mélange
avec le son reçu.
"""

from __future__ import annotations

from typing import Callable

import numpy as np

from remanence.effets import EFFETS

Lecteur = Callable[[int, int], np.ndarray]

FREQUENCE = 48000


def borne(lire: Lecteur, longueur: int) -> Lecteur:
    """Le lecteur, muet en dehors de [0, longueur) : un effet qui lit avant le début ou après
    la fin du clip n'entend pas le reste du média."""
    def lecteur(debut: int, n: int) -> np.ndarray:
        sortie = np.zeros((n, 2), np.float32)
        a, b = max(0, debut), min(longueur, debut + n)
        if b > a:
            sortie[a - debut:b - debut] = lire(a, b - a)
        return sortie
    return lecteur


def chaine(lire: Lecteur, effets_a: Callable[[int], list], par_image: float) -> Lecteur:
    """Le lecteur après les effets audio. effets_a(image) : les effets actifs, figés à cette
    image du porteur (`composition.actifs`), dans l'ordre."""
    def image(f: int, a: int, m: int) -> np.ndarray:
        courant = lire
        for e in effets_a(f):
            d = EFFETS.get(e.type)
            if d is None or not d.audio or not e.actif:
                continue
            courant = _avec_melange(courant, d.son(courant, e.params, e.graine, FREQUENCE),
                                    e.opacite)
        return courant(a, m)

    def lecteur(debut: int, n: int) -> np.ndarray:
        # Le bloc, coupé aux limites des images : chacune avec ses réglages.
        sortie = np.empty((n, 2), np.float32)
        position, fin = debut, debut + n
        while position < fin:
            # L'image de l'échantillon p est floor(p / par_image) : la suivante commence au
            # premier échantillon p ≥ (f + 1) × par_image.
            f = int(np.floor(max(0, position) / par_image))
            suivante = int(np.ceil((f + 1) * par_image))
            b = min(fin, suivante) if position >= 0 else min(fin, 0)
            sortie[position - debut:b - debut] = image(f, position, b - position)
            position = b
        return sortie
    return lecteur


def _avec_melange(sec: Lecteur, mouille: Lecteur, dosage: float) -> Lecteur:
    if dosage >= 1.0:
        return mouille
    if dosage <= 0.0:
        return sec

    def lecteur(debut: int, n: int) -> np.ndarray:
        return sec(debut, n) * (1.0 - dosage) + mouille(debut, n) * dosage
    return lecteur


# Outils des effets

def hasard(graine: int, *cles: int) -> float:
    """Nombre au hasard dans [0, 1[, fixé par la graine de l'effet et les clés (numéro de
    fenêtre…) : le même tirage à chaque lecture."""
    return float(np.random.default_rng([graine & 0xFFFFFFFF, *[k & 0xFFFFFFFF for k in cles]])
                 .random())


def lire_positions(lire: Lecteur, positions: np.ndarray) -> np.ndarray:
    """Les échantillons aux positions données (entières ou non : interpolation linéaire),
    lus en une fois sur la plage qui les couvre."""
    bas = int(np.floor(positions.min()))
    haut = int(np.ceil(positions.max())) + 1
    brut = lire(bas, haut - bas + 1)
    x = positions - bas
    i = np.floor(x).astype(np.int64)
    t = (x - i).astype(np.float32)[:, None]
    i = np.clip(i, 0, len(brut) - 2) if len(brut) > 1 else np.zeros_like(i)
    if len(brut) == 1:
        return np.repeat(brut, len(positions), axis=0)
    return (brut[i] * (1 - t) + brut[i + 1] * t).astype(np.float32)


def echantillons(ms: float) -> int:
    return max(1, int(round(ms * FREQUENCE / 1000)))
