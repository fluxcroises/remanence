"""Opérations de montage sur une séquence.

Chaque fonction modifie le modèle sur place. L'appelant enregistre ensuite
l'état dans l'historique. Le placement suit la logique d'écrasement des
logiciels de montage : un clip posé sur un autre remplace la partie recouverte.
"""

from __future__ import annotations

import copy

from remanence.projet.modele import (Clip, Media, Piste, Projet, Sequence, nouvel_id,
                                     valeur_enveloppe)


class EditionImpossible(Exception):
    pass


def regler_sequence_sur_media(seq: Sequence, media: Media):
    v = media.infos.video
    if not v:
        return
    seq.largeur, seq.hauteur, seq.cadence = v.largeur, v.hauteur, v.cadence
    seq.tc_debut = v.tc_debut or 0
    seq.tc_drop = v.tc_drop
    seq.reglee = True


def _piste_type(seq: Sequence, type_: str, apres: Piste | None = None) -> Piste:
    pistes = [p for p in seq.pistes if p.type == type_]
    if apres is not None and apres.type == type_:
        return apres
    if pistes:
        return pistes[0]
    p = Piste(nouvel_id(), type_, f"{'Vidéo' if type_ == 'video' else 'Audio'} 1")
    seq.pistes.append(p)
    return p


def ajouter_media(projet: Projet, seq: Sequence, media: Media, debut: int,
                  piste: Piste | None = None) -> list[Clip]:
    """Pose un média sur la timeline. Image et son arrivent liés."""
    if media.hors_ligne:
        raise EditionImpossible(f"Le média « {media.nom} » est hors ligne.")
    if not seq.reglee and media.infos.video and seq.duree() == 0:
        regler_sequence_sur_media(seq, media)
        if debut == 0 and media.infos.video.tc_debut is not None:
            seq.tc_debut = media.infos.video.tc_debut
    duree = media.nb_images(seq.fraction_cadence)
    lien = nouvel_id() if (media.infos.video and media.infos.audio) else None
    crees = []
    if media.infos.video:
        pv = piste if piste is not None and piste.type == "video" else _piste_type(seq, "video")
        crees.append((pv, Clip(nouvel_id(), media.id, max(0, debut), 0, duree, lien)))
    if media.infos.audio:
        pa = piste if piste is not None and piste.type == "audio" else _piste_type(seq, "audio")
        crees.append((pa, Clip(nouvel_id(), media.id, max(0, debut), 0, duree, lien)))
    for p, c in crees:
        if p.verrouillee:
            raise EditionImpossible(f"La piste « {p.nom} » est verrouillée.")
    for p, c in crees:
        liberer(p, c.debut, c.fin, set())
        p.clips.append(c)
        p.trier()
    return [c for _, c in crees]


def liberer(piste: Piste, debut: int, fin: int, exclure: set[str]):
    """Retire de la piste tout ce qui occupe [debut, fin), sauf les clips exclus."""
    nouveaux = []
    for c in piste.clips:
        if c.id in exclure or c.fin <= debut or c.debut >= fin:
            nouveaux.append(c)
            continue
        if c.debut < debut:
            gauche = copy.deepcopy(c)
            _rogner_fin(gauche, debut - c.debut)
            nouveaux.append(gauche)
        if c.fin > fin:
            droite = copy.deepcopy(c)
            droite.id = nouvel_id() if c.debut < debut else c.id
            _rogner_debut(droite, fin - c.debut)
            nouveaux.append(droite)
    piste.clips = nouveaux
    piste.trier()


def _rogner_debut(c: Clip, coupe: int):
    """Enlève `coupe` images au début du clip, en gardant son contenu en place."""
    if c.enveloppe:
        # Un point au nouveau bord garde la courbe identique à l'écran.
        bord = valeur_enveloppe(c.enveloppe, coupe)
        c.enveloppe = [[0, bord]] + [[x - coupe, y] for x, y in c.enveloppe if x > coupe]
    c.debut += coupe
    c.entree += coupe
    c.duree -= coupe
    c.fondu_entree = 0 if coupe > 0 else c.fondu_entree
    c.fondu_sortie = min(c.fondu_sortie, c.duree)


