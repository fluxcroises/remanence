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
from tests import test_gpu

pytestmark = test_gpu.pytestmark  # sans OpenGL 4.3, pas de test d'effet


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


@pytest.mark.parametrize("cle", sorted(c for c, d in EFFETS.items() if not d.codec))
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
    clip.effets = [nouvel_effet("blocs_deplaces", "Mosaïque brisée")]
    assert not np.array_equal(_image(projet, 5), _image(projet, 6)), "le hasard change à chaque image"
    clip.effets[0].graine = 7
    sept = _image(projet, 5)
    clip.effets[0].graine = 8
    assert not np.array_equal(sept, _image(projet, 5)), "un autre tirage, une autre image"


def test_clip_d_effet_et_effet_de_sequence(medias):
    """Un clip d'effet et un effet de séquence transforment l'image comme un effet de clip."""
    projet, clip = _projet(medias)
    clip.effets = [nouvel_effet("decalage_rvb", "Anaglyphe")]
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
    edition.ajouter_clip_effet(seq, 10, 8, [nouvel_effet("vhs", "Copie de copie")])
    rapport = exporter(projet, seq, tmp_path / "fx.mov")
    assert rapport.images_calculees == 8 and rapport.images_recopiees == 22
    sortie = empreintes_images(str(tmp_path / "fx.mov"))
    source = empreintes_images(str(medias["prores_hq"]))
    assert sortie[:10] == source[:10] and sortie[18:] == source[18:]
    assert sortie[10:18] != source[10:18]


def test_sauvegarde_coupe_et_retrait(medias):
    projet, clip = _projet(medias)
    seq = projet.sequence
    edition.ajouter_effet(clip, nouvel_effet("tri_pixels", "Coulure verticale"))
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


def test_prereglages_personnels():
    from remanence.effets import prereglages as pr
    assert len(pr.fournis()) == sum(len(d.prereglages) for d in EFFETS.values())
    assert not pr.personnels()
    a, b = nouvel_effet("vhs", "Copie de copie"), nouvel_effet("scanlines")
    b.params["force"] = 33
    pr.enregistrer("Ma pile", [a, b])
    (p,) = pr.personnels()
    assert p.famille == pr.FAMILLE_PERSONNELS and p.description.startswith("Cassette VHS + Scanlines")
    poses = p.nouveaux_effets()
    assert [e.type for e in poses] == ["vhs", "scanlines"] and poses[1].params["force"] == 33
    assert p.correspond(poses) and not p.correspond(poses[:1])
    assert pr.depuis_mime(pr.vers_mime(p)).effets == p.effets
    pr.renommer("Ma pile", "Écran fatigué")
    assert [x.nom for x in pr.personnels()] == ["Écran fatigué"]
    pr.supprimer("Écran fatigué")
    assert not pr.personnels()


def test_images_cles_interpolation():
    from remanence.effets import instantane, poser_cle, retirer_cle, valeur_a
    e = nouvel_effet("decalage_rvb")
    poser_cle(e, "force", 0, 0.0)
    poser_cle(e, "force", 10, 100.0)
    assert [valeur_a(e, "force", t) for t in (-5, 0, 5, 10, 20)] == [0, 0, 50, 100, 100]
    e.cles["force"][0][2] = "palier"
    assert valeur_a(e, "force", 9) == 0
    poser_cle(e, "opacite", 4, 0.25)
    snap = instantane(e, 4)
    assert snap.opacite == 0.25 and snap.params["force"] == 0 and e.params["force"] == 40
    retirer_cle(e, "opacite", 4)
    assert "opacite" not in e.cles and e.opacite == 0.25, "redevient fixe à sa dernière valeur"
    v = nouvel_effet("tri_pixels")
    poser_cle(v, "vertical", 0, 1.0)
    assert v.cles["vertical"][0][2] == "palier", "un interrupteur ne s'interpole pas"


