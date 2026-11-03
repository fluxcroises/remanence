"""Échanges avec le logiciel du monteur, par OpenTimelineIO (section 4.10 du cahier).

- `importer_montage` lit une EDL CMX 3600 ou un FCP XML et en fait une séquence : chaque plan
  est retrouvé parmi les médias du projet par son nom (nom du clip, bobine, nom du fichier) et
  posé avec son timecode, à sa place dans le montage. Un plan sans média devient un marqueur.
- `ecrire_remplacement` écrit la liste des plans exportés (EDL ou FCP XML) : le monteur
  l'importe, ou y relie ses plans, par le nom du fichier et le timecode.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from urllib.parse import unquote, urlparse

from remanence.projet.modele import Clip, Marqueur, Media, Piste, Projet, Sequence, nouvel_id

ADAPTATEURS = {".edl": "cmx_3600", ".xml": "fcp_xml"}
CADENCES = {23.976: "24000/1001", 24.0: "24", 25.0: "25", 29.97: "30000/1001", 30.0: "30",
            50.0: "50", 59.94: "60000/1001", 60.0: "60"}


def _cadence(rate: float) -> str:
    proche = min(CADENCES, key=lambda r: abs(r - rate))
    return CADENCES[proche] if abs(proche - rate) < 0.01 else str(Fraction(rate).limit_denominator(1001))


def _noms(clip) -> list[str]:
    """Les noms sous lesquels chercher le média d'un plan, du plus sûr au moins sûr."""
    noms = []
    ref = clip.media_reference
    url = getattr(ref, "target_url", None)
    if url:
        noms.append(Path(unquote(urlparse(url).path)).stem)
    if clip.name:
        noms.append(Path(clip.name).stem)
    bobine = (clip.metadata.get("cmx_3600") or {}).get("reel")
    if bobine:
        noms.append(bobine)
    return [n.lower() for n in noms if n]


def _trouver_media(projet: Projet, clip, source_tc: int, cadence: Fraction) -> Media | None:
    noms = _noms(clip)
    candidats = [m for m in projet.medias.values() if m.infos.video is not None]
    for nom in noms:
        for m in candidats:
            if Path(m.chemin).stem.lower() == nom:
                return m
    # Une bobine de caméra (A001C003) au début du nom du fichier, si le timecode concorde.
    for nom in noms:
        for m in candidats:
            tc0 = m.infos.video.tc_debut
            if Path(m.chemin).stem.lower().startswith(nom) and tc0 is not None                     and tc0 <= source_tc < tc0 + m.nb_images(cadence):
                return m
    if noms:
        return None  # un nom est donné et aucun média ne le porte : plan manquant
    # Sans nom, un seul média dont le timecode couvre le plan.
    couvrent = [m for m in candidats if m.infos.video.tc_debut is not None
                and m.infos.video.tc_debut <= source_tc
                < m.infos.video.tc_debut + m.nb_images(cadence)]
    return couvrent[0] if len(couvrent) == 1 else None


def _debut_edl(chemin: Path, cadence: Fraction) -> int:
    """Timecode d'enregistrement du premier événement d'une EDL (OpenTimelineIO ramène le
    montage à zéro) : le troisième des quatre timecodes de la ligne."""
    import re
    from remanence.media.timecode import tc_vers_images
    debuts = []
    for ligne in chemin.read_text(encoding="utf-8", errors="replace").splitlines():
        tcs = re.findall(r"\d\d:\d\d:\d\d[:;.]\d\d", ligne)
        if re.match(r"\s*\d+\s", ligne) and len(tcs) == 4:
            try:
                debuts.append(tc_vers_images(tcs[2], cadence)[0])
            except ValueError:
                pass
    return min(debuts, default=0)


