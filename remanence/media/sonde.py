"""Analyse d'un fichier média : fiche technique et index des images."""

from __future__ import annotations

import os
import re
import threading
from dataclasses import asdict, dataclass, field
from fractions import Fraction
from pathlib import Path

import av

from remanence.media import timecode as tcmod

EXTENSIONS_RAW = {
    ".braw": "Blackmagic RAW",
    ".r3d": "REDCODE RAW",
    ".ari": "ARRIRAW",
    ".arx": "ARRIRAW",
    ".mxr": "ARRIRAW",
    ".crm": "Canon Cinema RAW Light",
    ".nev": "Nikon N-RAW",
}

EXTENSIONS_IMAGES = {".dpx", ".exr", ".tif", ".tiff", ".png", ".jpg", ".jpeg"}

# Codecs où chaque image est compressée seule : on peut recopier une image sans réencoder.
CODECS_INTRA = {"prores", "dnxhd", "mjpeg", "png", "dpx", "tiff", "exr", "rawvideo", "cfhd", "v210"}

NOMS_PRIMAIRES = {1: "BT.709", 4: "BT.470M", 5: "BT.470BG", 6: "SMPTE 170M", 7: "SMPTE 240M",
                  9: "BT.2020", 11: "DCI-P3", 12: "Display P3", 2: "non précisé"}
NOMS_TRANSFERT = {1: "BT.709", 4: "Gamma 2.2", 5: "Gamma 2.8", 6: "SMPTE 170M", 8: "linéaire",
                  13: "sRGB", 14: "BT.2020 10 bits", 15: "BT.2020 12 bits", 16: "PQ (ST 2084)",
                  18: "HLG", 2: "non précisé"}
NOMS_MATRICE = {0: "RVB", 1: "BT.709", 5: "BT.470BG", 6: "SMPTE 170M", 7: "SMPTE 240M",
                9: "BT.2020 NCL", 10: "BT.2020 CL", 2: "non précisée"}
NOMS_PLAGE = {0: "non précisée", 1: "limitée (vidéo)", 2: "complète"}


class MediaIllisible(Exception):
    """Fichier que Remanence ne peut pas ouvrir, avec un message qui dit quoi faire."""


@dataclass
class Couleur:
    primaires: int = 2
    transfert: int = 2
    matrice: int = 2
    plage: int = 0

    def decrire(self) -> str:
        return (f"primaires {NOMS_PRIMAIRES.get(self.primaires, self.primaires)}, "
                f"transfert {NOMS_TRANSFERT.get(self.transfert, self.transfert)}, "
                f"matrice {NOMS_MATRICE.get(self.matrice, self.matrice)}, "
                f"plage {NOMS_PLAGE.get(self.plage, self.plage)}")


@dataclass
class InfosVideo:
    index_flux: int
    codec: str
    codec_long: str
    profil: str
    pix_fmt: str
    bits: int
    echantillonnage: str
    alpha: bool
    largeur: int
    hauteur: int
    rapport_pixel: str
    cadence: str
    nb_images: int
    tc_debut: int | None
    tc_drop: bool
    couleur: Couleur
    entrelace: bool
    trame_haute_dabord: bool
    cadence_variable: bool
    intra: bool

    @property
    def fraction_cadence(self) -> Fraction:
        return Fraction(self.cadence)

    @property
    def tc_texte(self) -> str | None:
        if self.tc_debut is None:
            return None
        return tcmod.images_vers_tc(self.tc_debut, self.fraction_cadence, self.tc_drop)


@dataclass
class InfosAudio:
    index_flux: int
    codec: str
    frequence: int
    canaux: int
    disposition: str
    format_echantillon: str
    bits: int


