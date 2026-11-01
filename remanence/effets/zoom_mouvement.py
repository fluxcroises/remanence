"""Zoom de mouvement : chaque vecteur est poussé vers un centre (ou repoussé), l'image se
creuse ou s'étire (moteur codec, FFglitch). Idée du script Zoom de dd_GlitchAssist, réécrite
pour Remanence."""

from remanence.effets import DescriptionEffet, Parametre
from remanence.moteurs.codec import scripts

# Le champ radial : pour chaque macrobloc, sa distance au centre (en macroblocs), calculé une
# fois. À force 100 %, un macrobloc à 10 blocs du centre se déplace de 10 demi-pixels.
CORPS = """
let radial = null;
let centre = [-1, -1];

export function glitch_frame(frame) {
  const mvs = frame.mv?.forward;
  if (!mvs) {
    __n++;
    return;
  }
  frame.mv.overflow = "truncate";
  const cx = val("centre_x") / 100 * (mvs.width - 1);
  const cy = val("centre_y") / 100 * (mvs.height - 1);
  if (!radial || centre[0] != cx || centre[1] != cy) {
    radial = new MV2DArray(mvs.width, mvs.height);
    radial.forEach((mv, i, j) => {
      mv[0] = Math.round((cx - j) * 4);
      mv[1] = Math.round((cy - i) * 4);
    });
    centre = [cx, cy];
  }
  const pousse = radial.dup();
  const f = Math.round(val("force"));
  pousse.mul(MV(f, f));
  pousse.div(MV(400, 400));
  mvs.add(pousse);
  __n++;
}
"""


def script(valeurs: list[dict], graine: int, effet=None) -> str:
    return scripts.entete(valeurs, ("force", "centre_x", "centre_y"), graine) + CORPS


DESCRIPTION = DescriptionEffet(
    cle="zoom_mouvement",
    nom="Zoom de mouvement",
    famille="Datamosh",
    moteur="codec",
    script=script,
    parametres=[Parametre("force", "Force", -200, 200, 20, "%"),
                Parametre("centre_x", "Centre X", 0, 100, 50, "%"),
                Parametre("centre_y", "Centre Y", 0, 100, 50, "%"),
                Parametre("blocs", "Blocs", 1, 31, 2)],
    prereglages={"Aspiration": {"force": 20},
                 "Explosion": {"force": -20},
                 "Zoom décentré": {"force": 35, "centre_x": 25, "centre_y": 30}},
)
