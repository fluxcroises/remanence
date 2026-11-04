"""Téléchargement de FFglitch : par Installer.bat dans outils/ffglitch du projet, ou depuis
Remanence (proposé au premier lancement, Aide > Installer FFglitch), à côté du programme.

L'archive est vérifiée par son empreinte SHA-256 avant d'être ouverte : un fichier différent
de celui attendu est refusé. Sans FFglitch, Remanence se sert du moteur Bavure.

    .venv\\Scripts\\python.exe -m remanence.moteurs.codec.installation
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
import zipfile
from pathlib import Path

from remanence.moteurs.codec import ffglitch

VERSION = "0.10.2"
ADRESSE = f"https://ffglitch.org/pub/bin/win64/ffglitch-{VERSION}-windows-x86_64.zip"
SHA256 = "e5190462eafe9c28428d39f8392a6be93dfd6ac2d59ce08848edec79acf965ca"


class EmpreinteFausse(RuntimeError):
    pass


def _dossier_inscriptible() -> Path:
    """Le premier dossier d'outils où l'on peut écrire."""
    for d in ffglitch.dossiers_outils():
        try:
            d.mkdir(parents=True, exist_ok=True)
            essai = d / ".essai"
            essai.write_bytes(b"")
            essai.unlink()
            return d
        except OSError:
            continue
    raise OSError("Aucun dossier où installer FFglitch.")


def installer(progression=None, annule=None) -> bool:
    """Télécharge, vérifie et décompresse FFglitch ; True s'il est prêt. progression(0 à 1) suit
    le téléchargement ; annule (threading.Event) l'arrête."""
    if ffglitch.disponible():
        return True
    dossier = _dossier_inscriptible()
    archive = dossier.parent / f"ffglitch-{VERSION}-windows-x86_64.zip"
    if not archive.exists():
        partiel = archive.with_suffix(".partiel")

        def suivi(blocs, taille_bloc, total):
            if annule is not None and annule.is_set():
                raise InterruptedError
            if progression and total > 0:
                progression(min(1.0, blocs * taille_bloc / total))
        urllib.request.urlretrieve(ADRESSE, partiel, suivi)
        partiel.replace(archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        archive.unlink()
        raise EmpreinteFausse("Le fichier téléchargé n'est pas celui attendu.")
    with zipfile.ZipFile(archive) as z:
        z.extractall(dossier)
    archive.unlink()
    return ffglitch.disponible()


if __name__ == "__main__":
    if ffglitch.disponible():
        print(f"FFglitch {VERSION} déjà installé.")
        sys.exit(0)
    print(f"Téléchargement de FFglitch {VERSION}...")
    try:
        ok = installer()
    except EmpreinteFausse:
        print("FFglitch refusé : le fichier téléchargé n'est pas celui attendu.")
        ok = False
    except OSError as e:
        print(f"Téléchargement de FFglitch impossible : {e}")
        ok = False
    print(f"FFglitch {VERSION} installé." if ok else "Remanence fonctionnera avec son moteur Bavure.")
    sys.exit(0)