@dataclass
class InfosMedia:
    chemin: str
    nom: str
    conteneur: str
    taille_octets: int
    date_modif: float
    duree_s: float
    video: InfosVideo | None = None
    audio: list[InfosAudio] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)
    sequence_images: dict | None = None

    def vers_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def depuis_dict(d: dict) -> "InfosMedia":
        d = dict(d)
        v = d.get("video")
        if v:
            v = dict(v)
            v["couleur"] = Couleur(**v["couleur"])
            d["video"] = InfosVideo(**v)
        d["audio"] = [InfosAudio(**a) for a in d.get("audio", [])]
        return InfosMedia(**d)

    def fiche(self) -> list[tuple[str, str]]:
        """Lignes de la fiche technique, prêtes à afficher."""
        lignes = [("Fichier", self.nom), ("Conteneur", self.conteneur),
                  ("Durée", f"{self.duree_s:.3f} s".replace(".", ","))]
        v = self.video
        if v:
            cad = float(v.fraction_cadence)
            lignes += [
                ("Codec vidéo", f"{v.codec_long} ({v.codec})"),
                ("Profil", v.profil or "non indiqué"),
                ("Image", f"{v.largeur} × {v.hauteur}, pixels {v.rapport_pixel}"),
                ("Profondeur", f"{v.bits} bits, {v.echantillonnage}{', avec alpha' if v.alpha else ''}"),
                ("Format de pixel", v.pix_fmt),
                ("Cadence", f"{cad:.3f} i/s ({v.cadence})".replace(".", ",", 1)
                 + (", variable" if v.cadence_variable else "")),
                ("Images", str(v.nb_images)),
                ("Timecode", v.tc_texte or "absent"),
                ("Balayage", ("entrelacé, trame " + ("haute" if v.trame_haute_dabord else "basse")
                              + " d'abord") if v.entrelace else "progressif"),
                ("Couleur", v.couleur.decrire()),
            ]
        else:
            lignes.append(("Vidéo", "aucune"))
        if self.audio:
            for i, a in enumerate(self.audio, 1):
                lignes.append((f"Audio {i}", f"{a.codec}, {a.frequence} Hz, {a.canaux} canal(aux) "
                                             f"{a.disposition}, {a.bits} bits"))
        else:
            lignes.append(("Audio", "aucun"))
        for av_ in self.avertissements:
            lignes.append(("Attention", av_))
        return lignes


@dataclass
class IndexImages:
    """Horodatages (pts) de chaque image dans l'ordre d'affichage, et images clés."""
    pts: list[int]
    cles: list[bool]
    base_temps: Fraction

    def __len__(self) -> int:
        return len(self.pts)


def _echantillonnage(pix_fmt: str) -> str:
    for motif, txt in (("420", "4:2:0"), ("422", "4:2:2"), ("444", "4:4:4"), ("411", "4:1:1"),
                       ("440", "4:4:0"), ("410", "4:1:0")):
        if motif in pix_fmt:
            return txt
    if pix_fmt.startswith(("rgb", "bgr", "gbr", "argb", "abgr", "rgba", "bgra")):
        return "RVB 4:4:4"
    if pix_fmt.startswith(("gray", "ya")):
        return "niveaux de gris"
    if pix_fmt in ("v210", "uyvy422", "yuyv422"):
        return "4:2:2"
    return "inconnu"


def _cadence(stream) -> Fraction:
    for r in (stream.average_rate, stream.guessed_rate, stream.base_rate):
        if r:
            return Fraction(r)
    return Fraction(24)


def _lire_timecode(conteneur, flux_video) -> str | None:
    for meta in [flux_video.metadata] + [s.metadata for s in conteneur.streams
                                         if s.type == "data"] + [conteneur.metadata]:
        # MOV écrit « timecode », Matroska et WebM « TIMECODE ».
        tc = next((v for k, v in meta.items() if k.lower() == "timecode"), None)
        if tc:
            return tc
    return None


MOTIF_SEQUENCE = re.compile(r"^(.*?)(\d+)(\.[A-Za-z0-9]+)$")


def detecter_sequence_images(chemin: Path) -> dict | None:
    """Si le fichier est une image numérotée, renvoie le motif de la séquence."""
    if chemin.suffix.lower() not in EXTENSIONS_IMAGES:
        return None
    m = MOTIF_SEQUENCE.match(chemin.name)
    if not m:
        return None
    prefixe, num, ext = m.groups()
    largeur = len(num)
    numeros = []
    motif_fichier = re.compile(re.escape(prefixe) + r"(\d{%d})" % largeur + re.escape(ext) + "$")
    for f in chemin.parent.iterdir():
        mm = motif_fichier.match(f.name)
        if mm:
            numeros.append(int(mm.group(1)))
    if len(numeros) < 2:
        return None
    numeros.sort()
    return {"motif": str(chemin.parent / f"{prefixe}%0{largeur}d{ext}"),
            "premier": numeros[0], "nombre": numeros[-1] - numeros[0] + 1}


def ouvrir_conteneur(chemin: str, sequence_images: dict | None = None, cadence: str | None = None):
    if sequence_images:
        options = {"framerate": cadence or "24", "start_number": str(sequence_images["premier"])}
        return av.open(sequence_images["motif"], format="image2", options=options)
    return av.open(chemin)


def construire_index(conteneur, flux) -> IndexImages:
    pts_cles = []
    for paquet in conteneur.demux(flux):
        if paquet.pts is None or paquet.size == 0:
            continue
        pts_cles.append((paquet.pts, paquet.is_keyframe))
    pts_cles.sort()
    return IndexImages([p for p, _ in pts_cles], [k for _, k in pts_cles], Fraction(flux.time_base))


_cache_analyses: dict[tuple, tuple[InfosMedia, IndexImages | None]] = {}
_verrou = threading.Lock()


