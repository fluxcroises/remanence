"""Aperçu en direct d'un effet à script, par fflive (le lecteur de FFglitch).

Le clip est encodé en MPEG-4 comme pour un pré-rendu (images clés à ses coupes), gardé en
cache tant que la source et les blocs ne changent pas ; fflive le lit en boucle avec le script
de l'effet, dans une fenêtre sans bord posée sur l'image du moniteur programme. Les scripts qui
se pilotent au clavier, à la manette ou au MIDI marchent ici, et seulement ici.

L'effet est montré seul, sur la source du clip : c'est un aperçu pour régler, la timeline et
l'export gardent leur calcul habituel.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from fractions import Fraction
from pathlib import Path

from remanence.effets import EFFETS
from remanence.moteurs.codec import ffglitch, prerendu, scripts
from remanence.projet.modele import Clip, Effet, Projet, Sequence

TITRE = "Remanence · Direct"
_SANS_FENETRE = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def accepte(effet: Effet) -> bool:
    """Effet qu'on peut voir en direct : un script FFglitch, ou un effet qui en génère un
    (vecteurs de mouvement, écho, zoom, saccades). Pas le transfert, qui demande deux clips."""
    d = EFFETS.get(effet.type)
    return d is not None and d.script is not None


def script(projet: Projet, seq: Sequence, clip: Clip, effet: Effet) -> str:
    """Le script de l'effet pour fflive, avec ses réglages (animés : une valeur par image)."""
    if effet.type == "script_ffglitch":
        noms = scripts.reglages(effet.script)
        reglages = {nom: effet.params.get(nom, v) for nom, v in noms.items()}
        return scripts.adapter(effet.script, reglages, effet.graine)
    valeurs = prerendu.valeurs_images(effet, clip.duree, seq, clip.debut, projet)
    return EFFETS[effet.type].script(valeurs, effet.graine, effet)


def flux(projet: Projet, seq: Sequence, clip: Clip, effet: Effet, annule=None) -> Path:
    """Le clip en MPEG-4 pour fflive, gardé en cache (même source, mêmes blocs : même fichier)."""
    media = projet.medias[clip.media_id]
    v = media.infos.video
    largeur, hauteur = v.largeur - v.largeur % 2, v.hauteur - v.hauteur % 2
    blocs = int(round({**EFFETS[effet.type].valeurs(), **effet.params}.get("blocs", 4)))
    empreinte = hashlib.sha1(json.dumps(
        [prerendu.cle_source(projet, seq, clip), media.chemin, clip.entree, clip.duree,
         clip.vitesse, clip.inverse, seq.cadence, blocs]).encode()).hexdigest()[:16]
    sortie = prerendu.dossier() / f"direct_{empreinte}.avi"
    if not sortie.exists():
        partiel = sortie.with_name(sortie.stem + ".partiel.avi")
        images = prerendu._images_source(projet, seq, clip)
        ffglitch.encoder(images, largeur, hauteur, Fraction(seq.cadence), blocs,
                         set(prerendu.coupes_du_clip(projet, clip)), partiel, n=clip.duree,
                         annule=annule)
        partiel.replace(sortie)
    return sortie


class Direct:
    """Une fenêtre de direct à la fois."""

    def __init__(self):
        self._processus: subprocess.Popen | None = None
        self.effet_id: str | None = None

    def actif(self) -> bool:
        return self._processus is not None and self._processus.poll() is None

    def lancer(self, fichier: Path, texte: str, rect: tuple[int, int, int, int],
               effet_id: str):
        """rect : (gauche, haut, largeur, hauteur) de la fenêtre, en pixels de l'écran."""
        self.arreter()
        outils = ffglitch.dossier()
        if outils is None:
            raise RuntimeError("FFglitch absent")
        js = fichier.with_name(f"direct_{effet_id}.js")
        js.write_text(texte, encoding="utf-8")
        x, y, l, h = rect
        self._processus = subprocess.Popen(
            [str(outils / "fflive.exe"), "-hide_banner", "-loglevel", "error", "-an",
             "-loop", "0", "-noborder", "-alwaysontop", "-window_title", TITRE,
             "-left", str(x), "-top", str(y), "-x", str(l), "-y", str(h),
             "-s", str(js), "-i", str(fichier)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            creationflags=_SANS_FENETRE)
        self.effet_id = effet_id

    def erreur(self) -> str:
        """Le message de fflive s'il s'est arrêté de lui-même sur une erreur."""
        if self._processus is None or self._processus.poll() is None:
            return ""
        try:
            return self._processus.stderr.read().decode("utf-8", "replace").strip()
        except (OSError, ValueError):
            return ""

    def arreter(self):
        if self._processus is not None and self._processus.poll() is None:
            self._processus.terminate()
            try:
                self._processus.wait(2)
            except subprocess.TimeoutExpired:
                self._processus.kill()
        self._processus = None
        self.effet_id = None
