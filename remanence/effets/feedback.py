"""Feedback : l'image rendue juste avant revient sous l'image, un peu agrandie, tournée,
décalée ou teintée, comme une caméra filmant son propre écran. Les retours successifs creusent
des tunnels et des spirales.

Calculé à part et gardé en cache, comme le flux optique : chaque image dépend de la
précédente. Zoom et décalage se mesurent en part de l'image.
"""

import math
from collections.abc import Iterable, Iterator

import cv2
import numpy as np

from remanence.effets import DescriptionEffet, Parametre


def _teinte(degres: float) -> np.ndarray:
    """Rotation des couleurs autour de l'axe des gris (formule de Rodrigues)."""
    a = math.radians(degres)
    c, s = math.cos(a), math.sin(a)
    k = 1.0 / math.sqrt(3.0)
    u = np.array([[0, -k, k], [k, 0, -k], [-k, k, 0]], np.float32)
    return (np.eye(3, dtype=np.float32) * c + u * s
            + np.full((3, 3), k * k, np.float32) * (1 - c)).astype(np.float32)


def feedback(images: Iterable[np.ndarray], valeurs: list[dict]) -> Iterator[np.ndarray]:
    n = len(valeurs)
    trace = None
    for t, rvb in enumerate(images):
        v = valeurs[min(t, n - 1)]
        retour = v["retour"] / 100
        if trace is None or retour <= 0:
            trace = rvb
            yield rvb
            continue
        h, w = rvb.shape[:2]
        m = cv2.getRotationMatrix2D((w / 2, h / 2), v["rotation"], 1 + v["zoom"] / 100)
        m[0, 2] += v["decalage_x"] / 100 * w
        m[1, 2] += v["decalage_y"] / 100 * h
        reprise = cv2.warpAffine(trace, m, (w, h), flags=cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        if v["teinte"]:
            reprise = reprise @ _teinte(v["teinte"]).T
        if v["eclaircir"] > 0.5:
            trace = np.maximum(rvb, reprise * retour)
        else:
            trace = rvb * (1 - retour) + reprise * retour
        yield trace


DESCRIPTION = DescriptionEffet(
    cle="feedback",
    nom="Feedback",
    famille="Signal",
    moteur="flux",
    flux=feedback,
    parametres=[Parametre("retour", "Retour", 0, 98, 70, "%"),
                Parametre("zoom", "Zoom", -20, 20, 3, "%", 1),
                Parametre("rotation", "Rotation", -10, 10, 0, "°", 1),
                Parametre("decalage_x", "Décalage X", -10, 10, 0, "%", 1),
                Parametre("decalage_y", "Décalage Y", -10, 10, 0, "%", 1),
                Parametre("teinte", "Teinte", -60, 60, 0, "°"),
                Parametre("eclaircir", "Éclaircir", 0, 1, 0, booleen=True)],
    prereglages={"Tunnel": {"retour": 85, "zoom": -4},
                 "Spirale": {"retour": 80, "zoom": 2, "rotation": 3},
                 "Écho psychédélique": {"retour": 88, "zoom": 1.5, "teinte": 20,
                                        "eclaircir": 1}},
)
