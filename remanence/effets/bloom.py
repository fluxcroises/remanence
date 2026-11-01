"""Bloom : le mouvement d'une image répété sur une durée, sans rallonger le plan ; les pixels
fondent (moteur codec)."""

from remanence.effets import DescriptionEffet, Parametre
from remanence.moteurs.codec import bavure


def traiter(paquets: list[bytes], v: dict, graine: int) -> list[bytes]:
    return bavure.bloom(paquets, int(v["instant"] / 100 * len(paquets)), int(v["repetitions"]))


DESCRIPTION = DescriptionEffet(
    cle="bloom",
    nom="Bloom",
    famille="Datamosh",
    moteur="codec",
    traiter=traiter,
    parametres=[Parametre("instant", "Instant", 0, 100, 30, "%"),
                Parametre("repetitions", "Durée", 1, 240, 24, "images"),
                Parametre("blocs", "Blocs", 1, 31, 4)],
    prereglages={"Fonte courte": {"repetitions": 12}, "Fonte lente": {"repetitions": 48},
                 "Fonte dès le début": {"instant": 5, "repetitions": 36}},
)
