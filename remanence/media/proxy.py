"""Proxies de lecture (ProRes 422 Proxy en demi-résolution) et chemins du cache."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import av

from remanence.config import dossier_cache, empreinte_fichier
from remanence.media.sonde import InfosMedia

LARGEUR_MINI_PROXY = 1280


def _base(infos: InfosMedia) -> Path:
    return dossier_cache() / empreinte_fichier(infos.chemin, infos.taille_octets, infos.date_modif)


def chemin_proxy(infos: InfosMedia) -> Path:
    return _base(infos).with_suffix(".proxy.mov")


def chemin_audio(infos: InfosMedia) -> Path:
    return _base(infos).with_suffix(".audio.f32")


def proxy_utile(infos: InfosMedia, largeur_mini: int = LARGEUR_MINI_PROXY) -> bool:
    v = infos.video
    # Les sources RVB n'ont pas de proxy : passer en YUV imposerait une conversion de couleur.
    return bool(v and v.largeur > largeur_mini and "yuv" in v.pix_fmt and not infos.sequence_images)


def generer_proxy(infos: InfosMedia, progression=None, annule=None,
                  cible: Path | None = None) -> Path:
    v = infos.video
    cible = cible or chemin_proxy(infos)
    cible.parent.mkdir(parents=True, exist_ok=True)
    partiel = cible.with_name(cible.stem + ".partiel.mov")
    largeur = max(2, (v.largeur // 2) & ~1)
    hauteur = max(2, (v.hauteur // 2) & ~1)
    pix = "yuva444p10le" if v.alpha else "yuv422p10le"
    plage = 2 if (v.couleur.plage == 2 or v.pix_fmt.startswith("yuvj")) else 1
    with av.open(infos.chemin) as entree, av.open(str(partiel), "w") as sortie:
        fe = entree.streams.video[0]
        fe.thread_type = "AUTO"
        cadence = Fraction(v.cadence)
        fs = sortie.add_stream("prores_ks", rate=cadence)
        fs.width, fs.height, fs.pix_fmt = largeur, hauteur, pix
        base_temps = 1 / cadence
        fs.time_base = base_temps
        fs.codec_context.options = {"profile": "4" if v.alpha else "0"}
        fs.codec_context.color_range = plage
        fs.codec_context.colorspace = v.couleur.matrice
        fs.codec_context.color_primaries = v.couleur.primaires
        fs.codec_context.color_trc = v.couleur.transfert
        n = 0
        for image in entree.decode(fe):
            if annule is not None and annule.is_set():
                break
            # Même plage en entrée et en sortie : le redimensionnement ne change pas les niveaux.
            reduite = image.reformat(width=largeur, height=hauteur, format=pix,
                                     src_color_range=plage, dst_color_range=plage,
                                     interpolation="BICUBIC")
            reduite.pts = n
            reduite.time_base = base_temps
            reduite.color_primaries = v.couleur.primaires
            reduite.color_trc = v.couleur.transfert
            reduite.colorspace = v.couleur.matrice
            reduite.color_range = plage
            for p in fs.encode(reduite):
                sortie.mux(p)
            n += 1
            if progression and v.nb_images:
                progression(n / v.nb_images)
        for p in fs.encode():
            sortie.mux(p)
    if annule is not None and annule.is_set():
        partiel.unlink(missing_ok=True)
        raise InterruptedError
    partiel.replace(cible)
    return cible
