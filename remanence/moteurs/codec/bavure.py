"""Moteur Bavure : l'algorithme du prototype, sans programme externe.

Les images sont encodées en MPEG-4 Part 2 (le codec de Xvid, le plus docile pour le datamosh),
sans images B : chaque paquet est une image, soit clé (I, image complète), soit P (seulement le
mouvement depuis l'image précédente). On travaille sur la liste des paquets, puis on la décode :
- supprimer une image clé fait baver l'image d'avant avec le mouvement de celle d'après ;
- répéter une image P (bloom) applique sans fin le même mouvement : les pixels fondent ;
- abîmer des octets des images P (databending) donne des artefacts imprévisibles ;
- une quantification extrême fait apparaître les macroblocs.

Le nombre d'images ne change jamais : le plan garde sa durée et reste calé sur le son.
"""

from __future__ import annotations

import random
from fractions import Fraction
from typing import Iterable, Iterator

import av
import numpy as np

CODE_VOP = b"\x00\x00\x01\xb6"  # début d'une image dans un flux MPEG-4 Part 2


def type_image(paquet: bytes) -> str:
    """« I » ou « P » d'après l'en-tête de l'image (VOP)."""
    i = paquet.find(CODE_VOP)
    if i < 0 or i + 4 >= len(paquet):
        return "?"
    return "IPBS"[(paquet[i + 4] >> 6) & 3]


# Écart moyen de luminosité (0 à 1) entre deux images réduites au-delà duquel on voit une coupe.
SEUIL_COUPE = 0.12


class Encodeur:
    """Encodeur MPEG-4 à quantification fixe : 1 propre, 31 très gros blocs. Il ne place
    d'images clés qu'au début et aux changements de plan. Ceux-ci sont repérés ici : livré à
    lui-même, l'encodeur code souvent une coupe en image P très lourde, sans image clé à
    supprimer, et la bavure n'a pas lieu."""

    def __init__(self, largeur: int, hauteur: int, cadence: Fraction, blocs: int):
        cc = self.cc = av.CodecContext.create("mpeg4", "w")
        cc.width, cc.height, cc.pix_fmt = largeur, hauteur, "yuv420p"
        cc.time_base = 1 / cadence
        cc.framerate = cadence
        cc.gop_size = 600
        cc.max_b_frames = 0
        q = max(1, min(31, int(round(blocs))))
        cc.qmin = cc.qmax = q
        cc.bit_rate = 400_000_000
        cc.open()
        self._n = 0
        self._precedente: np.ndarray | None = None

    def est_coupe(self, image: av.VideoFrame) -> bool:
        """Vrai si cette image commence un nouveau plan (et la retient pour la suivante)."""
        reduite = image.reformat(width=32, height=18, format="gray").to_ndarray()
        reduite = reduite.astype(np.float32)
        coupe = (self._precedente is not None
                 and np.abs(reduite - self._precedente).mean() / 255.0 > SEUIL_COUPE)
        self._precedente = reduite
        return coupe

    def encoder(self, image: av.VideoFrame, cle: bool = False) -> list[bytes]:
        """cle : image clé forcée (raccord d'une transition, retour au net)."""
        image = image.reformat(width=self.cc.width, height=self.cc.height, format="yuv420p")
        if self.est_coupe(image) or cle:
            image.pict_type = av.video.frame.PictureType.I
        else:
            image.pict_type = av.video.frame.PictureType.NONE
        image.pts = self._n
        image.time_base = self.cc.time_base
        self._n += 1
        return [bytes(p) for p in self.cc.encode(image)]

    def finir(self) -> list[bytes]:
        return [bytes(p) for p in self.cc.encode(None)]


def encoder(images: Iterable[av.VideoFrame], largeur: int, hauteur: int, cadence: Fraction,
            blocs: int) -> list[bytes]:
    e = Encodeur(largeur, hauteur, cadence, blocs)
    paquets = []
    for image in images:
        paquets += e.encoder(image)
    return paquets + e.finir()