def importer_montage(projet: Projet, chemin: Path, cadence: str | None = None
                     ) -> tuple[Sequence, list[str]]:
    """Une nouvelle séquence d'après le montage ; renvoie aussi les plans sans média. Une EDL
    ne dit pas sa cadence : celle de la séquence active sert, sauf si on en donne une."""
    import opentimelineio as otio
    chemin = Path(chemin)
    adaptateur = ADAPTATEURS.get(chemin.suffix.lower())
    if adaptateur is None:
        raise ValueError("Format de montage inconnu : EDL ou XML.")
    reference = projet.sequence
    options = {"rate": float(Fraction(cadence or reference.cadence))} \
        if adaptateur == "cmx_3600" else {}
    lu = otio.adapters.read_from_file(str(chemin), adaptateur, **options)
    timeline = lu if isinstance(lu, otio.schema.Timeline) else next(iter(lu))
    clips = list(timeline.find_clips())
    rate = clips[0].source_range.duration.rate if clips else float(Fraction(reference.cadence))
    cad = _cadence(rate)
    depart = timeline.global_start_time
    seq = Sequence(nouvel_id(), timeline.name or chemin.stem, reference.largeur,
                   reference.hauteur, cad, 0, False, True)
    if depart is not None:
        seq.tc_debut = round(depart.rescaled_to(rate).value)
    elif adaptateur == "cmx_3600":
        seq.tc_debut = _debut_edl(chemin, Fraction(cad))
    manquants: list[str] = []
    for genre, pistes in (("video", timeline.video_tracks()), ("audio", timeline.audio_tracks())):
        for n, piste_otio in enumerate(pistes, 1):
            piste = Piste(nouvel_id(), genre, f"{'Vidéo' if genre == 'video' else 'Audio'} {n}")
            for clip in piste_otio.find_clips():
                place = clip.range_in_parent()
                debut = round(place.start_time.rescaled_to(rate).value)
                duree = max(1, round(clip.source_range.duration.rescaled_to(rate).value))
                source_tc = round(clip.source_range.start_time.rescaled_to(rate).value)
                media = _trouver_media(projet, clip, source_tc, Fraction(cad))
                if media is None:
                    if genre == "video":
                        nom = clip.name or "Plan"
                        manquants.append(nom)
                        seq.marqueurs.append(Marqueur(debut, f"Manquant : {nom}", "warning"))
                    continue
                tc0 = media.infos.video.tc_debut or 0
                entree = max(0, min(source_tc - tc0, media.nb_images(Fraction(cad)) - 1))
                piste.clips.append(Clip(nouvel_id(), media.id, debut, entree, duree))
            piste.trier()
            # Les pistes vidéo de la plus haute à la plus basse, comme dans Remanence.
            if genre == "video":
                seq.pistes.insert(0, piste)
            else:
                seq.pistes.append(piste)
    if not seq.pistes_video:
        seq.pistes.insert(0, Piste(nouvel_id(), "video", "Vidéo 1"))
    # Mêmes liaisons qu'à la pose : l'image et le son d'un même plan au même endroit.
    for v in seq.pistes_video:
        for c in v.clips:
            for a in seq.pistes_audio:
                for s in a.clips:
                    if s.lien is None and (s.media_id, s.debut, s.entree, s.duree) == \
                            (c.media_id, c.debut, c.entree, c.duree):
                        c.lien = c.lien or nouvel_id()
                        s.lien = c.lien
    projet.sequences.append(seq)
    return seq, manquants


def ecrire_remplacement(plans: list[dict], chemin: Path, cadence: str):
    """plans : {"fichier", "tc" (timecode du premier plan exporté, en images), "duree",
    "enregistrement" (place dans le montage, en images de timecode)}. Écrit une EDL ou un FCP
    XML selon l'extension, plans triés par place, trous comblés."""
    import opentimelineio as otio
    chemin = Path(chemin)
    adaptateur = ADAPTATEURS.get(chemin.suffix.lower())
    if adaptateur is None:
        raise ValueError("Format de liste inconnu : EDL ou XML.")
    rate = float(Fraction(cadence))
    plans = sorted(plans, key=lambda p: p["enregistrement"])
    timeline = otio.schema.Timeline(name=chemin.stem)
    piste = otio.schema.Track(name="V1", kind=otio.schema.TrackKind.Video)
    timeline.tracks.append(piste)
    depart = plans[0]["enregistrement"] if plans else 0
    timeline.global_start_time = otio.opentime.RationalTime(depart, rate)
    position = depart
    for p in plans:
        if p["enregistrement"] > position:
            piste.append(otio.schema.Gap(source_range=otio.opentime.TimeRange(
                otio.opentime.RationalTime(0, rate),
                otio.opentime.RationalTime(p["enregistrement"] - position, rate))))
        fichier = Path(p["fichier"])
        plage = otio.opentime.TimeRange(otio.opentime.RationalTime(p["tc"], rate),
                                        otio.opentime.RationalTime(p["duree"], rate))
        clip = otio.schema.Clip(
            name=fichier.name,
            media_reference=otio.schema.ExternalReference(target_url=fichier.as_uri(),
                                                          available_range=plage),
            source_range=plage)
        clip.metadata["cmx_3600"] = {"reel": fichier.stem[:32]}
        piste.append(clip)
        position = max(position, p["enregistrement"] + p["duree"])
    otio.adapters.write_to_file(timeline, str(chemin), adaptateur)
