"""Outils communs : localisation de FFmpeg, lecture des infos vidéo, lancement de commandes."""
import os
import re
import shutil
import subprocess
import sys

# Sous Windows, évite qu'une fenêtre noire s'ouvre à chaque appel de FFmpeg
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def trouver_ffmpeg():
    """FFmpeg fourni par imageio-ffmpeg (installé automatiquement), sinon celui du système."""
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        return get_ffmpeg_exe()
    except Exception:
        chemin = shutil.which("ffmpeg")
        if chemin:
            return chemin
        raise RuntimeError("FFmpeg est introuvable. Relance installer.bat.")


FFMPEG = trouver_ffmpeg()


def lancer(args, **kw):
    return subprocess.run(args, capture_output=True, creationflags=CREATE_NO_WINDOW, **kw)


def ouvrir(args, **kw):
    return subprocess.Popen(args, creationflags=CREATE_NO_WINDOW, **kw)


def infos_video(chemin):
    """Renvoie un dict : largeur, hauteur, fps, duree (s), nb_images, audio (bool)."""
    sortie = lancer([FFMPEG, "-hide_banner", "-i", chemin]).stderr.decode("utf-8", "replace")
    infos = {"largeur": 0, "hauteur": 0, "fps": 25.0, "duree": 0.0, "audio": False}
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", sortie)
    if m:
        infos["duree"] = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    for ligne in sortie.splitlines():
        if "Video:" in ligne and not infos["largeur"]:
            t = re.search(r", (\d{2,5})x(\d{2,5})", ligne)
            if t:
                infos["largeur"], infos["hauteur"] = int(t[1]), int(t[2])
            f = re.search(r"([\d.]+) fps", ligne) or re.search(r"([\d.]+) tbr", ligne)
            if f:
                infos["fps"] = float(f[1])
        if "Audio:" in ligne:
            infos["audio"] = True
    if not infos["largeur"]:
        raise RuntimeError(f"Impossible de lire la vidéo : {os.path.basename(chemin)}")
    infos["nb_images"] = max(1, int(round(infos["duree"] * infos["fps"])))
    return infos


def taille_paire(largeur_src, hauteur_src, largeur_max=None):
    """Taille de sortie aux dimensions paires (obligatoire pour les encodeurs)."""
    l = largeur_src if not largeur_max else min(largeur_src, largeur_max)
    h = l * hauteur_src / largeur_src
    return int(l // 2 * 2), int(round(h / 2) * 2)
