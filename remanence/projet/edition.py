"""Opérations de montage sur une séquence.

Chaque fonction modifie le modèle sur place. L'appelant enregistre ensuite
l'état dans l'historique. Le placement suit la logique d'écrasement des
logiciels de montage : un clip posé sur un autre remplace la partie recouverte.
"""

from __future__ import annotations

import copy

from remanence.projet.modele import (ENTREE_CLIP_EFFET, Clip, Effet, Media, Piste, Projet,
                                     Sequence, Transition, nouvel_id, valeur_enveloppe)


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
    if c.est_effet or c.titre is not None:
        return 2 * ENTREE_CLIP_EFFET
    if c.sequence_id is not None:
        imbriquee = next((s for s in projet.sequences if s.id == c.sequence_id), None)
        brute = imbriquee.duree() if imbriquee is not None else c.duree
    else:
        brute = projet.medias[c.media_id].nb_images(seq.fraction_cadence)
    # En images de la source ralentie ou accélérée : l'entrée se compte ainsi.
    return max(1, int(brute / c.vitesse + 1e-6))


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
                  duree: int | None = None, piste_audio: Piste | None = None) -> list[Clip]:
    """Pose un média (ou la partie [entree, entree+duree)) sur la timeline, en écrasant ce
    qu'il recouvre. Image et son arrivent liés. piste_audio : la piste du son, si elle n'est
    pas celle par défaut."""
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
        pa = piste if piste is not None and piste.type == "audio" else \
            piste_audio if piste_audio is not None else _piste_type(seq, "audio")
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


# Poses rapides de l'espace Cut

def raccord_proche(seq: Sequence, f: int) -> int:
    """Le raccord (début ou fin de clip, ou le début de la séquence) le plus proche de f :
    là où l'insertion intelligente pose un plan, sans couper un plan en deux."""
    return min([0] + coupes(seq), key=lambda r: (abs(r - f), r))


def clip_sous(seq: Sequence, f: int, piste: Piste | None = None) -> Clip | None:
    """Le clip de la piste (V1 par défaut) sous l'image f."""
    piste = piste or _piste_type(seq, "video")
    return next((c for c in piste.clips if c.debut <= f < c.fin), None)


def _refermer(seq: Sequence, debut: int, fin: int):
    """Retire [debut, fin) de toutes les pistes non verrouillées et rapproche la suite."""
    duree = fin - debut
    for p in seq.pistes:
        if p.verrouillee:
            continue
        liberer(p, debut, fin, set())
        for c in p.clips:
            if c.debut >= fin:
                c.debut -= duree
    for m in seq.marqueurs:
        if m.position >= fin:
            m.position -= duree
        elif m.position > debut:
            m.position = debut


def remplacer_plan(projet: Projet, seq: Sequence, clip_id: str, media: Media, entree: int,
                   duree: int) -> list[Clip]:
    """Le plan prend la place du clip (et de ses liés) ; la suite de la séquence, sur toutes
    les pistes, se décale de la différence de durée."""
    piste, c = seq.trouver(clip_id)
    if c is None:
        raise EditionImpossible("Aucun plan à remplacer.")
    debut, fin = c.debut, c.fin
    ids = avec_lies(seq, {c.id})
    for p in seq.pistes:
        p.clips = [x for x in p.clips if x.id not in ids]
    longueur = media.nb_images(seq.fraction_cadence)
    duree = max(1, min(duree, longueur - entree))
    if duree > fin - debut:
        ouvrir_espace(seq, fin, duree - (fin - debut))
    elif duree < fin - debut:
        _refermer(seq, debut + duree, fin)
    return ajouter_media(projet, seq, media, debut, piste, entree, duree)


def placer_au_dessus(projet: Projet, seq: Sequence, media: Media, debut: int, entree: int,
                     duree: int) -> list[Clip]:
    """Le plan sur la première piste vidéo libre au-dessus de V1 (une nouvelle en haut s'il
    n'y en a pas), son son sur une piste audio libre : rien n'est écrasé."""
    longueur = media.nb_images(seq.fraction_cadence)
    duree = max(1, min(duree, longueur - entree))
    fin = debut + duree

    def libre(p: Piste) -> bool:
        return not p.verrouillee and all(c.fin <= debut or c.debut >= fin for c in p.clips)
    videos = seq.pistes_video
    v1 = _piste_type(seq, "video")
    dessus = [p for p in reversed(videos[:videos.index(v1)])] if v1 in videos else []
    pv = next((p for p in dessus if libre(p)), None) or ajouter_piste(seq, "video")
    pa = None
    if media.infos.audio:
        pa = next((p for p in seq.pistes_audio if libre(p)), None) or ajouter_piste(seq, "audio")
    return ajouter_media(projet, seq, media, debut, pv, entree, duree, piste_audio=pa)


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
                droite.transition = None
            _rogner_debut(droite, fin - c.debut)
            nouveaux.append(droite)
    piste.clips = nouveaux
    piste.trier()


