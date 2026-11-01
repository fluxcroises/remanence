"""Databending : des octets du flux compressé remplacés au hasard (moteur codec)."""

from remanence.effets import DescriptionEffet, Parametre
from remanence.moteurs.codec import bavure


def traiter(paquets: list[bytes], v: dict, graine: int) -> list[bytes]:
    return bavure.abimer(paquets, v["force"], graine)


DESCRIPTION = DescriptionEffet(
    cle="databending",
    nom="Databending",
    famille="Corruption",
    moteur="codec",
    traiter=traiter,
    parametres=[Parametre("force", "Force", 0, 100, 30, "%"),
                Parametre("blocs", "Blocs", 1, 31, 4)],
    prereglages={"Grains de sel": {"force": 15}, "Signal abîmé": {"force": 40},
                 "Flux brisé": {"force": 80}},
)
