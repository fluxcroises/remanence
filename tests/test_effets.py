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


def test_effet_entre_ses_images_cles(medias, tmp_path):
    """Un effet animé n'agit qu'entre sa première et sa dernière image clé ; hors de cette
    plage, l'export recopie la source. Une seule image clé : l'effet agit partout."""
    from remanence.effets import poser_cle
    projet, clip = _projet(medias)
    seq = projet.sequence
    source = {f: _image(projet, f) for f in (2, 5, 8, 20)}
    e = nouvel_effet("decalage_rvb")
    e.params["force"] = 80
    poser_cle(e, "force", 5, 80)
    clip.effets = [e]
    assert np.abs(_image(projet, 2) - source[2]).max() > 0.1, "une seule clé : partout"
    poser_cle(e, "force", 8, 80)
    assert np.abs(_image(projet, 2) - source[2]).max() < 1e-6, "avant la première clé"
    assert np.abs(_image(projet, 20) - source[20]).max() < 1e-6, "après la dernière clé"
    assert np.abs(_image(projet, 5) - source[5]).max() > 0.1
    assert np.abs(_image(projet, 8) - source[8]).max() > 0.1
    rapport = exporter(projet, seq, tmp_path / "entre.mov")
    assert rapport.conforme
    assert rapport.images_calculees == 4 and rapport.images_recopiees == clip.duree - 4


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


def _deux_plans(medias):
    """Deux plans ProRes à la suite : 422 HQ (20 images), puis 422 LT."""
    projet = Projet.nouveau()
    seq = projet.sequence
    for cle in ("prores_hq", "sans_audio_2997"):
        infos, _ = analyser(str(medias[cle]))
        m = Media(nouvel_id(), str(medias[cle]), infos)
        projet.medias[m.id] = m
    a, b = projet.medias.values()
    edition.ajouter_media(projet, seq, a, 0, duree=20)
    edition.ajouter_media(projet, seq, b, 20)
    return projet, seq, seq.pistes_video[0].clips[0], seq.pistes_video[0].clips[1]


@pytest.fixture(params=["ffglitch", "bavure"])
def moteur(request, monkeypatch):
    """Les deux moteurs codec : FFglitch (s'il est installé) et Bavure, le moteur de secours."""
    from remanence.moteurs.codec import ffglitch
    if request.param == "bavure":
        monkeypatch.setenv(ffglitch.VARIABLE, "")
    elif not ffglitch.disponible():
        pytest.skip("FFglitch n'est pas installé")
    return request.param


def test_transition_datamosh(medias, tmp_path, moteur):
    """Validation de l'étape 3 : deux plans ProRes enchaînés produisent une transition qui
    bave, et le plan exporté se réintègre au montage sans décalage."""
    from remanence.moteurs.codec import prerendu
    projet, seq, a, b = _deux_plans(medias)
    fin_a = _image(projet, a.fin - 1)
    propre = [_image(projet, b.debut + t) for t in range(b.duree)]
    edition.basculer_transition(seq, b.id, 8)
    assert b.transition.duree == 8
    prerendu.calculer_source(projet, seq, b)
    moshe = [_image(projet, b.debut + t) for t in range(b.duree)]
    ecart = lambda x, y: float(np.abs(x[..., :3] - y[..., :3]).mean())
    assert ecart(moshe[1], fin_a) < ecart(propre[1], fin_a), "le premier plan bave dans le second"
    assert all(np.array_equal(moshe[t], propre[t]) for t in range(8, b.duree)), \
        "après la transition, la source intacte"
    sortie = tmp_path / "plan_b.mov"
    rapport = exporter(projet, seq, sortie, debut=b.debut, fin=b.fin)
    assert rapport.conforme, [(v.critere, v.obtenu) for v in rapport.verifications if not v.ok]
    # Le plan LT est en 29,97 dans une séquence en 23,976 : réencodé en entier, pas recopié.
    assert rapport.images_calculees + rapport.images_recopiees == b.duree
    infos, _ = analyser(str(sortie))
    assert infos.video.nb_images == b.duree
    assert infos.video.tc_debut == seq.tc_debut + b.debut, "même timecode que dans le montage"


