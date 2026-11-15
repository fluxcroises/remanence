"""Tourbillon : le mouvement tourne autour d'un centre ; l'image s'enroule comme dans un
siphon (moteur codec, FFglitch). Idée des scripts Circle et Circular de dd_GlitchAssist,
réécrite pour Remanence ; « Fréquence » sous 100 % : seules des images tirées au hasard."""

from remanence.effets import DescriptionEffet, Parametre
from remanence.moteurs.codec import scripts

# Le champ tournant : pour chaque macrobloc, la perpendiculaire à sa direction depuis le
# centre, calculée une fois. À force 100 %, un bloc à 10 blocs du centre tourne de
# 10 demi-pixels par image.
CORPS = """
let tournant = null;
let centre = [-1, -1];

export function glitch_frame(frame) {
  const mvs = frame.mv?.forward;
  const touche = hasard() * 100 < val("frequence");
  if (!mvs || !touche) {
    __n++;
    return;
  }
  frame.mv.overflow = "truncate";
  const cx = val("centre_x") / 100 * (mvs.width - 1);
  const cy = val("centre_y") / 100 * (mvs.height - 1);
  if (!tournant || centre[0] != cx || centre[1] != cy) {
    tournant = new MV2DArray(mvs.width, mvs.height);
    tournant.forEach((mv, i, j) => {
      mv[0] = Math.round((i - cy) * 4);
      mv[1] = Math.round((cx - j) * 4);
    });
    centre = [cx, cy];
  }
  const pousse = tournant.dup();
  const f = Math.round(val("force"));
  pousse.mul(MV(f, f));
  pousse.div(MV(400, 400));
  mvs.add(pousse);
  __n++;
}
"""


def script(valeurs: list[dict], graine: int, effet=None) -> str:
    return scripts.entete(valeurs, ("force", "centre_x", "centre_y", "frequence"),
                          graine) + CORPS


DESCRIPTION = DescriptionEffet(
    cle="tourbillon",
    nom="Tourbillon",
    famille="Datamosh",
    moteur="codec",
    script=script,
    parametres=[Parametre("force", "Force", -200, 200, 20, "%"),
                Parametre("centre_x", "Centre X", 0, 100, 50, "%"),
                Parametre("centre_y", "Centre Y", 0, 100, 50, "%"),
                Parametre("frequence", "Fréquence", 1, 100, 100, "%"),
                Parametre("blocs", "Blocs", 1, 31, 2)],
    prereglages={"Tourbillon": {"force": 20},
                 "Tourbillon inverse": {"force": -20},
                 "Tourbillons au hasard": {"force": 60, "frequence": 15}},
    equivalents={"Tourbillon": "dd_circle", "Tourbillon inverse": "dd_circular",
                 "Tourbillons au hasard": "dd_RandomDamage(circular)"},
)
