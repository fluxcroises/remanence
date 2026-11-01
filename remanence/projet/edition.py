"""Opérations de montage sur une séquence.

Chaque fonction modifie le modèle sur place. L'appelant enregistre ensuite
l'état dans l'historique. Le placement suit la logique d'écrasement des
logiciels de montage : un clip posé sur un autre remplace la partie recouverte.
"""

from __future__ import annotations

import copy

from remanence.projet.modele import (ENTREE_CLIP_EFFET, Clip, Effet, Media, Piste, Projet,
                                     Sequence, nouvel_id, valeur_enveloppe)


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


def longueur_source(projet: Projet, seq: Sequence, c: Clip) -> int:
    """Longueur de ce que montre le clip ; un clip d'effet peut s'étendre sans limite."""
    if c.est_effet:
        return 2 * ENTREE_CLIP_EFFET
    return projet.medias[c.media_id].nb_images(seq.fraction_cadence)


def _piste_type(seq: Sequence, type_: str, apres: Piste | None = None) -> Piste:
    pistes = [p for p in seq.pistes if p.type == type_]
    if apres is not None and apres.type == type_:
        return apres
    if pistes:
        # V1 est la piste vidéo du bas (comme dans Resolve), A1 la première piste audio.
        return pistes[-1] if type_ == "video" else pistes[0]
    p = Piste(nouvel_id(), type_, f"{'Vidéo' if type_ == 'video' else 'Audio'} 1")
    seq.pistes.append(p)
    return p


def ajouter_media(projet: Projet, seq: Sequence, media: Media, debut: int,
                  piste: Piste | None = None, entree: int = 0,
                  duree: int | None = None) -> list[Clip]:
    """Pose un média (ou la partie [entree, entree+duree)) sur la timeline, en écrasant ce
    qu'il recouvre. Image et son arrivent liés."""
    if media.hors_ligne:
        raise EditionImpossible(f"Le média « {media.nom} » est hors ligne.")
    if not seq.reglee and media.infos.video and seq.duree() == 0:
        regler_sequence_sur_media(seq, media)
        if debut == 0 and media.infos.video.tc_debut is not None:
            seq.tc_debut = media.infos.video.tc_debut + entree
    longueur = media.nb_images(seq.fraction_cadence)
    entree = max(0, min(entree, longueur - 1))
    duree = longueur - entree if duree is None else max(1, min(duree, longueur - entree))
    lien = nouvel_id() if (media.infos.video and media.infos.audio) else None
    crees = []
    if media.infos.video:
        pv = piste if piste is not None and piste.type == "video" else _piste_type(seq, "video")
        crees.append((pv, Clip(nouvel_id(), media.id, max(0, debut), entree, duree, lien)))
    if media.infos.audio:
        pa = piste if piste is not None and piste.type == "audio" else _piste_type(seq, "audio")
        crees.append((pa, Clip(nouvel_id(), media.id, max(0, debut), entree, duree, lien)))
    for p, c in crees:
        if p.verrouillee:
            raise EditionImpossible(f"La piste « {p.nom} » est verrouillée.")
    for p, c in crees:
        liberer(p, c.debut, c.fin, set())
        p.clips.append(c)
        p.trier()
    return [c for _, c in crees]


def ouvrir_espace(seq: Sequence, f: int, duree: int):
    """Décale de `duree` images tout ce qui suit f sur les pistes non verrouillées, en coupant
    les clips à cheval : c'est l'insertion des logiciels de montage."""
    couper(seq, f)
    for p in seq.pistes:
        if p.verrouillee:
            continue
        for c in p.clips:
            if c.debut >= f:
                c.debut += duree
    for m in seq.marqueurs:
        if m.position >= f:
            m.position += duree


