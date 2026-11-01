"""Moteur FFglitch : deux programmes externes, téléchargés à l'installation.

- ffgac encode les images en MPEG-4 Part 2 sans macroblocs intra dans les images P
  (`+nopimb`) et avec un vecteur pour chaque macrobloc (`+forcemv`) : tout le contenu d'une
  image P vient du mouvement, la bavure est franche et chaque vecteur se modifie.
- ffedit réécrit les vecteurs du flux, par un script JavaScript (généré par Remanence à partir
  des réglages de l'effet) ou par un fichier JSON (transfert de mouvement).

Les paquets obtenus sont ceux de Bavure (mêmes images I et P) : les manipulations de
`bavure.py` et son décodeur s'appliquent tels quels. Sans FFglitch, Bavure encode seul.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
from fractions import Fraction
from pathlib import Path
from typing import Iterable

import av
import numpy as np

RACINE = Path(__file__).resolve().parents[3]
DOSSIER_OUTILS = RACINE / "outils" / "ffglitch"

# Les tests forcent l'absence de FFglitch (moteur de secours) en posant cette variable à "".
VARIABLE = "REMANENCE_FFGLITCH"

_SANS_FENETRE = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def dossier() -> Path | None:
    """Le dossier qui contient ffgac.exe et ffedit.exe ; None si FFglitch n'est pas installé."""
    force = os.environ.get(VARIABLE)
    if force is not None:
        candidats = [Path(force)] if force else []
    else:
        candidats = sorted(DOSSIER_OUTILS.glob("ffglitch-*"), reverse=True)
    for d in candidats:
        if (d / "ffgac.exe").exists() and (d / "ffedit.exe").exists():
            return d
    return None


def disponible() -> bool:
    return dossier() is not None


def _outils(outils: Path | None) -> Path:
    outils = outils or dossier()
    if outils is None:
        raise RuntimeError("FFglitch n'est pas installé.")
    return outils


def _lancer(arguments: list[str], entree=None, annule: threading.Event | None = None):
    """Lance un programme FFglitch ; les images arrivent par l'entrée standard si `entree`
    (itérable d'octets) est donné. Une erreur du programme lève RuntimeError."""
    with tempfile.TemporaryFile() as journal:
        p = subprocess.Popen(arguments,
                             stdin=subprocess.PIPE if entree is not None else subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=journal,
                             creationflags=_SANS_FENETRE)
        try:
            if entree is not None:
                try:
                    for bloc in entree:
                        if annule is not None and annule.is_set():
                            raise InterruptedError
                        p.stdin.write(bloc)
                finally:
                    try:
                        p.stdin.close()
                    except OSError:
                        pass
            code = p.wait()
        except BaseException:
            p.kill()
            p.wait()
            raise
        if code != 0:
            journal.seek(0)
            fin = journal.read().decode("utf-8", "replace").strip().splitlines()[-3:]
            raise RuntimeError(f"{Path(arguments[0]).stem} : " + " ".join(fin))


def encoder(images: Iterable[av.VideoFrame], largeur: int, hauteur: int, cadence: Fraction,
            blocs: int, cles: set[int], sortie: Path, progression=None, n: int = 0,
            annule: threading.Event | None = None, outils: Path | None = None) -> Path:
    """Encode les images avec ffgac. Images clés : la première et les indices de `cles`,
    nulle part ailleurs (pas de détection de plan : les coupes sont connues d'avance)."""
    q = max(1, min(31, int(round(blocs))))
    arguments = [str(_outils(outils) / "ffgac.exe"), "-hide_banner", "-loglevel", "error", "-y",
                 "-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", f"{largeur}x{hauteur}",
                 "-r", f"{cadence.numerator}/{cadence.denominator}", "-i", "-",
                 "-vcodec", "mpeg4", "-mpv_flags", "+nopimb+forcemv", "-qscale:v", str(q),
                 "-fcode", "6", "-g", "max", "-sc_threshold", "max"]
    forcees = sorted(i for i in cles if i > 0)
    if forcees:
        arguments += ["-force_key_frames",
                      "expr:" + "+".join(f"eq(n,{i})" for i in forcees)]
    arguments += ["-f", "avi", str(sortie)]

    def octets():
        for i, image in enumerate(images):
            image = image.reformat(width=largeur, height=hauteur, format="yuv420p")
            yield b"".join(bytes(plan) if plan.line_size == plan.width else
                           _plan_serre(plan) for plan in image.planes)
            if progression and n:
                progression((i + 1) / n)

    _lancer(arguments, octets(), annule)
    return sortie