def decoder(paquets: list[bytes], n: int) -> Iterator[av.VideoFrame]:
    """Décode exactement n images : un flux abîmé peut en perdre, on répète alors la dernière."""
    d = av.CodecContext.create("mpeg4", "r")
    rendues = 0
    derniere = None
    for b in paquets:
        try:
            images = d.decode(av.Packet(b))
        except av.error.FFmpegError:
            images = []  # paquet illisible : l'image d'avant tient sa place
            if derniere is not None:
                images = [derniere]
        for image in images:
            if rendues < n:
                derniere = image
                rendues += 1
                yield image
    try:
        for image in d.decode(None):
            if rendues < n:
                derniere = image
                rendues += 1
                yield image
    except av.error.FFmpegError:
        pass
    while rendues < n and derniere is not None:
        rendues += 1
        yield derniere


# Manipulations du flux : chacune rend une liste de même longueur.

def supprimer_cles(paquets: list[bytes], debut: int = 0, fin: int | None = None) -> list[bytes]:
    """Les images clés de [debut, fin), sauf la toute première, remplacées par l'image d'avant."""
    fin = len(paquets) if fin is None else fin
    sortie = []
    for i, p in enumerate(paquets):
        if i > 0 and debut <= i < fin and type_image(p) == "I" and sortie:
            sortie.append(sortie[-1] if type_image(sortie[-1]) == "P" else p)
        else:
            sortie.append(p)
    return sortie


def supprimer_cles_aux(paquets: list[bytes], indices: set[int]) -> list[bytes]:
    """Seules les images clés aux indices donnés sont remplacées par l'image d'avant."""
    sortie = []
    for i, p in enumerate(paquets):
        if i > 0 and i in indices and type_image(p) == "I" and sortie:
            sortie.append(sortie[-1])
        else:
            sortie.append(p)
    return sortie


def bloom(paquets: list[bytes], instant: int, repetitions: int) -> list[bytes]:
    """Le mouvement de l'image `instant` répété sur les `repetitions` images suivantes."""
    if not paquets:
        return paquets
    i = max(1, min(instant, len(paquets) - 1))
    while i < len(paquets) and type_image(paquets[i]) != "P":
        i += 1
    if i >= len(paquets):
        return list(paquets)
    sortie = list(paquets)
    for k in range(i + 1, min(len(paquets), i + 1 + repetitions)):
        sortie[k] = paquets[i]
    return sortie


def abimer(paquets: list[bytes], force: float, graine: int) -> list[bytes]:
    """Databending : des octets des images P remplacés au hasard. Jamais 0x00 ni 0x01, pour ne
    pas créer de faux début d'image ; l'en-tête de l'image est épargné."""
    if force <= 0:
        return list(paquets)
    rnd = random.Random(graine)
    sortie = []
    for p in paquets:
        if type_image(p) != "P" or len(p) < 24:
            sortie.append(p)
            continue
        b = bytearray(p)
        debut = p.find(CODE_VOP) + 12
        for _ in range(max(1, int(len(b) * (force / 100) ** 2 * 0.02))):
            b[rnd.randrange(min(debut, len(b) - 1), len(b))] = rnd.randrange(2, 256)
        sortie.append(bytes(b))
    return sortie


def coupes_du_media(chemin: str, sequence_images: dict | None = None,
                    cadence: str | None = None, annule=None) -> list[int]:
    """Images où commence un nouveau plan : là où l'encodeur posera une image clé, donc
    celles que l'on peut supprimer pour faire baver un plan dans le suivant."""
    from remanence.media.sonde import ouvrir_conteneur
    coupes = []
    precedente = None
    with ouvrir_conteneur(chemin, sequence_images, cadence) as c:
        for i, image in enumerate(c.decode(c.streams.video[0])):
            if annule is not None and annule.is_set():
                raise InterruptedError
            reduite = image.reformat(width=32, height=18, format="gray").to_ndarray()
            reduite = reduite.astype(np.float32)
            if precedente is not None and \
                    np.abs(reduite - precedente).mean() / 255.0 > SEUIL_COUPE:
                coupes.append(i)
            precedente = reduite
    return coupes
