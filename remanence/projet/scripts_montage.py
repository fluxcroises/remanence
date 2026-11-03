"""Scripts de glitch sur la timeline (section 4.12 du cahier des charges) : des commandes qui
transforment une sélection d'un coup, sur le modèle des scripts Vegas de datamosh.

- Scramble découpe les clips choisis en morceaux et mélange leur ordre ;
- Layer duplique les clips vidéo choisis sur de nouvelles pistes, décalés, pour un écho ;
- Automator pose des images clés au hasard sur les réglages d'un effet.

Tout le hasard part d'une graine : le même script relancé avec la même graine donne le même
montage. Le résultat est fait de clips et d'images clés ordinaires, qu'on retouche ensuite, et
chaque script s'annule d'un Ctrl+Z.
"""

from __future__ import annotations

import copy
import random

from remanence.effets import EFFETS, courbes
from remanence.projet import edition
from remanence.projet.modele import Effet, Sequence, nouvel_id


def scramble(seq: Sequence, ids: set[str], longueur: int, graine: int) -> set[str]:
    """Coupe les clips choisis (et leurs clips liés) tous les `longueur` images depuis le
    début de la sélection, puis rebat l'ordre des tranches de temps. Une tranche emporte tous
    ses morceaux, image et son ensemble. Renvoie les identifiants des morceaux."""
    longueur = max(1, int(longueur))
    ids = edition.avec_lies(seq, set(ids))
    choisis = [(p, c) for p, c in seq.tous_les_clips() if c.id in ids]
    if not choisis:
        raise edition.EditionImpossible("Aucun clip choisi.")
    if any(p.verrouillee for p, _ in choisis):
        raise edition.EditionImpossible("Une des pistes est verrouillée.")
    debut = min(c.debut for _, c in choisis)
    fin = max(c.fin for _, c in choisis)
    for f in range(debut + longueur, fin, longueur):
        ids |= set(edition.couper(seq, f, ids))
    morceaux = [(p, c) for p, c in seq.tous_les_clips() if c.id in ids]
    tranches = list(range(debut, fin, longueur))
    ordre = tranches[:]
    random.Random(graine).shuffle(ordre)
    # Chaque tranche reprend sa longueur (la dernière peut être plus courte), à la suite.
    nouvelle, position = {}, debut
    for t in ordre:
        nouvelle[t] = position
        position += min(longueur, fin - t)
    for _p, c in morceaux:
        t = debut + (c.debut - debut) // longueur * longueur
        c.debut = nouvelle[t] + (c.debut - t)
    for p in {p.id: p for p, _ in morceaux}.values():
        p.trier()
        edition.placer(p, ids, False)
    return ids


def layer(seq: Sequence, ids: set[str], copies: int, decalage: int, attenuation: float,
          fusion: str = "normal") -> set[str]:
    """Pour chaque clip vidéo choisi, `copies` copies sur autant de nouvelles pistes posées
    au-dessus de la sienne, chacune `decalage` images plus tard et `attenuation` (de 0 à 1)
    moins opaque que la précédente. Renvoie les identifiants des copies."""
    choisis = [(p, c) for p, c in seq.tous_les_clips()
               if c.id in ids and p.type == "video" and not c.est_effet]
    if not choisis:
        raise edition.EditionImpossible("Aucun clip vidéo choisi.")
    copies = max(1, int(copies))
    pistes: dict[tuple[str, int], object] = {}
    for p, _c in choisis:
        voisine = p
        for k in range(1, copies + 1):
            if (p.id, k) not in pistes:
                voisine = edition.ajouter_piste(seq, "video", voisine.id)
                voisine.nom = f"{p.nom} écho {k}"
                pistes[(p.id, k)] = voisine
            voisine = pistes[(p.id, k)]
    poses = set()
    for p, c in choisis:
        for k in range(1, copies + 1):
            cible = pistes[(p.id, k)]
            copie = copy.deepcopy(c)
            copie.id = nouvel_id()
            for e in copie.effets:
                e.id = nouvel_id()
                for m in e.masques:
                    m.id = nouvel_id()
            copie.lien = None
            copie.transition = None
            copie.debut = c.debut + k * int(decalage)
            copie.gain = c.gain * (1 - attenuation) ** k
            copie.fusion = fusion
            cible.clips.append(copie)
            poses.add(copie.id)
    for p in {id(p): p for p in pistes.values()}.values():
        p.trier()
        edition.placer(p, poses, False)
    return poses


def automator(effet: Effet, reglages: list[str], debut: int, fin: int, intervalle: int,
              amplitude: float, passage: str, graine: int):
    """Une image clé tous les `intervalle` images de `debut` à `fin` (temps de l'effet) sur
    chaque réglage choisi. Valeur tirée autour de la valeur actuelle, dans `amplitude` (de 0
    à 1) de la plage du réglage ; 1 : toute la plage. Les images clés déjà là dans cette
    plage de temps sont remplacées ; les interrupteurs passent en palier."""
    d = EFFETS[effet.type]
    if not d.animable:
        raise edition.EditionImpossible(f"« {d.nom} » ne s'anime pas.")
    parametres = {p.cle: p for p in d.parametres_pour(effet)}
    intervalle = max(1, int(intervalle))
    hasard = random.Random(graine)
    temps = list(range(int(debut), int(fin) + 1, intervalle))
    if temps[-1] != int(fin):
        temps.append(int(fin))
    for cle in reglages:
        p = parametres.get(cle)
        if p is None:
            continue
        actuelle = float(effet.params.get(cle, p.defaut))
        demi = (p.maximum - p.minimum) * amplitude / 2
        bas, haut = max(p.minimum, actuelle - demi), min(p.maximum, actuelle + demi)
        cles = [k for k in effet.cles.get(cle, []) if not debut <= k[0] <= fin]
        for t in temps:
            if p.booleen:
                v = float(hasard.random() < 0.5)
            else:
                v = round(hasard.uniform(bas, haut), p.decimales)
            cles = courbes.poser(cles, t, v, "palier" if p.booleen else passage)
        effet.cles[cle] = cles
