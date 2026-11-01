"""Macroblocs : quantification extrême, les blocs de compression apparaissent (moteur codec)."""

from remanence.effets import DescriptionEffet, Parametre


def traiter(paquets: list[bytes], v: dict, graine: int) -> list[bytes]:
    return paquets  # tout se joue dans la quantification de l'encodage


DESCRIPTION = DescriptionEffet(
    cle="macroblocs",
    nom="Macroblocs",
    famille="Corruption",
    moteur="codec",
    traiter=traiter,
    parametres=[Parametre("blocs", "Blocs", 2, 31, 20)],
    prereglages={"Blocs visibles": {"blocs": 14}, "Gros blocs": {"blocs": 24},
                 "Mosaïque grossière": {"blocs": 31}},
)
