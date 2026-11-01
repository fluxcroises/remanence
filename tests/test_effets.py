"""Effets en temps réel : rendu, déterminisme, niveaux d'application, export, sauvegarde."""

import numpy as np
import pytest

from remanence.effets import EFFETS, nouvel_effet
from remanence.media.sonde import analyser
from remanence.projet import edition
from remanence.projet.modele import Media, Projet, nouvel_id
from remanence.rendu.composition import Compositeur
from remanence.rendu.export import exporter
from tests.test_export import empreintes_images
from tests.test_gpu import pytestmark  # noqa: F401  (sans OpenGL 4.3, pas de test d'effet)


def _projet(medias, cle="prores_hq"):
    projet = Projet.nouveau()
    infos, _ = analyser(str(medias[cle]))
    m = Media(nouvel_id(), str(medias[cle]), infos)
    projet.medias[m.id] = m
    edition.ajouter_media(projet, projet.sequence, m, 0)
    return projet, projet.sequence.pistes_video[0].clips[0]


def _image(projet, f=5, echelle=1.0):
    c = Compositeur(projet)
    try:
        return c.image(projet.sequence, f, echelle)
    finally:
        c.fermer()


@pytest.mark.parametrize("cle", sorted(EFFETS))
def test_chaque_effet_a_0_50_et_100(medias, cle):
    projet, clip = _projet(medias)
    source = _image(projet)
    for force in (0, 50, 100):
        effet = nouvel_effet(cle)
        effet.params["force"] = force
        clip.effets = [effet]
        a, b = _image(projet), _image(projet)
        assert np.array_equal(a, b), "deux rendus identiques"
        assert np.isfinite(a).all() and a.shape == source.shape
        if force == 0:
            assert np.abs(a - source).max() < 1e-6, "à zéro, l'image est intacte"
        else:
            assert np.abs(a - source).max() > 0.01, "l'effet se voit"
        assert _image(projet, echelle=0.5).shape[0] == source.shape[0] // 2


def test_prereglages_et_animation(medias):
    projet, clip = _projet(medias)
    for cle, d in EFFETS.items():
        assert len(d.prereglages) >= 3, d.nom
        for nom in d.prereglages:
            clip.effets = [nouvel_effet(cle, nom)]
            _image(projet)
    clip.effets = [nouvel_effet("blocs_deplaces", "Chaos")]
    assert not np.array_equal(_image(projet, 5), _image(projet, 6)), "le hasard change à chaque image"
    clip.effets[0].graine = 7
    sept = _image(projet, 5)
    clip.effets[0].graine = 8
    assert not np.array_equal(sept, _image(projet, 5)), "un autre tirage, une autre image"


def test_clip_d_effet_et_effet_de_sequence(medias):
    """Un clip d'effet et un effet de séquence transforment l'image comme un effet de clip."""
    projet, clip = _projet(medias)
    clip.effets = [nouvel_effet("decalage_rvb", "Fort")]
    reference = _image(projet)
    effet = clip.effets.pop()
    seq = projet.sequence
    c = edition.ajouter_clip_effet(seq, 0, 30, [effet])
    assert c.est_effet and len(seq.pistes_video) == 2, "nouvelle piste : V1 est occupée"
    assert np.abs(_image(projet) - reference).max() < 1e-6
    c.gain = 0.5
    moitie = _image(projet)
    source = _image(_sans_effets(projet))
    assert np.abs(moitie - (source + reference) / 2).max() < 1e-5, "dosage par l'opacité"
    seq.pistes_video[0].clips.clear()
    seq.effets = [effet]
    assert np.abs(_image(projet) - reference).max() < 1e-6


def _sans_effets(projet):
    p = Projet.depuis_dict(projet.vers_dict())
    for piste in p.sequence.pistes:
        piste.clips = [c for c in piste.clips if not c.est_effet]
        for c in piste.clips:
            c.effets = []
    p.sequence.effets = []
    return p


def test_hors_clip_d_effet_l_export_est_la_source(medias, tmp_path):
    """Validation de l'étape 2 : hors du clip d'effet, les images exportées sont celles de la
    source, au pixel près ; dessous, elles sont recalculées."""
    projet, _ = _projet(medias)
    seq = projet.sequence
    edition.ajouter_clip_effet(seq, 10, 8, [nouvel_effet("vhs", "Fatiguée")])
    rapport = exporter(projet, seq, tmp_path / "fx.mov")
    assert rapport.images_calculees == 8 and rapport.images_recopiees == 22
    sortie = empreintes_images(str(tmp_path / "fx.mov"))
    source = empreintes_images(str(medias["prores_hq"]))
    assert sortie[:10] == source[:10] and sortie[18:] == source[18:]
    assert sortie[10:18] != source[10:18]


def test_sauvegarde_coupe_et_retrait(medias):
    projet, clip = _projet(medias)
    seq = projet.sequence
    edition.ajouter_effet(clip, nouvel_effet("tri_pixels", "Vertical"))
    edition.ajouter_effet(seq.pistes_video[0], nouvel_effet("scanlines"))
    seq.effets.append(nouvel_effet("vhs"))
    relu = Projet.depuis_dict(projet.vers_dict())
    assert relu.sequence.pistes_video[0].clips[0].effets[0].params["vertical"] == 1
    assert relu.sequence.pistes_video[0].effets[0].type == "scanlines"
    assert relu.sequence.effets[0].type == "vhs"
    ancien = projet.vers_dict()
    for sd in ancien["sequences"]:
        sd.pop("effets")
        for pd in sd["pistes"]:
            pd.pop("effets")
            for cd in pd["clips"]:
                cd.pop("effets")
    assert not Projet.depuis_dict(ancien).sequence.effets, "projet d'avant l'étape 2"
    edition.couper(seq, 10)
    a, b = seq.pistes_video[0].clips
    assert a.effets[0].id != b.effets[0].id, "chaque morceau a ses propres effets"
    edition.retirer_effet(seq, b.effets[0].id)
    assert not b.effets and a.effets
    with pytest.raises(edition.EditionImpossible):
        edition.ajouter_effet(seq.pistes_audio[0], nouvel_effet("vhs"))
