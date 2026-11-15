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
from dataclasses import dataclass, field
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
  // Le fichier de sortie est celui de Remanence, même si le script en choisit un autre.
  const __sortie = args.output;
  if (typeof __setup === "function")
    __setup(args);
  if (__sortie === undefined)
    delete args.output;
  else
    args.output = __sortie;
}

export function glitch_frame(frame, stream) {
  if (frame.mv)
    frame.mv.overflow = "truncate";
  // Un script sans glitch_frame (vide, ou qui ne fait que setup) laisse l'image passer.
  const r = typeof __glitch_frame === "function" ? __glitch_frame(frame, stream) : undefined;
  __n++;
  return r;
}
""")


def dossier_importes() -> Path:
    return dossier_donnees() / "scripts_ffglitch"


def nom_de(chemin: Path) -> str:
    return chemin.stem.replace("_", " ").replace("-", " ").strip()


# Ce que FFglitch sait modifier dans une vidéo MPEG-4 (`ffedit -i fichier.avi`) : un script qui
# demande autre chose (dqt, idat…) est fait pour des images JPEG ou PNG.
FEATURES_MPEG4 = {"info", "mv", "mv_delta", "mb", "gmc"}

_IMPORT = re.compile(r"^[ \t]*import\s+(?P<quoi>[^;]*?)\s+from\s+['\"](?P<module>[^'\"]+)['\"]"
                     r"[ \t]*;?[ \t]*$", re.M | re.S)
_FEATURES = re.compile(r"\bargs\.features\s*=\s*\[([^\]]*)\]")


_ENTREES_DIRECTES = re.compile(r"\bnew\s+SDL\s*\(|\bSDL\.SDL_|\bSDLInput\b")


def direct_seulement(texte: str) -> bool:
    """Le script lit un contrôleur MIDI, le clavier, une manette ou un autre programme
    (modules rtmidi et zmq, événements SDL de fflive) : il ne se lit qu'en direct. Dans un
    calcul pour la timeline, il attendrait ses commandes sans fin."""
    return any(not m.group("module").startswith(".") for m in _IMPORT.finditer(texte)) \
        or bool(_ENTREES_DIRECTES.search(texte))


def regrouper(texte: str, dossier: Path, vus: set | None = None) -> str:
    """Le script avec les modules voisins qu'il importe (`import {…} from "./helpers.mjs"`)
    recopiés dedans, sans leurs `export` : la bibliothèque garde un seul fichier, que
    Remanence peut lancer de n'importe où. Les modules de fflive (rtmidi, zmq) restent."""
    vus = set() if vus is None else vus

    def remplacer(m: re.Match) -> str:
        module = m.group("module")
        if not module.startswith("."):
            return m.group(0)
        chemin = (dossier / module).resolve()
        if chemin in vus:
            return ""
        vus.add(chemin)
        try:
            contenu = chemin.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return m.group(0)
        contenu = regrouper(contenu, chemin.parent, vus)
        contenu = re.sub(r"^([ \t]*)export\s+(?:default\s+)?", r"\1", contenu, flags=re.M)
        quoi = m.group("quoi").strip()
        espace = re.match(r"\*\s+as\s+(\w+)", quoi)
        if espace:
            # `import * as nom from …` : les fonctions du module, rangées sous `nom`.
            noms = re.findall(r"^(?:function|class|const|let|var)\s+(\w+)", contenu, re.M)
            return (f"// {module}\nconst {espace.group(1)} = (function () {{\n{contenu}\n"
                    f"return {{ {', '.join(noms)} }};\n}})();\n")
        return f"// {module}\n{contenu}\n"
    return _IMPORT.sub(remplacer, texte)


def pour_la_video(texte: str) -> bool:
    """Le script modifie ce que FFglitch sait modifier dans une vidéo MPEG-4."""
    m = _FEATURES.search(texte)
    if m is None:
        return True  # sans choix : Remanence demande les vecteurs de mouvement
    demandees = set(re.findall(r"['\"](\w+)['\"]", m.group(1)))
    return not demandees or demandees <= FEATURES_MPEG4


@dataclass
class Script:
    nom: str
    texte: str
    fourni: bool
    groupe: str = ""   # dossier d'origine, « instant damage » par exemple
    direct: bool = False