def test_transition_et_coupes_au_montage(medias):
    projet, seq, a, b = _deux_plans(medias)
    with pytest.raises(edition.EditionImpossible):
        edition.basculer_transition(seq, a.id)  # rien avant le premier clip
    edition.basculer_transition(seq, b.id)
    edition.couper(seq, b.debut + 5)
    gauche, droite = seq.pistes_video[0].clips[1:]
    assert gauche.transition is not None and droite.transition is None, "la coupe reste franche"
    edition.basculer_cle(seq, gauche.id, 3)
    edition.rogner(projet, seq, gauche.id, "debut", 1)
    assert seq.trouver(gauche.id)[1].cles_supprimees == [2]
    relu = Projet.depuis_dict(projet.vers_dict()).sequence.trouver(gauche.id)[1]
    assert relu.transition.duree == gauche.transition.duree and relu.cles_supprimees == [2]
    edition.basculer_transition(seq, gauche.id)
    assert seq.trouver(gauche.id)[1].transition is None


def test_vecteurs_animes(medias, monkeypatch):
    """FFglitch : le script généré reçoit la valeur de chaque image ; sans FFglitch, l'effet
    reste sans action."""
    from remanence.effets import poser_cle
    from remanence.effets.vecteurs import script
    from remanence.moteurs.codec import ffglitch, prerendu
    if not ffglitch.disponible():
        pytest.skip("FFglitch n'est pas installé")
    projet, clip = _projet(medias)
    seq = projet.sequence
    source = _image(projet, 20)
    effet = nouvel_effet("vecteurs")
    clip.effets = [effet]
    neutre = prerendu.calculer(projet, seq, clip)
    ecart = lambda x, y: float(np.abs(x[..., :3] - y[..., :3]).mean())
    assert ecart(_image(projet, 20), source) < 0.02, "réglages neutres : presque la source"
    poser_cle(effet, "horizontal", 0, 100)
    poser_cle(effet, "horizontal", clip.duree - 1, -400)
    assert EFFETS["vecteurs"].animable and not EFFETS["bloom"].animable
    js = script([{p.cle: 1.0 for p in EFFETS["vecteurs"].parametres}] * 3, 7)
    assert "glitch_frame" in js and "let graine = 7" in js
    anime = prerendu.calculer(projet, seq, clip)
    assert anime != neutre, "une image clé change le pré-rendu"
    assert ecart(_image(projet, 3), source) < ecart(_image(projet, clip.duree - 1), source),         "l'effet grandit avec l'animation"
    monkeypatch.setenv(ffglitch.VARIABLE, "")
    assert prerendu.cle(projet, seq, clip) != anime.stem.split("_")[1], "autre moteur"
    prerendu.calculer(projet, seq, clip)
    assert ecart(_image(projet, 20), source) < 0.02, "sans FFglitch, sans action"


def test_transfert_mouvement(medias):
    """Les vecteurs du clip de la piste au-dessus remplacent ceux du clip."""
    from remanence.moteurs.codec import ffglitch, prerendu
    if not ffglitch.disponible():
        pytest.skip("FFglitch n'est pas installé")
    projet, clip = _projet(medias)
    seq = projet.sequence
    effet = nouvel_effet("transfert_mouvement")
    effet.params["force"] = 0
    clip.effets = [effet]
    assert edition.clip_au_dessus(seq, clip) is None
    seul = prerendu.calculer(projet, seq, clip)
    dessus = edition.ajouter_piste(seq, "video")
    infos, _ = analyser(str(medias["h264"]))
    m = Media(nouvel_id(), str(medias["h264"]), infos)
    projet.medias[m.id] = m
    edition.ajouter_media(projet, seq, m, 0, piste=dessus)
    autre = edition.clip_au_dessus(seq, clip)
    assert autre is not None and autre.media_id == m.id
    sans = prerendu.calculer(projet, seq, clip)
    assert sans != seul, "le clip au-dessus entre dans l'empreinte"
    dessus.masquee = True  # la piste source se cache, son mouvement reste
    a = _image(projet, 20)
    effet.params["force"] = 100
    prerendu.calculer(projet, seq, clip)
    b = _image(projet, 20)
    assert np.abs(a - b).max() > 0.02, "le mouvement emprunté se voit"


