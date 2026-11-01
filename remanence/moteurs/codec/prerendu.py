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


def cle(projet: Projet, seq: Sequence, clip: Clip) -> str | None:
    """Empreinte du pré-rendu d'un clip ; None s'il n'a pas d'effet codec."""
    effets = effets_codec(clip)
    media = projet.medias.get(clip.media_id)
    if not effets or media is None or media.infos.video is None:
        return None
    source = Path(media.chemin)
    try:
        st = source.stat()
        signature = [str(source.resolve()), st.st_size, round(st.st_mtime, 3)]
    except OSError:
        signature = [media.chemin]
    donnees = {"source": signature, "entree": clip.entree, "duree": clip.duree,
               "cadence": seq.cadence,
               "effets": [[e.type, sorted(e.params.items()), e.graine] for e in effets]}
    return hashlib.sha1(json.dumps(donnees, sort_keys=True).encode()).hexdigest()[:20]


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
    media = projet.medias[clip.media_id]
    v = media.infos.video
    infos, index = analyser(media.chemin, v.cadence if media.infos.sequence_images else None)
    lecteur = LecteurVideo(media.chemin, index, infos.sequence_images, v.cadence)
    try:
        for k in range(clip.duree):
            yield lecteur.image(min(clip.entree + k, v.nb_images - 1))
    finally:
        lecteur.fermer()


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
    partiel = final.with_name(final.stem + ".partiel.mkv")
    try:
        with av.open(str(partiel), "w") as sortie:
            flux = sortie.add_stream("ffv1", rate=cadence)
            flux.width, flux.height, flux.pix_fmt = largeur, hauteur, "yuv420p"
            couleur = v.couleur
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
                    progression(min(1.0, (len(effets) - 0.5 + (i + 1) / n / 2) / len(effets)))
            for p in flux.encode(None):
                sortie.mux(p)
        with _verrou:
            partiel.replace(final)
    except BaseException:
        partiel.unlink(missing_ok=True)
        raise
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