def _rogner_fin(c: Clip, nouvelle_duree: int):
    if c.enveloppe:
        bord = valeur_enveloppe(c.enveloppe, nouvelle_duree - 1)
        c.enveloppe = [[x, y] for x, y in c.enveloppe if x < nouvelle_duree - 1] + \
            [[nouvelle_duree - 1, bord]]
    c.duree = nouvelle_duree
    c.fondu_sortie = 0
    c.fondu_entree = min(c.fondu_entree, c.duree)


def avec_lies(seq: Sequence, ids: set[str]) -> set[str]:
    liens = {c.lien for _, c in seq.tous_les_clips() if c.id in ids and c.lien}
    return ids | {c.id for _, c in seq.tous_les_clips() if c.lien and c.lien in liens}


def deplacer(seq: Sequence, ids: set[str], delta: int, delta_piste: int = 0,
             inclure_lies: bool = True):
    """Déplace des clips dans le temps, et d'une ou plusieurs pistes du même type."""
    ids = avec_lies(seq, ids) if inclure_lies else set(ids)
    mouvements = []
    for p, c in list(seq.tous_les_clips()):
        if c.id in ids:
            if p.verrouillee:
                raise EditionImpossible(f"La piste « {p.nom} » est verrouillée.")
            mouvements.append((p, c))
    if not mouvements:
        return
    delta = max(delta, -min(c.debut for _, c in mouvements))
    for p, c in mouvements:
        cible = p
        if delta_piste:
            meme_type = [q for q in seq.pistes if q.type == p.type]
            i = meme_type.index(p) + delta_piste
            if 0 <= i < len(meme_type) and not meme_type[i].verrouillee:
                cible = meme_type[i]
        p.clips.remove(c)
        c.debut += delta
        cible.clips.append(c)
    for p in seq.pistes:
        bouges = [c for c in p.clips if c.id in ids]
        for c in bouges:
            liberer(p, c.debut, c.fin, ids)
        p.trier()


def rogner(projet: Projet, seq: Sequence, clip_id: str, cote: str, delta: int,
           inclure_lies: bool = True) -> int:
    """Déplace le bord gauche ('debut') ou droit ('fin') d'un clip. Renvoie le delta appliqué."""
    ids = avec_lies(seq, {clip_id}) if inclure_lies else {clip_id}
    clips = [(p, c) for p, c in seq.tous_les_clips() if c.id in ids]
    for p, _ in clips:
        if p.verrouillee:
            raise EditionImpossible(f"La piste « {p.nom} » est verrouillée.")
    for _, c in clips:
        longueur = projet.medias[c.media_id].nb_images(seq.fraction_cadence)
        if cote == "debut":
            delta = max(delta, -c.entree, -c.debut)
            delta = min(delta, c.duree - 1)
        else:
            delta = min(delta, longueur - c.entree - c.duree)
            delta = max(delta, 1 - c.duree)
    for p, c in clips:
        if cote == "debut":
            ancien_debut = c.debut
            c.debut += delta
            c.entree += delta
            c.duree -= delta
            c.enveloppe = [[x - delta, y] for x, y in c.enveloppe if x - delta >= 0]
            c.fondu_entree = min(c.fondu_entree, c.duree)
            if delta < 0:
                liberer(p, c.debut, ancien_debut, {c.id})
        else:
            ancienne_fin = c.fin
            c.duree += delta
            c.enveloppe = [[x, y] for x, y in c.enveloppe if x < c.duree]
            c.fondu_sortie = min(c.fondu_sortie, c.duree)
            if delta > 0:
                liberer(p, ancienne_fin, c.fin, {c.id})
    return delta


