"""Façonnage du glitch d'une transition datamosh (demande de Lewis, 21 novembre 2026).

Pendant la bavure, le mouvement du second plan peut être amplifié ou inversé (intensité),
selon une évolution (constante, coup d'abord, montée) et sur un seul axe (direction) : un
script FFglitch multiplie ses vecteurs, image par image. Le bloom répète le mouvement du
raccord ; la corruption abîme des octets des images de la bavure. Réglages neutres : rien
n'est touché.
"""

from __future__ import annotations

import zlib

from remanence.moteurs.codec import bavure, scripts
from remanence.projet.modele import Transition

# Les vecteurs multipliés, sauf quand les deux gains valent 1 (images hors transition).
CORPS = """
export function glitch_frame(frame) {
  const mvs = frame.mv?.forward;
  const gx = val("gx"), gy = val("gy");
  if (mvs && (gx != 1 || gy != 1)) {
    frame.mv.overflow = "truncate";
    mvs.forEach((mv) => {
      mv[0] = Math.round(mv[0] * gx);
      mv[1] = Math.round(mv[1] * gy);
    });
  }
  __n++;
}
"""


# Préréglages : l'allure du glitch, la durée de la transition gardée. Le fondu et le bloom
# sont ramenés à la durée.
PREREGLAGES = {
    "Douce": {"intensite": 100.0, "evolution": "constante", "direction": "deux", "bloom": 0,
              "corruption": 0.0, "fondu": 12},
    "Brutale": {"intensite": 400.0, "evolution": "coup", "direction": "deux", "bloom": 0,
                "corruption": 0.0, "fondu": 0},
    "Explosion": {"intensite": 250.0, "evolution": "coup", "direction": "deux", "bloom": 8,
                  "corruption": 0.0, "fondu": 6},
    "Cassée": {"intensite": 150.0, "evolution": "constante", "direction": "deux", "bloom": 3,
               "corruption": 50.0, "fondu": 4},
}


def appliquer_prereglage(t: Transition, nom: str):
    for cle, valeur in PREREGLAGES[nom].items():
        setattr(t, cle, valeur)
    t.fondu = min(t.fondu, t.duree)
    t.bloom = min(t.bloom, max(0, t.duree - 1))


def prereglage_de(t: Transition) -> str:
    """Le préréglage que la transition suit exactement (fondu et bloom ramenés à la
    durée), sinon ""."""
    for nom, valeurs in PREREGLAGES.items():
        attendu = dict(valeurs, fondu=min(valeurs["fondu"], t.duree),
                       bloom=min(valeurs["bloom"], max(0, t.duree - 1)))
        if all(getattr(t, cle) == v for cle, v in attendu.items()):
            return nom
    return ""


def violence(t: Transition) -> float:
    """De 0 (transition d'avant) à 1 : sert à resserrer les hachures sur la timeline."""
    mouvement = min(1.0, abs(t.intensite / 100.0 - 1.0) / 3.0)
    if t.direction != "deux":
        mouvement = max(mouvement, 0.3)
    return min(1.0, max(mouvement, t.bloom / 8.0, t.corruption / 60.0))


def gains(t: Transition) -> list[tuple[float, float]]:
    """(horizontal, vertical) de chaque image de la transition. Coup d'abord : l'intensité
    entière au raccord, puis de plus en plus proche du mouvement normal ; montée : l'inverse."""
    k = t.intensite / 100.0
    n = max(1, t.duree)
    resultat = []
    for i in range(n):
        u = i / (n - 1) if n > 1 else 0.0
        if t.evolution == "coup":
            g = 1 + (k - 1) * (1 - u) ** 2
        elif t.evolution == "montee":
            g = 1 + (k - 1) * u ** 2
        else:
            g = k
        resultat.append((0.0 if t.direction == "vertical" else g,
                         0.0 if t.direction == "horizontal" else g))
    return resultat


def agit_sur_le_mouvement(t: Transition) -> bool:
    return t.intensite != 100.0 or t.direction != "deux"


def script(t: Transition, queue: int, total: int) -> str:
    """Script FFglitch pour le flux de la source modifiée : `queue` images du plan d'avant,
    puis le clip ; la transition commence à l'image `queue`."""
    valeurs = [{"gx": 1.0, "gy": 1.0} for _ in range(total)]
    for i, (gx, gy) in enumerate(gains(t)):
        if queue + i < total:
            valeurs[queue + i] = {"gx": gx, "gy": gy}
    return scripts.entete(valeurs, ("gx", "gy"), 0) + CORPS


def graine(clip_id: str) -> int:
    """Tirage de la corruption : le même d'un calcul à l'autre pour un clip donné."""
    return zlib.crc32(clip_id.encode())


def faconner(paquets: list[bytes], t: Transition, queue: int, clip_id: str) -> list[bytes]:
    """Bloom au raccord, puis corruption des images de la bavure (après la suppression de
    l'image clé du raccord)."""
    sortie = list(paquets)
    fin = min(len(sortie), queue + t.duree)
    if t.bloom > 0:
        sortie[:fin] = bavure.bloom(sortie[:fin], queue + 1, min(t.bloom, t.duree - 1))
    if t.corruption > 0:
        sortie[queue:fin] = bavure.abimer(sortie[queue:fin], t.corruption, graine(clip_id))
    return sortie
