"""Moteur de datamosh.

Principe : la vidéo est réencodée en MPEG-4 Part 2 (le codec de Xvid, idéal pour le datamosh)
sans images B. Le flux brut est découpé image par image :
  - image I (clé) : image complète
  - image P : uniquement le mouvement par rapport à l'image précédente
Supprimer des images I fait « baver » l'ancienne image avec le mouvement de la nouvelle.
Répéter une image P (bloom) applique sans fin le même mouvement : les pixels fondent.
Le databending modifie au hasard des octets des images P pour des artefacts imprévisibles.
"""
import os
import random
import re
from dataclasses import dataclass, field

from .outils import FFMPEG, lancer, infos_video, taille_paire

CODE_VOP = 0xB6  # début d'une image dans un flux MPEG-4 Part 2
TYPES = {0: "I", 1: "P", 2: "B", 3: "S"}


@dataclass
class ReglagesMosh:
    actif: bool = True
    supprimer_cles: bool = True       # supprimer les images clés (sauf la toute première)
    debut: float = 0.0                # zone de suppression (secondes)
    fin: float = 0.0                  # 0 = jusqu'à la fin
    bloom: bool = False               # répéter une image P
    bloom_instant: float = 1.0        # à quel moment (secondes)
    bloom_repetitions: int = 30       # combien de fois
    blocs: int = 4                    # 1 = propre, 31 = gros blocs (paramètre -q:v)
    databending: int = 0              # 0 à 100
    graine: int = 1234
    blooms_supplementaires: list = field(default_factory=list)  # [(instant, répétitions), ...]


# ---------------------------------------------------------------------------
# Encodage et découpage du flux
# ---------------------------------------------------------------------------

def encoder_en_mpeg4(sources, sortie_m4v, largeur_max, fps, blocs):
    """Réencode une ou plusieurs vidéos (mises bout à bout) en flux MPEG-4 brut sans images B."""
    info0 = infos_video(sources[0])
    l, h = taille_paire(info0["largeur"], info0["hauteur"], largeur_max)
    args = [FFMPEG, "-y", "-hide_banner"]
    for s in sources:
        args += ["-i", s]
    filtres = []
    for i in range(len(sources)):
        filtres.append(
            f"[{i}:v]scale={l}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={l}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p[v{i}]"
        )
    entrees = "".join(f"[v{i}]" for i in range(len(sources)))
    filtres.append(f"{entrees}concat=n={len(sources)}:v=1:a=0[v]")
    args += ["-filter_complex", ";".join(filtres), "-map", "[v]", "-an",
             "-c:v", "mpeg4", "-q:v", str(max(1, min(31, blocs))), "-bf", "0",
             "-g", "600", "-f", "m4v", sortie_m4v]
    r = lancer(args)
    if r.returncode != 0:
        raise RuntimeError("Échec de l'encodage MPEG-4 :\n" + r.stderr.decode("utf-8", "replace")[-800:])
    return l, h


def decouper(data):
    """Découpe le flux en (entête, [images]). Chaque image = dict(type, prefixe, corps)."""
    codes = [m.start() for m in re.finditer(b"\x00\x00\x01", data)]
    vops = [i for i, p in enumerate(codes) if p + 3 < len(data) and data[p + 3] == CODE_VOP]
    if not vops:
        raise RuntimeError("Aucune image trouvée dans le flux MPEG-4.")
    entete = data[:codes[vops[0]]]
    images = []
    fin_prec = codes[vops[0]]
    for i in vops:
        debut = codes[i]
        fin = codes[i + 1] if i + 1 < len(codes) else len(data)
        type_vop = TYPES[(data[debut + 4] >> 6) & 3]
        images.append({"type": type_vop, "prefixe": data[fin_prec:debut], "corps": data[debut:fin]})
        fin_prec = fin
    return entete, images


def abimer(corps, force, rnd):
    """Databending : remplace des octets au hasard (jamais 0x00 ni 0x01, pour ne pas
    créer de faux marqueurs de début d'image qui casseraient tout le fichier)."""
    if force <= 0 or len(corps) < 24:
        return corps
    b = bytearray(corps)
    n = max(1, int(len(b) * (force / 100) ** 2 * 0.02))
    for _ in range(n):
        pos = rnd.randrange(12, len(b))  # on épargne l'en-tête de l'image
        b[pos] = rnd.randrange(2, 256)
    return bytes(b)


def mosher(images, fps, r: ReglagesMosh):
    """Applique les réglages sur la liste d'images. Renvoie la nouvelle liste (octets)."""
    rnd = random.Random(r.graine)
    debut_img = int(r.debut * fps)
    fin_img = int(r.fin * fps) if r.fin > 0 else len(images) + 1
    blooms = {}
    if r.bloom:
        blooms[int(r.bloom_instant * fps)] = r.bloom_repetitions
    for instant, rep in r.blooms_supplementaires:
        blooms[int(instant * fps)] = rep

    sortie = []
    premiere_cle_vue = False
    for idx, img in enumerate(images):
        est_cle = img["type"] == "I"
        dans_zone = debut_img <= idx < fin_img
        if est_cle:
            if not premiere_cle_vue:
                premiere_cle_vue = True
                sortie.append(img["prefixe"] + img["corps"])
                continue
            if r.supprimer_cles and dans_zone:
                # On remplace l'image clé par une copie de l'image P précédente :
                # la durée reste identique (l'audio reste calé) et la bavure démarre ici.
                if sortie and len(sortie) > 1:
                    sortie.append(sortie[-1])
                continue
        corps = img["corps"]
        if not est_cle and r.databending and dans_zone:
            corps = abimer(corps, r.databending, rnd)
        sortie.append(img["prefixe"] + corps)
        if idx in blooms and not est_cle:
            sortie.extend([corps] * blooms[idx])
    return sortie


def lister_images_cles(chemin_m4v, fps):
    """Pour l'interface : les instants (s) des images clés."""
    with open(chemin_m4v, "rb") as f:
        _, images = decouper(f.read())
    return [i / fps for i, img in enumerate(images) if img["type"] == "I"]


def creer_flux_mosh(sources, dossier_tmp, largeur_max, reglages: ReglagesMosh, fps=None):
    """Étape complète : encodage, découpage, mosh.
    Renvoie (chemin du flux .m4v, fps, largeur, hauteur, instants des images clés)."""
    info = infos_video(sources[0])
    fps = fps or round(info["fps"], 3)
    propre = os.path.join(dossier_tmp, "propre.m4v")
    l, h = encoder_en_mpeg4(sources, propre, largeur_max, fps, reglages.blocs)
    with open(propre, "rb") as f:
        entete, images = decouper(f.read())
    cles = [i / fps for i, im in enumerate(images) if im["type"] == "I"]
    if reglages.actif:
        morceaux = mosher(images, fps, reglages)
    else:
        morceaux = [im["prefixe"] + im["corps"] for im in images]
    moshe = os.path.join(dossier_tmp, "moshe.m4v")
    with open(moshe, "wb") as f:
        f.write(entete)
        for m in morceaux:
            f.write(m)
    return moshe, fps, l, h, cles
