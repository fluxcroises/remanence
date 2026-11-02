"""Bavure par flux optique et Persistance : le datamosh simulé (moteur flux optique). Le
mouvement réel du clip déplace une image de référence, ou laisse des traînées, sans passer
par un codec : aucune perte de qualité, et ça marche sur un plan isolé, sans raccord."""

from remanence.effets import DescriptionEffet, Parametre
from remanence.moteurs import flux

BAVURE = DescriptionEffet(
    cle="bavure_flux",
    nom="Bavure par flux optique",
    famille="Datamosh",
    moteur="flux",
    flux=flux.bavure,
    parametres=[Parametre("depart", "Image de référence", 0, 100, 0, "%"),
                Parametre("force", "Force", -300, 300, 100, "%"),
                Parametre("lissage", "Lissage", 0, 10, 0.5, "%", 1),
                Parametre("rafraichissement", "Rafraîchissement", 0, 50, 0, "%", 1)],
    prereglages={"Matière qui glisse": {"force": 100},
                 "Bavure qui se dissipe": {"rafraichissement": 6},
                 "Coulée violente": {"force": 220, "lissage": 3}},
)

PERSISTANCE = DescriptionEffet(
    cle="persistance",
    nom="Persistance",
    famille="Datamosh",
    moteur="flux",
    flux=flux.persistance,
    parametres=[Parametre("persistance", "Persistance", 0, 98, 80, "%"),
                Parametre("force", "Force", -300, 300, 100, "%"),
                Parametre("lissage", "Lissage", 0, 10, 0.5, "%", 1),
                Parametre("eclaircir", "Éclaircir", 0, 1, 0, booleen=True)],
    prereglages={"Traînées": {"persistance": 80},
                 "Fantômes lumineux": {"persistance": 92, "eclaircir": 1},
                 "Écho court": {"persistance": 55}},
)
