"""La charte graphique est la seule source des couleurs, et ses contrastes tiennent."""

import os
import re
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from remanence.ui import charte  # noqa: E402

DOSSIER_UI = Path(__file__).parents[1] / "remanence" / "ui"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def luminance(hexa: str) -> float:
    canaux = [int(hexa[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in canaux]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contraste(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_aucune_couleur_codee_en_dur():
    fautes = []
    for f in DOSSIER_UI.glob("*.py"):
        texte = f.read_text(encoding="utf-8")
        for motif in (r"#[0-9a-fA-F]{6}\b", r"#[0-9a-fA-F]{3}\b", r"QColor\(\s*\d", r"rgba?\("):
            fautes += [f"{f.name} : {m}" for m in re.findall(motif, texte)]
    assert not fautes, fautes


@pytest.mark.parametrize("theme", ["dark"])
def test_feuille_de_style_complete(app, theme):
    c = charte.Charte(theme)
    feuille = c.feuille()
    assert c.hex("playhead") == c.hex("accent") and c.hex("focus") == c.hex("accent-2")
    assert c.hex("accent") in feuille and "{ink" not in feuille


# Paires effectivement utilisées par l'interface : (texte, fond, minimum).
PAIRES = [
    ("ink", "surface", 4.5), ("ink", "surface-raised", 4.5), ("ink", "bg-app", 4.5),
    ("ink-muted", "surface", 4.5), ("ink-muted", "surface-raised", 4.5),
    ("ink-muted", "bg-app", 4.5), ("ink-muted", "surface-hover", 4.5),
    ("ink", "clip-video", 4.5), ("ink", "clip-audio", 4.5), ("ink", "accent-soft", 4.5),
    ("accent", "surface", 4.5), ("accent", "accent-soft", 4.5), ("on-accent", "accent", 4.5),
    ("warning", "surface", 4.5), ("danger", "surface", 4.5),
    # En thème clair, success sur surface donne 4,499:1 : il n'est posé que sur surface-raised.
    ("success", "surface-raised", 4.5),
    ("ink-muted", "clip-audio", 3.0), ("accent", "clip-video", 3.0), ("accent", "clip-audio", 3.0),
    ("focus", "surface", 3.0), ("focus", "surface-raised", 3.0),
    ("control-border", "surface", 3.0), ("control-border", "surface-raised", 3.0),
    ("playhead", "surface", 3.0), ("accent-2", "bg-app", 3.0),
]


@pytest.mark.parametrize("theme", ["dark"])
@pytest.mark.parametrize("texte,fond,minimum", PAIRES)
def test_contrastes(theme, texte, fond, minimum):
    c = charte.Charte(theme)
    assert contraste(c.hex(texte), c.hex(fond)) >= minimum


def test_icones_et_polices_presentes(app):
    noms = set()
    for f in DOSSIER_UI.glob("*.py"):
        texte = f.read_text(encoding="utf-8")
        noms |= set(re.findall(r'bouton_icone\(\s*"([a-z0-9-]+)"', texte))
        noms |= set(re.findall(r'poser_icone\(\s*[\w.]+,\s*"([a-z0-9-]+)"', texte))
    # Icônes choisies par une variable (boutons de panneaux, verrou, lecture).
    noms |= {"play", "pause", "lock", "lock-open", "chevron-down", "app-window",
             "sliders-horizontal", "audio-lines"}
    manquantes = [n for n in noms if not (charte.RESSOURCES / "icones" / f"{n}.svg").exists()]
    assert not manquantes, manquantes
    assert {"IBM Plex Sans", "IBM Plex Mono"} <= set(charte.charger_polices())


def test_symbole_dessine(app):
    pm = charte.Charte("dark").symbole(64)
    image = pm.toImage()
    # Tranche d'accent (4e bande) : sa couleur est celle du fichier, donc le mauve de la charte.
    assert image.pixelColor(int(0.62 * image.width()), int(0.64 * image.height())).name() == "#b07cc6"


def test_feuille_lisible_dans_program_files(monkeypatch):
    """Installé dans « C:/Program Files/Flux Croisés/Remanence », la feuille de style doit
    rester lisible par Qt (étape 10 : l'espace du chemin la faisait rejeter en entier)."""
    from pathlib import Path
    from PySide6.QtCore import qInstallMessageHandler
    from PySide6.QtWidgets import QApplication, QComboBox
    from remanence.ui import charte
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(charte, "RESSOURCES",
                        Path("C:/Program Files/Flux Croisés/Remanence/_internal/remanence/ressources"))
    messages = []
    ancien = qInstallMessageHandler(lambda _t, _c, m: messages.append(m))
    try:
        boite = QComboBox()
        boite.setStyleSheet(charte.actuelle().feuille())
        boite.ensurePolished()
    finally:
        qInstallMessageHandler(ancien)
    assert not [m for m in messages if "stylesheet" in m.lower()], messages
