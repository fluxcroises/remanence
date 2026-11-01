"""Pré-rendu des effets codec d'un clip, gardé en cache en FFV1 sans perte.

Les effets codec d'un clip s'enchaînent : chacun encode en MPEG-4 les images qu'il reçoit,
abîme le flux, puis le décode pour le suivant. Tout passe d'une étape à l'autre image par image :
seuls les paquets compressés restent en mémoire, même en UHD. Le résultat est un fichier de même
durée que le clip, que la composition lit à la place de la source ; opacité, masques et mode
de fusion de l'effet le recomposent ensuite sur l'original.

Le nom du fichier est l'empreinte de tout ce qui change le résultat (source, partie du média,
cadence, réglages) : changer un réglage ne recalcule que ce clip.
"""

from __future__ import annotations

import hashlib
import json
import threading
from fractions import Fraction
from pathlib import Path

import av
import numpy as np

from remanence.config import dossier_cache
from remanence.effets import EFFETS
from remanence.media.lecteur import LecteurVideo
from remanence.media.sonde import analyser
from remanence.moteurs.codec import bavure
from remanence.projet import edition
from remanence.projet.modele import Clip, Effet, Projet, Sequence

# Dossier des pré-rendus : à côté du projet enregistré, sinon dans le cache de l'utilisateur.
_dossier_projet: Path | None = None
_verrou = threading.Lock()


def definir_projet(chemin: Path | None):
    """À l'enregistrement ou à l'ouverture d'un projet : ses pré-rendus vont à côté de lui."""
    global _dossier_projet
    _dossier_projet = None if chemin is None else Path(chemin).with_name(
        Path(chemin).stem + "_cache")


def dossier() -> Path:
    d = _dossier_projet or (dossier_cache() / "datamosh")
    d.mkdir(parents=True, exist_ok=True)
    return d


def effets_codec(clip: Clip) -> list[Effet]:
    return [e for e in clip.effets if e.actif and e.type in EFFETS and EFFETS[e.type].codec]


def _signature(projet: Projet, clip: Clip) -> list:
    media = projet.medias[clip.media_id]
    source = Path(media.chemin)
    try:
        st = source.stat()
        return [str(source.resolve()), st.st_size, round(st.st_mtime, 3), clip.entree, clip.duree]
    except OSError:
        return [media.chemin, clip.entree, clip.duree]


def _empreinte(donnees: dict) -> str:
    return hashlib.sha1(json.dumps(donnees, sort_keys=True).encode()).hexdigest()[:20]


def cle(projet: Projet, seq: Sequence, clip: Clip) -> str | None:
    """Empreinte du pré-rendu des effets codec d'un clip ; None s'il n'en a pas."""
    effets = effets_codec(clip)
    media = projet.medias.get(clip.media_id)
    if not effets or media is None or media.infos.video is None:
        return None
    donnees = {"source": _signature(projet, clip), "raccord": cle_source(projet, seq, clip),
               "cadence": seq.cadence,
               "effets": [[e.type, sorted(e.params.items()), e.graine] for e in effets]}
    return _empreinte(donnees)


# Source modifiée : transition datamosh depuis le clip précédent, images clés supprimées.

def _precedent(seq: Sequence, clip: Clip) -> Clip | None:
    if clip.transition is None:
        return None
    piste, _ = seq.trouver(clip.id)
    return edition.precedent(piste, clip) if piste is not None else None


def cle_source(projet: Projet, seq: Sequence, clip: Clip) -> str | None:
    """Empreinte de la source modifiée du clip ; None si rien ne la modifie."""
    media = projet.medias.get(clip.media_id)
    if media is None or media.infos.video is None:
        return None
    a = _precedent(seq, clip)
    if a is None and not clip.cles_supprimees:
        return None
    donnees = {"source": _signature(projet, clip), "cadence": seq.cadence,
               "cles": clip.cles_supprimees,
               "transition": None if a is None else [clip.transition.duree, clip.transition.blocs,
                                                     _signature(projet, a)]}
    return _empreinte(donnees)


def chemin_source(cle_source_: str) -> Path:
    return dossier() / f"raccord_{cle_source_}.mkv"


def source_prete(projet: Projet, seq: Sequence, clip: Clip) -> Path | None:
    k = cle_source(projet, seq, clip)
    if k is None:
        return None
    p = chemin_source(k)
    return p if p.exists() else None


