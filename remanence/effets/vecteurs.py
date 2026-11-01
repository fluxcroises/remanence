"""Vecteurs de mouvement : amplifier, inverser, figer un axe, moyenner dans le temps, décaler,
bruiter (moteur codec, FFglitch). Chaque réglage est animable : le script reçoit la valeur de
chaque image."""

import json

from remanence.effets import DescriptionEffet, Parametre

CLES = ("horizontal", "vertical", "decalage_x", "decalage_y", "moyenne", "bruit")

# Les vecteurs de MPEG-4 sont en demi-pixels.
MODELE = """// Généré par Remanence : opérations sur les vecteurs de mouvement.
const v = %(valeurs)s;
let graine = %(graine)d >>> 0;
function hasard() {  // mulberry32 : même graine, même tirage
  graine = (graine + 0x6D2B79F5) >>> 0;
  let t = graine;
  t = Math.imul(t ^ (t >>> 15), t | 1);
  t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
}
let n = 0;
let passe = [];

export function setup(args) {
  args.features = ["mv"];
}

export function glitch_frame(frame) {
  const i = Math.min(n, v.horizontal.length - 1);
  n++;
  const mvs = frame.mv?.forward;
  if (!mvs)
    return;
  frame.mv.overflow = "truncate";
  passe.push(mvs.dup());
  if (passe.length > 60)
    passe.shift();
  const k = Math.min(Math.max(1, Math.round(v.moyenne[i])), passe.length);
  if (k > 1) {
    const somme = new MV2DArray(mvs.width, mvs.height);
    for (let j = passe.length - k; j < passe.length; j++)
      somme.add(passe[j]);
    somme.div(MV(k, k));
    mvs.assign(somme);
  }
  mvs.mul(MV(Math.round(v.horizontal[i]), Math.round(v.vertical[i])));
  mvs.div(MV(100, 100));
  mvs.add(MV(Math.round(v.decalage_x[i] * 2), Math.round(v.decalage_y[i] * 2)));
  const b = v.bruit[i] * 2;
  if (b > 0)
    mvs.forEach((mv) => {
      mv[0] += Math.round((hasard() * 2 - 1) * b);
      mv[1] += Math.round((hasard() * 2 - 1) * b);
    });
}
"""


def script(valeurs: list[dict], graine: int, effet=None) -> str:
    colonnes = {cle: [round(v[cle], 3) for v in valeurs] for cle in CLES}
    return MODELE % {"valeurs": json.dumps(colonnes), "graine": graine}


DESCRIPTION = DescriptionEffet(
    cle="vecteurs",
    nom="Vecteurs de mouvement",
    famille="Datamosh",
    moteur="codec",
    script=script,
    parametres=[Parametre("horizontal", "Horizontal", -400, 400, 100, "%"),
                Parametre("vertical", "Vertical", -400, 400, 100, "%"),
                Parametre("decalage_x", "Décalage X", -64, 64, 0, "px"),
                Parametre("decalage_y", "Décalage Y", -64, 64, 0, "px"),
                Parametre("moyenne", "Moyenne", 1, 60, 1, "images"),
                Parametre("bruit", "Bruit", 0, 32, 0, "px"),
                Parametre("blocs", "Blocs", 1, 31, 2)],
    prereglages={"Mouvement amplifié": {"horizontal": 300, "vertical": 300},
                 "Mouvement inversé": {"horizontal": -100, "vertical": -100},
                 "Glissement horizontal": {"vertical": 0, "horizontal": 150},
                 "Traînée": {"moyenne": 12},
                 "Dérive": {"decalage_x": 3},
                 "Grouillement": {"bruit": 4}},
)
