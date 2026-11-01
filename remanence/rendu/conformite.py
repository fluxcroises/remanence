"""Vérification d'un fichier exporté : il doit pouvoir remplacer la source sans recalage."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

import numpy as np

from remanence.media import timecode as tcmod
from remanence.media.sonde import InfosMedia, ouvrir_conteneur


@dataclass
class Verification:
    critere: str
    attendu: str
    obtenu: str
    ok: bool


def verifier(sortie: InfosMedia, attendu: dict) -> list[Verification]:
    v = sortie.video
    if v is None:
        return [Verification("Vidéo", "présente", "absente", False)]
    cad = attendu["cadence"]
    tc_att = (tcmod.images_vers_tc(attendu["tc_debut"], cad) if attendu["tc_debut"] is not None
              else "absent")
    tc_obt = tcmod.images_vers_tc(v.tc_debut, cad) if v.tc_debut is not None else "absent"
    c_att, c_obt = attendu["couleur"], v.couleur
    return [
        Verification("Durée en images", str(attendu["nb_images"]), str(v.nb_images),
                     v.nb_images == attendu["nb_images"]),
        Verification("Cadence", str(cad), v.cadence, Fraction(v.cadence) == cad),
        Verification("Résolution", f"{attendu['largeur']} × {attendu['hauteur']}",
                     f"{v.largeur} × {v.hauteur}",
                     (v.largeur, v.hauteur) == (attendu["largeur"], attendu["hauteur"])),
        Verification("Rapport de pixel", attendu["rapport_pixel"], v.rapport_pixel,
                     v.rapport_pixel == attendu["rapport_pixel"]),
        Verification("Timecode de départ", tc_att, tc_obt, v.tc_debut == attendu["tc_debut"]),
        Verification("Métadonnées couleur", c_att.decrire(), c_obt.decrire(),
                     (c_att.primaires, c_att.transfert, c_att.matrice) ==
                     (c_obt.primaires, c_obt.transfert, c_obt.matrice)
                     and (c_att.plage or 1) == (c_obt.plage or 1)),
    ]


def empreintes_images(chemin: str, sequence_images: dict | None = None) -> list[bytes]:
    """Contenu décodé de chaque image (tous les plans), pour comparer deux fichiers au pixel près."""
    sortie = []
    with ouvrir_conteneur(chemin, sequence_images) as c:
        v = c.streams.video[0]
        for image in c.decode(v):
            morceaux = []
            octets = 2 if max(comp.bits for comp in image.format.components) > 8 else 1
            for p in image.planes:
                brut = np.frombuffer(p, dtype=np.uint8).reshape(p.height, p.line_size)
                morceaux.append(brut[:, : p.width * octets].tobytes())
            sortie.append(b"".join(morceaux))
    return sortie
