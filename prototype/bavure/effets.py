"""Effets glitch visuels appliqués image par image (tableaux numpy BGR, comme OpenCV).

Toutes les intensités vont de 0 à 100 et sont relatives à la taille de l'image :
l'aperçu (petite taille) et l'export (pleine taille) donnent le même rendu.
"""
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class ReglagesEffets:
    rvb: int = 0             # décalage des couches rouge / bleu
    tri_pixels: int = 0      # pixel sorting
    tri_vertical: bool = False
    scanlines: int = 0       # lignes de balayage + lignes qui sautent
    blocs: int = 0           # blocs déplacés au hasard
    vhs: int = 0             # bavure de couleur, bruit, ondulation, bande de tracking
    graine: int = 1234

    def actif(self):
        return any([self.rvb, self.tri_pixels, self.scanlines, self.blocs, self.vhs])


# ---------------------------------------------------------------------------

def decalage_rvb(img, force, n, rnd):
    h, w = img.shape[:2]
    d = int(w * 0.03 * force / 100) + rnd.integers(-1, 2) * int(force > 50)
    if d == 0:
        return img
    b, g, r = cv2.split(img)
    dy = int(rnd.integers(-1, 2) * h * 0.004 * force / 100)
    r = np.roll(r, (dy, d), axis=(0, 1))
    b = np.roll(b, (-dy, -d), axis=(0, 1))
    return cv2.merge([b, g, r])


def tri_pixels(img, force, vertical=False):
    """Trie les pixels par luminosité dans les zones claires (style Kim Asendorf).
    Entièrement vectorisé : un seul tri pour toute l'image."""
    if vertical:
        img = np.ascontiguousarray(img.transpose(1, 0, 2))
    h, w = img.shape[:2]
    lum = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.int32)
    seuil = int(255 - force * 2.2)  # plus la force est grande, plus la zone triée est large
    masque = lum >= seuil
    prec = np.zeros_like(masque)
    prec[:, 1:] = masque[:, :-1]
    prec[:, 0] = False  # chaque ligne commence un nouveau segment
    debut_segment = ~masque | ~prec
    segment = np.cumsum(debut_segment.ravel())
    ordre = np.lexsort((lum.ravel(), segment))
    resultat = img.reshape(-1, 3)[ordre].reshape(h, w, 3)
    if vertical:
        resultat = np.ascontiguousarray(resultat.transpose(1, 0, 2))
    return resultat


def scanlines(img, force, n, rnd):
    h, w = img.shape[:2]
    out = img.copy()
    pas = max(2, h // 240)
    sombre = 1 - 0.45 * force / 100
    out[::pas * 2] = (out[::pas * 2] * sombre).astype(np.uint8)
    # quelques bandes horizontales qui sautent
    for _ in range(int(force / 12)):
        y = int(rnd.integers(0, h))
        hauteur = int(rnd.integers(1, max(2, h // 30)))
        dx = int(rnd.normal(0, w * 0.04 * force / 100))
        out[y:y + hauteur] = np.roll(out[y:y + hauteur], dx, axis=1)
    return out


def blocs_deplaces(img, force, n, rnd):
    h, w = img.shape[:2]
    out = img.copy()
    taille = max(8, w // 40)
    for _ in range(int(force * 0.6)):
        bw = taille * int(rnd.integers(1, 6))
        bh = taille * int(rnd.integers(1, 3))
        x, y = int(rnd.integers(0, max(1, w - bw))), int(rnd.integers(0, max(1, h - bh)))
        x2 = int(np.clip(x + rnd.normal(0, w * 0.08), 0, w - bw))
        y2 = int(np.clip(y + rnd.normal(0, h * 0.02), 0, h - bh))
        bloc = img[y2:y2 + bh, x2:x2 + bw]
        if rnd.random() < 0.3:  # parfois, on décale aussi les couleurs du bloc
            bloc = bloc[:, :, list(rnd.permutation(3))]
        out[y:y + bh, x:x + bw] = bloc
    return out


def vhs(img, force, n, rnd):
    h, w = img.shape[:2]
    f = force / 100
    ycc = cv2.cvtColor(img, cv2.COLOR_BGR2YCrCb).astype(np.float32)
    # bavure de couleur horizontale, décalée vers la droite
    k = max(1, int(w * 0.02 * f)) * 2 + 1
    for c in (1, 2):
        ycc[:, :, c] = np.roll(cv2.blur(ycc[:, :, c], (k, 1)), int(w * 0.006 * f), axis=1)
    # ondulation des lignes
    ys = np.arange(h, dtype=np.float32)
    decal = (np.sin(ys / h * 18 + n * 0.35) * w * 0.003 * f
             + rnd.normal(0, w * 0.0008 * f, h)).astype(np.float32)
    carte_x = np.tile(np.arange(w, dtype=np.float32), (h, 1)) + decal[:, None]
    carte_y = np.repeat(ys[:, None], w, axis=1)
    ycc = cv2.remap(ycc, carte_x, carte_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    # bruit + légère désaturation
    ycc[:, :, 0] += rnd.normal(0, 9 * f, (h, w)).astype(np.float32)
    ycc[:, :, 1:] = 128 + (ycc[:, :, 1:] - 128) * (1 - 0.25 * f)
    out = cv2.cvtColor(np.clip(ycc, 0, 255).astype(np.uint8), cv2.COLOR_YCrCb2BGR)
    # bande de tracking qui remonte lentement
    if f > 0.2:
        hb = max(2, int(h * 0.04 * f))
        y = int((h - (n * 3) % (h + hb)) % h)
        bande = out[y:y + hb].astype(np.int16) + rnd.integers(-40, 60, out[y:y + hb].shape)
        out[y:y + hb] = np.roll(np.clip(bande, 0, 255).astype(np.uint8), int(w * 0.03), axis=1)
    return out


def appliquer(img, r: ReglagesEffets, n=0):
    """Applique tous les effets actifs sur l'image n (n sert à animer et à fixer le hasard)."""
    if not r.actif():
        return img
    rnd = np.random.default_rng(r.graine * 100003 + n)
    if r.tri_pixels:
        img = tri_pixels(img, r.tri_pixels, r.tri_vertical)
    if r.blocs:
        img = blocs_deplaces(img, r.blocs, n, rnd)
    if r.vhs:
        img = vhs(img, r.vhs, n, rnd)
    if r.rvb:
        img = decalage_rvb(img, r.rvb, n, rnd)
    if r.scanlines:
        img = scanlines(img, r.scanlines, n, rnd)
    return img