# Script écrit pour FFglitch 0.9 (sans export ni setup), comme ceux de dd_GlitchAssist.
SCRIPT_ANCIEN = """// test
var force = 3;
var compteur = 0;
let seuil = 0.5;

function glitch_frame(frame)
{
    compteur++;
    let mvs = frame["mv"];
    if ( !mvs )
        return;
    let fwd = mvs["forward"];
    if ( !fwd )
        return;
    for ( let i = 0; i < fwd.length; i++ )
        for ( let j = 0; j < fwd[i].length; j++ )
            if ( Math.random() > seuil )
                fwd[i][j][0] = fwd[i][j][0] * force;
}
"""


def test_scripts_de_la_bibliotheque(medias, tmp_path):
    """Réglages lus dans le script (pas les compteurs), ancien format accepté, hasard
    reproductible, import d'un dossier."""
    from remanence.effets import prereglages
    from remanence.moteurs.codec import ffglitch, prerendu, scripts
    assert scripts.reglages(SCRIPT_ANCIEN) == {"force": 3.0, "seuil": 0.5}
    adapte = scripts.adapter(SCRIPT_ANCIEN, {"force": 6, "seuil": 0.25}, 9)
    assert "var force = 6;" in adapte and "let seuil = 0.25;" in adapte
    assert "export function glitch_frame" in adapte and "Math.random = hasard" in adapte
    fournis = scripts.bibliotheque()
    assert {"Moyenne du mouvement", "Panoramique"} <= set(fournis)
    source = tmp_path / "mes scripts" / "dd"
    source.mkdir(parents=True)
    (source / "Multiplier_X.js").write_text(SCRIPT_ANCIEN, encoding="utf-8")
    assert scripts.importer(tmp_path / "mes scripts") == 1
    p = next(p for p in prereglages.fournis() if p.nom == "Multiplier X")
    assert p.famille == "Scripts"
    effet = p.nouveaux_effets()[0]
    assert effet.script == SCRIPT_ANCIEN and effet.params["force"] == 3
    assert not EFFETS["script_ffglitch"].animable
    if not ffglitch.disponible():
        return
    projet, clip = _projet(medias)
    seq = projet.sequence
    source_img = _image(projet, 20)
    effet.params["force"] = 8
    clip.effets = [effet]
    a = prerendu.calculer(projet, seq, clip)
    image = _image(projet, 20)
    assert np.abs(image - source_img).max() > 0.02, "le script agit"
    a.unlink()
    prerendu.calculer(projet, seq, clip)
    assert np.array_equal(_image(projet, 20), image), "même graine, même résultat"


def test_moteur_flux_optique(medias):
    """Flux optique : cache en 16 bits ; sans persistance, l'image est la source (aucune perte
    par le moteur) ; les réglages s'animent ; la bavure suit le mouvement."""
    import av
    from remanence.effets import poser_cle
    from remanence.moteurs import flux
    from remanence.moteurs.codec import prerendu
    projet, clip = _projet(medias)
    seq = projet.sequence
    source = {f: _image(projet, f) for f in (5, 25)}
    effet = nouvel_effet("persistance")
    effet.params["persistance"] = 0
    clip.effets = [effet]
    fichier = prerendu.calculer(projet, seq, clip)
    with av.open(str(fichier)) as c:
        assert c.streams.video[0].codec_context.pix_fmt == prerendu.FORMAT_FLUX
    assert np.abs(_image(projet, 25) - source[25]).max() < 2e-4, "16 bits, sans perte"
    assert EFFETS["persistance"].animable and EFFETS["bavure_flux"].codec
    effet = nouvel_effet("bavure_flux")
    poser_cle(effet, "force", 0, 100)
    poser_cle(effet, "force", clip.duree - 1, 300)
    clip.effets = [effet]
    prerendu.calculer(projet, seq, clip)
    assert np.abs(_image(projet, 25) - source[25]).max() > 0.05, "la bavure se voit"
    # Mouvement connu : une image décalée de 3 pixels.
    rng = np.random.default_rng(1)
    a = rng.random((120, 160, 3)).astype(np.float32)
    a = np.repeat(np.repeat(a[::8, ::8], 8, 0), 8, 1)[:120, :160]
    b = np.roll(a, 3, axis=1)
    m = flux.Mesure()
    m.suivante(a)
    mouvement = m.suivante(b)
    assert abs(float(np.median(mouvement[..., 0])) + 3) < 0.6, "d'où vient chaque pixel"
    assert np.abs(flux.deplacer(a, mouvement, 1.0)[20:100, 20:140]
                  - b[20:100, 20:140]).mean() < 0.05


