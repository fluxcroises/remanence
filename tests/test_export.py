"""Validation de l'étape 1 : un export sans effet remplace la source sans aucun recalage."""

import av
import numpy as np
import pytest

from remanence.media.lecteur import generer_cache_audio
from remanence.media.proxy import chemin_audio
from remanence.media.sonde import analyser
from remanence.projet import edition
from remanence.projet.modele import Media, Projet, nouvel_id
from remanence.rendu.conformite import empreintes_images
from remanence.rendu.export import exporter

FORMATS_VALIDATION = ["prores_hq", "prores_4444", "dnxhr_hqx", "h264", "hevc10"]


def _projet(medias, cle):
    projet = Projet.nouveau()
    infos, _ = analyser(str(medias[cle]))
    m = Media(nouvel_id(), str(medias[cle]), infos)
    projet.medias[m.id] = m
    edition.ajouter_media(projet, projet.sequence, m, 0)
    return projet, m


def _paquets_audio(chemin):
    with av.open(str(chemin)) as c:
        if not c.streams.audio:
            return []
        return [bytes(p) for p in c.demux(c.streams.audio[0]) if p.size]


@pytest.mark.parametrize("cle", FORMATS_VALIDATION)
def test_export_sans_effet_identique(medias, tmp_path, cle):
    projet, m = _projet(medias, cle)
    sortie = tmp_path / ("export" + medias[cle].suffix)
    rapport = exporter(projet, projet.sequence, sortie)
    assert rapport.conforme, [v for v in rapport.verifications if not v.ok]
    src, exp = analyser(str(medias[cle]))[0].video, analyser(str(sortie))[0].video
    assert (exp.codec, exp.profil, exp.pix_fmt) == (src.codec, src.profil, src.pix_fmt)
    assert exp.tc_debut == src.tc_debut and exp.tc_drop == src.tc_drop
    assert empreintes_images(str(sortie)) == empreintes_images(str(medias[cle]))
    assert rapport.images_calculees == 0
    assert _paquets_audio(sortie) == _paquets_audio(medias[cle])


def test_coupe_et_reassemblage_intra(medias, tmp_path):
    """Deux morceaux bout à bout d'un même plan ProRes restent identiques au pixel près."""
    projet, m = _projet(medias, "prores_hq")
    edition.couper(projet.sequence, 12)
    sortie = tmp_path / "coupe.mov"
    rapport = exporter(projet, projet.sequence, sortie)
    assert rapport.conforme
    assert empreintes_images(str(sortie)) == empreintes_images(str(medias["prores_hq"]))


def test_fondu_ne_touche_que_ses_images(medias, tmp_path):
    projet, m = _projet(medias, "prores_hq")
    generer_cache_audio(m.infos, chemin_audio(m.infos))
    v = projet.sequence.pistes_video[0].clips[0]
    edition.regler_fondu(projet.sequence, v.id, "sortie", 6)
    sortie = tmp_path / "fondu.mov"
    rapport = exporter(projet, projet.sequence, sortie)
    assert rapport.conforme
    assert (rapport.images_recopiees, rapport.images_calculees) == (24, 6)
    a, b = empreintes_images(str(sortie)), empreintes_images(str(medias["prores_hq"]))
    assert a[:24] == b[:24]
    assert all(x != y for x, y in zip(a[24:], b[24:]))
    # Le son, intact, est recopié tel quel.
    assert rapport.audio == "recopié sans réencodage"


def test_plage_partielle_et_timecode(medias, tmp_path):
    projet, m = _projet(medias, "prores_hq")
    generer_cache_audio(m.infos, chemin_audio(m.infos))
    sortie = tmp_path / "extrait.mov"
    rapport = exporter(projet, projet.sequence, sortie, debut=6, fin=18)
    assert rapport.conforme
    v = analyser(str(sortie))[0].video
    assert v.nb_images == 12 and v.tc_texte == "01:00:00:06"
    assert empreintes_images(str(sortie)) == empreintes_images(str(medias["prores_hq"]))[6:18]
    assert rapport.audio == "mixé et encodé"
    with av.open(str(sortie)) as c:
        duree_audio = sum(f.samples for f in c.decode(c.streams.audio[0])) / 48000
    assert duree_audio == pytest.approx(12 * 1001 / 24000, abs=1 / 48000)


def test_long_gop_partiel_reencode(medias, tmp_path):
    projet, _ = _projet(medias, "h264")
    sortie = tmp_path / "extrait.mp4"
    rapport = exporter(projet, projet.sequence, sortie, debut=5, fin=25)
    assert rapport.conforme
    assert rapport.images_calculees == 20