def couper(seq: Sequence, f: int, ids: set[str] | None = None) -> list[str]:
    """Coupe à l'image f les clips concernés (tous ceux sous la tête si ids est vide)."""
    nouveaux_liens: dict[str, str] = {}
    crees = []
    for p in seq.pistes:
        if p.verrouillee:
            continue
        for c in list(p.clips):
            if not (c.debut < f < c.fin):
                continue
            if ids and c.id not in ids:
                continue
            droite = copy.deepcopy(c)
            droite.id = nouvel_id()
            if c.lien:
                droite.lien = nouveaux_liens.setdefault(c.lien, nouvel_id())
            _rogner_debut(droite, f - c.debut)
            droite.fondu_sortie = c.fondu_sortie
            _rogner_fin(c, f - c.debut)
            p.clips.append(droite)
            crees.append(droite.id)
        p.trier()
    return crees


def supprimer(seq: Sequence, ids: set[str], inclure_lies: bool = True):
    ids = avec_lies(seq, ids) if inclure_lies else ids
    for p in seq.pistes:
        if p.verrouillee:
            continue
        p.clips = [c for c in p.clips if c.id not in ids]


def dissocier(seq: Sequence, ids: set[str]):
    for _, c in seq.tous_les_clips():
        if c.id in ids:
            c.lien = None


def lier(seq: Sequence, ids: set[str]):
    lien = nouvel_id()
    for _, c in seq.tous_les_clips():
        if c.id in ids:
            c.lien = lien


def regler_fondu(seq: Sequence, clip_id: str, cote: str, longueur: int):
    _, c = seq.trouver(clip_id)
    if c is None:
        return
    longueur = max(0, min(int(longueur), c.duree))
    if cote == "entree":
        c.fondu_entree = longueur
    else:
        c.fondu_sortie = longueur


def poser_point(seq: Sequence, clip_id: str, decalage: float, valeur: float) -> int:
    """Ajoute ou remplace un point d'enveloppe. Renvoie son rang dans la liste."""
    _, c = seq.trouver(clip_id)
    decalage = max(0.0, min(float(decalage), c.duree - 1))
    valeur = max(0.0, min(float(valeur), 1.0))
    c.enveloppe = [pt for pt in c.enveloppe if abs(pt[0] - decalage) > 1e-6]
    c.enveloppe.append([decalage, valeur])
    c.enveloppe.sort()
    return next(i for i, pt in enumerate(c.enveloppe) if pt[0] == decalage)


def retirer_point(seq: Sequence, clip_id: str, rang: int):
    _, c = seq.trouver(clip_id)
    if c and 0 <= rang < len(c.enveloppe):
        del c.enveloppe[rang]


def ajouter_piste(seq: Sequence, type_: str) -> Piste:
    n = len([p for p in seq.pistes if p.type == type_]) + 1
    p = Piste(nouvel_id(), type_, f"{'Vidéo' if type_ == 'video' else 'Audio'} {n}")
    if type_ == "video":
        seq.pistes.insert(0, p)
    else:
        seq.pistes.append(p)
    return p


def supprimer_piste(seq: Sequence, piste_id: str):
    seq.pistes = [p for p in seq.pistes if p.id != piste_id]


def deplacer_piste(seq: Sequence, piste_id: str, sens: int):
    """Échange la piste avec sa voisine du même type (sens -1 vers le haut, +1 vers le bas)."""
    p = next(p for p in seq.pistes if p.id == piste_id)
    meme = [i for i, q in enumerate(seq.pistes) if q.type == p.type]
    k = meme.index(seq.pistes.index(p)) + sens
    if 0 <= k < len(meme):
        i, j = seq.pistes.index(p), meme[k]
        seq.pistes[i], seq.pistes[j] = seq.pistes[j], seq.pistes[i]


def cibles_aimantation(seq: Sequence, exclure: set[str], tete: int) -> list[int]:
    cibles = {0, tete}
    for _, c in seq.tous_les_clips():
        if c.id not in exclure:
            cibles.update((c.debut, c.fin))
    cibles.update(m.position for m in seq.marqueurs)
    for pt in (seq.point_entree, seq.point_sortie):
        if pt is not None:
            cibles.add(pt)
    return sorted(cibles)


def aimanter(valeur: int, cibles: list[int], seuil: int) -> int:
    meilleure = min(cibles, key=lambda c: abs(c - valeur), default=None)
    if meilleure is not None and abs(meilleure - valeur) <= seuil:
        return meilleure
    return valeur
