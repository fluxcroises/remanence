"""Vitesse et inversion, titres, séquences imbriquées (étape 5, lot 4)."""

import numpy as np
import pytest

from remanence.media.sonde import analyser
from remanence.projet import edition
from remanence.projet.modele import Media, Projet, nouvel_id
from remanence.rendu.composition import Compositeur, couches
from tests import test_gpu

pytestmark = test_gpu.pytestmark


def _projet(medias, cle="prores_hq"):
    projet = Projet.nouveau()
    infos, _ = analyser(str(medias[cle]))
    m = Media(nouvel_id(), str(medias[cle]), infos)
    projet.medias[m.id] = m
    edition.ajouter_media(projet, projet.sequence, m, 0)
    return projet, projet.sequence, m


def _image(projet, seq, f):
    c = Compositeur(projet)
    try:
        return c.image(seq, f)
    finally:
        c.fermer()


def test_vitesse_et_inversion(medias):
    projet, seq, m = _projet(medias)
    nb = m.infos.video.nb_images
    video = seq.pistes_video[0].clips[0]
    edition.regler_vitesse(projet, seq, video.id, 2.0, False)
    assert video.duree == nb // 2 and seq.pistes_audio[0].clips[0].duree == nb // 2, \
        "image et son liés, deux fois plus courts"
    assert [couches(projet, seq, f)[0].image_source for f in range(4)] == [0, 2, 4, 6]
    edition.regler_vitesse(projet, seq, video.id, 1.0, True)
    assert video.duree == nb
    assert couches(projet, seq, 0)[0].image_source == nb - 1, "à rebours : la fin d'abord"
    assert couches(projet, seq, nb - 1)[0].image_source == 0
    edition.regler_vitesse(projet, seq, video.id, 0.5, False)
    assert video.duree == 2 * nb
    assert [couches(projet, seq, f)[0].image_source for f in range(4)] == [0, 0, 1, 1]
    # Le son suit : au ralenti, deux fois plus d'échantillons pour la même source.
    c = Compositeur(projet)
    try:
        son = c.audio(seq, 0, 4800)
    finally:
        c.fermer()
    assert son.shape == (4800, 2) and np.isfinite(son).all()
    # Rogner le début d'un clip ralenti : la source avance d'une image toutes les deux.
    edition.rogner(projet, seq, video.id, "debut", 4)
    assert couches(projet, seq, video.debut)[0].image_source == 2


def test_titre(medias):
    from PySide6.QtWidgets import QApplication
    from remanence.rendu import titres
    app = QApplication.instance() or QApplication([])
    projet, seq, _m = _projet(medias)
    titre = titres.nouveau_titre("REMANENCE")
    titre["taille"] = 20
    clip = edition.ajouter_titre(seq, 0, 10, titre)
    assert clip.titre is not None and not clip.est_effet and not clip.est_media
    image = _image(projet, seq, 5)
    seul = titres.rendre(titre, seq.largeur, seq.hauteur)
    assert seul[..., 3].max() > 0.99 and seul[:5, :5, 3].max() == 0.0, "texte au centre seulement"
    fond = _image(projet, seq, 15)
    assert np.abs(image - fond).max() > 0.5 if seq.duree() > 15 else True
    centre = image[seq.hauteur // 2 - 10:seq.hauteur // 2 + 10, seq.largeur // 2 - 30:
                   seq.largeur // 2 + 30]
    assert centre.max() > 0.9
    a = titres.rendre(titre, seq.largeur // 2, seq.hauteur // 2)
    assert a.shape == (seq.hauteur // 2, seq.largeur // 2, 4), "à la taille demandée"
    assert app is not None


def test_sequence_imbriquee(medias):
    from remanence.media.lecteur import generer_cache_audio
    from remanence.media.proxy import chemin_audio
    projet, seq, m = _projet(medias)
    generer_cache_audio(m.infos, chemin_audio(m.infos))
    avant = [_image(projet, seq, f) for f in (0, 7, 20)]
    ids = {c.id for _, c in seq.tous_les_clips()}
    sous = edition.imbriquer(projet, seq, ids)
    assert len(projet.sequences) == 2 and sous.duree() > 0
    imbrique = seq.pistes_video[0].clips[0]
    assert imbrique.sequence_id == sous.id and seq.pistes_audio[0].clips[0].lien == imbrique.lien
    apres = [_image(projet, seq, f) for f in (0, 7, 20)]
    for a, b in zip(avant, apres):
        assert np.abs(a - b).max() < 1e-5, "la même image à travers l'imbrication"
    c = Compositeur(projet)
    try:
        assert np.abs(c.audio(seq, 0, 9600)).max() > 0, "le son de la séquence imbriquée"
    finally:
        c.fermer()
    assert edition.contient_sequence(projet, seq, sous.id)
    edition.regler_vitesse(projet, seq, imbrique.id, 1.0, True)
    assert couches(projet, seq, 0)[0].image_source == sous.duree() - 1
    relu = Projet.depuis_dict(projet.vers_dict())
    assert relu.sequence.pistes_video[0].clips[0].sequence_id == sous.id


def test_poses_rapides_gardent_les_pistes_synchrones(medias):
    """Étape 11, lot 2 : remplacer décale la suite sur toutes les pistes (son et pistes du
    dessus compris) ; l'insertion intelligente vise un raccord ; placer au-dessus n'écrase rien."""
    from remanence.media.sonde import analyser
    from remanence.projet import edition
    from remanence.projet.modele import Media, Projet, nouvel_id
    p = Projet.nouveau()
    infos, _ = analyser(str(medias["prores_hq"]))
    m = Media(nouvel_id(), str(medias["prores_hq"]), infos)
    p.medias[m.id] = m
    seq = p.sequence
    edition.ajouter_media(p, seq, m, 0, duree=10)
    edition.ajouter_media(p, seq, m, 10, duree=10)
    haut = edition.placer_au_dessus(p, seq, m, 12, 0, 5)
    assert len(seq.pistes_video) == 2 and haut[0].debut == 12
    assert [c.debut for c in seq.pistes_video[-1].clips] == [0, 10], "rien d'écrasé"
    assert edition.raccord_proche(seq, 4) == 0 and edition.raccord_proche(seq, 8) == 10
    premier = seq.pistes_video[-1].clips[0]
    edition.remplacer_plan(p, seq, premier.id, m, 0, 4)
    v1 = seq.pistes_video[-1].clips
    assert [(c.debut, c.duree) for c in v1] == [(0, 4), (4, 10)]
    assert seq.pistes_video[0].clips[0].debut == 6, "la piste du dessus recule aussi"
    a1 = sorted((c.debut, c.duree) for c in seq.pistes_audio[0].clips)
    assert a1[:2] == [(0, 4), (4, 10)], "le son suit l'image"
    edition.remplacer_plan(p, seq, v1[0].id, m, 0, 9)
    assert [(c.debut, c.duree) for c in seq.pistes_video[-1].clips] == [(0, 9), (9, 10)]
    assert seq.pistes_video[0].clips[0].debut == 11


def test_plan_autour_et_raccord_a_rogner():
    from remanence.projet import edition
    assert edition.plan_autour([10, 20], 14, 30) == (10, 20)
    assert edition.plan_autour([10, 20], 3, 30) == (0, 10)
    assert edition.plan_autour([10, 20], 25, 30) == (20, 30)
    assert edition.plan_autour(None, 5, 30) == (0, 30)
