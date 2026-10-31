"""Accès image par image aux médias, et cache audio décodé."""

from __future__ import annotations

import bisect
import json
import threading
from collections import OrderedDict
from pathlib import Path

import av
import numpy as np

from remanence.media.sonde import IndexImages, InfosMedia, ouvrir_conteneur

FREQUENCE_MIXAGE = 48000


class LecteurVideo:
    """Décode l'image n d'un média, avec saut précis à l'image près.

    Un lecteur n'est utilisé que par un seul fil d'exécution à la fois.
    """

    def __init__(self, chemin: str, index: IndexImages, sequence_images: dict | None = None,
                 cadence: str | None = None, taille_cache: int = 8):
        self.chemin = chemin
        self.index = index
        self._conteneur = ouvrir_conteneur(chemin, sequence_images, cadence)
        self._flux = self._conteneur.streams.video[0]
        self._flux.thread_type = "AUTO"
        self._pts_vers_n = {p: i for i, p in enumerate(index.pts)}
        self._decodeur = None
        self._dernier = -10
        self._cache: OrderedDict[int, av.VideoFrame] = OrderedDict()
        self._taille_cache = taille_cache

    def fermer(self):
        self._conteneur.close()

    def __len__(self):
        return len(self.index)

    def image(self, n: int) -> av.VideoFrame:
        n = min(max(0, n), len(self.index) - 1)
        if n in self._cache:
            self._cache.move_to_end(n)
            return self._cache[n]
        # Avancer en décodant coûte moins qu'un saut tant que la cible est proche.
        if not (self._decodeur is not None and self._dernier < n <= self._dernier + 12):
            self._sauter(n)
        for image in self._decodeur:
            i = self._numero(image)
            self._dernier = i
            if i is None:
                continue
            self._memoriser(i, image)
            if i >= n:
                return self._cache.get(n, image)
        # Fin de flux atteinte sans trouver l'image : on renvoie la dernière décodée.
        self._decodeur = None
        if self._cache:
            return self._cache[next(reversed(self._cache))]
        raise IndexError(f"Image {n} introuvable dans {self.chemin}")

    def _numero(self, image) -> int | None:
        pts = image.pts
        if pts is None:
            return None
        if pts in self._pts_vers_n:
            return self._pts_vers_n[pts]
        # Horodatage inattendu : on prend l'image indexée la plus proche.
        k = bisect.bisect_left(self.index.pts, pts)
        return min(k, len(self.index) - 1)

    def _sauter(self, n: int):
        cible = self.index.pts[n]
        self._conteneur.seek(cible, stream=self._flux, backward=True, any_frame=False)
        self._decodeur = self._conteneur.decode(self._flux)
        self._dernier = -10

    def _memoriser(self, i, image):
        self._cache[i] = image
        self._cache.move_to_end(i)
        while len(self._cache) > self._taille_cache:
            self._cache.popitem(last=False)


class LecteurPaquets:
    """Lit les paquets compressés de la vidéo, pour les recopier sans réencoder."""

    def __init__(self, chemin: str, index: IndexImages, sequence_images: dict | None = None,
                 cadence: str | None = None):
        self.index = index
        self._conteneur = ouvrir_conteneur(chemin, sequence_images, cadence)
        self.flux = self._conteneur.streams.video[0]
        self._iter = None
        self._dernier = -10

    def fermer(self):
        self._conteneur.close()

    def paquet(self, n: int) -> av.Packet:
        cible = self.index.pts[n]
        if self._iter is None or n != self._dernier + 1:
            self._conteneur.seek(cible, stream=self.flux, backward=True, any_frame=True)
            self._iter = self._conteneur.demux(self.flux)
        for p in self._iter:
            if p.pts is None or p.size == 0:
                continue
            if p.pts == cible:
                self._dernier = n
                return p
            if p.pts > cible:
                break
        # Le paquet cherché a été dépassé : on recommence depuis un saut franc.
        self._conteneur.seek(cible, stream=self.flux, backward=True, any_frame=True)
        for p in self._conteneur.demux(self.flux):
            if p.pts == cible:
                self._iter = None
                self._dernier = n
                return p
        raise IndexError(f"Paquet de l'image {n} introuvable")


