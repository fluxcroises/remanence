"""Fichiers .remanence (JSON), versions numérotées et enregistrement automatique."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from remanence.config import dossier_donnees
from remanence.media.sonde import MediaIllisible, analyser
from remanence.projet.modele import Projet

EXTENSION = ".remanence"


def dossier_versions(chemin: Path) -> Path:
    return chemin.with_name(chemin.stem + "_versions")


def chemin_auto(chemin: Path | None) -> Path:
    if chemin is None:
        return dossier_donnees() / "sauvegarde_auto" / ("sans_titre" + EXTENSION)
    return chemin.with_name(chemin.stem + ".auto" + EXTENSION)


def _ecrire(projet: Projet, chemin: Path):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    temporaire = chemin.with_suffix(chemin.suffix + ".tmp")
    temporaire.write_text(json.dumps(projet.vers_dict(), ensure_ascii=False, indent=1),
                          encoding="utf-8")
    os.replace(temporaire, chemin)


def enregistrer(projet: Projet, chemin: Path) -> Path:
    """Écrit le projet et en garde une copie numérotée. Renvoie le chemin de la version."""
    chemin = Path(chemin)
    if chemin.suffix != EXTENSION:
        chemin = chemin.with_suffix(EXTENSION)
    _ecrire(projet, chemin)
    versions = dossier_versions(chemin)
    versions.mkdir(exist_ok=True)
    numeros = [int(m.group(1)) for f in versions.iterdir()
               if (m := re.search(r"_v(\d+)" + re.escape(EXTENSION) + "$", f.name))]
    version = versions / f"{chemin.stem}_v{max(numeros, default=0) + 1:03d}{EXTENSION}"
    _ecrire(projet, version)
    chemin_auto(chemin).unlink(missing_ok=True)
    return version


def enregistrer_auto(projet: Projet, chemin: Path | None) -> Path:
    cible = chemin_auto(chemin)
    _ecrire(projet, cible)
    return cible


def ouvrir(chemin: Path) -> Projet:
    """Charge un projet et réanalyse ses médias ; les fichiers absents passent hors ligne."""
    try:
        donnees = json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"Impossible de lire « {Path(chemin).name} » : {e}") from e
    projet = Projet.depuis_dict(donnees)
    for media in projet.medias.values():
        try:
            infos, _ = analyser(media.chemin)
            media.infos = infos
            media.hors_ligne = False
        except MediaIllisible:
            media.hors_ligne = True
    return projet


def sauvegarde_auto_plus_recente(chemin: Path) -> Path | None:
    auto = chemin_auto(chemin)
    if auto.exists() and auto.stat().st_mtime > Path(chemin).stat().st_mtime:
        return auto
    return None
