"""Composition sur la carte graphique : même résultat que le processeur, au pixel près."""

import numpy as np
import pytest

from remanence.media.lecteur import LecteurVideo
from remanence.media.sonde import analyser
from remanence.projet import edition
from remanence.projet.modele import Media, Projet, nouvel_id
from remanence.rendu.composition import Compositeur
from remanence.rendu.couleur import _plans, depuis_rvba

FORMATS = ["prores_hq", "prores_4444", "dnxhr_hqx", "h264", "hevc10"]


def _gpu_disponible() -> bool:
    c = Compositeur(Projet.nouveau(), gpu=True)
    ok = c.gpu() is not None
    c.fermer()
    return ok


pytestmark = pytest.mark.skipif(not _gpu_disponible(), reason="pas d'OpenGL 4.3")


def _projet(medias, *cles):
    projet = Projet.nouveau()
    for cle in cles:
        infos, _ = analyser(str(medias[cle]))
        m = Media(nouvel_id(), str(medias[cle]), infos)
        projet.medias[m.id] = m
    return projet


@pytest.mark.parametrize("cle", FORMATS)
def test_sans_effet_identique_a_la_source(medias, cle):
    """Décoder, composer sur la carte graphique, réencoder les plans : les valeurs du fichier
    reviennent exactement (hors pixels entièrement transparents, sans couleur)."""
    projet = _projet(medias, cle)
    m = next(iter(projet.medias.values()))
    seq = projet.sequence
    edition.ajouter_media(projet, seq, m, 0)
    infos, index = analyser(m.chemin)
    source = LecteurVideo(m.chemin, index).image(3)
    gpu = Compositeur(projet, gpu=True)
    cpu = Compositeur(projet, gpu=False)
    try:
        rvba_gpu = gpu.image(seq, 3)
        rvba_cpu = cpu.image(seq, 3)
    finally:
        gpu.fermer()
        cpu.fermer()
    assert np.abs(rvba_gpu - rvba_cpu).max() < 1e-5
    retour = depuis_rvba(rvba_gpu, source.format.name, m.infos.video.couleur)
    plans_a, plans_b = _plans(source), _plans(retour)
    visibles = None
    if len(plans_a) >= 4:
        assert np.array_equal(plans_a[3], plans_b[3]), "alpha"
        visibles = plans_a[3] > 0
    for i, (a, b) in enumerate(zip(plans_a[:3], plans_b[:3])):
        if visibles is None:
            assert np.array_equal(a, b), f"plan {i}"
        else:
            assert a.shape == visibles.shape  # 4:4:4 avec alpha
            assert np.array_equal(a[visibles], b[visibles]), f"plan {i}"


def test_couches_opacite_et_taille(medias):
    """Plusieurs couches, opacité, couche plus petite centrée : mêmes valeurs que le processeur."""
    projet = _projet(medias, "prores_hq", "prores_4444", "portrait_impair")
    fond, dessus, portrait = projet.medias.values()
    seq = projet.sequence
    edition.ajouter_media(projet, seq, fond, 0)
    edition.ajouter_piste(seq, "video")
    edition.ajouter_media(projet, seq, dessus, 0, piste=seq.pistes_video[0])
    edition.ajouter_piste(seq, "video")
    edition.ajouter_media(projet, seq, portrait, 0, piste=seq.pistes_video[0])
    seq.pistes_video[0].niveau = 0.6
    for echelle in (1.0, 0.5):
        gpu = Compositeur(projet, gpu=True)
        cpu = Compositeur(projet, gpu=False)
        try:
            a = gpu.image(seq, 4, echelle)
            b = cpu.image(seq, 4, echelle)
        finally:
            gpu.fermer()
            cpu.fermer()
        assert a.shape == b.shape
        assert np.abs(a - b).max() < 1e-5, echelle


def test_dans_un_fil_comme_la_lecture(medias):
    """La lecture et l'export calculent dans leur propre fil, avec leur propre contexte."""
    import threading
    projet = _projet(medias, "prores_hq", "prores_4444")
    fond, dessus = projet.medias.values()
    seq = projet.sequence
    edition.ajouter_media(projet, seq, fond, 0)
    edition.ajouter_piste(seq, "video")
    edition.ajouter_media(projet, seq, dessus, 0, piste=seq.pistes_video[0])
    resultats = {}

    def calculer():
        c = Compositeur(projet, apercu=True)
        try:
            resultats["gpu"] = c.gpu() is not None
            resultats["image"] = c.image(seq, 2)
        finally:
            c.fermer()
    fil = threading.Thread(target=calculer)
    fil.start()
    fil.join()
    reference = Compositeur(projet, gpu=False).image(seq, 2)
    assert resultats["gpu"]
    assert np.abs(resultats["image"] - reference).max() < 1e-5
