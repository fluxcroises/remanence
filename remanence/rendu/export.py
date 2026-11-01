"""Export d'une séquence, avec recopie des images que rien ne modifie.

Une image de la timeline qui n'est que l'image d'origine d'un média (clip
opaque, sans fondu ni effet) n'est pas réencodée : son paquet compressé est
recopié tel quel, donc ses pixels restent identiques à la source. Pour les
codecs à groupes d'images (H.264, HEVC), cette recopie n'est possible que si
l'export reprend le média entier sans modification.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

import av
import numpy as np

from remanence.media import timecode as tcmod
from remanence.media.lecteur import FREQUENCE_MIXAGE, LecteurPaquets
from remanence.media.sonde import Couleur, InfosVideo, analyser
from remanence.projet.modele import Media, Projet, Sequence
from remanence.rendu.composition import Compositeur, couches, identite
from remanence.rendu.conformite import Verification, verifier
from remanence.rendu.couleur import depuis_rvba


@dataclass
class FormatExport:
    cle: str
    nom: str
    codec: str
    pix_fmt: str
    extension: str
    famille: str
    profil: str = ""
    options: dict = field(default_factory=dict)
    # Une image par fichier, numérotée (DPX, EXR, TIFF) ; pas de son ni de timecode.
    sequence: bool = False


FORMATS = {f.cle: f for f in [
    FormatExport("prores_proxy", "ProRes 422 Proxy", "prores_ks", "yuv422p10le", ".mov", "prores",
                 "Proxy", {"profile": "0"}),
    FormatExport("prores_lt", "ProRes 422 LT", "prores_ks", "yuv422p10le", ".mov", "prores",
                 "LT", {"profile": "1"}),
    FormatExport("prores_422", "ProRes 422", "prores_ks", "yuv422p10le", ".mov", "prores",
                 "Standard", {"profile": "2"}),
    FormatExport("prores_hq", "ProRes 422 HQ", "prores_ks", "yuv422p10le", ".mov", "prores",
                 "HQ", {"profile": "3"}),
    FormatExport("prores_4444", "ProRes 4444", "prores_ks", "yuva444p10le", ".mov", "prores",
                 "4444", {"profile": "4"}),
    FormatExport("prores_xq", "ProRes 4444 XQ", "prores_ks", "yuva444p10le", ".mov", "prores",
                 "XQ", {"profile": "5"}),
    FormatExport("dnxhr_lb", "DNxHR LB", "dnxhd", "yuv422p", ".mov", "dnxhd", "DNXHR LB",
                 {"profile": "dnxhr_lb"}),
    FormatExport("dnxhr_sq", "DNxHR SQ", "dnxhd", "yuv422p", ".mov", "dnxhd", "DNXHR SQ",
                 {"profile": "dnxhr_sq"}),
    FormatExport("dnxhr_hq", "DNxHR HQ", "dnxhd", "yuv422p", ".mov", "dnxhd", "DNXHR HQ",
                 {"profile": "dnxhr_hq"}),
    FormatExport("dnxhr_hqx", "DNxHR HQX", "dnxhd", "yuv422p10le", ".mov", "dnxhd", "DNXHR HQX",
                 {"profile": "dnxhr_hqx"}),
    FormatExport("dnxhr_444", "DNxHR 444", "dnxhd", "yuv444p10le", ".mov", "dnxhd", "DNXHR 444",
                 {"profile": "dnxhr_444"}),
    FormatExport("h264", "H.264 (MP4)", "libx264", "yuv420p", ".mp4", "h264", "",
                 {"crf": "12", "preset": "slow"}),
    FormatExport("hevc10", "H.265 10 bits (MP4)", "libx265", "yuv420p10le", ".mp4", "hevc", "",
                 {"crf": "12", "preset": "slow", "x265-params": "log-level=error"}),
    FormatExport("av1", "AV1 10 bits (MP4)", "libsvtav1", "yuv420p10le", ".mp4", "av1", "",
                 {"crf": "20", "preset": "6"}),
    FormatExport("webm", "WebM VP9 avec alpha", "libvpx-vp9", "yuva420p", ".webm", "vp9", "",
                 {"crf": "18", "b": "0", "row-mt": "1", "auto-alt-ref": "0"}),
    FormatExport("gif", "GIF animé", "gif", "pal8", ".gif", "gif"),
    FormatExport("dpx10", "Séquence DPX 10 bits", "dpx", "gbrp10le", ".dpx", "dpx",
                 sequence=True),
    FormatExport("exr", "Séquence EXR demi-flottant", "exr", "gbrapf32le", ".exr", "exr", "",
                 {"format": "half", "compression": "zip16"}, sequence=True),
    FormatExport("tiff16", "Séquence TIFF 16 bits", "tiff", "rgb48le", ".tif", "tiff",
                 sequence=True),
]}


def chemin_image(chemin: Path, numero: int) -> Path:
    """Fichier d'une image d'une séquence : nom_0086400.dpx, numéroté comme le timecode."""
    return chemin.with_name(f"{chemin.stem}_{numero:07d}{chemin.suffix}")


def _trame_flottante(rvba: np.ndarray) -> av.VideoFrame:
    """EXR : les valeurs flottantes telles quelles (surblancs compris), sans prémultiplication."""
    a = rvba[..., 3:4]
    droit = np.where(a > 1e-6, rvba[..., :3] / np.maximum(a, 1e-6), 0.0)
    return av.VideoFrame.from_ndarray(
        np.ascontiguousarray(np.concatenate([droit, a], axis=2), dtype=np.float32),
        format="gbrapf32le")


class _PaletteGif:
    """Une palette de 256 couleurs par image (palettegen puis paletteuse de FFmpeg)."""

    def __init__(self, largeur: int, hauteur: int, cadence: Fraction):
        g = self.graphe = av.filter.Graph()
        self._entree = g.add_buffer(width=largeur, height=hauteur, format="rgb24",
                                    time_base=1 / cadence)
        separe = g.add("split")
        palette = g.add("palettegen", "stats_mode=single")
        usage = g.add("paletteuse", "new=1")
        sortie = g.add("buffersink")
        self._entree.link_to(separe)
        separe.link_to(usage, 0, 0)
        separe.link_to(palette, 1, 0)
        palette.link_to(usage, 0, 1)
        usage.link_to(sortie)
        g.configure()

    def convertir(self, rvba: np.ndarray, pts: int) -> av.VideoFrame:
        rvb = np.clip(rvba[..., :3], 0.0, 1.0) * 255.0 + 0.5
        trame = av.VideoFrame.from_ndarray(np.ascontiguousarray(rvb.astype(np.uint8)),
                                           format="rgb24")
        trame.pts = pts
        self.graphe.push(trame)
        return self.graphe.pull()

PROFILS_PRORES = {"proxy": "prores_proxy", "lt": "prores_lt", "standard": "prores_422",
                  "hq": "prores_hq", "4444": "prores_4444", "xq": "prores_xq", "4444xq": "prores_xq"}


@dataclass
class Rapport:
    chemin: Path
    images_recopiees: int
    images_calculees: int
    audio: str
    verifications: list[Verification]
    avertissements: list[str]

    @property
    def conforme(self) -> bool:
        return all(v.ok for v in self.verifications)


def format_source(v: InfosVideo) -> tuple[FormatExport, str | None]:
    """Format « comme la source ». Renvoie aussi un avertissement si ce n'est pas possible."""
    profil = (v.profil or "").lower().replace(" ", "")
    if v.codec == "prores":
        fmt = FORMATS["prores_hq"]
        for motif, cle in sorted(PROFILS_PRORES.items(), key=lambda kv: -len(kv[0])):
            if motif in profil:
                fmt = FORMATS[cle]
                break
        if fmt.pix_fmt.startswith("yuva") and not v.alpha:
            fmt = FormatExport(**{**fmt.__dict__, "pix_fmt": "yuv444p10le"})
        return fmt, None
    if v.codec == "dnxhd":
        for cle in ("dnxhr_hqx", "dnxhr_444", "dnxhr_hq", "dnxhr_sq", "dnxhr_lb"):
            if cle.split("_")[1] in profil.replace("dnxhr", ""):
                f = FORMATS[cle]
                return FormatExport(**{**f.__dict__, "pix_fmt": v.pix_fmt}), None
    if v.codec in ("h264", "hevc"):
        base = FORMATS["h264" if v.codec == "h264" else "hevc10"]
        return FormatExport(**{**base.__dict__, "pix_fmt": v.pix_fmt}), None
    return FORMATS["prores_hq"], (f"{v.codec_long} non réencodable à l'identique : "
                                  "export en ProRes 422 HQ.")


