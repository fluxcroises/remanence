"""LUT d'affichage : un fichier .cube (format Adobe / Resolve) appliqué aux moniteurs seulement,
pour regarder des rushs en log. Le rendu et l'export ne la voient jamais.

La visionneuse l'applique sur la carte graphique (texture 3D, interpolation trilinéaire) ;
`appliquer` fait le même calcul sur le processeur, sans OpenGL.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class Lut:
    nom: str
    taille: int
    table: np.ndarray  # taille³ × 3 float32, le rouge varie le plus vite (ordre du fichier)
    minimum: tuple[float, float, float] = (0.0, 0.0, 0.0)
    maximum: tuple[float, float, float] = (1.0, 1.0, 1.0)

    @property
    def cube(self) -> np.ndarray:
        """La table rangée [bleu, vert, rouge, canal]."""
        n = self.taille
        return self.table.reshape(n, n, n, 3)


def lire_cube(chemin: Path) -> Lut:
    chemin = Path(chemin)
    taille, nom = None, chemin.stem
    minimum, maximum = (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)
    valeurs = []
    for ligne in chemin.read_text(encoding="utf-8", errors="replace").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#"):
            continue
        mots = ligne.split()
        cle = mots[0].upper()
        if cle == "TITLE":
            nom = ligne[5:].strip().strip('"') or nom
        elif cle == "LUT_3D_SIZE":
            taille = int(mots[1])
        elif cle == "LUT_1D_SIZE":
            raise ValueError("LUT 1D non prise en charge : il faut une LUT 3D.")
        elif cle == "DOMAIN_MIN":
            minimum = tuple(float(x) for x in mots[1:4])
        elif cle == "DOMAIN_MAX":
            maximum = tuple(float(x) for x in mots[1:4])
        elif cle[0].isdigit() or cle[0] in "-.":
            valeurs.append([float(x) for x in mots[:3]])
    if taille is None or len(valeurs) != taille ** 3:
        raise ValueError("Fichier .cube illisible.")
    return Lut(nom, taille, np.asarray(valeurs, np.float32), minimum, maximum)


def appliquer(rgb: np.ndarray, lut: Lut) -> np.ndarray:
    """La LUT sur une image H × L × 3 (flottants de 0 à 1), interpolation trilinéaire."""
    n = lut.taille
    lo, hi = np.array(lut.minimum, np.float32), np.array(lut.maximum, np.float32)
    x = np.clip((rgb.astype(np.float32) - lo) / np.maximum(hi - lo, 1e-6), 0.0, 1.0) * (n - 1)
    i0 = np.minimum(np.floor(x).astype(np.int32), n - 2) if n > 1 else np.zeros_like(x, np.int32)
    t = x - i0
    c = lut.cube
    r0, g0, b0 = i0[..., 0], i0[..., 1], i0[..., 2]
    tr, tg, tb = t[..., 0:1], t[..., 1:2], t[..., 2:3]
    sortie = np.zeros(rgb.shape[:2] + (3,), np.float32)
    for db, pb in ((0, 1 - tb), (1, tb)):
        for dg, pg in ((0, 1 - tg), (1, tg)):
            for dr, pr in ((0, 1 - tr), (1, tr)):
                sortie += c[b0 + db, g0 + dg, r0 + dr] * (pb * pg * pr)
    return sortie
