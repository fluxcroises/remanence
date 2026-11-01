"""Transfert de mouvement : les vecteurs du clip de la piste au-dessus appliqués à ce clip
(moteur codec, FFglitch)."""

from remanence.effets import DescriptionEffet, Parametre

DESCRIPTION = DescriptionEffet(
    cle="transfert_mouvement",
    nom="Transfert de mouvement",
    famille="Datamosh",
    moteur="codec",
    transfert=True,
    parametres=[Parametre("force", "Force", 0, 100, 100, "%"),
                Parametre("blocs", "Blocs", 1, 31, 2)],
    prereglages={"Mouvement emprunté": {"force": 100},
                 "Mouvement mêlé": {"force": 50},
                 "Mouvement en blocs": {"force": 100, "blocs": 12}},
)
