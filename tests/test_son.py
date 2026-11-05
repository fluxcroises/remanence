"""Étape 12 : effets audio (moteur, Bitcrusher)."""

import av
import numpy as np

from remanence.effets import nouvel_effet, poser_cle
from remanence.media.lecteur import generer_cache_audio
from remanence.media.proxy import chemin_audio
from remanence.media.sonde import analyser
from remanence.projet import edition
from remanence.projet.modele import Media, Projet, nouvel_id
from remanence.rendu.composition import Compositeur
from remanence.rendu.export import exporter


def _projet(medias):
    p = Projet.nouveau()
    infos, _ = analyser(str(medias["prores_hq"]))
    m = Media(nouvel_id(), str(medias["prores_hq"]), infos)
    p.medias[m.id] = m
    if not chemin_audio(infos).exists():
        generer_cache_audio(infos, chemin_audio(infos))
    edition.ajouter_media(p, p.sequence, m, 0)
    return p, p.sequence.pistes_audio[0].clips[0]


def _son(projet, debut=0, n=None, blocs=None):
    seq = projet.sequence
    n = n or int(seq.duree() * 48000 / float(seq.fraction_cadence))
    c = Compositeur(projet)
    try:
        if not blocs:
            return c.audio(seq, debut, n)
        morceaux, position = [], debut
        for taille in blocs:
            morceaux.append(c.audio(seq, position, taille))
            position += taille
        return np.concatenate(morceaux)
    finally:
        c.fermer()


def test_bitcrusher_sur_un_clip_et_par_blocs(medias):
    projet, clip = _projet(medias)
    source = _son(projet)
    clip.effets.append(nouvel_effet("bitcrusher"))
    traite = _son(projet)
    assert traite.shape == source.shape and np.abs(traite - source).max() > 0.01
    # Lu par blocs de tailles quelconques (lecture, export) : les mêmes échantillons.
    n = len(traite)
    blocs = [997, 3, 4096, 12345]
    blocs.append(n - sum(blocs))
    assert np.array_equal(_son(projet, blocs=blocs), traite)
    # 6 bits : au plus 64 niveaux par demi-onde.
    assert len(np.unique(np.round(traite[:, 0] * 32))) <= 65


def test_melange_et_piste(medias):
    projet, clip = _projet(medias)
    source = _son(projet)
    e = nouvel_effet("bitcrusher")
    e.opacite = 0.0  # mélange nul : le son reçu
    clip.effets.append(e)
    assert np.array_equal(_son(projet), source)
    clip.effets.clear()
    piste = projet.sequence.pistes_audio[0]
    piste.effets.append(nouvel_effet("bitcrusher"))
    assert np.abs(_son(projet) - source).max() > 0.01


def test_effet_audio_anime(medias):
    projet, clip = _projet(medias)
    e = nouvel_effet("bitcrusher")
    poser_cle(e, "bits", 0, 16.0)
    poser_cle(e, "bits", 29, 2.0)
    e.params["reduction"] = 1
    clip.effets.append(e)
    son = _son(projet)
    par_image = 48000 / float(projet.sequence.fraction_cadence)
    debut = son[: int(par_image)]
    fin = son[int(27 * par_image): int(28 * par_image)]
    assert len(np.unique(fin[:, 0])) < len(np.unique(debut[:, 0]))


def test_export_avec_effet_audio(medias, tmp_path):
    projet, clip = _projet(medias)
    clip.effets.append(nouvel_effet("bitcrusher"))
    seq = projet.sequence
    r1 = exporter(projet, seq, tmp_path / "a.mov")
    r2 = exporter(projet, seq, tmp_path / "b.mov")
    assert r1.audio != "copie"

    def pcm(chemin):
        with av.open(str(chemin)) as c:
            return b"".join(bytes(p) for p in c.demux(audio=0))
    assert pcm(tmp_path / "a.mov") == pcm(tmp_path / "b.mov")


import pytest  # noqa: E402

from remanence.effets import EFFETS  # noqa: E402

AUDIO = sorted(c for c, d in EFFETS.items() if d.audio)


def test_six_effets_audio():
    assert AUDIO == ["arret_bande", "begaiement", "bitcrusher", "databending_audio", "gel",
                     "inversion_fragments"]


@pytest.mark.parametrize("cle", AUDIO)
def test_effet_audio_agit_et_se_lit_par_blocs(medias, cle):
    """Chaque effet change le son, donne les mêmes échantillons lu par blocs, et la même
    graine redonne le même son."""
    projet, clip = _projet(medias)
    source = _son(projet)
    e = nouvel_effet(cle)
    if cle in ("gel", "arret_bande"):
        e.params["intervalle"] = 0.5  # le clip de test dure à peine plus d'une seconde
    clip.effets.append(e)
    traite = _son(projet)
    assert np.abs(traite - source).max() > 0.05, "l'effet agit"
    n = len(traite)
    blocs = [1601, 7, 9000]
    blocs.append(n - sum(blocs))
    assert np.array_equal(_son(projet, blocs=blocs), traite)
    assert np.array_equal(_son(projet), traite)
