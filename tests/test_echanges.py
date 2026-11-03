"""Modèles de nommage, image fixe, import EDL et FCP XML, liste de remplacement."""

from fractions import Fraction
from pathlib import Path

import numpy as np

from remanence.media.sonde import analyser
from remanence.media.timecode import images_vers_tc
from remanence.projet import echanges, edition
from remanence.projet.modele import Media, Projet, nouvel_id
from remanence.rendu import nommage


def test_modeles_de_nommage(tmp_path):
    valeurs = {"plan": "A001:C003", "sequence": "Séquence 1", "projet": "film"}
    assert nommage.remplir("{plan}_remanence_v{version}", valeurs) == "A001_C003_remanence_v01"
    assert nommage.remplir("{projet}_{inconnue}", valeurs) == "film_{inconnue}"
    premier = nommage.nommer(nommage.MODELE_DEFAUT, valeurs, tmp_path, ".mov")
    assert premier.name == "A001_C003_remanence_v01.mov"
    premier.write_bytes(b"")
    assert nommage.nommer(nommage.MODELE_DEFAUT, valeurs, tmp_path, ".mov").name.endswith("v02.mov")
    reserve = {tmp_path / "A001_C003_remanence_v02.mov"}
    assert nommage.nommer(nommage.MODELE_DEFAUT, valeurs, tmp_path, ".mov",
                          reserve).name.endswith("v03.mov"), "un export en attente compte"


def _projet(medias, cle="prores_hq"):
    projet = Projet.nouveau()
    infos, _ = analyser(str(medias[cle]))
    m = Media(nouvel_id(), str(medias[cle]), infos)
    projet.medias[m.id] = m
    edition.regler_sequence_sur_media(projet.sequence, m)
    return projet, m


def test_import_edl_et_liste_de_remplacement(medias, tmp_path):
    projet, m = _projet(medias)
    v = m.infos.video
    cad = Fraction(v.cadence)
    tc = lambda n: images_vers_tc(n, cad, False)  # noqa: E731
    nom = Path(m.chemin).name
    edl = tmp_path / "montage.edl"
    edl.write_text(f"""TITLE: Montage
FCM: NON-DROP FRAME

001  AX       V     C        {tc(v.tc_debut + 2)} {tc(v.tc_debut + 12)} {tc(86400)} {tc(86410)}
* FROM CLIP NAME: {nom}
002  AX       V     C        {tc(v.tc_debut + 0)} {tc(v.tc_debut + 5)} {tc(86415)} {tc(86420)}
* FROM CLIP NAME: absent.mov
""", encoding="utf-8")
    seq, manquants = echanges.importer_montage(projet, edl)
    assert manquants == ["absent.mov"]
    assert seq.tc_debut == 86400 and Fraction(seq.cadence) == cad
    clip = seq.pistes_video[0].clips[0]
    assert (clip.media_id, clip.debut, clip.entree, clip.duree) == (m.id, 0, 2, 10)
    assert [mq.position for mq in seq.marqueurs] == [15] and "absent" in seq.marqueurs[0].nom

    plans = [{"fichier": str(tmp_path / "plan_remanence_v01.mov"), "tc": 86400, "duree": 10,
              "enregistrement": 86400}]
    for ext in (".edl", ".xml"):
        sortie = tmp_path / f"remplacement{ext}"
        echanges.ecrire_remplacement(plans, sortie, seq.cadence)
        import opentimelineio as otio
        lu = otio.adapters.read_from_file(str(sortie), echanges.ADAPTATEURS[ext],
                                          **({"rate": float(cad)} if ext == ".edl" else {}))
        lu = lu if isinstance(lu, otio.schema.Timeline) else next(iter(lu))
        c = next(iter(lu.find_clips()))
        assert "plan_remanence_v01" in (c.name or "") or "plan_remanence_v01" in \
            str(getattr(c.media_reference, "target_url", ""))
        assert round(c.source_range.start_time.value) == 86400
        assert round(c.source_range.duration.value) == 10


def test_image_fixe(medias, tmp_path):
    from remanence.rendu.export import exporter_image
    projet, m = _projet(medias, "prores_4444")
    edition.ajouter_media(projet, projet.sequence, m, 0)
    for ext in (".png", ".exr"):
        exporter_image(projet, projet.sequence, 3, tmp_path / f"image{ext}")
        infos, _ = analyser(str(tmp_path / f"image{ext}"))
        assert (infos.video.largeur, infos.video.hauteur) == (m.infos.video.largeur,
                                                              m.infos.video.hauteur)
        assert infos.video.alpha
    assert np.isfinite(1.0)
