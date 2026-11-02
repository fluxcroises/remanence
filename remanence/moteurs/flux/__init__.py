"""Moteur flux optique : le datamosh simulé, entièrement maîtrisé.

Le mouvement est mesuré entre deux images successives du clip (flux optique DIS d'OpenCV,
sur une version grise réduite), puis les pixels d'une image de référence sont déplacés avec
lui, image après image. Tout se fait en flottants 32 bits (le cache final est en 16 bits) :
aucune perte de qualité, contrairement au moteur codec.

Les images entrent et sortent en tableaux RVB float32 de 0 à 1 (H × L × 3). Le flux mesuré
est le même d'une fois sur l'autre : même projet, même rendu.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Iterable, Iterator

import cv2
import numpy as np

# Le flux est mesuré sur une image d'au plus cette largeur, puis remis à l'échelle.
LARGEUR_MESURE = 960


class Mesure:
    """Flux optique d'une image à la précédente, en pixels de l'image d'origine. Pour chaque
    pixel de l'image courante : d'où il vient dans l'image précédente."""

    def __init__(self):
        self._dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
        self._precedente: np.ndarray | None = None
        self._echelle = 1.0

    def _gris(self, rvb: np.ndarray) -> np.ndarray:
        h, l = rvb.shape[:2]
        self._echelle = min(1.0, LARGEUR_MESURE / l)
        gris = cv2.cvtColor(np.clip(rvb * 255, 0, 255).astype(np.uint8), cv2.COLOR_RGB2GRAY)
        if self._echelle < 1.0:
            gris = cv2.resize(gris, (round(l * self._echelle), round(h * self._echelle)),
                              interpolation=cv2.INTER_AREA)
        return gris

    def suivante(self, rvb: np.ndarray) -> np.ndarray | None:
        """Le flux de cette image vers la précédente (H × L × 2) ; None pour la première."""
        gris = self._gris(rvb)
        precedente, self._precedente = self._precedente, gris
        if precedente is None:
            return None
        flux = self._dis.calc(gris, precedente, None)
        h, l = rvb.shape[:2]
        if self._echelle < 1.0:
            flux = cv2.resize(flux, (l, h), interpolation=cv2.INTER_LINEAR) / self._echelle
        return flux


def lisser(flux: np.ndarray, lissage: float) -> np.ndarray:
    """Flou du champ de mouvement ; lissage en % de la largeur de l'image."""
    if lissage <= 0:
        return flux
    sigma = lissage / 100 * flux.shape[1] / 4
    return cv2.GaussianBlur(flux, (0, 0), sigma)


@lru_cache(maxsize=4)
def _grille(h: int, l: int) -> tuple[np.ndarray, np.ndarray]:
    return np.meshgrid(np.arange(l, dtype=np.float32), np.arange(h, dtype=np.float32))


def deplacer(image: np.ndarray, flux: np.ndarray, force: float) -> np.ndarray:
    """Chaque pixel prend la valeur de l'endroit d'où il vient (force 1 : le mouvement réel ;
    2 : deux fois plus loin ; négatif : à rebours)."""
    grille_x, grille_y = _grille(*image.shape[:2])
    carte_x = grille_x + flux[..., 0] * force
    carte_y = grille_y + flux[..., 1] * force
    return cv2.remap(image, carte_x, carte_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def bavure(images: Iterable[np.ndarray], valeurs: list[dict]) -> Iterator[np.ndarray]:
    """Bavure par flux optique. Jusqu'à l'image de départ, l'image du clip ; ensuite, l'image
    de départ suit le mouvement du clip, et le rafraîchissement y remêle un peu de l'image
    réelle à chaque pas (0 : la référence seule, à l'infini)."""
    mesure = Mesure()
    reference = None
    n = len(valeurs)
    for t, rvb in enumerate(images):
        v = valeurs[min(t, n - 1)]
        flux = mesure.suivante(rvb)
        depart = round(v["depart"] / 100 * max(0, n - 1))
        if t <= depart or flux is None or reference is None:
            reference = rvb if t <= depart or reference is None else reference
            yield rvb
            continue
        reference = deplacer(reference, lisser(flux, v["lissage"]), v["force"] / 100)
        rafraichi = v["rafraichissement"] / 100
        if rafraichi > 0:
            reference = reference * (1 - rafraichi) + rvb * rafraichi
        yield reference


def persistance(images: Iterable[np.ndarray], valeurs: list[dict]) -> Iterator[np.ndarray]:
    """Traînées : l'image rendue juste avant suit le mouvement et reste, effacée peu à peu,
    sous l'image réelle. « Éclaircir » ne garde que ce qui est plus clair que l'image réelle
    (des traînées lumineuses)."""
    mesure = Mesure()
    trace = None
    n = len(valeurs)
    for t, rvb in enumerate(images):
        v = valeurs[min(t, n - 1)]
        flux = mesure.suivante(rvb)
        if trace is None or flux is None:
            trace = rvb
            yield rvb
            continue
        trace = deplacer(trace, lisser(flux, v["lissage"]), v["force"] / 100)
        garde = v["persistance"] / 100
        if v["eclaircir"] > 0.5:
            trace = np.maximum(rvb, trace * garde + rvb * (1 - garde))
        else:
            trace = trace * garde + rvb * (1 - garde)
        yield trace
