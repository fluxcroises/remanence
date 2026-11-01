"""Emplacements des fichiers de Remanence sur la machine."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


def dossier_donnees() -> Path:
    """%APPDATA%\\Remanence : préréglages, sauvegardes automatiques, journal."""
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
