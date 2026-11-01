"""Masques : formes par défaut, et contour d'une forme libre pour le programme de la carte
graphique.

La forme libre passe par chacun de ses points (courbe de Catmull-Rom fermée, c'est-à-dire une
suite de courbes de Bézier dont les poignées se déduisent des points voisins) : on déplace des
points, sans poignées à régler.
"""

from __future__ import annotations

import math

import numpy as np

from remanence.projet.modele import Masque, nouvel_id

# Nombre maximal de sommets du contour envoyé à la carte graphique.
SOMMETS_MAX = 128
NOMS_FORMES = {"rectangle": "Rectangle", "ellipse": "Ellipse", "courbe": "Forme libre"}


def nouveau_masque(forme: str) -> Masque:
    """Forme centrée, de la moitié de l'image."""
    if forme == "courbe":
        points = [[0.5 + 0.25 * math.cos(a), 0.5 + 0.25 * math.sin(a)]
                  for a in (2 * math.pi * k / 5 - math.pi / 2 for k in range(5))]
    else:
        points = [[0.25, 0.25], [0.75, 0.75]]
    return Masque(nouvel_id(), forme, points)


def contour(points: list, pas: int | None = None) -> np.ndarray:
    """Sommets de la courbe fermée qui passe par les points (N×2, mêmes coordonnées)."""
    p = np.asarray(points, dtype=np.float64)
    n = len(p)
    if n < 3:
        return p.astype(np.float32)
    pas = pas or max(2, SOMMETS_MAX // n)
    t = np.arange(pas, dtype=np.float64)[:, None] / pas
    resultat = []
    for i in range(n):
        p0, p1, p2, p3 = p[(i - 1) % n], p[i], p[(i + 1) % n], p[(i + 2) % n]
        # Catmull-Rom uniforme entre p1 et p2.
        resultat.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t ** 2
                               + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    return np.concatenate(resultat).astype(np.float32)[:SOMMETS_MAX]