def test_courbes_lisse_bezier_et_listes():
    from remanence.effets import courbes
    cles = [[0, 0.0, "lisse"], [10, 100.0, "lineaire"]]
    assert courbes.interpoler(cles, 5) == 50.0
    assert courbes.interpoler(cles, 2) < 20.0, "départ en douceur"
    cles[0][2] = "bezier"
    assert abs(courbes.interpoler(cles, 5) - 50.0) < 0.5, "poignées à plat : symétrique"
    courbes.regler_poignee(cles, 0, "d", 3.0, 60.0)
    assert courbes.interpoler(cles, 2) > 30.0, "la poignée tire la courbe vers le haut"
    g, d = courbes.poignees(cles, 0)
    assert d == [3.0, 60.0] and g[0] < 0 and g[1] < 0, "poignées liées : alignées"
    cles[0][2] = "palier"
    assert courbes.interpoler(cles, 9) == 0.0
    points = [[0, [[0.0, 0.0], [0.2, 0.2]], "lineaire"], [10, [[0.5, 0.0], [0.7, 0.2]], "lineaire"]]
    assert np.allclose(courbes.interpoler(points, 5), [[0.25, 0.0], [0.45, 0.2]])
    autre = [[0, [[0.0, 0.0]], "lineaire"], [10, [[0.5, 0.0], [0.7, 0.2]], "lineaire"]]
    assert courbes.interpoler(autre, 5) == [[0.0, 0.0]], "nombre de points différent : palier"


def test_masque_anime_dans_l_image(medias):
    """Un masque qui glisse de la moitié gauche à la moitié droite emmène l'effet avec lui."""
    from remanence.effets import courbes, instantane
    from remanence.effets.masques import nouveau_masque
    projet, clip = _projet(medias)
    source = {f: _image(projet, f) for f in (0, 20)}
    effet = nouvel_effet("decalage_rvb")
    effet.params["force"] = 100
    m = nouveau_masque("rectangle")
    m.points = [[0.0, 0.0], [0.5, 1.0]]
    m.cles["points"] = []
    courbes.poser(m.cles["points"], 0, [[0.0, 0.0], [0.5, 1.0]])
    courbes.poser(m.cles["points"], 20, [[0.5, 0.0], [1.0, 1.0]])
    effet.masques = [m]
    clip.effets = [effet]
    assert instantane(effet, 10).masques[0].points == [[0.25, 0.0], [0.75, 1.0]]
    gauche, droite = slice(5, 150), slice(170, 315)
    a, b = _image(projet, 0), _image(projet, 20)
    assert np.abs(a[:, gauche] - source[0][:, gauche]).max() > 0.05
    assert np.abs(a[:, droite] - source[0][:, droite]).max() < 1e-6
    assert np.abs(b[:, gauche] - source[20][:, gauche]).max() < 1e-6
    assert np.abs(b[:, droite] - source[20][:, droite]).max() > 0.05
    relu = Projet.depuis_dict(projet.vers_dict())
    assert relu.sequence.pistes_video[0].clips[0].effets[0].masques[0].cles["points"][1][0] == 20


def test_signaux_des_modulateurs():
    from remanence.effets import modulateurs
    osc = modulateurs.nouveau_modulateur("oscillateur")
    osc.params["frequence"] = 1.0
    assert abs(modulateurs.valeur(osc, 0, 24)) < 1e-9
    assert abs(modulateurs.valeur(osc, 6, 24) - 1) < 1e-9, "un quart de période : le haut"
    osc.params["forme"] = "carre"
    assert modulateurs.valeur(osc, 3, 24) == 1.0 and modulateurs.valeur(osc, 15, 24) == -1.0
    osc.params["forme"] = "dents"
    assert modulateurs.valeur(osc, 0, 24) == -1.0
    alea = modulateurs.nouveau_modulateur("aleatoire")
    serie = [modulateurs.valeur(alea, f, 25) for f in range(200)]
    assert serie == [modulateurs.valeur(alea, f, 25) for f in range(200)], "toujours le même"
    assert all(-1 <= v <= 1 for v in serie) and max(serie) - min(serie) > 0.5
    assert max(abs(a - b) for a, b in zip(serie, serie[1:])) < 0.2, "lissé"
    alea.params["graine"] = 2
    assert [modulateurs.valeur(alea, f, 25) for f in range(200)] != serie
    tempo = modulateurs.nouveau_modulateur("tempo")
    tempo.params["bpm"] = 120  # un temps toutes les 12 images à 24 i/s
    assert modulateurs.valeur(tempo, 0, 24) == 1.0 and modulateurs.valeur(tempo, 12, 24) == 1.0
    assert modulateurs.valeur(tempo, 6, 24) < 0.1, "l'impulsion retombe"


