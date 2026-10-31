"""Intermédiaire à cadence fixe pour les sources à cadence variable (téléphones)."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import av

from remanence.config import dossier_cache, empreinte_fichier
from remanence.media.sonde import InfosMedia, analyser
from remanence.rendu.couleur import appliquer_couleur

CADENCES_COURANTES = [Fraction(24000, 1001), Fraction(24), Fraction(25), Fraction(30000, 1001),
                      Fraction(30), Fraction(50), Fraction(60000, 1001), Fraction(60)]


def cadence_cible(moyenne: Fraction) -> Fraction:
    return min(CADENCES_COURANTES, key=lambda c: abs(float(c) - float(moyenne)))


def chemin_intermediaire(infos: InfosMedia) -> Path:
    base = empreinte_fichier(infos.chemin, infos.taille_octets, infos.date_modif)
    return dossier_cache() / f"{base}.cfr.mov"


def creer_intermediaire(infos: InfosMedia, progression=None, annule=None) -> Path:
    """Réechantillonne la vidéo à cadence fixe en ProRes 422 HQ ; l'audio est recopié tel quel.

    Chaque image de sortie reprend l'image source affichée à cet instant, comme un lecteur.
    """
    v = infos.video
    _, index = analyser(infos.chemin)
    cible = chemin_intermediaire(infos)
    if cible.exists():
        return cible
    partiel = cible.with_name(cible.stem + ".partiel.mov")
    debut_s = float(index.pts[0] * index.base_temps)
    temps = [float(p * index.base_temps) - debut_s for p in index.pts]
    duree = temps[-1] + (temps[-1] - temps[-2] if len(temps) > 1 else 0)
    moyenne = Fraction(len(temps) / max(duree, 1e-6)).limit_denominator(1001)
    cadence = cadence_cible(moyenne)
    base_temps = 1 / cadence
    n_sortie = max(1, round(duree * float(cadence)))
    pix = "yuva444p10le" if v.alpha else "yuv422p10le"
    with av.open(infos.chemin) as entree, av.open(str(partiel), "w") as sortie:
        fe = entree.streams.video[0]
        fs = sortie.add_stream("prores_ks", rate=cadence)
        fs.width, fs.height, fs.pix_fmt = v.largeur, v.hauteur, pix
        fs.time_base = base_temps
        fs.codec_context.options = {"profile": "4" if v.alpha else "3"}
        audio = [(a, sortie.add_stream_from_template(a)) for a in entree.streams.audio]
        plage = v.couleur.plage or (2 if v.pix_fmt.startswith("yuvj") else 1)
        k = 0
        precedente = None
        for image in entree.decode(fe):
            if annule is not None and annule.is_set():
                break
            t_image = float(image.pts * fe.time_base) - debut_s
            # Écrire toutes les images de sortie dont l'instant précède cette nouvelle image.
            while k < n_sortie and k / float(cadence) < t_image - 1e-6 and precedente is not None:
                _encoder(fs, sortie, precedente, k, base_temps, pix, plage, v)
                k += 1
            precedente = image
            if progression:
                progression(k / n_sortie)
        while k < n_sortie and precedente is not None:
            _encoder(fs, sortie, precedente, k, base_temps, pix, plage, v)
            k += 1
        for p in fs.encode():
            sortie.mux(p)
        if audio and not (annule is not None and annule.is_set()):
            entree.seek(0)
            correspondance = {a.index: o for a, o in audio}
            for p in entree.demux([a for a, _ in audio]):
                if p.size:
                    p.stream = correspondance[p.stream.index]
                    sortie.mux(p)
    if annule is not None and annule.is_set():
        partiel.unlink(missing_ok=True)
        raise InterruptedError
    partiel.replace(cible)
    return cible


def _encoder(fs, sortie, image, k, base_temps, pix, plage, v):
    # ProRes ne connaît que la plage vidéo : une source en plage complète y est ramenée.
    trame = image.reformat(format=pix, src_color_range=plage, dst_color_range=1)
    trame.pts = k
    trame.time_base = base_temps
    appliquer_couleur(trame, v.couleur, 1)
    for p in fs.encode(trame):
        sortie.mux(p)