def analyser(chemin: str, cadence_sequence: str | None = None) -> tuple[InfosMedia, IndexImages | None]:
    """Analyse complète d'un média. Lève MediaIllisible avec un message en français."""
    p = Path(chemin)
    if p.suffix.lower() in EXTENSIONS_RAW:
        raise MediaIllisible(
            f"« {p.name} » : format RAW illisible "
            f"({EXTENSIONS_RAW[p.suffix.lower()]}). Importez un export ProRes ou DNxHR.")
    if not p.exists():
        raise MediaIllisible(f"Fichier introuvable : « {chemin} ».")
    st = p.stat()
    cle = (str(p.resolve()), st.st_size, st.st_mtime, cadence_sequence)
    with _verrou:
        if cle in _cache_analyses:
            return _cache_analyses[cle]
    seq = detecter_sequence_images(p)
    try:
        resultat = _analyser(p, st, seq, cadence_sequence)
    except av.error.FFmpegError as e:
        raise MediaIllisible(f"Fichier illisible : « {p.name} » ({e}).") from e
    with _verrou:
        _cache_analyses[cle] = resultat
    return resultat


def _analyser(p: Path, st: os.stat_result, seq: dict | None, cadence_sequence: str | None):
    avert: list[str] = []
    with ouvrir_conteneur(str(p), seq, cadence_sequence) as c:
        infos = InfosMedia(chemin=str(p), nom=p.name if not seq else Path(seq["motif"]).name,
                           conteneur=c.format.long_name or c.format.name,
                           taille_octets=st.st_size, date_modif=st.st_mtime,
                           duree_s=(c.duration or 0) / av.time_base, sequence_images=seq)
        for a in c.streams.audio:
            cc = a.codec_context
            fmt = cc.format.name if cc.format else "?"
            bits = cc.format.bytes * 8 if cc.format else 0
            if a.codec_context.name in ("pcm_s24le", "pcm_s24be"):
                bits = 24
            infos.audio.append(InfosAudio(a.index, cc.name, cc.sample_rate, cc.channels,
                                          cc.layout.name if cc.layout else "", fmt, bits))
        index = None
        if c.streams.video:
            v = c.streams.video[0]
            cc = v.codec_context
            fmt = av.VideoFormat(cc.pix_fmt) if cc.pix_fmt else None
            if fmt is None:
                raise MediaIllisible(f"Le format d'image de « {p.name} » est inconnu de FFmpeg.")
            cadence = _cadence(v)
            tc_txt = _lire_timecode(c, v)
            tc_debut, tc_drop = (None, False)
            if tc_txt:
                try:
                    tc_debut, tc_drop = tcmod.tc_vers_images(tc_txt, cadence)
                except ValueError:
                    avert.append(f"Timecode illisible : {tc_txt}")
            index = construire_index(c, v)
            c.seek(0)
            entrelace, haute = False, True
            for image in c.decode(v):
                entrelace = bool(image.interlaced_frame)
                haute = bool(getattr(image, "top_field_first", True))
                break
            vfr = _cadence_variable(index, cadence)
            if vfr:
                avert.append("Cadence variable : un intermédiaire à cadence fixe sera créé.")
            if entrelace:
                avert.append("Vidéo entrelacée.")
            sar = v.sample_aspect_ratio or cc.sample_aspect_ratio
            infos.video = InfosVideo(
                index_flux=v.index, codec=cc.name, codec_long=cc.codec.long_name,
                profil=cc.profile or "", pix_fmt=cc.pix_fmt,
                bits=max(comp.bits for comp in fmt.components),
                echantillonnage=_echantillonnage(cc.pix_fmt),
                alpha=any(comp.is_alpha for comp in fmt.components),
                largeur=cc.width, hauteur=cc.height,
                rapport_pixel=f"{sar.numerator}:{sar.denominator}" if sar else "1:1",
                cadence=f"{cadence.numerator}/{cadence.denominator}",
                nb_images=len(index), tc_debut=tc_debut, tc_drop=tc_drop,
                couleur=Couleur(int(cc.color_primaries), int(cc.color_trc), int(cc.colorspace),
                                int(cc.color_range)),
                entrelace=entrelace, trame_haute_dabord=haute, cadence_variable=vfr,
                intra=cc.name in CODECS_INTRA)
        elif not c.streams.audio:
            raise MediaIllisible(f"« {p.name} » ne contient ni vidéo ni audio.")
    infos.avertissements = avert
    return infos, index


def _cadence_variable(index: IndexImages, cadence: Fraction) -> bool:
    if len(index.pts) < 3:
        return False
    attendu = float(1 / (cadence * index.base_temps))
    ecarts = [b - a for a, b in zip(index.pts, index.pts[1:])]
    return any(abs(e - attendu) > max(1.0, attendu * 0.1) for e in ecarts)
