"""Chaîne de rendu complète : datamosh -> effets visuels -> export MP4 (H.264 + audio)."""
import os
import re
import shutil
import tempfile

import numpy as np

from . import effets as fx
from .moteur_mosh import ReglagesMosh, creer_flux_mosh
from .outils import FFMPEG, infos_video, ouvrir, taille_paire


class Annule(Exception):
    pass


def rendre(sources, sortie, reglages_mosh: ReglagesMosh, reglages_fx: fx.ReglagesEffets,
           largeur_max=None, qualite=18, progression=None, annuler=lambda: False, retour=None):
    """Crée la vidéo finale. progression(fraction 0-1, message) est appelée régulièrement.
    retour (dict facultatif) reçoit les instants des images clés détectées."""
    prog = progression or (lambda f, m: None)
    tmp = tempfile.mkdtemp(prefix="bavure_")
    try:
        info = infos_video(sources[0])
        garder_audio = info["audio"] and len(sources) == 1
        nb_total = sum(infos_video(s)["nb_images"] for s in sources)

        # 1) Datamosh (ou simple réencodage si inactif mais plusieurs clips)
        if reglages_mosh.actif or len(sources) > 1:
            prog(0.02, "Préparation du flux MPEG-4…")
            flux, fps, l, h, cles = creer_flux_mosh(sources, tmp, largeur_max, reglages_mosh)
            if retour is not None:
                retour["cles"] = cles
                retour["fps"] = fps
            entree = ["-r", str(fps), "-f", "m4v", "-i", flux]
            if reglages_mosh.bloom:
                nb_total += reglages_mosh.bloom_repetitions
        else:
            fps = info["fps"]
            l, h = taille_paire(info["largeur"], info["hauteur"], largeur_max)
            entree = ["-i", sources[0]]
        if annuler():
            raise Annule()

        # Audio : on reprend la piste de la vidéo d'origine (une seule source uniquement)
        if not garder_audio:
            audio_in, audio_map = [], []
        elif entree[-1] == sources[0]:
            audio_in, audio_map = [], ["-map", "0:a:0?", "-c:a", "aac", "-b:a", "192k"]
        else:
            audio_in, audio_map = ["-i", sources[0]], ["-map", "1:a:0?", "-c:a", "aac", "-b:a", "192k"]
        sortie_args = ["-c:v", "libx264", "-crf", str(qualite), "-preset", "veryfast",
                       "-pix_fmt", "yuv420p", "-movflags", "+faststart"]

        if not reglages_fx.actif():
            # 2a) Pas d'effet visuel : FFmpeg décode et réencode directement
            args = [FFMPEG, "-y", "-hide_banner", *entree, *audio_in, "-map", "0:v:0", *audio_map,
                    "-vf", f"scale={l}:{h},setsar=1", *sortie_args,
                    "-progress", "pipe:1", "-nostats", sortie]
            proc = ouvrir(args, stdout=-1, stderr=-3)
            for ligne in proc.stdout:
                m = re.match(rb"frame=(\d+)", ligne)
                if m:
                    prog(0.1 + 0.9 * min(1, int(m[1]) / max(1, nb_total)), "Export…")
                if annuler():
                    proc.kill()
                    raise Annule()
            proc.wait()
            if proc.returncode != 0:
                raise RuntimeError("Échec de l'export FFmpeg.")
        else:
            # 2b) Effets visuels : décodage -> Python (effets) -> encodage, par tuyaux
            lecteur = ouvrir([FFMPEG, "-hide_banner", "-loglevel", "error", *entree,
                              "-map", "0:v:0", "-vf", f"scale={l}:{h}", "-f", "rawvideo",
                              "-pix_fmt", "bgr24", "-"], stdout=-1, stderr=-3)
            ecrivain = ouvrir([FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                               "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{l}x{h}",
                               "-r", str(fps), "-i", "-", *tuyau_audio(garder_audio, sources[0]),
                               *sortie_args, sortie], stdin=-1, stderr=-3)
            taille = l * h * 3
            n = 0
            try:
                while True:
                    brut = lecteur.stdout.read(taille)
                    if len(brut) < taille:
                        break
                    img = np.frombuffer(brut, np.uint8).reshape(h, l, 3).copy()
                    img = fx.appliquer(img, reglages_fx, n)
                    ecrivain.stdin.write(np.ascontiguousarray(img).tobytes())
                    n += 1
                    if n % 5 == 0:
                        prog(0.1 + 0.9 * min(1, n / max(1, nb_total)), f"Effets… image {n}")
                    if annuler():
                        raise Annule()
            finally:
                lecteur.kill()
                try:
                    ecrivain.stdin.close()
                except Exception:
                    pass
                ecrivain.wait()
            if ecrivain.returncode != 0:
                raise RuntimeError("Échec de l'encodage final.")
        prog(1.0, "Terminé")
        return sortie
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def tuyau_audio(garder_audio, source):
    """En mode « effets », la vidéo arrive par le tuyau (entrée 0) et l'audio du fichier source (entrée 1)."""
    if not garder_audio:
        return []
    return ["-i", source, "-map", "0:v:0", "-map", "1:a:0?", "-c:a", "aac", "-b:a", "192k"]
