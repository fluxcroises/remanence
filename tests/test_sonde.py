from fractions import Fraction

import pytest

from remanence.media.sonde import MediaIllisible, analyser


def test_fiche_prores_hq(medias):
    infos, index = analyser(str(medias["prores_hq"]))
    v = infos.video
    assert (v.codec, v.profil, v.bits, v.echantillonnage) == ("prores", "HQ", 10, "4:2:2")
    assert Fraction(v.cadence) == Fraction(24000, 1001)
    assert v.nb_images == len(index) == 30
    assert v.tc_texte == "01:00:00:00"
    assert (v.couleur.primaires, v.couleur.transfert, v.couleur.matrice) == (1, 1, 1)
    assert infos.audio and infos.audio[0].bits == 24
    assert any(cle == "Timecode" for cle, _ in infos.fiche())


def test_alpha_et_drop_frame(medias):
    v = analyser(str(medias["prores_4444"]))[0].video
    assert v.alpha and v.tc_texte == "10:00:00:00"
    v = analyser(str(medias["dnxhr_hqx"]))[0].video
    assert v.tc_drop and v.tc_texte == "00:59:59;00"


def test_cadence_variable_signalee(medias):
    infos, _ = analyser(str(medias["vfr"]))
    assert infos.video.cadence_variable
    assert any("Cadence variable" in a for a in infos.avertissements)


def test_entrelace_signale(medias):
    infos, _ = analyser(str(medias["entrelace"]))
    assert infos.video.entrelace


def test_dimensions_impaires(medias):
    v = analyser(str(medias["portrait_impair"]))[0].video
    assert (v.largeur, v.hauteur) == (181, 321)


def test_sequence_dpx(medias):
    infos, index = analyser(str(medias["dpx"]), "24")
    assert infos.sequence_images["premier"] == 100
    assert len(index) == 10 and infos.video.bits == 16


def test_raw_explique(tmp_path):
    f = tmp_path / "A001.braw"
    f.write_bytes(b"\0" * 16)
    with pytest.raises(MediaIllisible, match="ProRes"):
        analyser(str(f))


def test_fichier_absent():
    with pytest.raises(MediaIllisible, match="introuvable"):
        analyser("C:/nulle_part/plan.mov")
