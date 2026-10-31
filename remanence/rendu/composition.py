"""Calcul d'une image et d'un bloc de son de la séquence.

Les pistes vidéo sont fusionnées de bas en haut en flottant 32 bits, alpha
prémultiplié. Quand une seule image source suffit à produire le résultat
(clip opaque, sans fondu ni piste visible dessous), `identite` le signale :
l'export recopie alors l'image d'origine sans la recalculer.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

import numpy as np

from remanence.media.lecteur import FREQUENCE_MIXAGE, LecteurVideo, Pool
from remanence.media.proxy import chemin_audio, chemin_proxy
from remanence.media.sonde import analyser
from remanence.projet.modele import Clip, Media, Projet, Sequence
from remanence.rendu.couleur import vers_rvb16_apercu, vers_rvba


@dataclass
class Couche:
    clip: Clip
    media: Media
    image_source: int
    opacite: float


def couches(projet: Projet, seq: Sequence, f: int) -> list[Couche]:
    """Clips visibles à l'image f, de la piste la plus basse à la plus haute."""
    resultat = []
    for piste in reversed(seq.pistes_video):
        if piste.masquee:
            continue
        c = piste.clip_a(f)
        if c is None:
            continue
        media = projet.medias.get(c.media_id)
        if media is None or media.hors_ligne or media.infos.video is None:
            continue
        opacite = c.facteur(f)
        if opacite <= 0.0:
            continue
        n = min(c.entree + (f - c.debut), media.infos.video.nb_images - 1)
        resultat.append(Couche(c, media, n, min(opacite, 1.0)))
    return resultat


def identite(pile: list[Couche]) -> Couche | None:
    """La couche dont l'image source est le résultat exact, s'il en existe une."""
    if not pile:
        return None
    haut = pile[-1]
    if haut.opacite < 1.0:
        return None
    if haut.media.infos.video.alpha and len(pile) > 1:
        return None
    return haut


class Compositeur:
    """Un compositeur par fil d'exécution : il garde ses propres décodeurs ouverts."""

    def __init__(self, projet: Projet, apercu: bool = False):
        self.projet = projet
        self.pool = Pool()
        self.apercu = apercu

    def fermer(self):
        self.pool.fermer()

    def lecteur(self, media: Media, proxy: bool) -> LecteurVideo:
        chemin = media.chemin
        if proxy:
            p = chemin_proxy(media.infos)
            if p.exists():
                chemin = str(p)
            else:
                proxy = False

        def fabrique():
            infos, index = analyser(chemin) if proxy else analyser(
                media.chemin, None if not media.infos.sequence_images else media.infos.video.cadence)
            return LecteurVideo(chemin, index, None if proxy else infos.sequence_images,
                                media.infos.video.cadence)
        return self.pool.video((media.id, proxy), fabrique)

    def image(self, seq: Sequence, f: int, echelle: float = 1.0, proxy: bool = False) -> np.ndarray:
        largeur = max(2, round(seq.largeur * echelle))
        hauteur = max(2, round(seq.hauteur * echelle))
        sortie = np.zeros((hauteur, largeur, 4), np.float32)
        pile = couches(self.projet, seq, f)
        for i, couche in enumerate(pile):
            rvba = self._image_couche(couche, largeur, hauteur, proxy)
            if i == 0 and couche.opacite >= 1.0 and rvba.shape == sortie.shape and \
                    not couche.media.infos.video.alpha:
                sortie = rvba
                continue
            if couche.opacite < 1.0:
                rvba = rvba * couche.opacite
            sortie = rvba + sortie * (1.0 - rvba[..., 3:4])
        return sortie

    def image_apercu(self, seq: Sequence, f: int, echelle: float, proxy: bool) -> np.ndarray:
        """Image pour la visionneuse : RVB uint16 si un seul clip opaque remplit l'écran,
        sinon RVB float16 issu de la composition complète."""
        largeur = max(2, round(seq.largeur * echelle))
        hauteur = max(2, round(seq.hauteur * echelle))
        pile = couches(self.projet, seq, f)
        if len(pile) == 1 and pile[0].opacite >= 1.0:
            v = pile[0].media.infos.video
            if not v.alpha and (v.largeur, v.hauteur) == (seq.largeur, seq.hauteur):
                image = self.lecteur(pile[0].media, proxy).image(pile[0].image_source)
                rapide = vers_rvb16_apercu(image, v.couleur, largeur, hauteur)
                if rapide is not None:
                    return rapide
        rvba = self.image(seq, f, echelle, proxy)
        return np.ascontiguousarray(rvba[..., :3].astype(np.float16))

    def _image_couche(self, couche: Couche, largeur: int, hauteur: int, proxy: bool) -> np.ndarray:
        v = couche.media.infos.video
        image = self.lecteur(couche.media, proxy).image(couche.image_source)
        if (image.width, image.height) == (largeur, hauteur):
            return vers_rvba(image, v.couleur, self.apercu)
        # Adapter à la séquence sans déformer : l'image tient entière, centrée.
        s = min(largeur / v.largeur, hauteur / v.hauteur)
        lp, hp = max(2, round(v.largeur * s)), max(2, round(v.hauteur * s))
        reduite = image.reformat(width=lp, height=hp, interpolation="BICUBIC")
        rvba = vers_rvba(reduite, v.couleur, self.apercu)
        toile = np.zeros((hauteur, largeur, 4), np.float32)
        y0, x0 = (hauteur - hp) // 2, (largeur - lp) // 2
        toile[y0:y0 + hp, x0:x0 + lp] = rvba[:hauteur - y0, :largeur - x0]
        return toile

    def audio(self, seq: Sequence, debut: int, n: int) -> np.ndarray:
        """Mixage stéréo des échantillons [debut, debut+n) à 48 kHz."""
        sortie = np.zeros((n, 2), np.float32)
        cadence = seq.fraction_cadence
        par_image = FREQUENCE_MIXAGE / float(cadence)
        for piste in seq.pistes_audio:
            if piste.muette:
                continue
            for c in piste.clips:
                e0 = round(c.debut * par_image)
                e1 = round(c.fin * par_image)
                a, b = max(debut, e0), min(debut + n, e1)
                if b <= a:
                    continue
                media = self.projet.medias.get(c.media_id)
                if media is None or media.hors_ligne or not media.infos.audio:
                    continue
                cache = self.pool.audio(chemin_audio(media.infos))
                if cache is None:
                    continue
                cad_media = Fraction(media.infos.video.cadence) if media.infos.video else cadence
                source0 = round((c.entree / float(cad_media) - cache.decalage_s) * FREQUENCE_MIXAGE)
                bloc = cache.lire(source0 + (a - e0), b - a)
                positions = (np.arange(a, b) - e0) / par_image
                images = np.arange(int(positions[0]), int(positions[-1]) + 2)
                gains = np.array([c.facteur(c.debut + min(int(k), c.duree - 1)) for k in images],
                                 np.float32)
                bloc *= np.interp(positions, images, gains).astype(np.float32)[:, None]
                sortie[a - debut:b - debut] += bloc
        return sortie