def decaler_cles(c: Clip, delta: int):
    """Le début du clip bouge de delta : ses images clés gardent leur place à l'écran."""
    for e in c.effets + ([c.transformation] if c.transformation else []):
        # Les images clés des masques comptent leur temps comme celles de l'effet.
        for cles in list(e.cles.values()) + [v for m in e.masques for v in m.cles.values()]:
            for k in cles:
                k[0] -= delta
    c.cles_supprimees = [k - delta for k in c.cles_supprimees if k - delta > 0]


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
            droite.transition = None  # la nouvelle coupe est franche
            if c.lien:
                droite.lien = nouveaux_liens.setdefault(c.lien, nouvel_id())
            _rogner_debut(droite, f - c.debut)
            droite.fondu_sortie = c.fondu_sortie
            _rogner_fin(c, f - c.debut)
            p.clips.append(droite)
            crees.append(droite.id)
        p.trier()
    return crees


def copier(seq: Sequence, ids: set[str]) -> list[tuple[str, Clip]]:
    """(piste, copie) des clips choisis et de leurs clips liés."""
    ids = avec_lies(seq, ids)
    return [(p.id, copy.deepcopy(c)) for p, c in seq.tous_les_clips() if c.id in ids]


def coller(seq: Sequence, copies: list[tuple[str, Clip]], debut: int,
           inserer: bool = False) -> set[str]:
    """Pose les copies sur leurs pistes, la plus précoce à l'image `debut`, les autres à la même
    distance qu'au moment de la copie. Elles écrasent ce qu'elles recouvrent, ou, avec
    `inserer`, poussent la suite de la séquence. Chaque copie est un nouveau clip (ses effets
    et ses liens aussi). Renvoie les identifiants posés."""
    pistes = {p.id: p for p in seq.pistes}
    copies = [(pistes[i], c) for i, c in copies if i in pistes]
    if not copies:
        raise EditionImpossible("Les pistes copiées n'existent plus.")
    if any(p.verrouillee for p, _ in copies):
        raise EditionImpossible("Une des pistes est verrouillée.")
    origine = min(c.debut for _, c in copies)
    if inserer:
        ouvrir_espace(seq, debut, max(c.fin for _, c in copies) - origine)
    liens: dict[str, str] = {}
    poses = set()
    for p, modele in copies:
        c = copy.deepcopy(modele)
        c.id = nouvel_id()
        _renouveler_effets(c)
        c.transition = None
        if c.lien:
            c.lien = liens.setdefault(c.lien, nouvel_id())
        c.debut = debut + modele.debut - origine
        p.clips.append(c)
        poses.add(c.id)
    for p in {p.id: p for p, _ in copies}.values():
        placer(p, poses, False)
    return poses


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


def ajouter_piste(seq: Sequence, type_: str, voisine_id: str | None = None,
                  dessous: bool = False) -> Piste:
    """Nouvelle piste : au-dessus (ou en dessous) de la piste voisine du même type ; sans
    voisine, tout en haut des pistes vidéo ou tout en bas des pistes audio."""
    n = len([p for p in seq.pistes if p.type == type_]) + 1
    p = Piste(nouvel_id(), type_, f"{'Vidéo' if type_ == 'video' else 'Audio'} {n}")
    voisine = next((q for q in seq.pistes if q.id == voisine_id and q.type == type_), None)
    if voisine is not None:
        seq.pistes.insert(seq.pistes.index(voisine) + (1 if dessous else 0), p)
    elif type_ == "video":
        seq.pistes.insert(0, p)
    else:
        seq.pistes.append(p)
    return p


def placer_piste(seq: Sequence, piste_id: str, cible_id: str):
    """Glisser une piste sur une autre du même type : elle prend sa place, les pistes entre
    les deux se décalent."""
    p = next((q for q in seq.pistes if q.id == piste_id), None)
    c = next((q for q in seq.pistes if q.id == cible_id), None)
    if p is None or c is None or p is c or p.type != c.type:
        return
    vers_le_haut = seq.pistes.index(p) > seq.pistes.index(c)
    seq.pistes.remove(p)
    seq.pistes.insert(seq.pistes.index(c) + (0 if vers_le_haut else 1), p)


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
    if c.transformation is not None:
        from remanence.effets.transformation import id_pour
        c.transformation.id = id_pour(c.id)


