"""Scripts JavaScript de FFglitch : ceux que Remanence génère, et ceux de la bibliothèque
(fournis, importés par l'utilisateur, écrits dans l'éditeur).

Un script généré commence par `entete` : les valeurs de chaque image (réglages animés), un
hasard reproductible tiré de la graine de l'effet, le numéro de l'image.

Un script de la bibliothèque passe par `adapter` : ses déclarations numériques du haut du
fichier (`var delay = 10;`) deviennent des réglages, `Math.random` suit la graine, et l'ancien
format (scripts de FFglitch 0.9, comme ceux de dd_GlitchAssist : fonctions sans `export`, sans
`setup`) est accepté.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from remanence.config import dossier_donnees

FOURNIS = Path(__file__).resolve().parents[2] / "ressources" / "scripts_ffglitch"

ENTETE = """// Généré par Remanence.
const v = %(valeurs)s;
let __graine = %(graine)d >>> 0;
function hasard() {  // mulberry32 : même graine, même tirage
  __graine = (__graine + 0x6D2B79F5) >>> 0;
  let t = __graine;
  t = Math.imul(t ^ (t >>> 15), t | 1);
  t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
}
let __n = 0;
// Valeur du réglage `cle` à l'image en cours.
function val(cle) {
  const liste = v[cle];
  return liste[Math.min(__n, liste.length - 1)];
}
"""

SETUP = """
export function setup(args) {
  args.features = ["mv"];
}
"""


def entete(valeurs: list[dict], cles, graine: int) -> str:
    """Début d'un script généré ; `glitch_frame` doit finir par `__n++`."""
    colonnes = {cle: [round(v[cle], 3) for v in valeurs] for cle in cles}
    return ENTETE % {"valeurs": json.dumps(colonnes), "graine": graine} + SETUP


# Scripts de la bibliothèque

_DECLARATION = re.compile(r"^(let|var|const)[ \t]+([A-Za-z_]\w*)[ \t]*=[ \t]*(-?\d+(?:\.\d+)?)"
                          r"[ \t]*;", re.M)


def reglages(texte: str) -> dict[str, float]:
    """Déclarations numériques du haut du script jamais réaffectées ensuite : les réglages.
    Les compteurs (`var frameCount = 0;` puis `frameCount++`) n'en sont pas."""
    trouves = {}
    for m in _DECLARATION.finditer(texte):
        nom = m.group(2)
        affectations = re.findall(rf"\b{nom}\s*(?:=(?!=)|\+=|-=|\*=|/=|\+\+|--)", texte)
        if len(affectations) == 1 and nom not in trouves:
            trouves[nom] = float(m.group(3))
    return trouves


def adapter(texte: str, valeurs: dict[str, float], graine: int) -> str:
    """Le script prêt pour ffedit : réglages remplacés, hasard reproductible, `setup` et
    `glitch_frame` exportés par Remanence (vecteurs de mouvement par défaut, débordements
    tronqués)."""
    def remplacer(m):
        nom = m.group(2)
        if nom not in valeurs:
            return m.group(0)
        v = valeurs[nom]
        nombre = str(int(v)) if float(v).is_integer() else repr(float(v))
        return f"{m.group(1)} {nom} = {nombre};"
    corps = _DECLARATION.sub(remplacer, texte)
    corps = re.sub(r"\bexport\s+(?=function\s+(glitch_frame|setup)\b)", "", corps)
    corps = re.sub(r"\bfunction\s+glitch_frame\s*\(", "function __glitch_frame(", corps)
    corps = re.sub(r"\bfunction\s+setup\s*\(", "function __setup(", corps)
    return (ENTETE % {"valeurs": "{}", "graine": graine}
            + "Math.random = hasard;\n\n" + corps + """

export function setup(args) {
  args.features = ["mv"];
  if (typeof __setup === "function")
    __setup(args);
}

export function glitch_frame(frame, stream) {
  if (frame.mv)
    frame.mv.overflow = "truncate";
  const r = __glitch_frame(frame, stream);
  __n++;
  return r;
}
""")


def dossier_importes() -> Path:
    return dossier_donnees() / "scripts_ffglitch"


def nom_de(chemin: Path) -> str:
    return chemin.stem.replace("_", " ").replace("-", " ").strip()


def bibliotheque() -> dict[str, tuple[str, bool]]:
    """Nom -> (texte, fourni). Les scripts importés suivent les fournis."""
    resultat = {}
    for dossier, fourni in ((FOURNIS, True), (dossier_importes(), False)):
        for f in sorted(dossier.glob("*.js")) if dossier.is_dir() else []:
            try:
                resultat.setdefault(nom_de(f), (f.read_text(encoding="utf-8",
                                                             errors="replace"), fourni))
            except OSError:
                continue
    return resultat


def importer(source: Path) -> int:
    """Copie les scripts .js d'un dossier (et de ses sous-dossiers) dans la bibliothèque."""
    cible = dossier_importes()
    cible.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in sorted(Path(source).rglob("*.js")):
        shutil.copyfile(f, cible / f.name)
        n += 1
    return n


def enregistrer(nom: str, texte: str) -> Path:
    cible = dossier_importes()
    cible.mkdir(parents=True, exist_ok=True)
    propre = re.sub(r"[^\w\- ]", "", nom).strip() or "script"
    chemin = cible / f"{propre}.js"
    chemin.write_text(texte, encoding="utf-8")
    return chemin