def scripts_de_la_bibliotheque() -> list[Script]:
    """Les scripts fournis puis importés (en gardant les dossiers d'origine). Deux scripts de
    même nom dans deux dossiers : le second prend le nom de son dossier entre parenthèses."""
    resultat: list[Script] = []
    noms: set[str] = set()
    for dossier, fourni in ((FOURNIS, True), (dossier_importes(), False)):
        for f in sorted(dossier.rglob("*.js")) if dossier.is_dir() else []:
            try:
                texte = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            groupe = nom_de(f.parent) if f.parent != dossier else ""
            nom = nom_de(f)
            if nom in noms:
                nom = f"{nom} ({groupe})" if groupe else nom
            if nom in noms:
                continue
            noms.add(nom)
            resultat.append(Script(nom, texte, fourni, groupe, direct_seulement(texte)))
    return resultat


def bibliotheque() -> dict[str, tuple[str, bool]]:
    """Nom -> (texte, fourni). Les scripts importés suivent les fournis."""
    return {s.nom: (s.texte, s.fourni) for s in scripts_de_la_bibliotheque()}


def _dossiers_ou_chercher() -> list[Path]:
    import os
    maison = Path.home()
    bases = [maison / "Downloads", maison / "Téléchargements", maison / "Desktop",
             maison / "Bureau", maison / "Documents", maison]
    for variable in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
        if os.environ.get(variable):
            bases.append(Path(os.environ[variable]) / ("Programs" if variable == "LOCALAPPDATA"
                                                       else ""))
    return [b for b in bases if b.is_dir()]


def trouver_live_mosher(bases: list[Path] | None = None) -> Path | None:
    """Le dossier des scripts de Live Mosher (son dossier « Examples ») s'il est dans un
    endroit habituel : un dossier dont le nom contient « LiveMosher », jusqu'à deux niveaux
    sous Téléchargements, le Bureau, Documents ou les dossiers des programmes."""
    for base in _dossiers_ou_chercher() if bases is None else bases:
        candidats = []
        for profondeur in ("*", "*/*"):
            try:
                candidats += [d for d in base.glob(profondeur)
                              if d.is_dir() and "livemosher" in d.name.lower().replace(" ", "")
                              .replace("-", "").replace("_", "")]
            except OSError:
                continue
        for d in candidats:
            for exemples in [d / "Examples", *d.glob("*/Examples"), *d.glob("*/*/Examples")]:
                if exemples.is_dir() and any(exemples.rglob("*.js")):
                    return exemples
    return None


@dataclass
class BilanImport:
    importes: int = 0
    direct: int = 0                       # importés, à lire en direct seulement
    ignores: list[tuple[str, str]] = field(default_factory=list)  # (fichier, raison)


def importer(source: Path) -> BilanImport:
    """Les scripts .js d'un dossier et de ses sous-dossiers (par exemple les exemples de Live
    Mosher ou dd_GlitchAssist) dans la bibliothèque, rangés dans les mêmes dossiers. Les
    modules voisins qu'ils importent y sont recopiés ; les modules d'aide seuls et les
    scripts pour images (JPEG, PNG) sont écartés."""
    source = Path(source)
    cible = dossier_importes() / source.name
    bilan = BilanImport()
    for f in sorted(source.rglob("*.js")):
        texte = regrouper(f.read_text(encoding="utf-8", errors="replace"), f.parent)
        relatif = f.relative_to(source)
        if not re.search(r"\bfunction\s+glitch_frame\b", texte):
            # Module d'aide, ou crochet d'un autre outil de FFglitch (filtre de fflive,
            # choix de l'encodeur ffgac) : rien à poser sur un clip.
            autre = re.search(r"^\s*export\s+function\s+(?!setup\b)\w+", texte, re.M)
            bilan.ignores.append((str(relatif), "autre usage" if autre else "module d'aide"))
            continue
        if not pour_la_video(texte):
            bilan.ignores.append((str(relatif), "pour les images"))
            continue
        if any(m.group("module").startswith(".") for m in _IMPORT.finditer(texte)):
            # Un module voisin manque : le script échouerait sur la timeline.
            bilan.ignores.append((str(relatif), "fichier voisin introuvable"))
            continue
        destination = cible / relatif
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(texte, encoding="utf-8")
        bilan.importes += 1
        bilan.direct += direct_seulement(texte)
    return bilan


def enregistrer(nom: str, texte: str) -> Path:
    cible = dossier_importes()
    cible.mkdir(parents=True, exist_ok=True)
    propre = re.sub(r"[^\w\- ]", "", nom).strip() or "script"
    chemin = cible / f"{propre}.js"
    chemin.write_text(texte, encoding="utf-8")
    return chemin
