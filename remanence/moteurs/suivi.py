"""Suivi automatique d'un masque : le suiveur CSRT d'OpenCV accompagne la zone du masque
image après image, et chaque position devient une image clé de sa forme.

Le suivi regarde l'image de la séquence sans aucun effet ni datamosh (une copie du projet
nettoyée) : un glitch ne doit pas perdre le suiveur. La zone suivie est le rectangle qui
entoure le masque ; le masque garde sa forme et suit le déplacement et le changement de taille
de ce rectangle.
"""

from __future__ import annotations

import copy
import threading

import cv2
import numpy as np

from remanence.projet.modele import Masque, Projet, Sequence

# Largeur de l'image donnée au suiveur : assez pour suivre, sans ralentir.
LARGEUR_SUIVI = 640


def _sans_effets(projet: Projet) -> Projet:
    copie = copy.deepcopy(projet)
    for seq in copie.sequences:
        seq.effets = []
        seq.modulateurs = []
        for piste in seq.pistes:
            piste.effets = []
            for c in piste.clips:
                c.effets = []
                c.transition = None
                c.cles_supprimees = []
            # Les clips d'effet ne montrent rien sans leurs effets.
            piste.clips = [c for c in piste.clips if not c.est_effet]
    return copie


def boite(points: list) -> tuple[float, float, float, float]:
    """(x0, y0, x1, y1) du rectangle qui entoure les points (coordonnées de 0 à 1)."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def transformer(points: list, depart, arrivee) -> list:
    """Les points du masque, du rectangle de départ à celui d'arrivée (déplacement et
    échelle autour du centre)."""
    (a0, b0, a1, b1), (c0, d0, c1, d1) = depart, arrivee
    sx = (c1 - c0) / (a1 - a0) if a1 > a0 else 1.0
    sy = (d1 - d0) / (b1 - b0) if b1 > b0 else 1.0
    return [[c0 + (x - a0) * sx, d0 + (y - b0) * sy] for x, y in points]


def suivre(projet: Projet, seq: Sequence, masque: Masque, debut: int, fin: int,
           progression=None, annule: threading.Event | None = None) -> tuple[dict, int | None]:
    """Suit la zone du masque de l'image `debut` à l'image `fin` de la séquence (incluses ;
    fin < debut : à rebours). Renvoie ({image de la séquence: points du masque}, image où le
    sujet a été perdu ou None)."""
    from remanence.rendu.composition import Compositeur

    nettoye = _sans_effets(projet)
    seq_n = next(s for s in nettoye.sequences if s.id == seq.id)
    echelle = min(1.0, LARGEUR_SUIVI / seq.largeur)
    compositeur = Compositeur(nettoye, apercu=True)
    sens = 1 if fin >= debut else -1
    images = list(range(debut, fin + sens, sens))
    resultats: dict[int, list] = {debut: copy.deepcopy(masque.points)}
    perdu = None
    try:
        def image(f: int) -> np.ndarray:
            rvba = compositeur.image(seq_n, f, echelle).astype(np.float32)
            rvb = np.clip(rvba[..., :3] * 255 + 0.5, 0, 255).astype(np.uint8)
            return cv2.cvtColor(np.ascontiguousarray(rvb), cv2.COLOR_RGB2BGR)

        premiere = image(debut)
        h, l = premiere.shape[:2]
        x0, y0, x1, y1 = boite(masque.points)
        rect = (int(round(x0 * l)), int(round(y0 * h)),
                max(4, int(round((x1 - x0) * l))), max(4, int(round((y1 - y0) * h))))
        suiveur = cv2.TrackerCSRT_create()
        suiveur.init(premiere, rect)
        depart = (x0, y0, x1, y1)
        for k, f in enumerate(images[1:], 1):
            if annule is not None and annule.is_set():
                raise InterruptedError
            ok, (rx, ry, rl, rh) = suiveur.update(image(f))
            if not ok or rl <= 0 or rh <= 0:
                perdu = f
                break
            arrivee = (rx / l, ry / h, (rx + rl) / l, (ry + rh) / h)
            resultats[f] = transformer(masque.points, depart, arrivee)
            if progression:
                progression(k / max(1, len(images) - 1))
    finally:
        compositeur.fermer()
    return resultats, perdu
