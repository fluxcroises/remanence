"""Suppression d'images clés : aux changements de plan du clip, l'image d'avant bave avec le
mouvement de celle d'après (moteur codec)."""

from remanence.effets import DescriptionEffet, Parametre
from remanence.moteurs.codec import bavure


def traiter(paquets: list[bytes], v: dict, graine: int) -> list[bytes]:
    n = len(paquets)
    return bavure.supprimer_cles(paquets, int(v["debut"] / 100 * n), int(v["fin"] / 100 * n))


DESCRIPTION = DescriptionEffet(
    cle="suppression_cles",
    nom="Suppression d'images clés",
    famille="Datamosh",
    moteur="codec",
    traiter=traiter,
    parametres=[Parametre("debut", "Début", 0, 100, 0, "%"),
                Parametre("fin", "Fin", 0, 100, 100, "%"),
                Parametre("blocs", "Blocs", 1, 31, 4)],
    prereglages={"Bavure aux coupes": {}, "Bavure grossière": {"blocs": 12},
                 "Seconde moitié": {"debut": 50}},
)
