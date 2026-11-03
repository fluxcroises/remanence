"""Slit-scan : chaque ligne de l'image vient d'un instant différent, de plus en plus ancien en
descendant (ou en allant vers la droite). Un mouvement s'étire et se tord dans le temps.

Calculé à part et gardé en cache, comme le flux optique : il lui faut les images passées. Une
image passée ne garde que les lignes qu'on lui demandera encore ; avec 60 images de retard au
plus, le tampon pèse une trentaine d'images. Le sens (lignes ou colonnes) est celui du début du
clip.
"""

from collections.abc import Iterable, Iterator

import numpy as np

from remanence.effets import DescriptionEffet, Parametre

PROFONDEUR_MAX = 60


def slit_scan(images: Iterable[np.ndarray], valeurs: list[dict]) -> Iterator[np.ndarray]:
    n = len(valeurs)
    profondeurs = [max(0, min(PROFONDEUR_MAX, int(round(v["profondeur"])))) for v in valeurs]
    vertical = valeurs[0]["vertical"] > 0.5 if valeurs else False
    passe: list[tuple[np.ndarray, np.ndarray]] = []  # (lignes gardées, leurs pixels), récent d'abord
    besoin = None
    for t, rvb in enumerate(images):
        v = valeurs[min(t, n - 1)]
        prof = profondeurs[min(t, n - 1)]
        lignes = np.swapaxes(rvb, 0, 1) if vertical else rvb
        total = lignes.shape[0]
        position = np.arange(total) / max(1, total - 1)
        if besoin is None:
            # Le plus long retard que chaque ligne demandera, sur tout le clip.
            besoin = np.zeros(total, int)
            for vv, pp in zip(valeurs, profondeurs):
                q = 1.0 - position if vv["inverser"] > 0.5 else position
                besoin = np.maximum(besoin, np.round(q * pp).astype(int))
        q = 1.0 - position if v["inverser"] > 0.5 else position
        # Au début du clip, les lignes trop anciennes prennent la première image.
        retard = np.minimum(np.round(q * prof).astype(int), len(passe))
        sortie = lignes.copy()
        for age in np.unique(retard):
            if age == 0:
                continue
            choix = np.nonzero(retard == age)[0]
            gardees, pixels = passe[age - 1]
            sortie[choix] = pixels[np.searchsorted(gardees, choix)].astype(np.float32)
        passe.insert(0, (np.arange(total), lignes.astype(np.float16)))
        vieilli = []
        for age, (gardees, pixels) in enumerate(passe, 1):
            utiles = besoin[gardees] >= age
            if not utiles.any():
                break  # plus aucune ligne ne remontera aussi loin
            vieilli.append((gardees, pixels) if utiles.all()
                           else (gardees[utiles], pixels[utiles]))
        passe = vieilli
        yield np.ascontiguousarray(np.swapaxes(sortie, 0, 1)) if vertical else sortie


DESCRIPTION = DescriptionEffet(
    cle="slit_scan",
    nom="Slit-scan",
    famille="Pixels",
    moteur="flux",
    flux=slit_scan,
    parametres=[Parametre("profondeur", "Profondeur", 0, PROFONDEUR_MAX, 24, "images"),
                Parametre("inverser", "Inverser", 0, 1, 0, booleen=True),
                Parametre("vertical", "Vertical", 0, 1, 0, booleen=True)],
    prereglages={"Temps qui coule": {"profondeur": 24},
                 "Rideau vertical": {"profondeur": 30, "vertical": 1},
                 "Grande torsion": {"profondeur": 60, "inverser": 1}},
)
