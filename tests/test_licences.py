"""LICENCES.md cite chaque dépendance, et les textes GNU sont dans le projet."""

import re
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
NOMS = {"opencv-contrib-python-headless": "opencv-contrib-python-headless", "av": "PyAV",
        "pyside6": "PySide6", "opentimelineio": "OpenTimelineIO"}


def test_chaque_dependance_est_dans_licences():
    licences = (RACINE / "LICENCES.md").read_text(encoding="utf-8").lower()
    for fichier in ("requirements.txt", "requirements-construction.txt"):
        for ligne in (RACINE / fichier).read_text(encoding="utf-8").splitlines():
            nom = re.split(r"[=<>\[ ]", ligne.strip())[0]
            if not nom:
                continue
            cherche = NOMS.get(nom.lower(), nom).lower()
            assert cherche in licences, f"{nom} manque dans LICENCES.md"


def test_textes_des_licences_gnu():
    dossier = RACINE / "remanence" / "ressources" / "licences"
    for nom, debut in (("gpl-2.0.txt", "GNU GENERAL PUBLIC LICENSE"),
                       ("gpl-3.0.txt", "GNU GENERAL PUBLIC LICENSE"),
                       ("lgpl-2.1.txt", "GNU LESSER GENERAL PUBLIC LICENSE"),
                       ("lgpl-3.0.txt", "GNU LESSER GENERAL PUBLIC LICENSE")):
        assert debut in (dossier / nom).read_text(encoding="utf-8")[:300]
