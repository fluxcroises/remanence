"""Emplacements des fichiers de Remanence sur la machine."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


def dossier_donnees() -> Path:
    """%APPDATA%\\Remanence : préréglages, sauvegardes automatiques, journal."""
    if os.environ.get("REMANENCE_DONNEES"):  # tests : un dossier à part
        d = Path(os.environ["REMANENCE_DONNEES"])
        d.mkdir(parents=True, exist_ok=True)
        return d
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    d = Path(base) / "Remanence"
    d.mkdir(parents=True, exist_ok=True)
    return d


def dossier_cache() -> Path:
    """%LOCALAPPDATA%\\Remanence\\cache : proxies et audio décodé, recalculables à tout moment."""
    base = os.environ.get("REMANENCE_CACHE") or os.environ.get("LOCALAPPDATA") \
        or str(Path.home() / ".cache")
    d = Path(base) / "Remanence" / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def empreinte_fichier(chemin: str, taille: int, date_modif: float) -> str:
    cle = f"{Path(chemin).resolve()}|{taille}|{date_modif:.3f}"
    return hashlib.sha1(cle.encode("utf-8")).hexdigest()[:20]


def reglages_interface():
    """Réglages de l'interface (dispositions, dernier espace de travail).

    Le format par défaut est respecté : les tests le redirigent vers un dossier temporaire au
    lieu du registre Windows de l'utilisateur.
    """
    from PySide6.QtCore import QSettings
    return QSettings(QSettings.defaultFormat(), QSettings.UserScope, "Remanence", "Remanence")


# Dossier proposé au départ par les fenêtres de fichiers, selon ce qu'on y cherche.
DOSSIERS_DEPART = {"projets": "DocumentsLocation", "medias": "MoviesLocation",
                   "montages": "DocumentsLocation", "luts": "DocumentsLocation",
                   "images": "PicturesLocation", "scripts": "DocumentsLocation"}


def dossier_fichiers(genre: str) -> str:
    """Le dernier dossier utilisé pour ce genre de fichiers ; sinon Documents, Vidéos ou Images
    (jamais le dossier du programme)."""
    from PySide6.QtCore import QStandardPaths
    retenu = reglages_interface().value(f"dossiers/{genre}", "") or ""
    if retenu and Path(retenu).is_dir():
        return retenu
    emplacement = getattr(QStandardPaths, DOSSIERS_DEPART.get(genre, "DocumentsLocation"))
    return QStandardPaths.writableLocation(emplacement) or str(Path.home())


def retenir_dossier(genre: str, chemin: str):
    """Après un choix dans une fenêtre de fichiers : son dossier sera proposé la fois suivante."""
    if chemin:
        d = Path(chemin)
        reglages_interface().setValue(f"dossiers/{genre}", str(d if d.is_dir() else d.parent))