def plages_modifiees(projet: Projet, seq: Sequence, clip: Clip) -> list[tuple[int, int]]:
    """Images du clip (depuis son début) que la source modifiée remplace : la durée de la
    transition, et chaque coupe dont l'image clé est supprimée, jusqu'à la coupe suivante.
    Ailleurs, l'image reste celle de la source (et l'export la recopie)."""
    plages = []
    if _precedent(seq, clip) is not None:
        plages.append((0, min(clip.transition.duree, clip.duree)))
    if clip.cles_supprimees:
        media = projet.medias.get(clip.media_id)
        coupes = sorted(c - clip.entree for c in (media.coupes or []) if media) if media else []
        for t in clip.cles_supprimees:
            suivante = next((c for c in coupes if c > t and c not in clip.cles_supprimees),
                            clip.duree)
            plages.append((t, min(suivante, clip.duree)))
    return plages


def dans_plages(projet: Projet, seq: Sequence, clip: Clip, t: int) -> bool:
    if clip.transition is None and not clip.cles_supprimees:
        return False
    return any(a <= t < b for a, b in plages_modifiees(projet, seq, clip))


def _images(projet: Projet, clip: Clip, debut: int, nombre: int):
    """Images du média du clip, à partir de l'image `debut` du clip."""
    media = projet.medias[clip.media_id]
    v = media.infos.video
    infos, index = analyser(media.chemin, v.cadence if media.infos.sequence_images else None)
    lecteur = LecteurVideo(media.chemin, index, infos.sequence_images, v.cadence)
    try:
        for k in range(nombre):
            yield lecteur.image(min(clip.entree + debut + k, v.nb_images - 1))
    finally:
        lecteur.fermer()


def calculer_source(projet: Projet, seq: Sequence, clip: Clip, progression=None,
                    annule: threading.Event | None = None) -> Path | None:
    """Source modifiée : la fin du clip précédent (s'il y a une transition), puis le clip, en
    MPEG-4 ; l'image clé du raccord et celles des coupes choisies sont supprimées, une image clé
    forcée à la fin de la transition rend l'image nette."""
    k = cle_source(projet, seq, clip)
    if k is None:
        return None
    final = chemin_source(k)
    if final.exists():
        return final
    v = projet.medias[clip.media_id].infos.video
    largeur, hauteur = v.largeur - v.largeur % 2, v.hauteur - v.hauteur % 2
    cadence = Fraction(seq.cadence)
    a = _precedent(seq, clip)
    queue = min(a.duree, 4) if a is not None else 0
    retour = queue + clip.transition.duree if a is not None else None
    encodeur = bavure.Encodeur(largeur, hauteur, cadence,
                               clip.transition.blocs if a is not None else 4)
    paquets = []
    images = []
    if a is not None:
        images.append(_images(projet, a, a.duree - queue, queue))
    images.append(_images(projet, clip, 0, clip.duree))
    i = 0
    total = queue + clip.duree
    for source in images:
        for image in source:
            if annule is not None and annule.is_set():
                raise InterruptedError
            paquets += encodeur.encoder(image, cle=(i == queue and a is not None) or i == retour)
            i += 1
            if progression:
                progression(i / total / 2)
    paquets += encodeur.finir()
    supprimees = {queue + t for t in clip.cles_supprimees}
    if a is not None:
        supprimees.add(queue)
    paquets = bavure.supprimer_cles_aux(paquets, supprimees)
    decodees = bavure.decoder(paquets, total)
    for _ in range(queue):
        next(decodees)
    _ecrire(final, decodees, clip.duree, largeur, hauteur, cadence, v.couleur, progression,
            annule, 0.5)
    return final


def _ecrire(final: Path, images, n: int, largeur: int, hauteur: int, cadence: Fraction,
            couleur, progression, annule, depart: float):
    """Écrit n images en FFV1 sans perte, d'abord dans un fichier partiel."""
    partiel = final.with_name(final.stem + ".partiel.mkv")
    try:
        with av.open(str(partiel), "w") as sortie:
            flux = sortie.add_stream("ffv1", rate=cadence)
            flux.width, flux.height, flux.pix_fmt = largeur, hauteur, "yuv420p"
            cc = flux.codec_context
            cc.color_primaries, cc.color_trc = couleur.primaires, couleur.transfert
            cc.colorspace, cc.color_range = couleur.matrice, couleur.plage or 1
            for i, image in enumerate(images):
                if annule is not None and annule.is_set():
                    raise InterruptedError
                image = image.reformat(width=largeur, height=hauteur, format="yuv420p")
                image.pts = i
                image.time_base = 1 / cadence
                for p in flux.encode(image):
                    sortie.mux(p)
                if progression:
                    progression(min(1.0, depart + (1 - depart) * (i + 1) / n))
            for p in flux.encode(None):
                sortie.mux(p)
        with _verrou:
            partiel.replace(final)
    except BaseException:
        partiel.unlink(missing_ok=True)
        raise


