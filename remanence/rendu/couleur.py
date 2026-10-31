"""Passage explicite entre les plans YUV d'un fichier et une image RVBA flottante.

La conversion utilise la matrice et la plage lues dans le fichier, et l'opération
inverse les réapplique à l'identique. Aucune courbe de transfert n'est touchée :
une image en log reste en log.
"""

from __future__ import annotations

import av
import numpy as np

from remanence.media.sonde import Couleur

COEFFICIENTS = {1: (0.2126, 0.0722), 5: (0.299, 0.114), 6: (0.299, 0.114),
                7: (0.212, 0.087), 9: (0.2627, 0.0593), 10: (0.2627, 0.0593)}


def coefficients(matrice: int, hauteur: int) -> tuple[float, float]:
    if matrice in COEFFICIENTS:
        return COEFFICIENTS[matrice]
    # Matrice non précisée : même convention que les lecteurs courants (HD en 709, SD en 601).
    return COEFFICIENTS[1] if hauteur >= 720 else COEFFICIENTS[6]


def _est_yuv(fmt: av.VideoFormat) -> bool:
    n = fmt.name
    return n.startswith(("yuv", "yuvj", "nv12", "p010", "p210", "p410")) or n in ("v210",)


def _plage_complete(fmt: av.VideoFormat, couleur: Couleur) -> bool:
    return fmt.name.startswith("yuvj") or couleur.plage == 2


def _plans(image: av.VideoFrame) -> list[np.ndarray]:
    fmt = image.format
    octets = 2 if max(c.bits for c in fmt.components) > 8 else 1
    dtype = np.uint16 if octets == 2 else np.uint8
    plans = []
    for p in image.planes:
        brut = np.frombuffer(p, dtype=dtype)
        plans.append(brut.reshape(p.height, p.line_size // octets)[:, : p.width])
    return plans


def vers_rvba(image: av.VideoFrame, couleur: Couleur) -> np.ndarray:
    """Image décodée vers un tableau H×L×4 float32, alpha prémultiplié, valeurs 0 à 1."""
    fmt = image.format
    h, l = image.height, image.width
    if not _est_yuv(fmt) or len(image.planes) < 3:
        brut = image.reformat(format="rgba64le").to_ndarray().astype(np.float32) / 65535.0
        brut[..., :3] *= brut[..., 3:4]
        return brut
    bits = max(c.bits for c in fmt.components)
    y, u, v = (p.astype(np.float32) for p in _plans(image)[:3])
    echelle = float(1 << (bits - 8))
    if _plage_complete(fmt, couleur):
        maxv = float((1 << bits) - 1)
        y = y / maxv
        u = (u - 128.0 * echelle) / maxv
        v = (v - 128.0 * echelle) / maxv
    else:
        y = (y - 16.0 * echelle) / (219.0 * echelle)
        u = (u - 128.0 * echelle) / (224.0 * echelle)
        v = (v - 128.0 * echelle) / (224.0 * echelle)
    fy, fx = -(-h // u.shape[0]), -(-l // u.shape[1])
    if fy > 1 or fx > 1:
        u = np.repeat(np.repeat(u, fy, axis=0), fx, axis=1)[:h, :l]
        v = np.repeat(np.repeat(v, fy, axis=0), fx, axis=1)[:h, :l]
    kr, kb = coefficients(couleur.matrice, h)
    kg = 1.0 - kr - kb
    r = y + 2.0 * (1.0 - kr) * v
    b = y + 2.0 * (1.0 - kb) * u
    g = (y - kr * r - kb * b) / kg
    sortie = np.empty((h, l, 4), np.float32)
    sortie[..., 0], sortie[..., 1], sortie[..., 2] = r, g, b
    if len(image.planes) >= 4 and any(c.is_alpha for c in fmt.components):
        a = _plans(image)[3].astype(np.float32) / float((1 << bits) - 1)
        sortie[..., 3] = a
        sortie[..., :3] *= a[..., None]
    else:
        sortie[..., 3] = 1.0
    return sortie


def depuis_rvba(rvba: np.ndarray, pix_fmt: str, couleur: Couleur) -> av.VideoFrame:
    """Opération inverse de vers_rvba, vers le format de pixel demandé."""
    fmt = av.VideoFormat(pix_fmt)
    h, l = rvba.shape[:2]
    a = np.clip(rvba[..., 3], 0.0, 1.0)
    droite = rvba[..., :3] / np.maximum(a, 1e-6)[..., None]
    droite[a <= 1e-6] = 0.0
    if not _est_yuv(fmt):
        tab = np.empty((h, l, 4), np.uint16)
        tab[..., :3] = np.clip(np.rint(droite * 65535.0), 0, 65535)
        tab[..., 3] = np.rint(a * 65535.0)
        image = av.VideoFrame.from_ndarray(tab, format="rgba64le").reformat(format=pix_fmt)
        return appliquer_couleur(image, couleur)
    bits = max(c.bits for c in fmt.components)
    kr, kb = coefficients(couleur.matrice, h)
    kg = 1.0 - kr - kb
    r, g, b = droite[..., 0], droite[..., 1], droite[..., 2]
    y = kr * r + kg * g + kb * b
    u = (b - y) / (2.0 * (1.0 - kb))
    v = (r - y) / (2.0 * (1.0 - kr))
    image = av.VideoFrame(l, h, pix_fmt)
    plans_dims = [(p.height, p.width) for p in image.planes]
    ch, cl = plans_dims[1]
    fy, fx = -(-h // ch), -(-l // cl)

    def reduire(c):
        if fy == 1 and fx == 1:
            return c
        hp, lp = ch * fy, cl * fx
        c = np.pad(c, ((0, hp - h), (0, lp - l)), mode="edge")
        return c.reshape(ch, fy, cl, fx).mean(axis=(1, 3))

    u, v = reduire(u), reduire(v)
    echelle = float(1 << (bits - 8))
    maxv = float((1 << bits) - 1)
    if _plage_complete(fmt, couleur):
        yq, uq, vq = y * maxv, u * maxv + 128 * echelle, v * maxv + 128 * echelle
    else:
        yq = y * 219 * echelle + 16 * echelle
        uq = u * 224 * echelle + 128 * echelle
        vq = v * 224 * echelle + 128 * echelle
    valeurs = [yq, uq, vq]
    if len(image.planes) >= 4:
        valeurs.append(a * maxv)
    dtype = np.uint16 if bits > 8 else np.uint8
    for plan, val in zip(image.planes, valeurs):
        octets = np.dtype(dtype).itemsize
        tampon = np.zeros((plan.height, plan.line_size // octets), dtype)
        tampon[:, : plan.width] = np.clip(np.rint(val), 0, maxv)
        plan.update(tampon.tobytes())
    return appliquer_couleur(image, couleur, 2 if _plage_complete(fmt, couleur) else 1)


def appliquer_couleur(image: av.VideoFrame, couleur: Couleur, plage: int | None = None):
    """FFmpeg écrit dans le fichier les métadonnées portées par chaque image encodée."""
    image.color_primaries = couleur.primaires
    image.color_trc = couleur.transfert
    image.colorspace = couleur.matrice
    image.color_range = plage if plage is not None else (couleur.plage or 1)
    return image
