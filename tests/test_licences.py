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


def test_guide():
    """Le guide se refait sans captures ; chaque chapitre et chaque image y sont."""
    import subprocess
    import sys
    subprocess.run([sys.executable, str(RACINE / "scripts" / "guide.py"), "--sans-captures"],
                   check=True, capture_output=True)
    guide = RACINE / "remanence" / "ressources" / "guide"
    texte = (guide / "index.html").read_text(encoding="utf-8")
    for ancre in ("00-bienvenue", "01-ecran", "aide-01-monter", "catalogue", "raccourcis",
                  "90-depannage"):
        assert f'id="{ancre}"' in texte, ancre
    images = re.findall(r'src="([^"]+)"', texte)
    assert len(images) > 30 and all((guide / s).resolve().exists() for s in images)
    assert "{NB}" not in texte and "Ctrl+Z" in texte


def test_version_et_notes():
    """Étape 10, lot 1 : version 1.0.0 sur trois nombres (propriétés du programme), notes
    de version de cette version, dans un onglet d'À propos."""
    from PySide6.QtWidgets import QApplication
    from remanence import __version__
    from remanence.ui.apropos import APropos
    QApplication.instance() or QApplication([])
    from remanence.ui.charte import RACINE
    assert [int(x) for x in __version__.split(".")] == [1, 0, 0]
    notes = (RACINE / "NOTES_DE_VERSION.md").read_text(encoding="utf-8")
    assert f"## Remanence {__version__}" in notes and "—" not in notes
    fenetre = APropos()
    assert [fenetre.onglets.tabText(i) for i in range(fenetre.onglets.count())] ==         ["Notes de version", "Licences"]
    assert "Limites connues" in fenetre.onglets.widget(0).toPlainText()


def test_installateur():
    """Étape 10, lot 2 : réglages essentiels de l'installateur Inno Setup."""
    from remanence.ui.charte import RACINE
    iss = (RACINE / "Remanence.iss").read_text(encoding="utf-8-sig")
    for attendu in ("PrivilegesRequired=admin", "PrivilegesRequiredOverridesAllowed=dialog",
                    r"DefaultDirName={autopf}\Flux Croisés\Remanence",
                    r'Name: "{localappdata}\Remanence\outils"',
                    r'Excludes: "\outils"', r"Software\Classes\.remanence",
                    r'""{app}\Remanence.exe"" ""%1""', "ChangesAssociations=yes",
                    "AppId={{F0F6C70C-6D7E-48AC-AFDE-D030DD36D9D4}",
                    r'Name: "{app}\outils"', "French.isl"):
        assert attendu in iss, attendu
    bat = (RACINE / "Construire.bat").read_text(encoding="utf-8")
    assert "Remanence.iss" in bat and "images_installateur.py" in bat
