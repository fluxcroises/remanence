"""Analyse du son pour le modulateur audio : le niveau d'une piste (ou de toutes) à chaque
image de la séquence, en volume ou dans une bande de fréquences.

Le son vient des caches audio des médias (float32 stéréo 48 kHz). Pour chaque image, une
fenêtre de deux images de son centrée sur elle donne un niveau en dB, ramené de 0 à 1 ; un
suiveur d'enveloppe (attaque, relâche) l'adoucit. L'enveloppe de toute la séquence est
calculée une fois puis gardée, tant que rien ne change dans le son ni dans les réglages.
"""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

import numpy as np

from remanence.media.lecteur import AudioCache
from remanence.media.proxy import chemin_audio
from remanence.projet.modele import Projet, Sequence

FREQUENCE = 48000
BANDES = {"volume": "Volume", "graves": "Graves", "mediums": "Médiums", "aigus": "Aigus"}
LIMITES = {"graves": (20, 250), "mediums": (250, 4000), "aigus": (4000, 16000)}
# Plage de niveaux ramenée de 0 à 1 : de -48 dB à 0 dB, décalée par la sensibilité.
PLAGE_DB = 48.0

_enveloppes: dict[str, np.ndarray] = {}


def _clips(projet: Projet, seq: Sequence, piste_id: str):
    for piste in seq.pistes_audio:
        if piste_id and piste.id != piste_id:
            continue
        for c in piste.clips:
            media = projet.medias.get(c.media_id)
            if media is not None and not media.hors_ligne and media.infos.audio:
                yield piste, c, media


def signature(projet: Projet, seq: Sequence, params: dict) -> str:
    """Tout ce dont dépend l'enveloppe : réglages, clips de son, caches audio."""
    signature = []
    for piste, c, media in _clips(projet, seq, params.get("piste", "")):
        cache = chemin_audio(media.infos)
        signature.append([c.id, c.debut, c.entree, c.duree, c.gain, c.fondu_entree,
                          c.fondu_sortie, c.enveloppe, piste.niveau, str(cache),
                          cache.exists()])
    return json.dumps([seq.cadence, seq.duree(), sorted(params.items()), signature],
                      sort_keys=True, default=str)


def _mixage(projet: Projet, seq: Sequence, piste_id: str, debut: int, n: int) -> np.ndarray:
    """Son mono des échantillons [debut, debut+n) des clips choisis, gains compris."""
    sortie = np.zeros(n, np.float32)
    par_image = FREQUENCE / float(seq.fraction_cadence)
    for piste, c, media in _clips(projet, seq, piste_id):
        fichier = chemin_audio(media.infos)
        if not fichier.exists():
            continue
        e0, e1 = round(c.debut * par_image), round(c.fin * par_image)
        a, b = max(debut, e0), min(debut + n, e1)
        if b <= a:
            continue
        cache = AudioCache(Path(fichier))
        cad_media = Fraction(media.infos.video.cadence) if media.infos.video \
            else seq.fraction_cadence
        source0 = round((c.entree / float(cad_media) - cache.decalage_s) * FREQUENCE)
        bloc = cache.lire(source0 + (a - e0), b - a).mean(axis=1)
        positions = (np.arange(a, b) - e0) / par_image
        images = np.arange(int(positions[0]), int(positions[-1]) + 2)
        gains = np.array([c.facteur(c.debut + min(int(k), c.duree - 1)) * piste.niveau
                          for k in images], np.float32)
        sortie[a - debut:b - debut] += bloc * np.interp(positions, images, gains)
    return sortie


def enveloppe(projet: Projet, seq: Sequence, params: dict) -> np.ndarray:
    """Niveau de 0 à 1 à chaque image de la séquence. params : piste ("" : toutes), bande,
    sensibilite (dB), attaque et relache (ms)."""
    cle = signature(projet, seq, params)
    if cle in _enveloppes:
        return _enveloppes[cle]
    cadence = float(seq.fraction_cadence)
    n_images = seq.duree()
    par_image = FREQUENCE / cadence
    fenetre = 1 << int(np.ceil(np.log2(max(64, 2 * par_image))))
    bande = params.get("bande", "volume")
    frequences = np.fft.rfftfreq(fenetre, 1 / FREQUENCE)
    masque = None
    if bande in LIMITES:
        bas, haut = LIMITES[bande]
        masque = (frequences >= bas) & (frequences < haut)
    hann = np.hanning(fenetre).astype(np.float32)
    niveaux = np.zeros(n_images, np.float32)
    # Par blocs de 10 s : le son d'une longue séquence ne tient pas en mémoire d'un coup.
    bloc_images = max(1, int(10 * cadence))
    for f0 in range(0, n_images, bloc_images):
        f1 = min(n_images, f0 + bloc_images)
        debut = int(f0 * par_image) - fenetre // 2
        son = _mixage(projet, seq, params.get("piste", ""), debut,
                      int((f1 - f0) * par_image) + fenetre)
        for f in range(f0, f1):
            i = int(f * par_image) - debut - fenetre // 2
            morceau = son[max(0, i):i + fenetre]
            if len(morceau) < fenetre:
                morceau = np.pad(morceau, (0, fenetre - len(morceau)))
            if masque is None:
                rms = float(np.sqrt(np.mean(morceau * morceau)))
            else:
                spectre = np.abs(np.fft.rfft(morceau * hann)) / (fenetre / 4)
                rms = float(np.sqrt(np.sum(spectre[masque] ** 2) / 2))
            db = 20 * np.log10(rms + 1e-9)
            niveaux[f] = (db + PLAGE_DB + params.get("sensibilite", 0)) / PLAGE_DB
    niveaux = np.clip(niveaux, 0, 1)
    # Suiveur d'enveloppe : monte en « attaque », redescend en « relâche ».
    attaque = np.exp(-1000 / max(1.0, params.get("attaque", 10)) / cadence)
    relache = np.exp(-1000 / max(1.0, params.get("relache", 200)) / cadence)
    suivi = np.zeros_like(niveaux)
    v = 0.0
    for f, x in enumerate(niveaux):
        a = attaque if x > v else relache
        v = a * v + (1 - a) * x
        suivi[f] = v
    if len(_enveloppes) > 32:
        _enveloppes.clear()
    _enveloppes[cle] = suivi
    return suivi