def test_animation_et_opacite_dans_l_image(medias):
    from remanence.effets import poser_cle
    projet, clip = _projet(medias)
    source = [_image(projet, f) for f in (0, 5, 10)]
    e = nouvel_effet("decalage_rvb")
    poser_cle(e, "force", 0, 0.0)
    poser_cle(e, "force", 10, 100.0)
    clip.effets = [e]
    assert np.abs(_image(projet, 0) - source[0]).max() < 1e-6, "force 0 au début"
    assert np.abs(_image(projet, 10) - source[2]).max() > 0.1
    e.cles.clear()
    e.params["force"] = 80
    plein = _image(projet, 5)
    e.opacite = 0.0
    assert np.abs(_image(projet, 5) - source[1]).max() < 1e-6, "opacité 0 : effet invisible"
    e.opacite = 0.5
    assert np.abs(_image(projet, 5) - (source[1] + plein) / 2).max() < 1e-5


@pytest.mark.parametrize("mode", ["addition", "ecran", "produit", "difference"])
def test_modes_de_fusion(medias, mode):
    """Un clip opaque posé sur un autre avec un mode : la formule du mode, pixel par pixel."""
    projet = Projet.nouveau()
    seq = projet.sequence
    for cle in ("prores_hq", "dnxhr_hqx"):
        infos, _ = analyser(str(medias[cle]))
        m = Media(nouvel_id(), str(medias[cle]), infos)
        projet.medias[m.id] = m
    fond, dessus = projet.medias.values()
    edition.ajouter_media(projet, seq, fond, 0)
    b = _image(projet, 3)[..., :3]
    edition.ajouter_piste(seq, "video")
    edition.ajouter_media(projet, seq, dessus, 0, piste=seq.pistes_video[0])
    s = _image(projet, 3)[..., :3]
    seq.pistes_video[0].clips[0].fusion = mode
    attendu = {"addition": b + s, "ecran": b + s - b * s, "produit": b * s,
               "difference": np.abs(b - s)}[mode]
    assert np.abs(_image(projet, 3)[..., :3] - attendu).max() < 1e-4


def test_rogner_le_debut_garde_les_cles_en_place(medias):
    from remanence.effets import poser_cle
    projet, clip = _projet(medias)
    e = nouvel_effet("vhs")
    poser_cle(e, "force", 10, 50.0)
    clip.effets = [e]
    edition.rogner(projet, projet.sequence, clip.id, "debut", 4)
    assert e.cles["force"][0][0] == 6, "même image de la séquence qu'avant"
    edition.couper(projet.sequence, 8)
    droite = projet.sequence.pistes_video[0].clips[1]
    assert droite.effets[0].cles["force"][0][0] == 2


def _masque_effet(projet, clip, *masques):
    e = nouvel_effet("decalage_rvb", "Anaglyphe")
    e.masques = list(masques)
    clip.effets = [e]
    return e


@pytest.mark.parametrize("forme", ["rectangle", "ellipse", "courbe"])
def test_hors_masque_l_image_est_la_source(medias, forme):
    """Validation de l'étape 2 : hors masque, image identique à la source au pixel près."""
    from remanence.effets.masques import nouveau_masque
    projet, clip = _projet(medias)
    source = _image(projet)
    clip.effets = [nouvel_effet("decalage_rvb", "Anaglyphe")]
    plein = _image(projet)
    m = nouveau_masque(forme)
    m.adoucissement = 2.0
    _masque_effet(projet, clip, m)
    img = _image(projet)
    h, l = img.shape[:2]
    y, x = np.mgrid[0:h, 0:l]
    loin = (np.abs(x / l - 0.5) > 0.32) | (np.abs(y / h - 0.5) > 0.32)
    centre = (np.abs(x / l - 0.5) < 0.08) & (np.abs(y / h - 0.5) < 0.08)
    assert np.array_equal(img[loin], source[loin]), "hors masque : la source, exactement"
    assert np.abs(img[centre] - plein[centre]).max() < 1e-5, "dans le masque : l'effet entier"
    m.inverse = True
    inv = _image(projet)
    assert np.array_equal(inv[centre], source[centre])


