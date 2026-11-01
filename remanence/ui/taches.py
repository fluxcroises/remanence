"""Calculs longs en arrière-plan, avec progression et annulation, affichés dans la barre d'état."""

from __future__ import annotations

import threading
import traceback

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QWidget


class _Signaux(QObject):
    progression = Signal(float)
    fini = Signal(object)
    erreur = Signal(str, str)
    annulee = Signal()


class Tache(QRunnable):
    """Exécute fonction(progression, annule) dans un fil séparé."""

    def __init__(self, libelle: str, fonction):
        super().__init__()
        self.libelle = libelle
        self.fonction = fonction
        self.annule = threading.Event()
        self.signaux = _Signaux()
        self.avancement = 0.0
        self.setAutoDelete(False)

    def run(self):
        try:
            resultat = self.fonction(self._progresser, self.annule)
        except InterruptedError:
            self.signaux.annulee.emit()
        except Exception as e:
            self.signaux.erreur.emit(str(e), traceback.format_exc())
        else:
            if self.annule.is_set():
                self.signaux.annulee.emit()
            else:
                self.signaux.fini.emit(resultat)

    def _progresser(self, valeur: float):
        self.avancement = valeur
        self.signaux.progression.emit(valeur)


class GestionnaireTaches(QWidget):
    """Zone de la barre d'état : tâche en cours, progression, bouton Annuler."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._taches: list[Tache] = []
        self._pool = QThreadPool.globalInstance()
        self._pool.setMaxThreadCount(max(2, self._pool.maxThreadCount() // 2))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._libelle = QLabel()
        self._barre = QProgressBar()
        self._barre.setFixedWidth(160)
        self._barre.setRange(0, 1000)
        self._annuler = QPushButton("Annuler")
        self._annuler.setToolTip("Annuler la tâche")
        self._annuler.clicked.connect(self._annuler_courante)
        for w in (self._libelle, self._barre, self._annuler):
            lay.addWidget(w)
        self._rafraichir()

    def lancer(self, tache: Tache, fini=None, erreur=None, annulee=None) -> Tache:
        if fini:
            tache.signaux.fini.connect(fini)
        if erreur:
            tache.signaux.erreur.connect(erreur)
        if annulee:
            tache.signaux.annulee.connect(annulee)
        for sig in (tache.signaux.fini, tache.signaux.erreur, tache.signaux.annulee):
            sig.connect(lambda *_, t=tache: self._terminer(t))
        tache.signaux.progression.connect(lambda _v: self._rafraichir())
        self._taches.append(tache)
        self._pool.start(tache)
        self._rafraichir()
        return tache

    def tout_annuler(self):
        for t in self._taches:
            t.annule.set()

    def attendre(self, delai_ms: int = 5000):
        self._pool.waitForDone(delai_ms)

    @Slot()
    def _annuler_courante(self):
        if self._taches:
            self._taches[0].annule.set()
            self._libelle.setText(f"Annulation : {self._taches[0].libelle}")

    def _terminer(self, tache: Tache):
        if tache in self._taches:
            self._taches.remove(tache)
        self._rafraichir()

    def _rafraichir(self):
        visible = bool(self._taches)
        for w in (self._libelle, self._barre, self._annuler):
            w.setVisible(visible)
        if visible:
            t = self._taches[0]
            autres = len(self._taches) - 1
            texte = t.libelle + (f" (et {autres} autre{'s' if autres > 1 else ''} en attente)"
                                 if autres else "")
            if not t.annule.is_set():
                self._libelle.setText(texte)
            self._barre.setValue(int(t.avancement * 1000))
