import json

import pytest

from remanence.media.sonde import analyser
from remanence.projet import edition, serialisation
from remanence.projet.historique import Historique
from remanence.projet.modele import Media, Projet, nouvel_id


def _projet_avec(medias, cle="prores_hq"):
    projet = Projet.nouveau()
    infos, _ = analyser(str(medias[cle]))
    m = Media(nouvel_id(), str(medias[cle]), infos)
    projet.medias[m.id] = m
    return projet, m


def test_premier_media_regle_la_sequence(medias):
    projet, m = _projet_avec(medias)
    seq = projet.sequence
    clips = edition.ajouter_media(projet, seq, m, 0)
    assert len(clips) == 2 and clips[0].lien == clips[1].lien
    assert (seq.largeur, seq.hauteur, seq.cadence) == (320, 180, "24000/1001")
    assert seq.tc_debut == 86400 and seq.duree() == 30


def test_couper_deplacer_rogner(medias):
    projet, m = _projet_avec(medias)
    seq = projet.sequence
    v, a = edition.ajouter_media(projet, seq, m, 0)
    edition.couper(seq, 10)
    pv = seq.pistes_video[0]
    assert [(c.debut, c.entree, c.duree) for c in pv.clips] == [(0, 0, 10), (10, 10, 20)]
    droite = pv.clips[1]
    # Les moitiés droites image et son restent liées entre elles.
    assert sum(1 for _, c in seq.tous_les_clips() if c.lien == droite.lien) == 2
    edition.deplacer(seq, {droite.id}, 5)
    assert pv.clips[1].debut == 15 and seq.pistes_audio[0].clips[1].debut == 15
    edition.deplacer(seq, {droite.id}, -12)
    # Posé sur le premier clip, il l'écrase : il ne reste que 3 images à gauche.
    assert [(c.debut, c.duree) for c in pv.clips] == [(0, 3), (3, 20)]
    delta = edition.rogner(projet, seq, pv.clips[1].id, "fin", 100)
    assert delta == 0, "le média n'a plus d'images après la fin du clip"
    delta = edition.rogner(projet, seq, pv.clips[1].id, "debut", -100)
    # Bloqué au début de la timeline ; le clip étendu recouvre le précédent.
    assert delta == -3
    assert [(c.debut, c.entree, c.duree) for c in pv.clips] == [(0, 7, 23)]


def test_piste_verrouillee(medias):
    projet, m = _projet_avec(medias)
    seq = projet.sequence
    v, _ = edition.ajouter_media(projet, seq, m, 0)
    seq.pistes_video[0].verrouillee = True
    with pytest.raises(edition.EditionImpossible):
        edition.deplacer(seq, {v.id}, 3)


def test_fondus_et_enveloppe(medias):
    projet, m = _projet_avec(medias)
    seq = projet.sequence
    v, _ = edition.ajouter_media(projet, seq, m, 0)
    edition.regler_fondu(seq, v.id, "entree", 4)
    assert v.facteur(0) == pytest.approx(1 / 5) and v.facteur(4) == 1.0
    edition.poser_point(seq, v.id, 10, 1.0)
    edition.poser_point(seq, v.id, 20, 0.0)
    assert v.facteur(15) == pytest.approx(0.5)
    edition.couper(seq, 15)
    droite = seq.pistes_video[0].clips[1]
    assert droite.facteur(15) == pytest.approx(0.5), "la courbe ne bouge pas à la coupe"


def test_annuler_retablir(medias):
    projet, m = _projet_avec(medias)
    h = Historique(projet)
    edition.ajouter_media(projet, projet.sequence, m, 0)
    assert h.valider(projet, "Ajout")
    edition.couper(projet.sequence, 5)
    h.valider(projet, "Coupe")
    p1 = h.annuler()
    assert len(p1.sequence.pistes_video[0].clips) == 1
    p0 = h.annuler()
    assert p0.sequence.duree() == 0
    p2 = h.retablir()
    assert p2.sequence.duree() == 30
    assert not h.valider(p2, "Rien"), "un état identique n'est pas empilé"


def test_enregistrer_ouvrir_versions(medias, tmp_path):
    projet, m = _projet_avec(medias)
    edition.ajouter_media(projet, projet.sequence, m, 0)
    chemin = tmp_path / "court.remanence"
    serialisation.enregistrer(projet, chemin)
    serialisation.enregistrer(projet, chemin)
    versions = sorted(p.name for p in serialisation.dossier_versions(chemin).iterdir())
    assert versions == ["court_v001.remanence", "court_v002.remanence"]
    relu = serialisation.ouvrir(chemin)
    assert json.dumps(relu.vers_dict()) == json.dumps(projet.vers_dict())


def test_media_hors_ligne(medias, tmp_path):
    projet, m = _projet_avec(medias)
    d = projet.vers_dict()
    d["medias"][0]["chemin"] = str(tmp_path / "deplace.mov")
    chemin = tmp_path / "p.remanence"
    chemin.write_text(json.dumps(d), encoding="utf-8")
    relu = serialisation.ouvrir(chemin)
    assert next(iter(relu.medias.values())).hors_ligne