def _compatible(v: InfosVideo, fmt: FormatExport, seq: Sequence) -> bool:
    if v.codec != fmt.famille:
        return False
    if fmt.famille == "prores":
        # Le décodeur ProRes de FFmpeg sort le 4444 en 12 bits : on compare profil et alpha.
        if v.alpha != fmt.pix_fmt.startswith("yuva"):
            return False
    elif v.pix_fmt != fmt.pix_fmt:
        return False
    if (v.largeur, v.hauteur) != (seq.largeur, seq.hauteur):
        return False
    if Fraction(v.cadence) != seq.fraction_cadence:
        return False
    if fmt.profil and fmt.profil.lower().replace(" ", "") not in (v.profil or "").lower().replace(" ", ""):
        return False
    return True


def media_reference(projet: Projet, seq: Sequence, debut: int, fin: int) -> Media | None:
    for f in range(debut, fin):
        media = next((c.media for c in reversed(couches(projet, seq, f)) if c.media), None)
        if media is not None:
            return media
    return None


def _plan_audio(projet: Projet, seq: Sequence, debut: int, fin: int):
    """('copie', media) si l'audio d'un média est repris entier et inchangé, sinon ('mix'|None)."""
    clips = [(p, c) for p in seq.pistes_entendues("audio") for c in p.clips
             if c.fin > debut and c.debut < fin]
    if not clips:
        return None, None
    if len(clips) == 1 and clips[0][0].niveau == 1.0:
        c = clips[0][1]
        m = projet.medias.get(c.media_id)
        if m and m.infos.video and c.debut <= debut and c.fin >= fin \
                and c.entree + (debut - c.debut) == 0 and fin - debut == m.infos.video.nb_images \
                and all(abs(c.facteur(f) - 1.0) < 1e-9 for f in range(debut, fin)):
            return "copie", m
    return "mix", None


