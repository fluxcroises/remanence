"""Modèles de nommage des exports, par exemple `{plan}_remanence_v{version}`.

Variables : {plan} (le média du plan exporté), {sequence}, {projet}, {date} (AAAA-MM-JJ),
{format} et {version}, le premier numéro libre sur deux chiffres (01, 02…) dans le dossier.
Une variable inconnue reste écrite telle quelle ; les caractères interdits par Windows dans un
nom de fichier sont remplacés par « _ ».
"""

from __future__ import annotations

import re
import time
from pathlib import Path

MODELE_DEFAUT = "{plan}_remanence_v{version}"
VARIABLES = ("plan", "sequence", "projet", "version", "date", "format")
INTERDITS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class _Valeurs(dict):
    def __missing__(self, cle):
        return "{" + cle + "}"


def remplir(modele: str, valeurs: dict, version: int = 1) -> str:
    v = _Valeurs({k: INTERDITS.sub("_", str(x)) for k, x in valeurs.items()})
    v.setdefault("date", time.strftime("%Y-%m-%d"))
    v["version"] = f"{version:02d}"
    try:
        nom = modele.format_map(v)
    except (ValueError, IndexError):
        nom = modele  # accolade isolée : le modèle tel quel
    return INTERDITS.sub("_", nom).strip(" .") or "export"


def nommer(modele: str, valeurs: dict, dossier: Path, extension: str,
           reserves: set[Path] | frozenset = frozenset()) -> Path:
    """Chemin du fichier : la première version libre (ni sur le disque, ni réservée par un
    export en attente)."""
    dossier = Path(dossier)
    for version in range(1, 1000):
        chemin = dossier / (remplir(modele, valeurs, version) + extension)
        if not chemin.exists() and chemin not in reserves:
            return chemin
        if "{version}" not in modele:
            return chemin  # sans numéro de version, le fichier existant est remplacé
    return chemin
