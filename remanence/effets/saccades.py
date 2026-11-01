"""Saccades : par moments tirés au hasard, le mouvement s'inverse (Inversion par saccades) ou
l'image zoome de plus en plus fort (Zoom par saccades), puis tout redevient normal (moteur
codec, FFglitch). Idée des scripts Invert-reverse et Slice de dd_GlitchAssist, réécrite pour
Remanence ; le hasard suit la graine de l'effet."""

from remanence.effets import DescriptionEffet, Parametre
from remanence.moteurs.codec import scripts

# Une saccade commence avec la probabilité « frequence » (en %) à chaque image, et dure de 1 à
# « duree » images.
DECLENCHEUR = """
let reste = 0;
let age = 0;
let sens = 1;

function saccade() {
  if (reste <= 0 && hasard() * 100 < val("frequence")) {
    reste = 1 + Math.floor(hasard() * val("duree"));
    age = 0;
    sens = hasard() < 0.5 ? -1 : 1;
  }
  if (reste <= 0)
    return false;
  reste--;
  age++;
  return true;
}
"""

INVERSION = DECLENCHEUR + """
export function glitch_frame(frame) {
  const en_cours = saccade();
  const mvs = frame.mv?.forward;
  if (mvs && en_cours) {
    frame.mv.overflow = "truncate";
    const f = Math.round(val("intensite"));
    mvs.mul(MV(-f, -f));
    mvs.div(MV(100, 100));
  }
  __n++;
}
"""

ZOOM = DECLENCHEUR + """
let radial = null;

export function glitch_frame(frame) {
  const en_cours = saccade();
  const mvs = frame.mv?.forward;
  if (mvs && en_cours) {
    frame.mv.overflow = "truncate";
    if (!radial) {
      radial = new MV2DArray(mvs.width, mvs.height);
      const cx = (mvs.width - 1) / 2, cy = (mvs.height - 1) / 2;
      radial.forEach((mv, i, j) => {
        mv[0] = Math.round((cx - j) * 4);
        mv[1] = Math.round((cy - i) * 4);
      });
    }
    // Le zoom grandit à chaque image de la saccade, dans un sens tiré au hasard.
    const f = Math.round(val("intensite") * age * sens);
    const pousse = radial.dup();
    pousse.mul(MV(f, f));
    pousse.div(MV(400, 400));
    mvs.add(pousse);
  }
  __n++;
}
"""

CLES = ("frequence", "duree", "intensite")


def script_inversion(valeurs: list[dict], graine: int, effet=None) -> str:
    return scripts.entete(valeurs, CLES, graine) + INVERSION


def script_zoom(valeurs: list[dict], graine: int, effet=None) -> str:
    return scripts.entete(valeurs, CLES, graine) + ZOOM


def _parametres(intensite: float, maximum: float):
    return [Parametre("frequence", "Fréquence", 0, 50, 5, "%"),
            Parametre("duree", "Durée", 1, 60, 10, "images"),
            Parametre("intensite", "Intensité", 0, maximum, intensite, "%"),
            Parametre("blocs", "Blocs", 1, 31, 2)]


INVERSION_PAR_SACCADES = DescriptionEffet(
    cle="inversion_saccades",
    nom="Inversion par saccades",
    famille="Datamosh",
    moteur="codec",
    script=script_inversion,
    parametres=_parametres(100, 400),
    prereglages={"Saccades rares": {"frequence": 3, "duree": 10},
                 "Longues saccades": {"frequence": 4, "duree": 30},
                 "Saccades fréquentes": {"frequence": 25, "duree": 8, "intensite": 200}},
)

ZOOM_PAR_SACCADES = DescriptionEffet(
    cle="zoom_saccades",
    nom="Zoom par saccades",
    famille="Datamosh",
    moteur="codec",
    script=script_zoom,
    parametres=_parametres(25, 200),
    prereglages={"Coups de zoom": {"frequence": 5, "duree": 6},
                 "Grands coups de zoom": {"frequence": 4, "duree": 12, "intensite": 60},
                 "Zoom nerveux": {"frequence": 25, "duree": 4, "intensite": 40}},
)
