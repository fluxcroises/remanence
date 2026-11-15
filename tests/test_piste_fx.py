"""Piste FX (étape 13, lot 5) : les clips d'effet ont leur piste, en haut, à part des plans."""

import pytest

from remanence.effets import nouvel_effet
from remanence.projet import edition
from remanence.projet.modele import Projet
from remanence.ui.inspecteur import nom_court_piste
from tests.test_effets import _projet


def test_piste_fx(medias):
    projet, clip = _projet(medias)
    seq = projet.sequence
    plan = seq.trouver(clip.id)[0]

    # Le premier clip d'effet crée la piste FX tout en haut.
    a = edition.ajouter_clip_effet(seq, 0, 50, [nouvel_effet("vhs")])
    fx = seq.trouver(a.id)[0]
    assert fx.fx and fx.nom == "FX" and seq.pistes_video[0] is fx
    assert nom_court_piste(seq, fx) == "FX" and nom_court_piste(seq, plan) == "V1"

    # Lâché dans le vide d'une piste ordinaire : il va quand même sur la piste FX.
    b = edition.ajouter_clip_effet(seq, 100, 50, [], piste_id=plan.id)
    assert seq.trouver(b.id)[0] is fx

    # La piste FX est occupée à cet endroit : une seconde piste FX, au-dessus.
    c = edition.ajouter_clip_effet(seq, 10, 20, [])
    fx2 = seq.trouver(c.id)[0]
    assert fx2.fx and fx2 is not fx and seq.pistes_video[0] is fx2
    assert nom_court_piste(seq, fx2) == "FX2" and nom_court_piste(seq, fx) == "FX"

    # Une nouvelle piste vidéo et un titre se posent sous les pistes FX.
    nouvelle = edition.ajouter_piste(seq, "video")
    assert seq.pistes_video.index(nouvelle) == 2 and not nouvelle.fx
    assert nouvelle.nom == "Vidéo 2", "les pistes FX ne comptent pas"
    titre = edition.ajouter_titre(seq, 0, 25, {"texte": "Titre"})
    assert not seq.trouver(titre.id)[0].fx

    # Pas de média sur une piste FX : posé, il est refusé ; glissé, il reste sur sa piste.
    media = projet.medias[clip.media_id]
    with pytest.raises(edition.EditionImpossible):
        edition.ajouter_media(projet, seq, media, 300, piste=fx)
    rang = seq.pistes_video.index(plan)
    edition.deplacer(seq, {clip.id}, 5, delta_piste=-rang, inclure_lies=False)
    assert seq.trouver(clip.id)[0] is plan and clip.debut == 5
    # Un clip d'effet passe d'une piste FX à l'autre.
    edition.deplacer(seq, {a.id}, 200, delta_piste=-1)
    assert seq.trouver(a.id)[0] is fx2

    # Enregistrée avec le projet ; les projets d'avant n'ont pas de piste FX.
    relu = Projet.depuis_dict(projet.vers_dict())
    assert [p.fx for p in relu.sequence.pistes] == [p.fx for p in seq.pistes]
    ancien = projet.vers_dict()
    for s in ancien["sequences"]:
        for p in s["pistes"]:
            p.pop("fx")
    assert not any(p.fx for p in Projet.depuis_dict(ancien).sequence.pistes)
