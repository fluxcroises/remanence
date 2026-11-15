"""Gravité : une poussée constante dans une direction, ajoutée au mouvement ; l'image coule
vers le bas, monte ou glisse (moteur codec, FFglitch). Idée des scripts Gravity et
Anti-gravity de dd_GlitchAssist, réécrite pour Remanence ; « Fréquence » sous 100 % : seules
des images tirées au hasard sont poussées (scripts RandomDamage)."""

from remanence.effets import DescriptionEffet, Parametre
from remanence.moteurs.codec import scripts

# Un vecteur MPEG-4 dit où chercher le bloc dans l'image précédente : pour que l'image aille
# vers le bas, on cherche plus haut, d'où le signe moins. Unités : demi-pixels.
CORPS = """
export function glitch_frame(frame) {
  const mvs = frame.mv?.forward;
  if (mvs && hasard() * 100 < val("frequence")) {
    frame.mv.overflow = "truncate";
    const a = val("direction") * Math.PI / 180;
    const f = val("force") * 2;
    mvs.add(MV(Math.round(-Math.sin(a) * f), Math.round(-Math.cos(a) * f)));
  }
  __n++;
}
"""


def script(valeurs: list[dict], graine: int, effet=None) -> str:
    return scripts.entete(valeurs, ("direction", "force", "frequence"), graine) + CORPS


DESCRIPTION = DescriptionEffet(
    cle="gravite",
    nom="Gravité",
    famille="Datamosh",
    moteur="codec",
    script=script,
    parametres=[Parametre("direction", "Direction", 0, 359, 0, "°"),
                Parametre("force", "Force", 0, 64, 5, "px"),
                Parametre("frequence", "Fréquence", 1, 100, 100, "%"),
                Parametre("blocs", "Blocs", 1, 31, 2)],
    prereglages={"Gravité": {"direction": 0, "force": 5},
                 "Antigravité": {"direction": 180, "force": 5},
                 "Chutes au hasard": {"direction": 0, "force": 20, "frequence": 15}},
    equivalents={"Gravité": "dd_gravity", "Antigravité": "dd_antiGravity",
                 "Chutes au hasard": "dd_RandomDamage(grav)"},
)
