"""Écho de mouvement : chaque image reprend le mouvement d'une image plus ancienne, comme un
écho sonore (moteur codec, FFglitch). Avec du retour, les échos s'accumulent. Idée des scripts
Delay et Buffer de dd_GlitchAssist, réécrite pour Remanence."""

from remanence.effets import DescriptionEffet, Parametre
from remanence.moteurs.codec import scripts

CORPS = """
let ligne = [];

export function glitch_frame(frame) {
  const mvs = frame.mv?.forward;
  if (!mvs) {
    __n++;
    return;
  }
  frame.mv.overflow = "truncate";
  const retard = Math.max(1, Math.round(val("retard")));
  const retour = Math.round(val("retour"));
  const entree = mvs.dup();
  if (ligne.length >= retard) {
    const sortie = ligne[ligne.length - retard];
    // Ce qui entre dans la ligne : l'image, plus une part de l'écho qui sort.
    const reinjecte = sortie.dup();
    reinjecte.mul(MV(retour, retour));
    reinjecte.div(MV(100, 100));
    entree.add(reinjecte);
    mvs.assign(sortie);
  }
  ligne.push(entree);
  if (ligne.length > 120)
    ligne.shift();
  __n++;
}
"""


def script(valeurs: list[dict], graine: int, effet=None) -> str:
    return scripts.entete(valeurs, ("retard", "retour"), graine) + CORPS


DESCRIPTION = DescriptionEffet(
    cle="echo_mouvement",
    nom="Écho de mouvement",
    famille="Datamosh",
    moteur="codec",
    script=script,
    parametres=[Parametre("retard", "Retard", 1, 120, 20, "images"),
                Parametre("retour", "Retour", 0, 95, 0, "%"),
                Parametre("blocs", "Blocs", 1, 31, 2)],
    prereglages={"Écho": {"retard": 20, "retour": 0},
                 "Échos qui s'accumulent": {"retard": 10, "retour": 50},
                 "Écho lointain": {"retard": 45, "retour": 30}},
)
