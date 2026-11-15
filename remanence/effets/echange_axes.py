"""Échange des axes : le mouvement horizontal devient vertical et inversement ; l'image se
tord en diagonale (moteur codec, FFglitch). Idée du script Swap de dd_GlitchAssist, réécrite
pour Remanence ; « Fréquence » sous 100 % : seules des images tirées au hasard."""

from remanence.effets import DescriptionEffet, Parametre
from remanence.moteurs.codec import scripts

CORPS = """
export function glitch_frame(frame) {
  const mvs = frame.mv?.forward;
  if (mvs && hasard() * 100 < val("frequence")) {
    frame.mv.overflow = "truncate";
    mvs.forEach((mv) => {
      const x = mv[0];
      mv[0] = mv[1];
      mv[1] = x;
    });
  }
  __n++;
}
"""


def script(valeurs: list[dict], graine: int, effet=None) -> str:
    return scripts.entete(valeurs, ("frequence",), graine) + CORPS


DESCRIPTION = DescriptionEffet(
    cle="echange_axes",
    nom="Échange des axes",
    famille="Datamosh",
    moteur="codec",
    script=script,
    parametres=[Parametre("frequence", "Fréquence", 1, 100, 100, "%"),
                Parametre("blocs", "Blocs", 1, 31, 2)],
    prereglages={"Échange": {"frequence": 100},
                 "Échanges au hasard": {"frequence": 15},
                 "Échanges rares": {"frequence": 4}},
    equivalents={"Échange": "dd_swap", "Échanges au hasard": "dd_RandomDamage(swap)",
                 "Échanges rares": "dd_RandomDamage(swapRandomN)"},
)