def inserer_media(projet: Projet, seq: Sequence, media: Media, debut: int,
                  piste: Piste | None = None, entree: int = 0,
                  duree: int | None = None) -> list[Clip]:
    """Comme ajouter_media, mais en poussant la suite de la séquence au lieu de l'écraser."""
    longueur = media.nb_images(seq.fraction_cadence)
    duree = longueur - entree if duree is None else duree
    ouvrir_espace(seq, debut, duree)
    return ajouter_media(projet, seq, media, debut, piste, entree, duree)


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
            if c.debut < debut:
                # La partie gauche garde l'identité du clip ; celle-ci devient un autre clip.
                droite.id = nouvel_id()
                _renouveler_effets(droite)
            _rogner_debut(droite, fin - c.debut)
            nouveaux.append(droite)
    piste.clips = nouveaux
    piste.trier()


def decaler_cles(c: Clip, delta: int):
    """Le début du clip bouge de delta : ses images clés gardent leur place à l'écran."""
    for e in c.effets:
        for cles in e.cles.values():
            for k in cles:
                k[0] -= delta


def _rogner_debut(c: Clip, coupe: int):
    """Enlève `coupe` images au début du clip, en gardant son contenu en place."""
    decaler_cles(c, coupe)
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


def placer(piste: Piste, ids: set[str], fondus_auto: bool):
    """Installe les clips `ids` de la piste à leur nouvelle place.

    Un clip qui en recouvre un autre l'écrase, sauf quand fondus_auto est vrai et que le
    recouvrement ne touche qu'un bord : les deux clips restent et se fondent l'un dans l'autre
    sur la zone commune, comme dans Vegas Pro.
    """
    poses = [c for c in piste.clips if c.id in ids]
    for c in poses:
        for o in [o for o in piste.clips if o.id not in ids and o.fin > c.debut and o.debut < c.fin]:
            if fondus_auto and o.debut < c.debut < o.fin <= c.fin:
                commun = o.fin - c.debut
                if commun < min(c.duree, o.duree):
                    o.fondu_sortie = commun
                    c.fondu_entree = commun
                    continue
            if fondus_auto and c.debut <= o.debut < c.fin < o.fin:
                commun = c.fin - o.debut
                if commun < min(c.duree, o.duree):
                    c.fondu_sortie = commun
                    o.fondu_entree = commun
                    continue
            liberer(piste, max(c.debut, o.debut), min(c.fin, o.fin), ids)
    piste.trier()


def deplacer(seq: Sequence, ids: set[str], delta: int, delta_piste: int = 0,
             inclure_lies: bool = True, fondus_auto: bool = False):
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
        if any(c.id in ids for c in p.clips):
            placer(p, ids, fondus_auto)


def rogner(projet: Projet, seq: Sequence, clip_id: str, cote: str, delta: int,
           inclure_lies: bool = True, ripple: bool = False) -> int:
    """Déplace le bord gauche ('debut') ou droit ('fin') d'un clip. Renvoie le delta appliqué.

    En ripple, la place du clip ne change pas : ce qui le suit sur ses pistes avance ou recule
    d'autant, sans laisser de trou ni écraser.
    """
    if ripple:
        return _rogner_ripple(projet, seq, clip_id, cote, delta, inclure_lies)
    ids = avec_lies(seq, {clip_id}) if inclure_lies else {clip_id}
    clips = [(p, c) for p, c in seq.tous_les_clips() if c.id in ids]
    for p, _ in clips:
        if p.verrouillee:
            raise EditionImpossible(f"La piste « {p.nom} » est verrouillée.")
    for _, c in clips:
        longueur = longueur_source(projet, seq, c)
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
            decaler_cles(c, delta)
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


