"""Databending audio : le datamosh du son. Le son est encodé en MP2 (le format des vieilles
radios numériques et des Video CD), des octets des paquets sont abîmés, puis il est décodé :
craquements, trous, bouts de son répétés ou métalliques.

Le travail se fait par tranches d'une seconde comptées depuis le début du clip ; chaque tranche
dépend de son seul contenu, du débit, de la corruption et de la graine (même son à chaque
lecture). Les tranches calculées sont gardées en mémoire, la lecture les redemande souvent."""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from fractions import Fraction

import av
import numpy as np

from remanence.effets import DescriptionEffet, Parametre

TRANCHE = 48000
TRAME = 1152          # échantillons d'une trame MP2
RETARD = 481          # retard du codeur et du décodeur MP2 de FFmpeg, mesuré
ENTETE = 4            # octets d'en-tête de trame, laissés intacts (la trame reste lisible)
_cache: OrderedDict = OrderedDict()
CACHE_MAX = 64


def _encoder(pcm: np.ndarray, debit: int) -> list[bytes]:
    enc = av.CodecContext.create("mp2", "w")
    enc.sample_rate, enc.layout, enc.format = 48000, "stereo", "s16"
    enc.bit_rate = debit
    enc.time_base = Fraction(1, 48000)
    paquets = []
    for i in range(0, len(pcm), TRAME):
        bloc = pcm[i:i + TRAME]
        if len(bloc) < TRAME:
            bloc = np.pad(bloc, ((0, TRAME - len(bloc)), (0, 0)))
        trame = av.AudioFrame.from_ndarray(np.ascontiguousarray(bloc).reshape(1, -1),
                                           format="s16", layout="stereo")
        trame.sample_rate, trame.pts = 48000, i
        paquets += [bytes(p) for p in enc.encode(trame)]
    paquets += [bytes(p) for p in enc.encode(None)]
    return paquets


def _decoder(paquets: list[bytes]) -> np.ndarray:
    dec = av.CodecContext.create("mp2", "r")
    dec.sample_rate, dec.layout = 48000, "stereo"
    morceaux = []
    for octets in paquets:
        try:
            for trame in dec.decode(av.Packet(octets)):
                x = trame.to_ndarray()
                morceaux.append(x.T if x.shape[0] == 2 else x.reshape(-1, 2))
        except (av.error.FFmpegError, ValueError):
            morceaux.append(np.zeros((TRAME, 2), np.int16))  # trame illisible : un trou
    if not morceaux:
        return np.zeros((0, 2), np.float32)
    return np.concatenate(morceaux).astype(np.float32) / 32768


def _abimer(paquets: list[bytes], corruption: float, graine: int, tranche: int) -> list[bytes]:
    hasard = np.random.default_rng([graine & 0xFFFFFFFF, tranche & 0xFFFFFFFF, 7])
    abimes = []
    for octets in paquets:
        if len(octets) > ENTETE + 1 and hasard.random() < corruption:
            b = bytearray(octets)
            for _ in range(1 + int(hasard.integers(0, 8))):
                i = int(hasard.integers(ENTETE, len(b)))
                b[i] = int(hasard.integers(0, 256))
            octets = bytes(b)
        abimes.append(octets)
    return abimes


def _tranche(lire, k: int, debit: int, corruption: float, graine: int) -> np.ndarray:
    entree = lire(k * TRANCHE, TRANCHE + RETARD + TRAME)
    empreinte = hashlib.sha1(entree.tobytes()).hexdigest()
    cle = (empreinte, debit, round(corruption, 4), graine, k)
    if cle in _cache:
        _cache.move_to_end(cle)
        return _cache[cle]
    pcm = (np.clip(entree, -1, 1) * 32767).astype(np.int16)
    sortie = _decoder(_abimer(_encoder(pcm, debit), corruption, graine, k))
    sortie = sortie[RETARD:RETARD + TRANCHE]
    if len(sortie) < TRANCHE:
        sortie = np.pad(sortie, ((0, TRANCHE - len(sortie)), (0, 0)))
    _cache[cle] = sortie
    if len(_cache) > CACHE_MAX:
        _cache.popitem(last=False)
    return sortie


def son(lire, valeurs, graine, frequence):
    debit = int(valeurs.get("debit", 64)) * 1000
    debit = min((32, 48, 56, 64, 80, 96, 112, 128, 160, 192),
                key=lambda d: abs(d * 1000 - debit)) * 1000  # débits permis par MP2
    corruption = valeurs.get("corruption", 20) / 100

    def lecteur(debut: int, n: int) -> np.ndarray:
        sortie = np.zeros((n, 2), np.float32)
        for k in range(int(np.floor(debut / TRANCHE)), int(np.floor((debut + n - 1) / TRANCHE)) + 1):
            a, b = max(debut, k * TRANCHE), min(debut + n, (k + 1) * TRANCHE)
            t = _tranche(lire, k, debit, corruption, graine)
            sortie[a - debut:b - debut] = t[a - k * TRANCHE:b - k * TRANCHE]
        return sortie
    return lecteur


DESCRIPTION = DescriptionEffet(
    cle="databending_audio", nom="Databending audio", famille="Son", moteur="audio", son=son,
    prereglages={"Radio abîmée": {"debit": 64, "corruption": 15},
                 "Fichier corrompu": {"debit": 96, "corruption": 45},
                 "Crépitements": {"debit": 32, "corruption": 8}},
    parametres=[Parametre("debit", "Débit", 32, 192, 64, "kb/s"),
                Parametre("corruption", "Corruption", 0, 100, 20, "%")],
)