def test_combinaison_et_adoucissement(medias):
    from remanence.effets.masques import nouveau_masque
    projet, clip = _projet(medias)
    source = _image(projet)
    grand, trou = nouveau_masque("rectangle"), nouveau_masque("ellipse")
    trou.points = [[0.4, 0.4], [0.6, 0.6]]
    trou.mode = "soustraction"
    _masque_effet(projet, clip, grand, trou)
    img = _image(projet)
    h, l = img.shape[:2]
    assert np.array_equal(img[h // 2, l // 2], source[h // 2, l // 2]), "le trou est soustrait"
    assert not np.array_equal(img[int(h * 0.3), int(l * 0.3)], source[int(h * 0.3), int(l * 0.3)])
    grand.mode, trou.mode = "addition", "intersection"
    img = _image(projet)
    assert np.array_equal(img[int(h * 0.3), int(l * 0.3)], source[int(h * 0.3), int(l * 0.3)])
    # Adoucissement : une rampe, ni 0 ni 1, de part et d'autre du bord.
    seul = nouveau_masque("rectangle")
    seul.adoucissement = 10.0
    _masque_effet(projet, clip, seul)
    clip.effets[0].params["force"] = 100
    clip.effets[0].fusion = "difference"
    a = _image(projet)
    bord = a[h // 2, int(l * 0.22):int(l * 0.28), 0]
    assert len(np.unique(np.round(bord, 4))) > 2


def test_masques_enregistres(medias):
    from remanence.effets.masques import contour, nouveau_masque
    projet, clip = _projet(medias)
    e = _masque_effet(projet, clip, nouveau_masque("courbe"))
    e.masques[0].expansion = -3.0
    relu = Projet.depuis_dict(projet.vers_dict()).sequence.pistes_video[0].clips[0].effets[0]
    assert relu.masques[0].forme == "courbe" and relu.masques[0].expansion == -3.0
    assert len(contour(relu.masques[0].points)) <= 128
    edition.couper(projet.sequence, 10)
    a, b = projet.sequence.pistes_video[0].clips
    assert a.effets[0].masques[0].id != b.effets[0].masques[0].id


@pytest.mark.parametrize("cle", sorted(c for c, d in EFFETS.items() if d.codec))
def test_effets_codec(medias, tmp_path, cle):
    """Moteur codec : pré-rendu de même durée, recomposé dans l'image ; à l'export, calculé
    sur-le-champ et recopie de la source hors du clip."""
    from remanence.moteurs.codec import prerendu
    projet, clip = _projet(medias)
    seq = projet.sequence
    source = _image(projet, 20)
    effet = nouvel_effet(cle, list(EFFETS[cle].prereglages)[-1])
    clip.effets = [effet]
    assert prerendu.pret(projet, seq, clip) is None
    c = Compositeur(projet)
    try:
        sans = c.image(seq, 20)
        assert np.array_equal(sans, source) and clip.id in c.manquants, "pas encore calculé"
    finally:
        c.fermer()
    fichier = prerendu.calculer(projet, seq, clip)
    infos, _ = analyser(str(fichier))
    assert infos.video.nb_images == clip.duree
    mosh = _image(projet, 20)
    assert np.abs(mosh - source).max() > 0.02, "le datamosh se voit"
    assert np.array_equal(mosh, _image(projet, 20)), "déterministe"
    effet.opacite = 0.0
    assert np.array_equal(_image(projet, 20), source)
    effet.opacite = 1.0
    clip.effets = [nouvel_effet(cle, list(EFFETS[cle].prereglages)[0])]
    rapport = exporter(projet, seq, tmp_path / "mosh.mov")
    assert rapport.conforme and rapport.images_calculees == 30
    with pytest.raises(edition.EditionImpossible):
        edition.ajouter_effet(seq.pistes_video[0], nouvel_effet(cle))