def _rogner_ripple(projet: Projet, seq: Sequence, clip_id: str, cote: str, delta: int,
                   inclure_lies: bool) -> int:
    ids = avec_lies(seq, {clip_id}) if inclure_lies else {clip_id}
    clips = [(p, c) for p, c in seq.tous_les_clips() if c.id in ids]
    for p, _ in clips:
        if p.verrouillee:
            raise EditionImpossible(f"La piste « {p.nom} » est verrouillée.")
    for _, c in clips:
        longueur = longueur_source(projet, seq, c)
        if cote == "debut":
            delta = min(max(delta, -c.entree), c.duree - 1)
        else:
            delta = max(min(delta, longueur - c.entree - c.duree), 1 - c.duree)
    for p, c in clips:
        ancienne_fin = c.fin
        if cote == "debut":
            c.entree += delta
            c.duree -= delta
            c.enveloppe = [[x - delta, y] for x, y in c.enveloppe if x - delta >= 0]
            decaler_cles(c, delta)
            c.fondu_entree = min(c.fondu_entree, c.duree)
            decalage = -delta
        else:
            c.duree += delta
            c.enveloppe = [[x, y] for x, y in c.enveloppe if x < c.duree]
            c.fondu_sortie = min(c.fondu_sortie, c.duree)
            decalage = delta
        for o in p.clips:
            if o.id != c.id and o.debut >= ancienne_fin:
                o.debut += decalage
        p.trier()
    return delta


def supprimer_ripple(seq: Sequence, ids: set[str], inclure_lies: bool = True):
    """Supprime des clips et referme les trous sur leurs pistes."""
    ids = avec_lies(seq, ids) if inclure_lies else set(ids)
    for p in seq.pistes:
        if p.verrouillee:
            continue
        retires = sorted((c for c in p.clips if c.id in ids), key=lambda c: c.debut,
                         reverse=True)
        p.clips = [c for c in p.clips if c.id not in ids]
        for r in retires:
            suivants = [o for o in p.clips if o.debut > r.debut]
            if not suivants:
                continue
            # Le premier clip suivant vient à la place du clip retiré, même s'il le chevauchait.
            recul = min(r.duree, min(o.debut for o in suivants) - r.debut)
            for o in suivants:
                if o.debut < r.fin:
                    o.fondu_entree = 0
                o.debut -= recul
        p.trier()


def glisser_contenu(projet: Projet, seq: Sequence, clip_id: str, delta: int,
                    inclure_lies: bool = True) -> int:
    """Slip : le clip reste en place, son contenu glisse (le point d'entrée change)."""
    ids = avec_lies(seq, {clip_id}) if inclure_lies else {clip_id}
    clips = [(p, c) for p, c in seq.tous_les_clips() if c.id in ids]
    for p, c in clips:
        if p.verrouillee:
            raise EditionImpossible(f"La piste « {p.nom} » est verrouillée.")
        longueur = longueur_source(projet, seq, c)
        delta = min(max(delta, -c.entree), longueur - c.entree - c.duree)
    for _, c in clips:
        c.entree += delta
    return delta


def _voisins(piste: Piste, c: Clip) -> tuple[Clip | None, Clip | None]:
    avant = next((o for o in piste.clips if o.fin == c.debut and o.id != c.id), None)
    apres = next((o for o in piste.clips if o.debut == c.fin and o.id != c.id), None)
    return avant, apres


def faire_glisser(projet: Projet, seq: Sequence, clip_id: str, delta: int,
                  inclure_lies: bool = True) -> int:
    """Slide : le clip se déplace avec son contenu ; ses voisins collés s'allongent ou se
    raccourcissent pour qu'il n'y ait ni trou ni écrasement."""
    ids = avec_lies(seq, {clip_id}) if inclure_lies else {clip_id}
    clips = [(p, c) for p, c in seq.tous_les_clips() if c.id in ids]
    for p, c in clips:
        if p.verrouillee:
            raise EditionImpossible(f"La piste « {p.nom} » est verrouillée.")
        avant, apres = _voisins(p, c)
        if avant is not None:
            fin_media = longueur_source(projet, seq, avant)
            delta = max(min(delta, fin_media - avant.entree - avant.duree), 1 - avant.duree)
        else:
            delta = max(delta, -c.debut)
        if apres is not None:
            delta = min(max(delta, -apres.entree), apres.duree - 1)
    for p, c in clips:
        avant, apres = _voisins(p, c)
        if avant is not None:
            avant.duree += delta
        if apres is not None:
            apres.debut += delta
            apres.entree += delta
            apres.duree -= delta
        c.debut += delta
        p.trier()
    return delta


