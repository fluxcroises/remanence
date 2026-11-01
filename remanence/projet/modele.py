"""Modèle de données d'un projet : médias, séquences, pistes et clips.

Toutes les positions et durées sont en images de la séquence.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from fractions import Fraction

from remanence.media.sonde import InfosMedia

VERSION_FORMAT = 1


def nouvel_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Media:
    id: str
    chemin: str
    infos: InfosMedia
    hors_ligne: bool = False
    # Points d'entrée et de sortie posés dans le moniteur source (images du média, sortie exclue).
    point_entree: int | None = None
    point_sortie: int | None = None

    @property
    def nom(self) -> str:
        return self.infos.nom

    def nb_images(self, cadence: Fraction) -> int:
        """Longueur du média en images ; un média audio seul est mesuré à la cadence donnée."""
        if self.infos.video:
            return self.infos.video.nb_images
        return max(1, round(self.infos.duree_s * float(cadence)))

    def plage_source(self, cadence: Fraction) -> tuple[int, int]:
        """Partie du média choisie dans le moniteur source : (entrée, sortie exclue)."""
        fin = self.nb_images(cadence)
        a = min(max(0, self.point_entree or 0), fin - 1)
        b = self.point_sortie if self.point_sortie is not None else fin
        return a, max(a + 1, min(b, fin))

    def vers_dict(self) -> dict:
        d = {"id": self.id, "chemin": self.chemin, "infos": self.infos.vers_dict()}
        if self.point_entree is not None or self.point_sortie is not None:
            d["points"] = [self.point_entree, self.point_sortie]
        return d

    @staticmethod
    def depuis_dict(d: dict) -> "Media":
        entree, sortie = d.get("points", [None, None])
        return Media(d["id"], d["chemin"], InfosMedia.depuis_dict(d["infos"]),
                     point_entree=entree, point_sortie=sortie)


@dataclass
class Clip:
    id: str
    media_id: str
    debut: int
    entree: int
    duree: int
    lien: str | None = None
    gain: float = 1.0
    enveloppe: list[list[float]] = field(default_factory=list)
    fondu_entree: int = 0
    fondu_sortie: int = 0

    @property
    def fin(self) -> int:
        return self.debut + self.duree

    def contient(self, f: int) -> bool:
        return self.debut <= f < self.fin

    def facteur(self, f: int) -> float:
        """Opacité (vidéo) ou volume (audio) à l'image f de la séquence."""
        decalage = f - self.debut
        if decalage < 0 or decalage >= self.duree:
            return 0.0
        valeur = self.gain * valeur_enveloppe(self.enveloppe, decalage)
        if self.fondu_entree and decalage < self.fondu_entree:
            valeur *= (decalage + 1) / (self.fondu_entree + 1)
        reste = self.duree - 1 - decalage
        if self.fondu_sortie and reste < self.fondu_sortie:
            valeur *= (reste + 1) / (self.fondu_sortie + 1)
        return valeur


def valeur_enveloppe(points: list[list[float]], decalage: float) -> float:
    """Interpolation linéaire entre les points [décalage, valeur] ; 1 sans point."""
    if not points:
        return 1.0
    if decalage <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if decalage <= x1:
            if x1 == x0:
                return y1
            return y0 + (y1 - y0) * (decalage - x0) / (x1 - x0)
    return points[-1][1]


@dataclass
class Piste:
    id: str
    type: str
    nom: str
    masquee: bool = False
    muette: bool = False
    verrouillee: bool = False
    solo: bool = False
    niveau: float = 1.0
    clips: list[Clip] = field(default_factory=list)

    def clip_a(self, f: int) -> Clip | None:
        for c in self.clips:
            if c.contient(f):
                return c
        return None

    def trier(self):
        self.clips.sort(key=lambda c: c.debut)


@dataclass
class Marqueur:
    position: int
    nom: str = ""
    couleur: str = "accent-2"  # nom d'un token de la charte


@dataclass
class Sequence:
    id: str
    nom: str
    largeur: int = 1920
    hauteur: int = 1080
    cadence: str = "24000/1001"
    tc_debut: int = 0
    tc_drop: bool = False
    reglee: bool = False
    pistes: list[Piste] = field(default_factory=list)
    marqueurs: list[Marqueur] = field(default_factory=list)
    point_entree: int | None = None
    point_sortie: int | None = None

    @property
    def fraction_cadence(self) -> Fraction:
        return Fraction(self.cadence)

    @property
    def pistes_video(self) -> list[Piste]:
        """Pistes vidéo de la plus haute (au premier plan) à la plus basse."""
        return [p for p in self.pistes if p.type == "video"]

    @property
    def pistes_audio(self) -> list[Piste]:
        return [p for p in self.pistes if p.type == "audio"]

    def pistes_entendues(self, type_: str) -> list[Piste]:
        """Pistes qui participent au rendu : ni masquées ni muettes, et seulement les pistes
        en solo s'il y en a une."""
        pistes = [p for p in self.pistes if p.type == type_ and not (p.masquee or p.muette)]
        solos = [p for p in pistes if p.solo]
        return solos or pistes

    def duree(self) -> int:
        return max((c.fin for p in self.pistes for c in p.clips), default=0)

    def tous_les_clips(self):
        for p in self.pistes:
            for c in p.clips:
                yield p, c

    def trouver(self, clip_id: str) -> tuple[Piste, Clip] | tuple[None, None]:
        for p, c in self.tous_les_clips():
            if c.id == clip_id:
                return p, c
        return None, None


@dataclass
class Projet:
    medias: dict[str, Media] = field(default_factory=dict)
    sequences: list[Sequence] = field(default_factory=list)
    sequence_active: str | None = None
    graine: int = 0

    @property
    def sequence(self) -> Sequence:
        for s in self.sequences:
            if s.id == self.sequence_active:
                return s
        return self.sequences[0]

    @staticmethod
    def nouveau() -> "Projet":
        p = Projet()
        s = Sequence(nouvel_id(), "Séquence 1")
        s.pistes = [Piste(nouvel_id(), "video", "Vidéo 1"), Piste(nouvel_id(), "audio", "Audio 1")]
        p.sequences.append(s)
        p.sequence_active = s.id
        return p

    def vers_dict(self) -> dict:
        return {
            "format": "remanence",
            "version": VERSION_FORMAT,
            "graine": self.graine,
            "sequence_active": self.sequence_active,
            "medias": [m.vers_dict() for m in self.medias.values()],
            "sequences": [asdict(s) for s in self.sequences],
        }

    @staticmethod
    def depuis_dict(d: dict) -> "Projet":
        if d.get("format") != "remanence":
            raise ValueError("Ce fichier n'est pas un projet Remanence.")
        if d.get("version", 0) > VERSION_FORMAT:
            raise ValueError("Ce projet vient d'une version plus récente de Remanence. "
                             "Mettez Remanence à jour pour l'ouvrir.")
        p = Projet(graine=d.get("graine", 0), sequence_active=d.get("sequence_active"))
        for md in d.get("medias", []):
            m = Media.depuis_dict(md)
            p.medias[m.id] = m
        for sd in d.get("sequences", []):
            sd = dict(sd)
            pistes = []
            for pd in sd.pop("pistes", []):
                pd = dict(pd)
                clips = [Clip(**c) for c in pd.pop("clips", [])]
                pistes.append(Piste(**pd, clips=clips))
            marqueurs = [Marqueur(**m) for m in sd.pop("marqueurs", [])]
            p.sequences.append(Sequence(**sd, pistes=pistes, marqueurs=marqueurs))
        if not p.sequences:
            return Projet.nouveau()
        return p