def test_superposition_et_alpha(medias, tmp_path):
    """Un ProRes 4444 avec alpha posé sur un plan : seules les images composées sont calculées."""
    projet, fond = _projet(medias, "prores_hq")
    infos, _ = analyser(str(medias["prores_4444"]))
    dessus = Media(nouvel_id(), str(medias["prores_4444"]), infos)
    projet.medias[dessus.id] = dessus
    seq = projet.sequence
    edition.ajouter_piste(seq, "video")
    edition.ajouter_media(projet, seq, dessus, 5, piste=seq.pistes_video[0])
    sortie = tmp_path / "compo.mov"
    rapport = exporter(projet, seq, sortie)
    assert rapport.conforme
    assert rapport.images_calculees == 20 and rapport.images_recopiees == 10
    images = empreintes_images(str(sortie))
    ref = empreintes_images(str(medias["prores_hq"]))
    assert images[:5] == ref[:5] and images[25:] == ref[25:]


def test_couleur_aller_retour():
    from remanence.media.sonde import Couleur
    from remanence.rendu.couleur import depuis_rvba, vers_rvba
    rng = np.random.default_rng(0)
    image = av.VideoFrame(64, 32, "yuv444p10le")
    for p in image.planes:
        brut = rng.integers(200, 800, size=(p.height, p.line_size // 2), dtype=np.uint16)
        p.update(brut.tobytes())
    c = Couleur(1, 1, 1, 1)
    retour = depuis_rvba(vers_rvba(image, c), "yuv444p10le", c)
    for p, q in zip(image.planes, retour.planes):
        a = np.frombuffer(p, np.uint16).reshape(p.height, -1)[:, :64].astype(int)
        b = np.frombuffer(q, np.uint16).reshape(q.height, -1)[:, :64].astype(int)
        assert np.abs(a - b).max() <= 1


def test_niveau_et_solo_de_piste(medias, tmp_path):
    """Une piste à 50 % est recalculée ; une piste en solo masque les autres."""
    projet, fond = _projet(medias, "prores_hq")
    seq = projet.sequence
    seq.pistes_video[0].niveau = 0.5
    sortie = tmp_path / "niveau.mov"
    rapport = exporter(projet, seq, sortie)
    assert rapport.conforme and rapport.images_calculees == 30
    seq.pistes_video[0].niveau = 1.0
    infos, _ = analyser(str(medias["prores_4444"]))
    dessus = Media(nouvel_id(), str(medias["prores_4444"]), infos)
    projet.medias[dessus.id] = dessus
    edition.ajouter_piste(seq, "video")
    edition.ajouter_media(projet, seq, dessus, 5, piste=seq.pistes_video[0])
    seq.pistes_video[1].solo = True
    sortie = tmp_path / "solo.mov"
    rapport = exporter(projet, seq, sortie)
    assert rapport.images_calculees == 0
    assert empreintes_images(str(sortie)) == empreintes_images(str(medias["prores_hq"]))


def test_fondu_enchaine_exporte(medias, tmp_path):
    """À mi-fondu, l'image vaut la moyenne des deux plans."""
    from remanence.rendu.composition import Compositeur
    projet = Projet.nouveau()
    infos, _ = analyser(str(medias["prores_hq"]))
    m = Media(nouvel_id(), str(medias["prores_hq"]), infos)
    projet.medias[m.id] = m
    seq = projet.sequence
    edition.ajouter_media(projet, seq, m, 0, entree=0, duree=20)
    edition.ajouter_media(projet, seq, m, 20, entree=10, duree=20)
    pv = seq.pistes_video[0]
    edition.deplacer(seq, {pv.clips[1].id}, -9, fondus_auto=True)
    a, b = pv.clips
    assert (a.fondu_sortie, b.fondu_entree) == (9, 9)
    c = Compositeur(projet)
    f = 15  # 5e image du fondu de 9 : poids 5/10
    melange = c.image(seq, f)
    projet_a = Projet.depuis_dict(projet.vers_dict())
    projet_a.sequence.pistes_video[0].clips.pop(1)
    projet_a.sequence.pistes_video[0].clips[0].fondu_sortie = 0
    projet_b = Projet.depuis_dict(projet.vers_dict())
    projet_b.sequence.pistes_video[0].clips.pop(0)
    projet_b.sequence.pistes_video[0].clips[0].fondu_entree = 0
    ia = Compositeur(projet_a).image(projet_a.sequence, f)
    ib = Compositeur(projet_b).image(projet_b.sequence, f)
    poids = b.facteur(f)
    assert poids == pytest.approx(0.5)
    assert np.abs(melange - (ia * (1 - poids) + ib * poids)).max() < 1e-4
    rapport = exporter(projet, seq, tmp_path / "fondu.mov")
    assert rapport.conforme and rapport.images_calculees == 9