def rouler(projet: Projet, seq: Sequence, clip_id: str, delta: int,
           inclure_lies: bool = True) -> int:
    """Roll : déplace la coupe entre le clip et son voisin de droite ; la durée totale ne
    change pas, l'un gagne ce que l'autre perd."""
    ids = avec_lies(seq, {clip_id}) if inclure_lies else {clip_id}
    paires = []
    for p, c in seq.tous_les_clips():
        if c.id in ids:
            _, apres = _voisins(p, c)
            if apres is None:
                continue
            if p.verrouillee:
                raise EditionImpossible(f"La piste « {p.nom} » est verrouillée.")
            paires.append((c, apres))
    if not paires:
        return 0
    for c, apres in paires:
        fin_media = longueur_source(projet, seq, c)
        delta = max(min(delta, fin_media - c.entree - c.duree, apres.duree - 1),
                    1 - c.duree, -apres.entree)
    for c, apres in paires:
        c.duree += delta
        apres.debut += delta
        apres.entree += delta
        apres.duree -= delta
    return delta


def coupes(seq: Sequence) -> list[int]:
    """Toutes les coupes de la séquence (débuts et fins de clips), triées."""
    return sorted({f for _, c in seq.tous_les_clips() for f in (c.debut, c.fin)})


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
            _renouveler_effets(droite)
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


# Effets

def _renouveler_effets(c: Clip):
    """Un clip dupliqué (coupe) reçoit ses propres effets, indépendants de ceux de l'original."""
    for e in c.effets:
        e.id = nouvel_id()
        for m in e.masques:
            m.id = nouvel_id()


def porteurs_effets(seq: Sequence):
    """Tout ce qui peut porter des effets : la séquence, ses pistes, ses clips."""
    yield seq
    for p in seq.pistes:
        yield p
        yield from p.clips


def trouver_effet(seq: Sequence, effet_id: str):
    for porteur in porteurs_effets(seq):
        for e in porteur.effets:
            if e.id == effet_id:
                return porteur, e
    return None, None


def ajouter_effet(porteur, effet: Effet):
    """Ajoute un effet en fin de chaîne d'un clip, d'une piste vidéo ou de la séquence."""
    if isinstance(porteur, Piste) and porteur.type != "video":
        raise EditionImpossible("Les effets vont sur les pistes vidéo.")
    from remanence.effets import EFFETS
    if effet.type in EFFETS and EFFETS[effet.type].codec and \
            not (isinstance(porteur, Clip) and not porteur.est_effet):
        # Le moteur codec réencode les images d'un média : il lui faut un clip.
        raise EditionImpossible(f"{EFFETS[effet.type].nom} se pose sur un clip.")
    porteur.effets.append(effet)


def retirer_effet(seq: Sequence, effet_id: str):
    porteur, e = trouver_effet(seq, effet_id)
    if porteur is not None:
        porteur.effets.remove(e)


def deplacer_effet(seq: Sequence, effet_id: str, sens: int):
    """Monte (sens -1) ou descend (sens 1) un effet dans sa chaîne."""
    porteur, e = trouver_effet(seq, effet_id)
    if porteur is None:
        return
    i = porteur.effets.index(e)
    j = max(0, min(len(porteur.effets) - 1, i + sens))
    porteur.effets.insert(j, porteur.effets.pop(i))


def ajouter_clip_effet(seq: Sequence, debut: int, duree: int, effets: list[Effet],
                       piste_id: str | None = None) -> Clip:
    """Clip d'effet sur la piste vidéo demandée, ou celle du haut ; si elle est occupée à cet
    endroit, sur une nouvelle piste au-dessus, pour ne rien écraser."""
    haut = next((p for p in seq.pistes if p.id == piste_id and p.type == "video"), None) \
        or (seq.pistes_video[0] if seq.pistes_video else None)
    if haut is None or haut.verrouillee or any(c.fin > debut and c.debut < debut + duree
                                               for c in haut.clips):
        haut = ajouter_piste(seq, "video")
    c = Clip(nouvel_id(), "", max(0, debut), ENTREE_CLIP_EFFET, max(1, duree), effets=effets)
    haut.clips.append(c)
    haut.trier()
    return c
