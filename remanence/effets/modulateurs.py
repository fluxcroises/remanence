"""Modulateurs : des signaux qui font varier des réglages d'effets dans le temps, en plus de
leurs images clés.

Un modulateur appartient à la séquence et suit son temps (en images). Il rend une valeur de
-1 à 1 (le tempo et l'audio, de 0 à 1 : une impulsion à chaque temps, le niveau du son).
Chaque cible ajoute au réglage `valeur × profondeur` (en % de la plage du réglage), puis le
réglage reste dans sa plage.
Tout est calculé, rien n'est tiré au hasard à la lecture : même projet, même rendu.
"""

from __future__ import annotations

import math

from remanence.effets import Parametre
from remanence.projet.modele import Modulateur, Sequence, nouvel_id

TYPES = {"oscillateur": "Oscillateur", "aleatoire": "Aléatoire lissé", "tempo": "Tempo",
         "audio": "Audio"}
# Signaux de 0 à 1 (les autres vont de -1 à 1).
UNIPOLAIRES = ("tempo", "audio")

FORMES = {"sinus": "Sinus", "triangle": "Triangle", "carre": "Carré",
          "dents": "Dents de scie"}
DIVISIONS = {4.0: "Mesure (4 temps)", 1.0: "Temps", 0.5: "Demi-temps", 0.25: "Quart de temps"}

PARAMETRES = {
    "oscillateur": [Parametre("frequence", "Fréquence", 0.05, 20, 1, "Hz", 2),
                    Parametre("phase", "Phase", 0, 360, 0, "°")],
    "aleatoire": [Parametre("vitesse", "Vitesse", 0.1, 20, 2, "/s", 1)],
    "tempo": [Parametre("bpm", "Tempo", 20, 300, 120, "BPM", 1),
              Parametre("declin", "Déclin", 1, 100, 40, "%"),
              Parametre("decalage", "Décalage", 0, 100, 0, "%")],
    "audio": [Parametre("sensibilite", "Sensibilité", -24, 24, 0, "dB", 1),
              Parametre("attaque", "Attaque", 1, 500, 10, "ms"),
              Parametre("relache", "Relâche", 10, 2000, 200, "ms")],
}
DEFAUTS_CHOIX = {"oscillateur": {"forme": "sinus"}, "aleatoire": {"graine": 1},
                 "tempo": {"division": 1.0}, "audio": {"bande": "volume", "piste": ""}}


def nouveau_modulateur(type_: str, numero: int = 1) -> Modulateur:
    params = {p.cle: p.defaut for p in PARAMETRES[type_]}
    params.update(DEFAUTS_CHOIX[type_])
    return Modulateur(nouvel_id(), type_, f"{TYPES[type_]} {numero}", params)


def _hasard(graine: int, k: int) -> float:
    """Valeur de -1 à 1 fixée par (graine, k)."""
    v = (k * 374761393 + graine * 668265263) & 0xFFFFFFFF
    v = ((v ^ (v >> 13)) * 1274126177) & 0xFFFFFFFF
    v ^= v >> 16
    return v / 0xFFFFFFFF * 2 - 1


def valeur(m: Modulateur, f: float, cadence: float, projet=None, seq=None) -> float:
    """Le signal à l'image f de la séquence. L'audio a besoin du projet et de la séquence
    (sans eux : 0)."""
    p = m.params
    if m.type == "audio":
        if projet is None or seq is None:
            return 0.0
        from remanence.moteurs.audio import enveloppe
        niveaux = enveloppe(projet, seq, p)
        return float(niveaux[int(f)]) if 0 <= int(f) < len(niveaux) else 0.0
    secondes = f / cadence
    if m.type == "oscillateur":
        cycle = (secondes * p.get("frequence", 1) + p.get("phase", 0) / 360) % 1.0
        forme = p.get("forme", "sinus")
        if forme == "triangle":
            return 1 - 4 * abs(cycle - 0.5)
        if forme == "carre":
            return 1.0 if cycle < 0.5 else -1.0
        if forme == "dents":
            return 2 * cycle - 1
        return math.sin(2 * math.pi * cycle)
    if m.type == "aleatoire":
        position = secondes * p.get("vitesse", 2)
        k = math.floor(position)
        s = position - k
        s = s * s * (3 - 2 * s)
        graine = int(p.get("graine", 1))
        return _hasard(graine, k) * (1 - s) + _hasard(graine, k + 1) * s
    if m.type == "tempo":
        # Une impulsion au début de chaque division, qui retombe selon le déclin.
        duree = 60 / max(1.0, p.get("bpm", 120)) * p.get("division", 1.0)
        position = (secondes / duree + p.get("decalage", 0) / 100) % 1.0
        declin = max(0.01, p.get("declin", 40) / 100)
        return math.exp(-position / declin * 4)
    return 0.0


def decalages(seq: Sequence, f: float, projet=None) -> dict[tuple[str, str], float]:
    """(identifiant de l'effet, réglage) -> décalage en fraction de la plage, à l'image f.
    projet : pour les modulateurs audio."""
    resultat: dict[tuple[str, str], float] = {}
    cadence = float(seq.fraction_cadence)
    for m in seq.modulateurs:
        if not m.actif or not m.cibles:
            continue
        v = valeur(m, f, cadence, projet, seq)
        for effet_id, cle, profondeur in m.cibles:
            resultat[(effet_id, cle)] = resultat.get((effet_id, cle), 0.0) + v * profondeur / 100
    return resultat


def cibles_de(seq: Sequence, effet_id: str) -> list:
    """Les modulateurs qui pilotent un réglage de cet effet (pour l'empreinte des caches)."""
    return [m for m in seq.modulateurs if any(c[0] == effet_id for c in m.cibles)]