def porteurs_effets(seq: Sequence):
    """Tout ce qui peut porter des effets : la séquence, ses pistes, ses clips."""
    yield seq
    for p in seq.pistes:
        yield p
        yield from p.clips


def trouver_effet(seq: Sequence, effet_id: str, creer: bool = False):
    """(porteur, effet) ; la transformation d'un clip compte (porteur : le clip). creer : la
    transformation visée par son identifiant (`transformation.id_pour`) est créée si elle
    manque encore."""
    for porteur in porteurs_effets(seq):
        for e in porteur.effets:
            if e.id == effet_id:
                return porteur, e
        t = getattr(porteur, "transformation", None)
        if t is not None and t.id == effet_id:
            return porteur, t
    if creer and effet_id.startswith("tr-"):
        from remanence.effets.transformation import nouvelle
        piste, c = seq.trouver(effet_id[3:])
        if c is not None and piste.type == "video" and not c.est_effet:
            c.transformation = nouvelle(c.id)
            return c, c.transformation
    return None, None


def ajouter_effet(porteur, effet: Effet):
    """Ajoute un effet en fin de chaîne d'un clip, d'une piste vidéo ou de la séquence."""
    if isinstance(porteur, Piste) and porteur.type != "video":
        raise EditionImpossible("Les effets vont sur les pistes vidéo.")
    from remanence.effets import EFFETS
    if effet.type in EFFETS and EFFETS[effet.type].codec and \
            not (isinstance(porteur, Clip) and porteur.est_media):
        # Le moteur codec réencode les images d'un média : il lui faut un clip.
        raise EditionImpossible(f"{EFFETS[effet.type].nom} se pose sur un clip.")
    porteur.effets.append(effet)


def retirer_effet(seq: Sequence, effet_id: str):
    porteur, e = trouver_effet(seq, effet_id)
    if porteur is not None and e in porteur.effets:
        porteur.effets.remove(e)


def deplacer_effet(seq: Sequence, effet_id: str, sens: int):
    """Monte (sens -1) ou descend (sens 1) un effet dans sa chaîne."""
    porteur, e = trouver_effet(seq, effet_id)
    if porteur is None or e not in porteur.effets:
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


# Datamosh : transitions et images clés supprimées

def precedent(piste: Piste, clip: Clip) -> Clip | None:
    """Le clip de média qui finit exactement là où celui-ci commence, sur la même piste."""
    return next((o for o in piste.clips if o.fin == clip.debut and o.id != clip.id
                 and o.est_media), None)


def basculer_transition(seq: Sequence, clip_id: str, duree: int | None = None):
    """Pose ou retire la transition datamosh à l'entrée du clip."""
    piste, c = seq.trouver(clip_id)
    if c is None:
        return
    if piste.verrouillee:
        raise EditionImpossible(f"La piste « {piste.nom} » est verrouillée.")
    if c.transition is not None:
        c.transition = None
        return
    if precedent(piste, c) is None:
        raise EditionImpossible("Une transition datamosh se pose entre deux clips qui se suivent.")
    c.transition = Transition("datamosh", max(1, min(duree or 24, c.duree)))


def basculer_cle(seq: Sequence, clip_id: str, t: int):
    """Supprime (ou rend) l'image clé de la coupe à l'image t du clip."""
    piste, c = seq.trouver(clip_id)
    if c is None or t <= 0:
        return
    if piste.verrouillee:
        raise EditionImpossible(f"La piste « {piste.nom} » est verrouillée.")
    if t in c.cles_supprimees:
        c.cles_supprimees.remove(t)
    else:
        c.cles_supprimees = sorted(c.cles_supprimees + [t])


def clip_au_dessus(seq: Sequence, clip: Clip) -> Clip | None:
    """Le clip de média de la piste vidéo la plus proche au-dessus qui chevauche le clip
    (source du transfert de mouvement)."""
    piste, _ = seq.trouver(clip.id)
    pistes = seq.pistes_video
    if piste not in pistes:
        return None
    for p in reversed(pistes[:pistes.index(piste)]):
        for c in sorted(p.clips, key=lambda c: c.debut):
            if c.est_media and c.debut < clip.fin and c.fin > clip.debut:
                return c
    return None


# Vitesse, titres, séquences imbriquées (étape 5)

VITESSE_MIN, VITESSE_MAX = 0.05, 20.0


