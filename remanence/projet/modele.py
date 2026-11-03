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
    # Chutier où le média est rangé ; None : à la racine du projet.
    chutier: str | None = None
    # Changements de plan détectés (images du média) ; None : pas encore analysé.
    coupes: list[int] | None = None

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
        if self.chutier:
            d["chutier"] = self.chutier
        if self.coupes is not None:
            d["coupes"] = self.coupes
        return d

    @staticmethod
    def depuis_dict(d: dict) -> "Media":
        entree, sortie = d.get("points", [None, None])
        return Media(d["id"], d["chemin"], InfosMedia.depuis_dict(d["infos"]),
                     point_entree=entree, point_sortie=sortie, chutier=d.get("chutier"),
                     coupes=d.get("coupes"))


@dataclass
class Masque:
    """Zone de l'image où agit un effet. Coordonnées de 0 à 1 sur l'image de la séquence,
    depuis le coin haut gauche. Rectangle et ellipse : deux coins opposés ; forme libre : les
    points d'une courbe fermée qui passe par chacun d'eux."""
    id: str
    forme: str  # "rectangle" | "ellipse" | "courbe"
    points: list = field(default_factory=list)
    adoucissement: float = 0.0  # en % de la largeur de l'image
    expansion: float = 0.0      # idem ; négatif : le masque se resserre
    inverse: bool = False
    mode: str = "addition"      # avec les masques précédents : addition, soustraction, intersection
    actif: bool = True
    # Images clés : "points" | "adoucissement" | "expansion" -> [[temps, valeur, passage], ...]
    # (voir effets/courbes.py) ; au même temps que celles de l'effet.
    cles: dict = field(default_factory=dict)


MODES_MASQUE = {"addition": "Addition", "soustraction": "Soustraction",
                "intersection": "Intersection"}


@dataclass
class Effet:
    """Un effet posé sur un clip, une piste ou la séquence. type : clé d'une description de
    `remanence.effets` ; params : valeur de chaque paramètre ; graine : tirage du hasard."""
    id: str
    type: str
    params: dict = field(default_factory=dict)
    actif: bool = True
    graine: int = 1
    # Dosage de l'effet sur l'image qu'il reçoit, et façon de les mêler (voir MODES_FUSION).
    opacite: float = 1.0
    fusion: str = "normal"
    # Images clés : paramètre (ou "opacite") -> [[temps, valeur, "lineaire" | "palier"], ...],
    # triées. Temps en images depuis le début du clip, ou de la séquence pour un effet de piste
    # ou de séquence. Un paramètre sans image clé garde sa valeur fixe.
    cles: dict = field(default_factory=dict)
    # Sans masque, l'effet couvre toute l'image.
    masques: list[Masque] = field(default_factory=list)
    # Script FFglitch : le texte JavaScript de l'effet (vide pour les autres effets).
    script: str = ""


@dataclass
class Modulateur:
    """Signal qui fait varier des réglages d'effets (voir effets/modulateurs.py). cibles :
    [[identifiant de l'effet, réglage, profondeur en % de la plage], ...]."""
    id: str
    type: str  # "oscillateur" | "aleatoire" | "tempo"
    nom: str
    params: dict = field(default_factory=dict)
    cibles: list = field(default_factory=list)
    actif: bool = True


# Modes de fusion du cahier des charges : clé enregistrée -> nom affiché.
MODES_FUSION = {"normal": "Normal", "addition": "Addition", "ecran": "Écran",
                "produit": "Produit", "difference": "Différence",
                "luminosite": "Luminosité seule", "couleur": "Couleur seule"}


@dataclass
class Transition:
    """Transition à l'entrée d'un clip, depuis le clip qui le précède sur sa piste. Datamosh :
    l'image clé du raccord est supprimée, le clip précédent bave avec le mouvement de celui-ci
    pendant `duree` images, puis une image clé le rend net."""
    type: str = "datamosh"
    duree: int = 24
    blocs: int = 4