def exporter(projet: Projet, seq: Sequence, chemin: Path, cle_format: str = "source",
             debut: int | None = None, fin: int | None = None, progression=None,
             annule: threading.Event | None = None) -> Rapport:
    chemin = Path(chemin)
    debut = seq.point_entree if debut is None and seq.point_entree is not None else (debut or 0)
    fin = fin if fin is not None else (seq.point_sortie if seq.point_sortie is not None
                                       else seq.duree())
    if fin <= debut:
        raise ValueError("Rien à exporter : la plage est vide.")
    avertissements: list[str] = []
    ref = media_reference(projet, seq, debut, fin)
    couleur = ref.infos.video.couleur if ref else Couleur(1, 1, 1, 1)
    if cle_format == "source":
        if ref is None:
            fmt = FORMATS["prores_hq"]
        else:
            fmt, avert = format_source(ref.infos.video)
            if avert:
                avertissements.append(avert)
    else:
        fmt = FORMATS[cle_format]
    cadence = seq.fraction_cadence
    base_temps = 1 / cadence
    n_images = fin - debut

    piles = [couches(projet, seq, f) for f in range(debut, fin)]
    idents = [identite(p, seq) for p in piles]
    remux_total = (
        ref is not None and all(i is not None and i.media.id == ref.id for i in idents)
        and [i.image_source for i in idents] == list(range(ref.infos.video.nb_images))
        and _compatible(ref.infos.video, fmt, seq))
    mode_audio, media_audio = _plan_audio(projet, seq, debut, fin)

    if fmt.sequence or fmt.famille == "gif":
        # Ni son ni recopie : chaque image est calculée.
        mode_audio, media_audio = None, None
        remux_total = False
        idents = [None] * n_images
    elif mode_audio == "copie" and chemin.suffix.lower() == ".webm":
        mode_audio = "mix"  # WebM n'accepte pas le son des sources de montage : il est réencodé.
    if fmt.famille == "gif":
        avertissements.append("GIF : durée de chaque image arrondie au centième de seconde.")
    numero_depart = seq.tc_debut + debut
    partiel = chemin.with_name(chemin.stem + ".partiel" + chemin.suffix)
    # Synchrone : les pré-rendus codec manquants sont calculés pendant l'export.
    compositeur = Compositeur(projet, synchrone=True)
    lecteurs_paquets: dict[str, LecteurPaquets] = {}
    sources_ouvertes = []
    copiees = calculees = 0
    sortie = None
    palette = None
    try:
        if fmt.sequence:
            motif = chemin.with_name(f"{chemin.stem}_%07d{chemin.suffix}")
            sortie = av.open(str(motif), "w", format="image2",
                             options={"start_number": str(numero_depart)})
        else:
            sortie = av.open(str(partiel), "w")
        # Une source sans timecode (téléphone, web) donne un export sans timecode.
        sans_tc = ref is not None and ref.infos.video.tc_debut is None and seq.tc_debut == 0
        tc = None if sans_tc else tcmod.images_vers_tc(seq.tc_debut + debut, cadence, seq.tc_drop)
        if tc:
            sortie.metadata["timecode"] = tc

        if remux_total:
            src = av.open(ref.chemin)
            sources_ouvertes.append(src)
            fv_src = src.streams.video[0]
            fv = sortie.add_stream_from_template(fv_src)
            # Sans cadence explicite (le décodeur ProRes la laisse à 0), MOV n'écrit pas de timecode.
            fv.codec_context.framerate = cadence
            # Le gabarit perd l'étiquette du codec ; MOV en déduirait un ProRes HQ par défaut.
            fv.codec_context.codec_tag = fv_src.codec_context.codec_tag
            if tc:
                fv.metadata["timecode"] = tc
        else:
            fv = sortie.add_stream(fmt.codec, rate=cadence)
            fv.width, fv.height, fv.pix_fmt = seq.largeur, seq.hauteur, fmt.pix_fmt
            fv.time_base = base_temps
            cc = fv.codec_context
            cc.options = dict(fmt.options)
            cc.color_primaries = couleur.primaires
            cc.color_trc = couleur.transfert
            cc.colorspace = couleur.matrice
            cc.color_range = couleur.plage or 1
            if ref and ref.infos.video.rapport_pixel != "1:1":
                cc.sample_aspect_ratio = Fraction(ref.infos.video.rapport_pixel.replace(":", "/"))
            if tc:
                fv.metadata["timecode"] = tc

        flux_audio_copie = []
        fa = None
        if mode_audio == "copie":
            src_a = av.open(media_audio.chemin)
            sources_ouvertes.append(src_a)
            for a in src_a.streams.audio:
                flux_audio_copie.append((a, sortie.add_stream_from_template(a)))
            iter_audio = src_a.demux([a for a, _ in flux_audio_copie])
        elif mode_audio == "mix":
            codec_audio = {".mp4": "aac", ".m4v": "aac", ".webm": "libopus"}.get(
                chemin.suffix.lower(), "pcm_s24le")
            fa = sortie.add_stream(codec_audio, rate=FREQUENCE_MIXAGE)
            fa.layout = "stereo"
            if codec_audio in ("aac", "libopus"):
                fa.bit_rate = 320000
        audio_attente = None
        echantillons_ecrits = 0
        par_image = FREQUENCE_MIXAGE / float(cadence)

        def pousser_audio(jusqua_s: float):
            nonlocal audio_attente, echantillons_ecrits
            if mode_audio == "copie":
                while True:
                    if audio_attente is None:
                        audio_attente = next(iter_audio, False)
                    if audio_attente is False:
                        return
                    p = audio_attente
                    if p.pts is not None and float(p.pts * p.time_base) >= jusqua_s:
                        return
                    if p.size:
                        p.stream = dict((a.index, o) for a, o in flux_audio_copie)[p.stream.index]
                        sortie.mux(p)
                    audio_attente = None
            elif mode_audio == "mix":
                cible = round(jusqua_s * FREQUENCE_MIXAGE)
                if cible <= echantillons_ecrits:
                    return
                debut_seq = round(debut * par_image)
                bloc = compositeur.audio(seq, debut_seq + echantillons_ecrits,
                                         cible - echantillons_ecrits)
                bloc = np.clip(bloc, -1.0, 1.0)
                if fa.codec_context.name in ("aac", "libopus"):
                    trame = av.AudioFrame.from_ndarray(np.ascontiguousarray(bloc.T), format="fltp",
                                                       layout="stereo")
                else:
                    entiers = (np.rint(bloc * 8388607.0).astype(np.int32) << 8).reshape(1, -1)
                    trame = av.AudioFrame.from_ndarray(entiers, format="s32", layout="stereo")
                trame.sample_rate = FREQUENCE_MIXAGE
                trame.pts = echantillons_ecrits
                trame.time_base = Fraction(1, FREQUENCE_MIXAGE)
                for p in fa.encode(trame):
                    sortie.mux(p)
                echantillons_ecrits = cible

        if remux_total:
            n = 0
            for p in src.demux(fv_src):
                if annule is not None and annule.is_set():
                    raise InterruptedError
                if p.size == 0:
                    continue
                p.stream = fv
                sortie.mux(p)
                n += 1
                copiees += 1
                pousser_audio(n / float(cadence))
                if progression:
                    progression(n / n_images)
        else:
            for i in range(n_images):
                if annule is not None and annule.is_set():
                    raise InterruptedError
                ident = idents[i]
                v = ident.media.infos.video if ident else None
                if ident and v.intra and _compatible(v, fmt, seq):
                    lp = lecteurs_paquets.get(ident.media.id)
                    if lp is None:
                        infos, index = analyser(ident.media.chemin)
                        lp = lecteurs_paquets[ident.media.id] = LecteurPaquets(
                            ident.media.chemin, index, infos.sequence_images, v.cadence)
                    p = lp.paquet(ident.image_source)
                    p.stream = fv
                    p.pts = p.dts = i
                    p.duration = 1
                    p.time_base = base_temps
                    sortie.mux(p)
                    copiees += 1
                else:
                    rvba = compositeur.image(seq, debut + i)
                    if fmt.famille == "gif":
                        if palette is None:
                            palette = _PaletteGif(seq.largeur, seq.hauteur, cadence)
                        trame = palette.convertir(rvba, i)
                    elif fmt.pix_fmt.endswith("f32le"):
                        trame = _trame_flottante(rvba)
                    else:
                        trame = depuis_rvba(rvba, fmt.pix_fmt, couleur)
                    trame.pts = i
                    trame.time_base = base_temps
                    for p in fv.encode(trame):
                        sortie.mux(p)
                    calculees += 1
                pousser_audio((i + 1) / float(cadence))
                if progression:
                    progression((i + 1) / n_images)
            if calculees:
                for p in fv.encode():
                    sortie.mux(p)
        pousser_audio(n_images / float(cadence) + (1.0 if mode_audio == "copie" else 0.0))
        if fa is not None:
            for p in fa.encode():
                sortie.mux(p)
        sortie.close()
    except BaseException:
        if sortie is not None:
            try:
                sortie.close()
            except Exception:
                pass
        partiel.unlink(missing_ok=True)
        if fmt.sequence:
            # Rien de la séquence interrompue ne reste sur le disque.
            for k in range(n_images):
                chemin_image(chemin, numero_depart + k).unlink(missing_ok=True)
        raise
    finally:
        compositeur.fermer()
        for lp in lecteurs_paquets.values():
            lp.fermer()
        for s in sources_ouvertes:
            s.close()
    if fmt.sequence:
        chemin = chemin_image(chemin, numero_depart)
        infos_sortie, _ = analyser(str(chemin), str(cadence))
    else:
        partiel.replace(chemin)
        infos_sortie, _ = analyser(str(chemin))
    rvb = fmt.sequence or fmt.famille == "gif"
    attendu = {
        "nb_images": n_images, "cadence": cadence, "largeur": seq.largeur, "hauteur": seq.hauteur,
        # Séquences d'images et GIF : ni timecode ni métadonnées couleur dans ces fichiers.
        "tc_debut": None if tc is None or rvb else seq.tc_debut + debut,
        "couleur": None if rvb else couleur,
        "cadence_exacte": fmt.famille != "gif",
        "rapport_pixel": ref.infos.video.rapport_pixel if ref else "1:1",
    }
    return Rapport(chemin, copiees, calculees,
                   {"copie": "recopié sans réencodage", "mix": "mixé et encodé",
                    None: "aucun"}[mode_audio],
                   verifier(infos_sortie, attendu), avertissements)