def chemin(cle_prerendu: str) -> Path:
    return dossier() / f"datamosh_{cle_prerendu}.mkv"


def pret(projet: Projet, seq: Sequence, clip: Clip) -> Path | None:
    """Le fichier du pré-rendu s'il est déjà calculé."""
    k = cle(projet, seq, clip)
    if k is None:
        return None
    p = chemin(k)
    return p if p.exists() else None


def _images_source(projet: Projet, seq: Sequence, clip: Clip):
    """Les images du clip, prises dans sa source modifiée sur les plages qu'elle remplace
    (transition, coupes), et dans la source partout ailleurs."""
    modifiee = calculer_source(projet, seq, clip)
    if modifiee is None:
        yield from _images(projet, clip, 0, clip.duree)
        return
    media = projet.medias[clip.media_id]
    v = media.infos.video
    infos, index = analyser(media.chemin, v.cadence if media.infos.sequence_images else None)
    source = LecteurVideo(media.chemin, index, infos.sequence_images, v.cadence)
    _, index_mod = analyser(str(modifiee))
    mod = LecteurVideo(str(modifiee), index_mod)
    plages = plages_modifiees(projet, seq, clip)
    try:
        for t in range(clip.duree):
            if any(a <= t < b for a, b in plages):
                yield mod.image(t)
            else:
                yield source.image(min(clip.entree + t, v.nb_images - 1))
    finally:
        source.fermer()
        mod.fermer()


def calculer(projet: Projet, seq: Sequence, clip: Clip, progression=None,
             annule: threading.Event | None = None) -> Path | None:
    """Calcule (ou retrouve) le pré-rendu du clip et renvoie son fichier."""
    k = cle(projet, seq, clip)
    if k is None:
        return None
    final = chemin(k)
    if final.exists():
        return final
    media = projet.medias[clip.media_id]
    v = media.infos.video
    # MPEG-4 veut des dimensions paires : une ligne ou une colonne de moins si besoin.
    largeur, hauteur = v.largeur - v.largeur % 2, v.hauteur - v.hauteur % 2
    cadence = Fraction(seq.cadence)
    effets = effets_codec(clip)
    n = clip.duree
    images = _images_source(projet, seq, clip)
    for etape, effet in enumerate(effets):
        d = EFFETS[effet.type]
        valeurs = {**d.valeurs(), **effet.params}
        encodeur = bavure.Encodeur(largeur, hauteur, cadence, valeurs.get("blocs", 4))
        paquets = []
        for i, image in enumerate(images):
            if annule is not None and annule.is_set():
                raise InterruptedError
            paquets += encodeur.encoder(image)
            if progression:
                progression((etape + (i + 1) / n / 2) / len(effets))
        paquets += encodeur.finir()
        paquets = d.traiter(paquets, valeurs, effet.graine)
        images = bavure.decoder(paquets, n)
    _ecrire(final, images, n, largeur, hauteur, cadence, v.couleur, progression, annule, 0.5)
    return final


def apercu(images: list[np.ndarray], effets: list[Effet], cadence: Fraction = Fraction(24)
           ) -> list[np.ndarray]:
    """Effets codec appliqués à une courte suite d'images RVB uint8 (vignettes)."""
    h, l = images[0].shape[:2]
    trames = [av.VideoFrame.from_ndarray(np.ascontiguousarray(i), format="rgb24") for i in images]
    for effet in effets:
        if effet.type not in EFFETS or not EFFETS[effet.type].codec:
            continue
        d = EFFETS[effet.type]
        valeurs = {**d.valeurs(), **effet.params}
        paquets = bavure.encoder(trames, l - l % 2, h - h % 2, cadence, valeurs.get("blocs", 4))
        trames = list(bavure.decoder(d.traiter(paquets, valeurs, effet.graine), len(images)))
    return [t.reformat(width=l, height=h, format="rgb24").to_ndarray() for t in trames]