def test_sauvegarde_auto(medias, tmp_path):
    projet, _ = _projet_avec(medias)
    chemin = tmp_path / "p.remanence"
    serialisation.enregistrer(projet, chemin)
    auto = serialisation.enregistrer_auto(projet, chemin)
    assert auto.name == "p.auto.remanence"
    assert serialisation.sauvegarde_auto_plus_recente(chemin) == auto


def test_plage_source_et_insertion(medias):
    projet, m = _projet_avec(medias)
    seq = projet.sequence
    m.point_entree, m.point_sortie = 5, 15
    a, b = m.plage_source(seq.fraction_cadence)
    v, _ = edition.ajouter_media(projet, seq, m, 0, entree=a, duree=b - a)
    assert (v.entree, v.duree) == (5, 10) and seq.tc_debut == 86400 + 5
    edition.inserer_media(projet, seq, m, 4, entree=0, duree=6)
    pv = seq.pistes_video[0]
    assert [(c.debut, c.entree, c.duree) for c in pv.clips] == [(0, 5, 4), (4, 0, 6), (10, 9, 6)]
    relu = Projet.depuis_dict(projet.vers_dict())
    assert relu.medias[m.id].point_entree == 5 and relu.medias[m.id].point_sortie == 15


def test_chutiers(medias):
    from remanence.projet.modele import Chutier
    projet, m = _projet_avec(medias)
    rushs = Chutier(nouvel_id(), "Rushs")
    glitch = Chutier(nouvel_id(), "Glitch", parent=rushs.id)
    projet.chutiers += [rushs, glitch]
    m.chutier = glitch.id
    assert projet.sous_chutiers(rushs.id) == {rushs.id, glitch.id}
    relu = Projet.depuis_dict(projet.vers_dict())
    assert [c.nom for c in relu.chutiers] == ["Rushs", "Glitch"]
    assert relu.medias[m.id].chutier == glitch.id
    assert relu.clips_du_media(m.id) == 0


def _deux_clips(medias):
    projet, m = _projet_avec(medias)
    seq = projet.sequence
    edition.ajouter_media(projet, seq, m, 0, duree=20)
    edition.ajouter_media(projet, seq, m, 20, entree=5, duree=20)
    return projet, seq, seq.pistes_video[0]


def test_fondu_enchaine_au_chevauchement(medias):
    projet, seq, pv = _deux_clips(medias)
    b = pv.clips[1]
    edition.deplacer(seq, {b.id}, -6, fondus_auto=True)
    a, b = pv.clips
    assert (a.fin, b.debut, a.fondu_sortie, b.fondu_entree) == (20, 14, 6, 6)
    pa = seq.pistes_audio[0].clips
    assert (pa[0].fondu_sortie, pa[1].fondu_entree) == (6, 6), "le son se fond aussi"
    # Sans fondus automatiques, le clip posé écrase la fin du précédent.
    projet, seq, pv = _deux_clips(medias)
    edition.deplacer(seq, {pv.clips[1].id}, -6)
    assert [(c.debut, c.duree) for c in pv.clips] == [(0, 14), (14, 20)]


def test_ripple_apres_fondu_enchaine(medias):
    """Supprimer en ripple le premier clip d'un fondu enchaîné : le second prend sa place."""
    projet, seq, pv = _deux_clips(medias)
    edition.deplacer(seq, {pv.clips[1].id}, -6, fondus_auto=True)
    edition.supprimer_ripple(seq, {pv.clips[0].id})
    assert [(c.debut, c.fondu_entree) for c in pv.clips] == [(0, 0)]


def test_imports_fusionnes_dans_l_historique(medias):
    projet, m = _projet_avec(medias)
    h = Historique(projet)
    for nom in ("a", "b"):
        projet.medias[nom] = Media(nom, m.chemin, m.infos)
        assert h.valider(projet, "Import de médias", fusionner=True)
    assert h.libelles()[1:] == ["Import de médias"], "un seul Ctrl+Z pour tout le lot"
    assert len(h.annuler().medias) == len(projet.medias) - 2


def test_ripple_slip_slide_roll(medias):
    projet, seq, pv = _deux_clips(medias)
    a, b = pv.clips
    assert edition.rogner(projet, seq, a.id, "fin", -5, ripple=True) == -5
    assert [(c.debut, c.duree) for c in pv.clips] == [(0, 15), (15, 20)]
    edition.supprimer_ripple(seq, {pv.clips[0].id})
    assert [(c.debut, c.entree) for c in pv.clips] == [(0, 5)]
    assert len(seq.pistes_audio[0].clips) == 1

    projet, seq, pv = _deux_clips(medias)
    a, b = pv.clips
    assert edition.glisser_contenu(projet, seq, b.id, 3) == 3
    assert (b.debut, b.entree, b.duree) == (20, 8, 20)
    assert edition.rouler(projet, seq, a.id, 4) == 4
    assert [(c.debut, c.entree, c.duree) for c in pv.clips] == [(0, 0, 24), (24, 12, 16)]
    edition.ajouter_media(projet, seq, projet.medias[a.media_id], 40, entree=0, duree=10)
    milieu = pv.clips[1]
    assert edition.faire_glisser(projet, seq, milieu.id, 2) == 2
    assert [(c.debut, c.entree, c.duree) for c in pv.clips] == \
        [(0, 0, 26), (26, 12, 16), (42, 2, 8)]
    assert edition.coupes(seq)[:3] == [0, 26, 42]
