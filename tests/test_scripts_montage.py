"""Scripts de glitch sur la timeline : Scramble, Layer, Automator."""

import pytest

from remanence.effets import nouvel_effet, valeur_a
from remanence.media.sonde import analyser
from remanence.projet import edition, scripts_montage
from remanence.projet.modele import Media, Projet, nouvel_id


def _projet(medias):
    projet = Projet.nouveau()
    infos, _ = analyser(str(medias["prores_hq"]))
    m = Media(nouvel_id(), str(medias["prores_hq"]), infos)
    projet.medias[m.id] = m
    edition.ajouter_media(projet, projet.sequence, m, 0)
    return projet, projet.sequence


def test_scramble(medias):
    projet, seq = _projet(medias)
    video = seq.pistes_video[0].clips[0]
    duree, entree = video.duree, video.entree
    ids = scripts_montage.scramble(seq, {video.id}, 6, graine=3)
    morceaux = seq.pistes_video[0].clips
    assert len(morceaux) == -(-duree // 6) and len(ids) == 2 * len(morceaux), "image et son"
    assert sum(c.duree for c in morceaux) == duree, "rien ne se perd"
    assert [c.debut for c in morceaux] == sorted(c.debut for c in morceaux)
    assert morceaux[-1].fin == duree and morceaux[0].debut == 0, "même place, sans trou"
    entrees = [c.entree for c in morceaux]
    assert entrees != sorted(entrees), "l'ordre est rebattu"
    assert sorted(entrees) == list(range(entree, entree + duree, 6))
    for c in morceaux:  # le son suit son image
        son = next(a for a in seq.pistes_audio[0].clips if a.lien == c.lien)
        assert (son.debut, son.entree) == (c.debut, c.entree)
    projet2, seq2 = _projet(medias)
    scripts_montage.scramble(seq2, {seq2.pistes_video[0].clips[0].id}, 6, graine=3)
    assert [c.entree for c in seq2.pistes_video[0].clips] == entrees, "même graine, même ordre"


def test_layer(medias):
    projet, seq = _projet(medias)
    video = seq.pistes_video[0].clips[0]
    poses = scripts_montage.layer(seq, {video.id}, 3, 4, 0.3, "ecran")
    assert len(poses) == 3 and len(seq.pistes_video) == 4
    # Les pistes d'écho au-dessus de l'original, la plus décalée tout en haut.
    copies = [p.clips[0] for p in seq.pistes_video[:3]]
    assert [c.debut for c in copies] == [12, 8, 4]
    assert copies[0].gain == pytest.approx(0.7 ** 3) and copies[2].fusion == "ecran"
    assert all(c.lien is None and c.id != video.id for c in copies)
    with pytest.raises(edition.EditionImpossible):
        scripts_montage.layer(seq, {seq.pistes_audio[0].clips[0].id}, 2, 4, 0.3)


def test_automator(medias):
    projet, seq = _projet(medias)
    effet = nouvel_effet("decalage_rvb")
    scripts_montage.automator(effet, ["force"], 0, 20, 5, 1.0, "lineaire", graine=9)
    cles = effet.cles["force"]
    assert [k[0] for k in cles] == [0, 5, 10, 15, 20]
    assert all(0 <= k[1] <= 100 for k in cles) and len({k[1] for k in cles}) > 2
    assert valeur_a(effet, "force", 2.5) == pytest.approx((cles[0][1] + cles[1][1]) / 2)
    autre = nouvel_effet("decalage_rvb")
    scripts_montage.automator(autre, ["force"], 0, 20, 5, 1.0, "lineaire", graine=9)
    assert autre.cles == effet.cles, "même graine, mêmes images clés"
    etroit = nouvel_effet("decalage_rvb")
    scripts_montage.automator(etroit, ["force"], 0, 20, 5, 0.2, "palier", graine=9)
    assert all(30 <= k[1] <= 50 and k[2] == "palier" for k in etroit.cles["force"]), \
        "autour de 40, sur 20 % de la plage"
    with pytest.raises(edition.EditionImpossible):
        scripts_montage.automator(nouvel_effet("bloom"), ["force"], 0, 20, 5, 1, "lineaire", 1)
