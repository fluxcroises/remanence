"""Calcul d'une image et d'un bloc de son de la séquence.

Les pistes vidéo sont fusionnées de bas en haut en flottant 32 bits, alpha
prémultiplié. Quand une seule image source suffit à produire le résultat
(clip opaque, sans fondu ni piste visible dessous), `identite` le signale :
l'export recopie alors l'image d'origine sans la recalculer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

import numpy as np

from remanence.media.lecteur import FREQUENCE_MIXAGE, LecteurVideo, Pool
from remanence.media.proxy import chemin_audio, chemin_proxy
from remanence.media.sonde import analyser
from remanence.effets import EFFETS, agit_a, instantane, modulateurs, transitions
from remanence.projet.modele import Clip, Effet, Media, Projet, Sequence
from remanence.moteurs.codec import prerendu
from remanence.rendu import titres
from remanence.rendu.couleur import vers_rvb16_apercu, vers_rvba
from remanence.rendu.gpu import RenduGPU, gpu_demande


@dataclass
class Couche:
    clip: Clip
    media: Media | None  # None : clip d'effet, qui transforme ce qui est dessous
    image_source: int
    opacite: float
    # Effets à appliquer à la couche : ceux du clip, puis ceux de sa piste, tels qu'ils sont à
    # cette image (images clés évaluées).
    effets: list[Effet] = field(default_factory=list)
    fusion: str = "normal"
    # Image prise dans la source modifiée du clip (transition datamosh, images clés supprimées).
    modifiee: bool = False
    # Couche calculée et non décodée : titre, ou image d'une séquence imbriquée.
    calcul: bool = False


def actifs(effets: list[Effet], t: float = 0, decalages: dict | None = None) -> list[Effet]:
    """Effets allumés, figés au temps t (depuis le début de leur porteur), avec les décalages
    des modulateurs à cet instant. Les effets codec passent en tête : leur pré-rendu part de la
    source, avant tout effet en temps réel."""
    allumes = [instantane(e, t, decalages) for e in effets
               if e.actif and e.type in EFFETS and agit_a(e, t)]
    return sorted(allumes, key=lambda e: not EFFETS[e.type].codec)


def couches(projet: Projet, seq: Sequence, f: int) -> list[Couche]:
    """Clips visibles à l'image f, de la piste la plus basse à la plus haute."""
    resultat = []
    mod = modulateurs.decalages(seq, f, projet)
    for piste in reversed(seq.pistes_entendues("video")):
        presents = piste.clips_a(f)
        for i, c in enumerate(presents):
            if c.est_effet:
                effets = actifs(c.effets, f - c.debut, mod)
                opacite = c.facteur(f) * piste.niveau
                if effets and opacite > 0.0:
                    resultat.append(Couche(c, None, 0, min(opacite, 1.0), effets, c.fusion))
                continue
            calcul = c.titre is not None or c.sequence_id is not None
            media = None
            if c.sequence_id is not None:
                imbriquee = sequence_par_id(projet, c.sequence_id)
                if imbriquee is None or imbriquee is seq:
                    continue
                n = c.source(f - c.debut, max(1, imbriquee.duree()))
            elif c.titre is not None:
                n = 0
            else:
                media = projet.medias.get(c.media_id)
                if media is None or media.hors_ligne or media.infos.video is None:
                    continue
                n = c.source(f - c.debut, media.infos.video.nb_images)
            # Fondu enchaîné : le clip recouvert garde toute son opacité sous le suivant.
            dessous = i < len(presents) - 1
            opacite = c.facteur(f, sans_fondu_sortie=dessous) * piste.niveau
            entree_fondu = []
            if transitions.actif(c, f - c.debut):
                # Transition : le clip entre par elle et non par un mélange ; celui qui sort
                # (juste avant sur la piste) peut s'abîmer aussi.
                part, entree_fondu, sortie_fondu = transitions.effets_du_fondu(c, f - c.debut)
                opacite = c.facteur(f, dessous, sans_fondu_entree=True) * piste.niveau * part
                precedente = next((x for x in reversed(resultat)
                                   if i > 0 and x.clip is presents[i - 1]), None)
                if precedente is not None:
                    precedente.effets = precedente.effets + sortie_fondu
            if opacite <= 0.0:
                continue
            resultat.append(Couche(c, media, n, min(opacite, 1.0),
                                   actifs(c.effets, f - c.debut, mod)
                                   + actifs(piste.effets, f, mod) + entree_fondu,
                                   c.fusion, not calcul and prerendu.dans_plages(
                                       projet, seq, c, f - c.debut), calcul))
    return resultat


