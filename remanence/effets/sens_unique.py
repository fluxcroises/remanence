"""Sens unique : seul le mouvement dans les directions cochées reste, le reste s'arrête ;
l'image ne fait plus que tomber, monter ou glisser d'un côté (moteur codec, FFglitch). Idée
des scripts Only fall, Only rise, Max zero et Min zero de dd_GlitchAssist, réécrite pour
Remanence ; « Fréquence » sous 100 % : seules des images tirées au hasard."""

from remanence.effets import DescriptionEffet, Parametre
from remanence.moteurs.codec import scripts

# Directions à l'écran ; un vecteur va dans le sens contraire (voir gravite.py).
CORPS = """
export function glitch_frame(frame) {
  const mvs = frame.mv?.forward;
  if (mvs && hasard() * 100 < val("frequence")) {
    frame.mv.overflow = "truncate";
    const bas = val("bas") > 0.5, haut = val("haut") > 0.5;
    const gauche = val("gauche") > 0.5, droite = val("droite") > 0.5;
    mvs.forEach((mv) => {
      if (!((mv[0] < 0 && droite) || (mv[0] > 0 && gauche)))
        mv[0] = 0;
      if (!((mv[1] < 0 && bas) || (mv[1] > 0 && haut)))
        mv[1] = 0;
    });
  }
  __n++;
}
"""


def script(valeurs: list[dict], graine: int, effet=None) -> str:
    return scripts.entete(valeurs, ("bas", "haut", "gauche", "droite", "frequence"),
                          graine) + CORPS


DESCRIPTION = DescriptionEffet(
    cle="sens_unique",
    nom="Sens unique",
    famille="Datamosh",
    moteur="codec",
    script=script,
    parametres=[Parametre("bas", "Vers le bas", 0, 1, 1, booleen=True),
                Parametre("haut", "Vers le haut", 0, 1, 0, booleen=True),
                Parametre("gauche", "Vers la gauche", 0, 1, 0, booleen=True),
                Parametre("droite", "Vers la droite", 0, 1, 0, booleen=True),
                Parametre("frequence", "Fréquence", 1, 100, 100, "%"),
                Parametre("blocs", "Blocs", 1, 31, 2)],
    prereglages={"Chute seule": {"bas": 1, "haut": 0, "gauche": 0, "droite": 0},
                 "Montée seule": {"bas": 0, "haut": 1, "gauche": 0, "droite": 0},
                 "Vers la gauche et le haut": {"bas": 0, "haut": 1, "gauche": 1,
                                               "droite": 0}},
    equivalents={"Chute seule": "dd_onlyFall", "Montée seule": "dd_onlyRise",
                 "Vers la gauche et le haut": "dd_maxZero"},
)
