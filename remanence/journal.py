"""Journal de Remanence : %APPDATA%\\Remanence\\journal\\remanence.log.

Il garde ce qu'il faut pour comprendre une erreur à distance : en tête de chaque séance, les
versions (Remanence, Python, Windows, Qt, FFmpeg, carte graphique) ; puis les actions validées
et les tâches de fond (l'opération en cours) ; enfin chaque erreur avec sa pile d'appels, d'où
qu'elle vienne (fenêtre, fil de calcul, message de Qt). Un plantage brutal (pilote graphique,
bibliothèque C) est écrit par faulthandler dans plantage.log, à côté.

Le fichier tourne : 1 Mo, cinq anciens gardés.
"""

from __future__ import annotations

import contextlib
import datetime
import faulthandler
import logging
import logging.handlers
import platform
import sys
import threading
import traceback
from pathlib import Path

from remanence.config import dossier_donnees

_journal = logging.getLogger("remanence")
# Sans demarrer() (tests, scripts), le journal se tait au lieu d'écrire sur la console.
_journal.addHandler(logging.NullHandler())
_local = threading.local()
_plantage = None


def dossier() -> Path:
    d = dossier_donnees() / "journal"
    d.mkdir(parents=True, exist_ok=True)
    return d


def fichier() -> Path:
    return dossier() / "remanence.log"


def demarrer(versions: dict[str, str] | None = None):
    """Ouvre le journal et branche les crochets d'erreurs (une fois par séance)."""
    global _plantage
    if any(isinstance(h, logging.handlers.RotatingFileHandler) for h in _journal.handlers):
        return
    try:
        sortie = logging.handlers.RotatingFileHandler(fichier(), maxBytes=1_000_000,
                                                      backupCount=5, encoding="utf-8")
    except OSError:
        return  # dossier en lecture seule : Remanence marche sans journal
    sortie.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(threadName)s] "
                                          "%(message)s", "%Y-%m-%d %H:%M:%S"))
    _journal.addHandler(sortie)
    _journal.setLevel(logging.INFO)
    _journal.propagate = False
    try:
        _plantage = open(dossier() / "plantage.log", "a", encoding="utf-8")
        _plantage.write(f"\n--- séance du {datetime.datetime.now():%Y-%m-%d %H:%M:%S} ---\n")
        _plantage.flush()
        faulthandler.enable(_plantage)
    except OSError:
        _plantage = None
    entete = {"Python": sys.version.split()[0], "Système": platform.platform()}
    entete.update(versions or {})
    _journal.info("Séance ouverte · " + " · ".join(f"{k} {v}" for k, v in entete.items()))
    threading.excepthook = _erreur_fil
    _brancher_qt()


def info(message: str):
    _journal.info(message)


def avertissement(message: str):
    _journal.warning(message)


def erreur(titre: str, message: str = "", detail: str = ""):
    operation = getattr(_local, "operation", None)
    ligne = titre + (f" : {message}" if message else "")
    if operation:
        ligne += f" (pendant : {operation})"
    _journal.error(ligne + (f"\n{detail.rstrip()}" if detail else ""))


def exception(titre: str, type_, valeur, tb):
    erreur(titre, str(valeur), "".join(traceback.format_exception(type_, valeur, tb)))


@contextlib.contextmanager
def operation(nom: str):
    """L'opération en cours dans ce fil, rappelée par chaque erreur qui y survient."""
    avant = getattr(_local, "operation", None)
    _local.operation = nom
    try:
        yield
    finally:
        _local.operation = avant


def _erreur_fil(args):
    if args.exc_type is SystemExit:
        return
    exception(f"Erreur dans le fil {args.thread.name if args.thread else '?'}",
              args.exc_type, args.exc_value, args.exc_traceback)


def _brancher_qt():
    """Les avertissements et erreurs de Qt (OpenGL, polices, fichiers) vont au journal."""
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except ImportError:
        return
    niveaux = {QtMsgType.QtWarningMsg: logging.WARNING, QtMsgType.QtCriticalMsg: logging.ERROR,
               QtMsgType.QtFatalMsg: logging.CRITICAL}

    deja: set[str] = set()

    def relais(type_, _contexte, message):
        # Une fois par séance : sans OpenGL, Qt répète le même avertissement à chaque dessin.
        niveau = niveaux.get(type_)
        if niveau is not None and message not in deja:
            deja.add(message)
            _journal.log(niveau, f"Qt : {message}")
    qInstallMessageHandler(relais)


def dernieres_lignes(n: int = 200) -> str:
    try:
        return "\n".join(fichier().read_text(encoding="utf-8").splitlines()[-n:])
    except OSError:
        return ""
