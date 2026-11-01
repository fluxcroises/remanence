"""Téléchargement de FFglitch par Installer.bat, dans outils/ffglitch du projet.

L'archive est vérifiée par son empreinte SHA-256 avant d'être ouverte : un fichier différent
de celui attendu est refusé. Sans FFglitch, Remanence se sert du moteur Bavure.

    .venv\\Scripts\\python.exe -m remanence.moteurs.codec.installation
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
import zipfile

from remanence.moteurs.codec import ffglitch

VERSION = "0.10.2"
ADRESSE = f"https://ffglitch.org/pub/bin/win64/ffglitch-{VERSION}-windows-x86_64.zip"
SHA256 = "e5190462eafe9c28428d39f8392a6be93dfd6ac2d59ce08848edec79acf965ca"


def installer() -> bool:
    if ffglitch.disponible():
        print(f"FFglitch {VERSION} déjà installé.")
        return True
    ffglitch.DOSSIER_OUTILS.mkdir(parents=True, exist_ok=True)
    archive = ffglitch.DOSSIER_OUTILS.parent / f"ffglitch-{VERSION}-windows-x86_64.zip"
    if not archive.exists():
        print(f"Téléchargement de FFglitch {VERSION}...")
        partiel = archive.with_suffix(".partiel")
        urllib.request.urlretrieve(ADRESSE, partiel)
        partiel.replace(archive)
    empreinte = hashlib.sha256(archive.read_bytes()).hexdigest()
    if empreinte != SHA256:
        archive.unlink()
        print("FFglitch refusé : le fichier téléchargé n'est pas celui attendu.")
        return False
    with zipfile.ZipFile(archive) as z:
        z.extractall(ffglitch.DOSSIER_OUTILS)
    print(f"FFglitch {VERSION} installé.")
    return ffglitch.disponible()


if __name__ == "__main__":
    try:
        ok = installer()
    except OSError as e:
        print(f"Téléchargement de FFglitch impossible : {e}")
        ok = False
    if not ok:
        print("Remanence fonctionnera avec son moteur Bavure.")
    sys.exit(0)
