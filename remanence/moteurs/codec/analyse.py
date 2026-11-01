"""Analyse d'un clip par le moteur codec, pour l'espace Datamosh : le type (I ou P) et le
poids de chaque image compressée, et ses vecteurs de mouvement.

Le clip est encodé comme pour un datamosh (moteur FFglitch s'il est installé, sinon Bavure ;
images clés aux coupes), depuis sa source modifiée s'il en a une. Le décodeur de FFmpeg rend
les vecteurs (`export_mvs`). Le résultat est gardé en cache à côté des pré-rendus.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import av
import numpy as np

from remanence.moteurs.codec import bavure, ffglitch, prerendu
from remanence.projet.modele import Clip, Projet, Sequence


@dataclass
class Analyse:
    types: list[str]          # « I » ou « P » pour chaque image du clip
    tailles: list[int]        # octets de chaque image compressée
    # Vecteurs : lignes (image, x, y, dx, dy) en pixels du média ; (x, y) est le centre du
    # bloc, (dx, dy) son déplacement depuis l'image précédente.
    vecteurs: np.ndarray
    largeur: int
    hauteur: int
    moteur: str               # « FFglitch » ou « Bavure »

    def vecteurs_de(self, t: int) -> np.ndarray:
        return self.vecteurs[self.vecteurs[:, 0] == t][:, 1:]


def cle(projet: Projet, seq: Sequence, clip: Clip) -> str | None:
    media = projet.medias.get(clip.media_id)
    if clip.est_effet or media is None or media.infos.video is None:
        return None
    donnees = {"source": prerendu._signature(projet, clip), "cadence": seq.cadence,
               "raccord": prerendu.cle_source(projet, seq, clip),
               "ffglitch": ffglitch.disponible()}
    return prerendu._empreinte(donnees)


def chemin(cle_analyse: str) -> Path:
    return prerendu.dossier() / f"analyse_{cle_analyse}.npz"


def lire(projet: Projet, seq: Sequence, clip: Clip) -> Analyse | None:
    """L'analyse déjà calculée, ou None."""
    k = cle(projet, seq, clip)
    if k is None or not chemin(k).exists():
        return None
    try:
        with np.load(chemin(k)) as d:
            return Analyse([chr(c) for c in d["types"]], d["tailles"].tolist(), d["vecteurs"],
                           int(d["taille"][0]), int(d["taille"][1]), str(d["moteur"]))
    except (OSError, ValueError, KeyError):
        return None


def analyser(projet: Projet, seq: Sequence, clip: Clip, progression=None,
             annule: threading.Event | None = None) -> Analyse | None:
    k = cle(projet, seq, clip)
    if k is None:
        return None
    deja = lire(projet, seq, clip)
    if deja is not None:
        return deja
    v = projet.medias[clip.media_id].infos.video
    largeur, hauteur = v.largeur - v.largeur % 2, v.hauteur - v.hauteur % 2
    images = prerendu._images_source(projet, seq, clip)
    cles = set(prerendu.coupes_du_clip(projet, clip))
    with ffglitch.dossier_travail(prerendu.dossier()) as travail:
        paquets = prerendu.encoder(images, clip.duree, largeur, hauteur, Fraction(seq.cadence),
                                   2, cles, Path(travail), progression, annule)
    types = [bavure.type_image(p) for p in paquets]
    tailles = [len(p) for p in paquets]
    d = av.CodecContext.create("mpeg4", "r")
    d.options = {"flags2": "+export_mvs"}
    lignes = []
    t = 0
    for p in paquets + [None]:
        try:
            trames = d.decode(av.Packet(p) if p is not None else None)
        except av.error.FFmpegError:
            trames = []
        for trame in trames:
            mv = trame.side_data.get("MOTION_VECTORS")
            if mv is not None and len(mv):
                a = mv.to_ndarray()
                echelle = np.maximum(a["motion_scale"], 1)
                dx = -a["motion_x"] / echelle
                dy = -a["motion_y"] / echelle
                bouge = (dx != 0) | (dy != 0)
                lignes.append(np.stack([np.full(bouge.sum(), t), a["dst_x"][bouge],
                                        a["dst_y"][bouge], dx[bouge], dy[bouge]], axis=1))
            t += 1
    vecteurs = np.concatenate(lignes).astype(np.float32) if lignes else np.zeros((0, 5),
                                                                                np.float32)
    moteur = "FFglitch" if ffglitch.disponible() else "Bavure"
    final = chemin(k)
    partiel = final.with_name(final.stem + ".partiel.npz")
    np.savez_compressed(partiel, types=np.array([ord(x) for x in types], np.uint8),
                        tailles=np.array(tailles, np.int64), vecteurs=vecteurs,
                        taille=np.array([largeur, hauteur]), moteur=np.array(moteur))
    partiel.replace(final)
    return Analyse(types, tailles, vecteurs, largeur, hauteur, moteur)
