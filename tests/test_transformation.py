"""Étape 8, lot 1 : position, taille, rotation, recadrage et retournement des clips."""

import numpy as np

from remanence.effets import poser_cle, transformation
from remanence.projet import edition
from remanence.media.sonde import analyser
from remanence.projet.modele import Media, Projet, nouvel_id
from remanence.rendu.composition import Compositeur, couches, identite
from remanence.rendu.conformite import empreintes_images
from remanence.rendu.export import exporter
from tests import test_gpu
from tests.test_effets import _projet

pytestmark = test_gpu.pytestmark  # la transformation est calculée par la carte graphique


def _image(projet, f=5):
    c = Compositeur(projet)
    try:
        return c.image(projet.sequence, f)
    finally:
        c.fermer()


def _transformer(clip, **reglages):
    clip.transformation = transformation.nouvelle()
    clip.transformation.params.update(reglages)
    return clip.transformation


def test_sans_transformation_rien_ne_change(medias, tmp_path):
    projet, clip = _projet(medias)
    source = _image(projet)
    _transformer(clip)
    assert np.array_equal(_image(projet), source)
    seq = projet.sequence
    assert identite(couches(projet, seq, 5), seq, 5) is not None
    rapport = exporter(projet, seq, tmp_path / "neutre.mov")
    assert rapport.images_calculees == 0
    assert empreintes_images(str(tmp_path / "neutre.mov")) == \
        empreintes_images(str(medias["prores_hq"]))


def test_deplacement_au_pixel_pres(medias):
    projet, clip = _projet(medias)
    source = _image(projet)
    # 320 × 180 : 10 px à droite, 9 px vers le bas.
    _transformer(clip, x=10 / 320 * 100, y=9 / 180 * 100)
    image = _image(projet)
    assert identite(couches(projet, projet.sequence, 5), projet.sequence, 5) is None
    assert np.array_equal(image[9:, 10:], source[:-9, :-10])
    assert not image[:9].any() and not image[:, :10].any()  # transparent


def test_retournements_et_demi_tour(medias):
    projet, clip = _projet(medias)
    source = _image(projet)
    _transformer(clip, miroir_h=1)
    assert np.array_equal(_image(projet), source[:, ::-1])
    _transformer(clip, miroir_v=1)
    assert np.array_equal(_image(projet), source[::-1])
    _transformer(clip, rotation=180)
    assert np.abs(_image(projet) - source[::-1, ::-1]).max() < 1e-4


def test_rotation_d_un_quart_de_tour(medias):
    projet, clip = _projet(medias)
    source = _image(projet)
    _transformer(clip, rotation=90)
    image = _image(projet)
    # Sens inverse des aiguilles d'une montre : le bord droit de la source monte en haut.
    # Le carré central de 180 × 180 se retrouve tourné.
    c = source[:, 70:250]
    attendu = np.rot90(c, 1)
    assert np.abs(image[:, 70:250] - attendu).max() < 1e-4
    assert not image[:, :20].any()  # hors de l'image tournée : transparent


def test_reduction_et_recadrage(medias):
    projet, clip = _projet(medias)
    source = _image(projet)
    _transformer(clip, taille=50)
    image = _image(projet)
    assert not image[:44, :].any() and not image[:, :79].any()
    centre = image[46:134, 81:239]
    assert np.allclose(centre[..., 3], 1.0)
    assert abs(centre[..., :3].mean() - source[..., :3].mean()) < 0.03
    _transformer(clip, rognage_gauche=25, rognage_haut=10)
    image = _image(projet)
    assert not image[:, :80].any() and not image[:18].any()
    assert np.array_equal(image[18:, 80:], source[18:, 80:])


def test_animation_exportee_deux_fois(medias, tmp_path):
    """Validation : une position animée donne deux exports identiques, conformes à
    l'aperçu."""
    projet, clip = _projet(medias)
    t = _transformer(clip, rotation=15, taille=70)
    poser_cle(t, "x", 0, -20)
    poser_cle(t, "x", 29, 20)
    seq = projet.sequence
    r1 = exporter(projet, seq, tmp_path / "a.mov", "prores_4444")
    r2 = exporter(projet, seq, tmp_path / "b.mov", "prores_4444")
    assert r1.conforme and r1.images_calculees == 30
    assert empreintes_images(str(tmp_path / "a.mov")) == empreintes_images(str(tmp_path / "b.mov"))
    # Après la dernière image clé, la position reste là où elle est arrivée.
    assert transformation.neutre({"x": 0}) and couches(projet, seq, 29)[0].effets
    apercu = _image(projet, 12)
    relu = Projet.nouveau()
    infos, _ = analyser(str(tmp_path / "a.mov"))
    m = Media(nouvel_id(), str(tmp_path / "a.mov"), infos)
    relu.medias[m.id] = m
    edition.ajouter_media(relu, relu.sequence, m, 0)
    exporte = _image(relu, 12)
    assert np.abs(exporte - apercu).mean() < 0.002


def test_enregistree_coupee_et_rognee(medias):
    projet, clip = _projet(medias)
    t = _transformer(clip, taille=80)
    poser_cle(t, "rotation", 10, 0)
    poser_cle(t, "rotation", 20, 90)
    copie = Projet.depuis_dict(projet.vers_dict())
    c2 = copie.sequence.pistes_video[0].clips[0]
    assert c2.transformation.params["taille"] == 80
    assert c2.transformation.cles["rotation"][1][:2] == [20, 90]
    seq = projet.sequence
    droite = edition.couper(seq, 15)
    gauche_t = clip.transformation
    nouveau = next(c for c in seq.pistes_video[0].clips if c.id in droite)
    assert nouveau.transformation.id != gauche_t.id
    # La rotation reste à sa place à l'écran.
    assert np.array_equal(_image(projet, 18), _image(copie, 18))