def test_effet_module_exporte_deux_fois(medias, tmp_path):
    """Validation de l'étape 4 : un effet modulé exporté deux fois donne les mêmes images ; la
    modulation change l'image dans le temps ; elle entre dans l'empreinte des pré-rendus."""
    from remanence.effets import modulateurs
    from remanence.moteurs.codec import prerendu
    projet, clip = _projet(medias)
    seq = projet.sequence
    effet = nouvel_effet("decalage_rvb")
    effet.params["force"] = 0
    clip.effets = [effet]
    sans = [_image(projet, f) for f in (0, 6)]
    osc = modulateurs.nouveau_modulateur("oscillateur")
    osc.params["frequence"] = 1.0
    osc.cibles.append([effet.id, "force", 80])
    seq.modulateurs.append(osc)
    a, b = _image(projet, 0), _image(projet, 6)
    assert np.abs(a - sans[0]).max() < 1e-6, "sinus à 0 : l'effet à 0"
    assert np.abs(b - sans[1]).max() > 0.05, "un quart de période plus tard : l'effet se voit"
    premier = exporter(projet, seq, tmp_path / "a.mov")
    second = exporter(projet, seq, tmp_path / "b.mov")
    assert premier.conforme and second.conforme
    assert empreintes_images(tmp_path / "a.mov") == empreintes_images(tmp_path / "b.mov")
    relu = Projet.depuis_dict(projet.vers_dict())
    assert relu.sequence.modulateurs[0].cibles == [[effet.id, "force", 80]]
    # Pré-rendu (flux optique) : un modulateur qui le pilote change son empreinte.
    flux = nouvel_effet("persistance")
    clip.effets = [flux]
    avant = prerendu.cle(projet, seq, clip)
    osc.cibles.append([flux.id, "persistance", 50])
    assert prerendu.cle(projet, seq, clip) != avant
    valeurs = prerendu.valeurs_images(flux, 12, seq, clip.debut)
    assert valeurs[0]["persistance"] != valeurs[6]["persistance"]


def test_modulateur_audio(medias):
    """Le niveau du son d'une piste pilote un réglage ; il suit le gain du clip et entre dans
    l'empreinte des pré-rendus."""
    from remanence.effets import modulateurs
    from remanence.media.lecteur import generer_cache_audio
    from remanence.media.proxy import chemin_audio
    from remanence.moteurs import audio
    from remanence.moteurs.codec import prerendu
    projet, clip = _projet(medias)
    seq = projet.sequence
    media = projet.medias[clip.media_id]
    if not chemin_audio(media.infos).exists():
        generer_cache_audio(media.infos, chemin_audio(media.infos))
    m = modulateurs.nouveau_modulateur("audio")
    effet = nouvel_effet("persistance")
    clip.effets = [effet]
    m.cibles.append([effet.id, "persistance", 50])
    seq.modulateurs.append(m)
    lie = next(c for c in seq.pistes_audio[0].clips)
    niveaux = audio.enveloppe(projet, seq, m.params)
    assert len(niveaux) == seq.duree() and niveaux.max() > 0.2
    assert modulateurs.valeur(m, 10, 24, projet, seq) == float(niveaux[10])
    assert modulateurs.valeur(m, 10, 24) == 0.0, "sans le projet : rien"
    avant = prerendu.cle(projet, seq, clip)
    lie.gain = 0.0
    assert audio.enveloppe(projet, seq, m.params).max() < 0.05, "le gain du clip compte"
    assert prerendu.cle(projet, seq, clip) != avant
    m.params["bande"] = "aigus"
    assert len(audio.enveloppe(projet, seq, m.params)) == seq.duree()
