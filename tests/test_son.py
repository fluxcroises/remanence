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
    assert r1.audio != "recopié sans réencodage"

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


def test_le_son_bave_avec_l_image(medias):
    """Lot 3 : pendant la transition datamosh, le grain du plan d'avant tourne et s'efface ;
    ailleurs le son ne change pas ; le résultat ne dépend pas du découpage."""
    projet, _ = _projet(medias)
    seq = projet.sequence
    m = next(iter(projet.medias.values()))
    for p in seq.pistes:
        p.clips.clear()
    edition.ajouter_media(projet, seq, m, 0, duree=15)
    edition.ajouter_media(projet, seq, m, 15, entree=10, duree=15)
    v2 = seq.pistes_video[0].clips[1]
    edition.basculer_transition(seq, v2.id, 8)
    source = _son(projet)
    v2.son_bave = True
    bave = _son(projet)
    par_image = 48000 / float(seq.fraction_cadence)
    a, b = round(15 * par_image), round(23 * par_image)
    assert np.array_equal(bave[:a], source[:a]) and np.array_equal(bave[b:], source[b:])
    assert np.abs(bave[a:b] - source[a:b]).max() > 0.01
    blocs = [777, 9001, 333]
    blocs.append(len(bave) - sum(blocs))
    assert np.array_equal(_son(projet, blocs=blocs), bave)


NEUTRES = {"bitcrusher": {"bits": 16, "reduction": 1}, "begaiement": {"probabilite": 0},
           "inversion_fragments": {"probabilite": 0}, "gel": {"probabilite": 0},
           "arret_bande": {"probabilite": 0}}


def _paquets_audio(chemin):
    with av.open(str(chemin)) as c:
        return [bytes(p) for p in c.demux(audio=0) if p.size]


@pytest.mark.parametrize("cle", AUDIO)
def test_effet_audio_a_zero_son_recopie(medias, tmp_path, cle):
    """Validation de l'étape 12 : réglé à zéro (ou mélange nul), un effet audio laisse le son
    intact, et l'export recopie le son d'origine, au bit près."""
    projet, clip = _projet(medias)
    e = nouvel_effet(cle)
    if cle in NEUTRES:
        e.params.update(NEUTRES[cle])
    else:
        e.opacite = 0.0  # le databending repasse toujours par le codec : mélange nul
    clip.effets.append(e)
    seq = projet.sequence
    r = exporter(projet, seq, tmp_path / "zero.mov")
    assert r.audio == "recopié sans réencodage"
    assert _paquets_audio(tmp_path / "zero.mov") == _paquets_audio(medias["prores_hq"])


def test_six_effets_exportes_deux_fois(medias, tmp_path):
    """Validation : les six effets empilés (graines, hasard, codec) donnent deux exports au
    son identique."""
    projet, clip = _projet(medias)
    for cle in AUDIO:
        e = nouvel_effet(cle)
        if cle in ("gel", "arret_bande"):
            e.params["intervalle"] = 0.5
        clip.effets.append(e)
    seq = projet.sequence
    exporter(projet, seq, tmp_path / "a.mov")
    exporter(projet, seq, tmp_path / "b.mov")
    a, b = _paquets_audio(tmp_path / "a.mov"), _paquets_audio(tmp_path / "b.mov")
    assert a == b and a != _paquets_audio(medias["prores_hq"])


def test_lecture_fluide_avec_trois_effets(medias):
    """Validation : trois effets audio calculés par blocs de 1024 échantillons (ceux de la
    lecture), bien plus vite que le temps réel."""
    import time
    projet, clip = _projet(medias)
    for cle in ("begaiement", "gel", "databending_audio"):
        clip.effets.append(nouvel_effet(cle))
    seq = projet.sequence
    n = int(seq.duree() * 48000 / float(seq.fraction_cadence))
    c = Compositeur(projet)
    try:
        c.audio(seq, 0, 1024)
        t = time.perf_counter()
        for debut in range(0, n, 1024):
            c.audio(seq, debut, 1024)
        duree = time.perf_counter() - t
    finally:
        c.fermer()
    assert duree < 0.5 * n / 48000, f"{duree:.3f} s pour {n / 48000:.2f} s de son"