class AudioCache:
    """Audio d'un média décodé en flottant 32 bits stéréo à 48 kHz, lu par projection mémoire."""

    def __init__(self, fichier: Path):
        meta = json.loads(fichier.with_suffix(".json").read_text(encoding="utf-8"))
        self.decalage_s = meta["decalage_s"]
        self.nb = meta["echantillons"]
        self._donnees = (np.memmap(fichier, dtype=np.float32, mode="r", shape=(self.nb, 2))
                         if self.nb else np.zeros((0, 2), np.float32))

    def lire(self, debut: int, n: int) -> np.ndarray:
        """Échantillons [debut, debut+n) ; les zones hors média sont du silence."""
        sortie = np.zeros((n, 2), np.float32)
        a, b = max(debut, 0), min(debut + n, self.nb)
        if b > a:
            sortie[a - debut:b - debut] = self._donnees[a:b]
        return sortie

    def cretes(self, nb_cases: int) -> np.ndarray:
        """Amplitude maximale par case, pour dessiner la forme d'onde."""
        if self.nb == 0 or nb_cases <= 0:
            return np.zeros(max(nb_cases, 0), np.float32)
        pas = max(1, self.nb // nb_cases)
        utile = self._donnees[: pas * (self.nb // pas)]
        return np.abs(utile).max(axis=1).reshape(-1, pas).max(axis=1)


def generer_cache_audio(infos: InfosMedia, fichier: Path, progression=None, annule=None) -> Path:
    """Décode le premier flux audio du média vers `fichier` (brut float32 stéréo 48 kHz)."""
    fichier.parent.mkdir(parents=True, exist_ok=True)
    temporaire = fichier.with_suffix(".partiel")
    total = 0
    decalage = 0.0
    with av.open(infos.chemin) as c:
        a = c.streams.audio[0]
        debut_video = 0.0
        if c.streams.video:
            v = c.streams.video[0]
            if v.start_time is not None:
                debut_video = float(v.start_time * v.time_base)
        if a.start_time is not None:
            decalage = float(a.start_time * a.time_base) - debut_video
        reech = av.AudioResampler(format="flt", layout="stereo", rate=FREQUENCE_MIXAGE)
        duree = max(infos.duree_s, 1e-6)
        with open(temporaire, "wb") as f:
            def ecrire(images):
                nonlocal total
                for img in images:
                    tab = img.to_ndarray().reshape(-1, 2).astype(np.float32, copy=False)
                    f.write(tab.tobytes())
                    total += tab.shape[0]
            for image in c.decode(a):
                if annule is not None and annule.is_set():
                    break
                ecrire(reech.resample(image))
                if progression:
                    progression(min(1.0, total / FREQUENCE_MIXAGE / duree))
            ecrire(reech.resample(None))
    if annule is not None and annule.is_set():
        temporaire.unlink(missing_ok=True)
        raise InterruptedError
    temporaire.replace(fichier)
    fichier.with_suffix(".json").write_text(
        json.dumps({"decalage_s": decalage, "echantillons": total}), encoding="utf-8")
    return fichier


class Pool:
    """Réserve de lecteurs ouverts, un par (chemin, variante), pour un fil d'exécution donné."""

    def __init__(self):
        self._lecteurs: dict[tuple, LecteurVideo] = {}
        self._audio: dict[str, AudioCache | None] = {}
        self._verrou = threading.Lock()

    def video(self, cle: tuple, fabrique) -> LecteurVideo:
        if cle not in self._lecteurs:
            self._lecteurs[cle] = fabrique()
        return self._lecteurs[cle]

    def audio(self, fichier: Path) -> AudioCache | None:
        cle = str(fichier)
        with self._verrou:
            if self._audio.get(cle) is None and fichier.exists():
                self._audio[cle] = AudioCache(fichier)
            return self._audio.get(cle)

    def oublier_audio(self, fichier: Path):
        with self._verrou:
            self._audio.pop(str(fichier), None)

    def fermer(self):
        for l in self._lecteurs.values():
            l.fermer()
        self._lecteurs.clear()