def _plan_serre(plan) -> bytes:
    """Lignes d'un plan sans le remplissage de fin de ligne."""
    brut = np.frombuffer(bytes(plan), np.uint8).reshape(-1, plan.line_size)
    return brut[:plan.height, :plan.width].tobytes()


def paquets(fichier: Path) -> list[bytes]:
    with av.open(str(fichier)) as c:
        flux = c.streams.video[0]
        return [bytes(p) for p in c.demux(flux) if p.size]


def appliquer_script(fichier: Path, script: str, sortie: Path,
                     annule: threading.Event | None = None, outils: Path | None = None) -> Path:
    """Passe le flux dans ffedit avec un script JavaScript."""
    js = sortie.with_suffix(".js")
    js.write_text(script, encoding="utf-8")
    _lancer([str(_outils(outils) / "ffedit.exe"), "-hide_banner", "-loglevel", "error", "-y",
             "-i", str(fichier), "-s", str(js), "-o", str(sortie)], annule=annule)
    return sortie


def vecteurs(fichier: Path, outils: Path | None = None) -> list[np.ndarray | None]:
    """Vecteurs de mouvement de chaque image : tableau (lignes, colonnes, 2), None pour une
    image clé."""
    sortie = fichier.with_suffix(".mv.json")
    _lancer([str(_outils(outils) / "ffedit.exe"), "-hide_banner", "-loglevel", "error", "-y",
             "-i", str(fichier), "-f", "mv", "-e", str(sortie)])
    images = json.loads(sortie.read_text())["streams"][0]["frames"]
    return [_tableau(f["mv"].get("forward")) for f in images]


def _tableau(lignes) -> np.ndarray | None:
    if not lignes:
        return None
    return np.array([[v if v else (0, 0) for v in ligne] for ligne in lignes], np.int32)


def transferer(fichier: Path, source: Path, forces: list[float], sortie: Path,
               annule: threading.Event | None = None, outils: Path | None = None) -> Path:
    """Transfert de mouvement : les vecteurs de `source` (même taille d'image) remplacent ceux
    du flux, mélangés selon la force de chaque image (0 : les siens, 1 : ceux de la source)."""
    outils = _outils(outils)
    donnees_json = fichier.with_suffix(".mv.json")
    _lancer([str(outils / "ffedit.exe"), "-hide_banner", "-loglevel", "error", "-y",
             "-i", str(fichier), "-f", "mv", "-e", str(donnees_json)])
    donnees = json.loads(donnees_json.read_text())
    autres = vecteurs(source, outils)
    for i, image in enumerate(donnees["streams"][0]["frames"]):
        if annule is not None and annule.is_set():
            raise InterruptedError
        propres = _tableau(image["mv"].get("forward"))
        autre = autres[min(i, len(autres) - 1)] if autres else None
        if propres is None or autre is None or autre.shape != propres.shape:
            continue
        force = forces[min(i, len(forces) - 1)]
        melange = np.rint(propres * (1 - force) + autre * force).astype(np.int32)
        image["mv"]["forward"] = melange.tolist()
    donnees_json.write_text(json.dumps(donnees))
    _lancer([str(outils / "ffedit.exe"), "-hide_banner", "-loglevel", "error", "-y",
             "-i", str(fichier), "-f", "mv", "-a", str(donnees_json), "-o", str(sortie)],
            annule=annule)
    return sortie


def dossier_travail(parent: Path) -> tempfile.TemporaryDirectory:
    parent.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(prefix="ffglitch_", dir=parent)