def _longueur_brute(projet: Projet, seq: Sequence, c: Clip) -> int:
    """Longueur de la source du clip en images, sans la vitesse."""
    if c.sequence_id is not None:
        imbriquee = next((s for s in projet.sequences if s.id == c.sequence_id), None)
        return max(1, imbriquee.duree()) if imbriquee is not None else c.duree
    return projet.medias[c.media_id].nb_images(seq.fraction_cadence)


def regler_vitesse(projet: Projet, seq: Sequence, clip_id: str, vitesse: float, inverse: bool):
    """Change la vitesse (et le sens) du clip et de ses clips liés. Le clip montre la même
    partie de sa source : sa durée change, et ce qui le suit sur sa piste se décale d'autant
    (rien n'est écrasé)."""
    vitesse = max(VITESSE_MIN, min(VITESSE_MAX, float(vitesse)))
    ids = avec_lies(seq, {clip_id})
    for p, c in list(seq.tous_les_clips()):
        if c.id not in ids or not (c.est_media or c.sequence_id):
            continue
        if p.verrouillee:
            raise EditionImpossible(f"La piste « {p.nom} » est verrouillée.")
        longueur = _longueur_brute(projet, seq, c)
        # La partie de la source que couvre le clip, en images de la source.
        debut, fin_source = c.entree * c.vitesse, (c.entree + c.duree) * c.vitesse
        if c.inverse:
            debut, fin_source = longueur - fin_source, longueur - debut
        bas = max(0, min(longueur - 1, round(debut)))
        haut = max(bas + 1, min(longueur, round(fin_source)))
        fin = c.fin
        c.vitesse, c.inverse = vitesse, bool(inverse)
        c.entree = round((longueur - haut if c.inverse else bas) / vitesse)
        duree = max(1, round((haut - bas) / vitesse))
        delta = duree - c.duree
        c.duree = duree
        c.fondu_entree = min(c.fondu_entree, duree)
        c.fondu_sortie = min(c.fondu_sortie, duree)
        if delta:
            for o in p.clips:
                if o is not c and o.debut >= fin:
                    o.debut += delta
        p.trier()


def ajouter_titre(seq: Sequence, debut: int, duree: int, titre: dict,
                  piste_id: str | None = None) -> Clip:
    """Titre sur la piste vidéo demandée, ou celle du haut ; si elle est occupée à cet
    endroit, sur une nouvelle piste au-dessus."""
    c = ajouter_clip_effet(seq, debut, duree, [], piste_id)
    c.titre = titre
    return c


def contient_sequence(projet: Projet, seq: Sequence, cible_id: str) -> bool:
    """La séquence montre-t-elle `cible_id`, elle-même ou par une imbrication ?"""
    if seq.id == cible_id:
        return True
    for _p, c in seq.tous_les_clips():
        if c.sequence_id is not None:
            sous = next((s for s in projet.sequences if s.id == c.sequence_id), None)
            if sous is not None and contient_sequence(projet, sous, cible_id):
                return True
    return False


def imbriquer(projet: Projet, seq: Sequence, ids: set[str]) -> Sequence:
    """Les clips choisis (et leurs clips liés) passent dans une nouvelle séquence, à la même
    place les uns par rapport aux autres, sur autant de pistes. Ils sont remplacés par un clip
    vidéo de cette séquence (et un clip audio lié s'il y avait du son)."""
    ids = avec_lies(seq, set(ids))
    choisis = [(p, c) for p, c in seq.tous_les_clips() if c.id in ids]
    if not choisis:
        raise EditionImpossible("Aucun clip choisi.")
    if any(p.verrouillee for p, _ in choisis):
        raise EditionImpossible("Une des pistes est verrouillée.")
    debut = min(c.debut for _, c in choisis)
    fin = max(c.fin for _, c in choisis)
    n = len(projet.sequences) + 1
    nouvelle = Sequence(nouvel_id(), f"Imbrication {n}", seq.largeur, seq.hauteur, seq.cadence,
                        seq.tc_debut, seq.tc_drop, True)
    for p in seq.pistes:
        clips = [c for q, c in choisis if q is p]
        if not clips:
            continue
        copie = Piste(nouvel_id(), p.type, p.nom)
        for c in clips:
            p.clips.remove(c)
            c.debut -= debut
            copie.clips.append(c)
        copie.trier()
        nouvelle.pistes.append(copie)
    projet.sequences.append(nouvelle)
    lien = nouvel_id()
    for type_ in ("video", "audio"):
        source = next((p for p, _ in choisis if p.type == type_), None)
        if source is None:
            continue
        c = Clip(nouvel_id(), "", debut, 0, fin - debut, lien, sequence_id=nouvelle.id)
        source.clips.append(c)
        placer(source, {c.id}, False)
    return nouvelle