def sequence_par_id(projet: Projet, sequence_id: str) -> Sequence | None:
    return next((s for s in projet.sequences if s.id == sequence_id), None)


def identite(pile: list[Couche], seq: Sequence | None = None, f: int = 0) -> Couche | None:
    """La couche dont l'image source est le résultat exact à l'image f, s'il en existe une :
    aucun effet sur elle, au-dessus d'elle ni sur la séquence."""
    if not pile or (seq is not None and actifs(seq.effets, f)):
        return None
    haut = pile[-1]
    if haut.media is None or haut.effets or haut.opacite < 1.0 or haut.fusion != "normal" \
            or haut.modifiee:
        return None
    if haut.media.infos.video.alpha and len(pile) > 1:
        return None
    return haut


class Compositeur:
    """Un compositeur par fil d'exécution : il garde ses propres décodeurs ouverts, et son
    contexte de carte graphique, créé au premier calcul dans ce fil.

    gpu : None pour le choix automatique (carte graphique si possible), False pour le
    processeur seul (référence des tests)."""

    def __init__(self, projet: Projet, apercu: bool = False, gpu: bool | None = None,
                 synchrone: bool = False):
        self.projet = projet
        self.pool = Pool()
        self.apercu = apercu
        # synchrone (export) : un pré-rendu codec manquant est calculé sur-le-champ. Sinon
        # (aperçu) l'image sort sans lui, et le clip est noté dans `manquants`.
        self.synchrone = synchrone
        self.manquants: set[str] = set()
        self._gpu_voulu = gpu_demande() if gpu is None else gpu
        self._gpu: RenduGPU | None = None

    def fermer(self):
        self.pool.fermer()
        if self._gpu is not None:
            self._gpu.fermer()
            self._gpu = None

    def gpu(self) -> RenduGPU | None:
        """Le contexte de la carte graphique, ou None si elle n'est pas utilisable ici."""
        if self._gpu is None and self._gpu_voulu:
            try:
                self._gpu = RenduGPU()
            except Exception:
                # Pas d'OpenGL 4.3 : le processeur prend le relais, avec le même résultat.
                self._gpu_voulu = False
        return self._gpu

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
        # Les couches calculées d'abord : une séquence imbriquée se compose elle-même sur la
        # carte graphique, avant que la composition de cette image ne commence.
        calculees = {id(c): self._image_calculee(c, largeur, hauteur, proxy)
                     for c in pile if c.calcul}
        g = self.gpu()
        if g is not None:
            g.commencer(largeur, hauteur)
            for couche in pile:
                if couche.calcul:
                    g.ajouter_rvba(calculees[id(couche)], couche.opacite, couche.effets, f,
                                   couche.fusion)
                    continue
                if couche.media is None:
                    g.effet_dessous(couche.effets, couche.opacite, f, couche.fusion)
                    continue
                trame, x0, y0 = self._trame_couche(couche, largeur, hauteur, proxy)
                if couche.modifiee:
                    trame = self._trame_modifiee(seq, couche, f, trame)
                codec = None
                if any(EFFETS[e.type].codec for e in couche.effets):
                    codec = self._trame_codec(seq, couche, f, trame)
                g.ajouter(trame, couche.media.infos.video.couleur, couche.opacite, x0, y0,
                          couche.effets, f, couche.fusion, codec)
            effets = actifs(seq.effets, f, modulateurs.decalages(seq, f, self.projet))
            if effets:
                g.effets_sequence(effets, f)
            return g.lire()
        # Sans carte graphique, les effets ne sont pas calculés : seules les images sont fusionnées.
        pile = [c for c in pile if c.media is not None or c.calcul]
        for i, couche in enumerate(pile):
            if couche.calcul:
                rvba = calculees[id(couche)]
                if couche.opacite < 1.0:
                    rvba = rvba * couche.opacite
                sortie = rvba + sortie * (1.0 - rvba[..., 3:4])
                continue
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
        """Image pour la visionneuse : RVB uint16 si un seul clip opaque remplit l'écran,
        sinon RVB float16 issu de la composition complète."""
        largeur = max(2, round(seq.largeur * echelle))
        hauteur = max(2, round(seq.hauteur * echelle))
        pile = couches(self.projet, seq, f)
        if len(pile) == 1 and identite(pile, seq, f) is not None:
            v = pile[0].media.infos.video
            if not v.alpha and (v.largeur, v.hauteur) == (seq.largeur, seq.hauteur):
                image = self.lecteur(pile[0].media, proxy).image(pile[0].image_source)
                rapide = vers_rvb16_apercu(image, v.couleur, largeur, hauteur)
                if rapide is not None:
                    return rapide
        rvba = self.image(seq, f, echelle, proxy)
        return np.ascontiguousarray(rvba[..., :3].astype(np.float16))

    def _image_calculee(self, couche: Couche, largeur: int, hauteur: int,
                        proxy: bool) -> np.ndarray:
        """Titre dessiné, ou image de la séquence imbriquée : elle tient entière, centrée."""
        c = couche.clip
        if c.titre is not None:
            return titres.rendre(c.titre, largeur, hauteur)
        imbriquee = sequence_par_id(self.projet, c.sequence_id)
        s = min(largeur / imbriquee.largeur, hauteur / imbriquee.hauteur)
        image = self.image(imbriquee, couche.image_source, s, proxy)
        hp, lp = image.shape[:2]
        if (hp, lp) == (hauteur, largeur):
            return image
        toile = np.zeros((hauteur, largeur, 4), np.float32)
        y0, x0 = max(0, (hauteur - hp) // 2), max(0, (largeur - lp) // 2)
        toile[y0:y0 + hp, x0:x0 + lp] = image[:hauteur - y0, :largeur - x0]
        return toile

    @staticmethod
    def _son_du_clip(c: Clip, lire, cadence: float, decalage_s: float, longueur: int,
                     depart: int, n: int) -> np.ndarray:
        """Les n échantillons du clip à partir de `depart` (depuis son début), vitesse et sens
        compris. lire(début, n) lit la source ; vitesse 1 à l'endroit : lecture directe."""
        if c.vitesse == 1.0 and not c.inverse:
            source0 = round((c.entree / cadence - decalage_s) * FREQUENCE_MIXAGE)
            return lire(source0 + depart, n)
        t = c.entree * c.vitesse / cadence + np.arange(depart, depart + n) * c.vitesse \
            / FREQUENCE_MIXAGE
        if c.inverse:
            t = longueur / cadence - t
        position = (t - decalage_s) * FREQUENCE_MIXAGE
        bas = int(np.floor(position.min()))
        brut = lire(bas, int(np.ceil(position.max())) - bas + 2)
        x = np.arange(bas, bas + len(brut))
        return np.stack([np.interp(position, x, brut[:, k]) for k in (0, 1)],
                        axis=1).astype(np.float32)

    def _trame_couche(self, couche: Couche, largeur: int, hauteur: int,
                      proxy: bool) -> tuple[object, int, int]:
        """L'image décodée de la couche, à sa taille dans la séquence, et sa position.
        Adapter à la séquence sans déformer : l'image tient entière, centrée."""
        v = couche.media.infos.video
        image = self.lecteur(couche.media, proxy).image(couche.image_source)
        if (image.width, image.height) == (largeur, hauteur):
            return image, 0, 0
        s = min(largeur / v.largeur, hauteur / v.hauteur)
        lp, hp = max(2, round(v.largeur * s)), max(2, round(v.hauteur * s))
        reduite = image.reformat(width=lp, height=hp, interpolation="BICUBIC")
        return reduite, (largeur - lp) // 2, (hauteur - hp) // 2

    def _lire_prerendu(self, fichier, t: int, trame):
        def fabrique():
            _, index = analyser(str(fichier))
            return LecteurVideo(str(fichier), index)
        image = self.pool.video(("datamosh", str(fichier)), fabrique).image(max(0, t))
        if (image.width, image.height) != (trame.width, trame.height):
            image = image.reformat(width=trame.width, height=trame.height)
        return image

    def _trame_modifiee(self, seq: Sequence, couche: Couche, f: int, trame):
        """L'image de la source modifiée du clip ; l'image d'origine si elle n'est pas prête."""
        clip = couche.clip
        fichier = prerendu.source_prete(self.projet, seq, clip)
        if fichier is None and self.synchrone:
            fichier = prerendu.calculer_source(self.projet, seq, clip)
        if fichier is None:
            self.manquants.add(clip.id)
            return trame
        return self._lire_prerendu(fichier, min(f - clip.debut, clip.duree - 1), trame)

    def _trame_codec(self, seq: Sequence, couche: Couche, f: int, trame):
        """L'image du pré-rendu codec du clip, à la taille de sa couche ; None s'il n'est pas
        encore calculé (aperçu)."""
        clip = couche.clip
        fichier = prerendu.pret(self.projet, seq, clip)
        if fichier is None and self.synchrone:
            fichier = prerendu.calculer(self.projet, seq, clip)
        if fichier is None:
            self.manquants.add(clip.id)
            return None

        return self._lire_prerendu(fichier, min(f - clip.debut, clip.duree - 1), trame)

    def _image_couche(self, couche: Couche, largeur: int, hauteur: int, proxy: bool) -> np.ndarray:
        trame, x0, y0 = self._trame_couche(couche, largeur, hauteur, proxy)
        rvba = vers_rvba(trame, couche.media.infos.video.couleur, self.apercu)
        if (x0, y0) == (0, 0) and rvba.shape[:2] == (hauteur, largeur):
            return rvba
        toile = np.zeros((hauteur, largeur, 4), np.float32)
        hp, lp = rvba.shape[:2]
        toile[y0:y0 + hp, x0:x0 + lp] = rvba[:hauteur - y0, :largeur - x0]
        return toile

    def audio(self, seq: Sequence, debut: int, n: int) -> np.ndarray:
        """Mixage stéréo des échantillons [debut, debut+n) à 48 kHz."""
        sortie = np.zeros((n, 2), np.float32)
        cadence = seq.fraction_cadence
        par_image = FREQUENCE_MIXAGE / float(cadence)
        for piste in seq.pistes_entendues("audio"):
            for c in piste.clips:
                e0 = round(c.debut * par_image)
                e1 = round(c.fin * par_image)
                a, b = max(debut, e0), min(debut + n, e1)
                if b <= a:
                    continue
                if c.sequence_id is not None:
                    imbriquee = sequence_par_id(self.projet, c.sequence_id)
                    if imbriquee is None or imbriquee is seq:
                        continue
                    lire = (lambda s, k, q=imbriquee: self.audio(q, s, k))
                    cad_source, decalage_s, longueur = cadence, 0.0, imbriquee.duree()
                else:
                    media = self.projet.medias.get(c.media_id)
                    if media is None or media.hors_ligne or not media.infos.audio:
                        continue
                    cache = self.pool.audio(chemin_audio(media.infos))
                    if cache is None:
                        continue
                    lire = cache.lire
                    cad_source = Fraction(media.infos.video.cadence) if media.infos.video \
                        else cadence
                    decalage_s, longueur = cache.decalage_s, media.nb_images(cadence)
                bloc = self._son_du_clip(c, lire, float(cad_source), decalage_s, longueur,
                                         a - e0, b - a)
                positions = (np.arange(a, b) - e0) / par_image
                images = np.arange(int(positions[0]), int(positions[-1]) + 2)
                gains = np.array([c.facteur(c.debut + min(int(k), c.duree - 1)) * piste.niveau
                                  for k in images], np.float32)
                bloc *= np.interp(positions, images, gains).astype(np.float32)[:, None]
                sortie[a - debut:b - debut] += bloc
        return sortie