# Un clip d'effet n'a pas de média : il transforme tout ce qui est sous lui. Son entrée est
# placée loin dans une source imaginaire, pour qu'on puisse le rallonger des deux côtés.
ENTREE_CLIP_EFFET = 1_000_000


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
    effets: list[Effet] = field(default_factory=list)
    fusion: str = "normal"
    # Datamosh : transition depuis le clip précédent, et images clés supprimées aux coupes du
    # clip (images depuis son début).
    transition: Transition | None = None
    cles_supprimees: list[int] = field(default_factory=list)
    # Allure du fondu d'entrée (voir effets/transitions.py) : {"type": "volet" | "blocs" |
    # "rvb" | "coupure", réglages…} ; None, le fondu ordinaire.
    style_fondu: dict | None = None
    # Vitesse (1 : normale ; 0,5 : ralenti) et lecture à rebours. L'entrée se compte alors en
    # images du média ralenti ou accéléré (et retourné) : voir `source`.
    vitesse: float = 1.0
    inverse: bool = False
    # Titre (texte dessiné, voir rendu/titres.py) ou séquence imbriquée : un clip sans média.
    titre: dict | None = None
    sequence_id: str | None = None

    @property
    def fin(self) -> int:
        return self.debut + self.duree

    @property
    def est_effet(self) -> bool:
        return not self.media_id and self.titre is None and self.sequence_id is None

    @property
    def est_media(self) -> bool:
        return bool(self.media_id)

    def source(self, decalage: float, longueur: int) -> int:
        """L'image de la source (média ou séquence imbriquée, `longueur` images) montrée
        `decalage` images après le début du clip, vitesse et sens compris."""
        k = int((self.entree + decalage) * self.vitesse + 1e-6)
        if self.inverse:
            k = longueur - 1 - k
        return max(0, min(longueur - 1, k))

    def contient(self, f: int) -> bool:
        return self.debut <= f < self.fin

    def facteur(self, f: int, sans_fondu_sortie: bool = False,
                sans_fondu_entree: bool = False) -> float:
        """Opacité (vidéo) ou volume (audio) à l'image f de la séquence.

        sans_fondu_sortie sert au fondu enchaîné vidéo : le clip du dessous reste plein
        pendant que celui du dessus apparaît, ce qui donne exactement A × (1 − t) + B × t.
        """
        decalage = f - self.debut
        if decalage < 0 or decalage >= self.duree:
            return 0.0
        valeur = self.gain * valeur_enveloppe(self.enveloppe, decalage)
        # sans_fondu_entree : une transition (volet, blocs…) fait entrer le clip.
        if self.fondu_entree and decalage < self.fondu_entree and not sans_fondu_entree:
            valeur *= (decalage + 1) / (self.fondu_entree + 1)
        reste = self.duree - 1 - decalage
        if self.fondu_sortie and reste < self.fondu_sortie and not sans_fondu_sortie:
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
    # Hauteur choisie à la souris ; None : la hauteur par défaut de la charte.
    hauteur: int | None = None
    # Couleur des clips et de l'en-tête : nom d'un token de la charte ; None : celle du type.
    couleur: str | None = None
    clips: list[Clip] = field(default_factory=list)
    effets: list[Effet] = field(default_factory=list)

    def clips_a(self, f: int) -> list[Clip]:
        """Clips présents à l'image f, du plus ancien au plus récent (deux lors d'un fondu)."""
        return sorted((c for c in self.clips if c.contient(f)), key=lambda c: c.debut)

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
    effets: list[Effet] = field(default_factory=list)
    # Modulateurs de la séquence (clé facultative, absente avant l'étape 4).
    modulateurs: list[Modulateur] = field(default_factory=list)

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
class Chutier:
    """Dossier virtuel du panneau Média ; parent None : à la racine du projet."""
    id: str
    nom: str
    parent: str | None = None


@dataclass
class Projet:
    medias: dict[str, Media] = field(default_factory=dict)
    chutiers: list[Chutier] = field(default_factory=list)
    sequences: list[Sequence] = field(default_factory=list)
    sequence_active: str | None = None
    graine: int = 0

    @property
    def sequence(self) -> Sequence:
        for s in self.sequences:
            if s.id == self.sequence_active:
                return s
        return self.sequences[0]

    def sous_chutiers(self, chutier_id: str | None) -> set[str]:
        """Le chutier et tous ceux qu'il contient, à n'importe quelle profondeur."""
        ids = {chutier_id}
        ajoute = True
        while ajoute:
            ajoute = False
            for c in self.chutiers:
                if c.parent in ids and c.id not in ids:
                    ids.add(c.id)
                    ajoute = True
        return ids

    def clips_du_media(self, media_id: str) -> int:
        return sum(1 for s in self.sequences for _, c in s.tous_les_clips()
                   if c.media_id and c.media_id == media_id)

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
            "chutiers": [asdict(c) for c in self.chutiers],
            "sequences": [asdict(s) for s in self.sequences],
        }

    @staticmethod
    def depuis_dict(d: dict) -> "Projet":
        if d.get("format") != "remanence":
            raise ValueError("Ce fichier n'est pas un projet Remanence.")
        if d.get("version", 0) > VERSION_FORMAT:
            raise ValueError("Projet créé par une version plus récente de Remanence.")
        p = Projet(graine=d.get("graine", 0), sequence_active=d.get("sequence_active"))
        for md in d.get("medias", []):
            m = Media.depuis_dict(md)
            p.medias[m.id] = m
        p.chutiers = [Chutier(**c) for c in d.get("chutiers", [])]
        for sd in d.get("sequences", []):
            sd = dict(sd)
            pistes = []
            for pd in sd.pop("pistes", []):
                pd = dict(pd)
                clips = []
                for c in pd.pop("clips", []):
                    c = dict(c)
                    effets = _effets(c.pop("effets", None))
                    transition = c.pop("transition", None)
                    clips.append(Clip(**c, effets=effets,
                                      transition=Transition(**transition) if transition else None))
                effets = _effets(pd.pop("effets", None))
                pistes.append(Piste(**pd, clips=clips, effets=effets))
            marqueurs = [Marqueur(**m) for m in sd.pop("marqueurs", [])]
            effets = _effets(sd.pop("effets", None))
            modulateurs = [Modulateur(**m) for m in sd.pop("modulateurs", [])]
            p.sequences.append(Sequence(**sd, pistes=pistes, marqueurs=marqueurs, effets=effets,
                                        modulateurs=modulateurs))
        if not p.sequences:
            return Projet.nouveau()
        return p


def _effets(liste: list[dict] | None) -> list[Effet]:
    """Les effets enregistrés ; absents des projets d'avant l'étape 2."""
    effets = []
    for e in liste or []:
        e = dict(e)
        masques = [Masque(**m) for m in e.pop("masques", [])]
        effets.append(Effet(**e, masques=masques))
    return effets
