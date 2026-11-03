"""Moteur de lecture : calcule les images dans un fil séparé et joue le son.

À vitesse normale, l'horloge est celle de la carte son : l'image suit le son.
En lecture rapide ou arrière (J, L répétés), l'horloge est celle du système et le son est coupé.
"""

from __future__ import annotations

import threading
import time
import traceback

import numpy as np
from PySide6.QtCore import QObject, Signal

from remanence.media.lecteur import FREQUENCE_MIXAGE
from remanence.projet.modele import Projet
from remanence.rendu.composition import Compositeur, sans_effets

try:
    import sounddevice
except Exception:  # Pas de PortAudio : lecture muette, l'horloge système prend le relais.
    sounddevice = None

QUALITES = {"Pleine": (1.0, False), "1/2": (0.5, True), "1/4": (0.25, True)}


# Comparaison avant / après : « avant » est la séquence sans aucun effet (sans_effets).
COMPARAISONS = {"apres": "Après", "avant": "Avant", "volet": "Volet", "cote": "Côte à côte"}


class MoteurLecture(QObject):
    # L'image, ou (après, avant) pour un volet ou un côte à côte.
    image_prete = Signal(object, int)
    position_changee = Signal(int)
    lecture_changee = Signal(bool)
    erreur = Signal(str, str)

    def __init__(self):
        super().__init__()
        self._projet: Projet | None = None
        self._verrou = threading.Condition()
        self._position = 0
        self._demande = 0
        self._derniere_rendue = None
        self._vitesse = 0.0
        self._qualite = "1/2"
        self._comparaison = "apres"
        self._projet_avant: Projet | None = None
        self._version = 0
        self._arret = False
        self._flux = None
        self._echantillon = 0
        self._depart = (0.0, 0)
        self._fil = threading.Thread(target=self._boucle, name="rendu-lecture", daemon=True)
        self._fil.start()
        self._compo_audio = None
        self._cretes = None
        self._boucle: tuple[int, int] | None = None

    # Côté interface

    def definir_boucle(self, plage: tuple[int, int] | None):
        """Lecture en boucle entre deux images (fin exclue), ou None."""
        with self._verrou:
            self._boucle = plage if plage and plage[1] > plage[0] else None

    def definir_projet(self, projet: Projet):
        """Le moteur travaille sur une copie : l'interface peut modifier l'original sans risque."""
        copie = Projet.depuis_dict(projet.vers_dict())
        for m in copie.medias.values():
            m.hors_ligne = projet.medias[m.id].hors_ligne
        avant = sans_effets(copie) if self._comparaison != "apres" else None
        with self._verrou:
            self._projet = copie
            self._projet_avant = avant
            self._version += 1
            self._derniere_rendue = None
            self._compo_audio = None
            self._verrou.notify_all()

    def definir_comparaison(self, mode: str):
        """apres (normal), avant, volet ou cote : voir COMPARAISONS."""
        with self._verrou:
            if mode == self._comparaison:
                return
            self._comparaison = mode
            if mode != "apres" and self._projet_avant is None and self._projet is not None:
                self._projet_avant = sans_effets(self._projet)
            self._version += 1
            self._derniere_rendue = None
            self._verrou.notify_all()

    @property
    def comparaison(self) -> str:
        return self._comparaison

    def definir_qualite(self, qualite: str):
        with self._verrou:
            self._qualite = qualite
            self._derniere_rendue = None
            self._verrou.notify_all()

    @property
    def position(self) -> int:
        return self._position

    @property
    def en_lecture(self) -> bool:
        return self._vitesse != 0

    @property
    def vitesse(self) -> float:
        return self._vitesse

    def aller_a(self, f: int):
        with self._verrou:
            f = max(0, int(f))
            self._position = self._demande = f
            if self._vitesse:
                self._redemarrer_horloge()
            self._verrou.notify_all()
        self.position_changee.emit(f)

    def lire(self, vitesse: float = 1.0):
        with self._verrou:
            self._vitesse = vitesse
            self._redemarrer_horloge()
            self._verrou.notify_all()
        self.lecture_changee.emit(True)

    def pause(self):
        with self._verrou:
            self._vitesse = 0.0
            self._arreter_son()
            self._verrou.notify_all()
        self.lecture_changee.emit(False)

    def rafraichir(self):
        with self._verrou:
            self._derniere_rendue = None
            self._verrou.notify_all()

    def fermer(self):
        with self._verrou:
            self._arret = True
            self._arreter_son()
            self._verrou.notify_all()
        self._fil.join(timeout=2)

    # Horloge et son

    def _cadence(self) -> float:
        return float(self._projet.sequence.fraction_cadence) if self._projet else 24.0

    def _redemarrer_horloge(self):
        self._arreter_son()
        self._depart = (time.perf_counter(), self._position)
        par_image = FREQUENCE_MIXAGE / self._cadence()
        self._echantillon = round(self._position * par_image)
        if self._vitesse == 1.0 and sounddevice is not None and self._projet is not None:
            try:
                self._flux = sounddevice.OutputStream(
                    samplerate=FREQUENCE_MIXAGE, channels=2, dtype="float32",
                    callback=self._rappel_son, blocksize=1024)
                self._flux.start()
            except Exception:
                self._flux = None

    def _arreter_son(self):
        if self._flux is not None:
            try:
                self._flux.stop()
                self._flux.close()
            except Exception:
                pass
            self._flux = None

    def _rappel_son(self, sortie, n, _infos, _etat):
        projet = self._projet
        if projet is None:
            sortie.fill(0)
            return
        if self._compo_audio is None or self._compo_audio.projet is not projet:
            self._compo_audio = Compositeur(projet)
        try:
            bloc = self._compo_audio.audio(projet.sequence, self._echantillon, n)
            self._cretes = tuple(float(v) for v in np.abs(bloc).max(axis=0)) if n else None
            sortie[:] = np.clip(bloc, -1, 1)
        except Exception:
            sortie.fill(0)
        self._echantillon += n

    def cretes(self) -> tuple[float, float] | None:
        """Crêtes du dernier bloc de son joué, pour les vumètres ; None à l'arrêt."""
        return self._cretes if self._flux is not None else None

    def _image_horloge(self) -> int:
        if self._flux is not None:
            latence = self._flux.latency if isinstance(self._flux.latency, float) else 0.0
            secondes = self._echantillon / FREQUENCE_MIXAGE - latence
            return max(0, int(secondes * self._cadence()))
        t0, f0 = self._depart
        return max(0, int(f0 + (time.perf_counter() - t0) * self._cadence() * self._vitesse))

    # Fil de rendu

    def _boucle(self):
        compositeur = avant = None
        version = -1
        while True:
            with self._verrou:
                while not self._arret and self._vitesse == 0 and \
                        self._derniere_rendue == (self._demande, self._version, self._qualite):
                    self._verrou.wait(0.1)
                if self._arret:
                    break
                projet = self._projet
                if self._vitesse:
                    cible = self._image_horloge()
                    fin = projet.sequence.duree() if projet else 0
                    if self._boucle and self._vitesse > 0 and cible >= self._boucle[1]:
                        self._position = self._boucle[0]
                        self._redemarrer_horloge()
                        cible = self._boucle[0]
                    if cible >= fin or cible <= 0 and self._vitesse < 0:
                        cible = max(0, min(cible, fin - 1)) if fin else 0
                        self._vitesse = 0.0
                        self._arreter_son()
                        arret_auto = True
                    else:
                        arret_auto = False
                    self._position = self._demande = cible
                else:
                    cible = self._demande
                    arret_auto = False
                cle = (cible, self._version, self._qualite)
                qualite = self._qualite
                comparaison = self._comparaison
                projet_avant = self._projet_avant if comparaison != "apres" else None
                if self._version != version:
                    for c in (compositeur, avant):
                        if c is not None:
                            c.fermer()
                    compositeur = Compositeur(projet, apercu=True) if projet else None
                    avant = Compositeur(projet_avant, apercu=True) if projet_avant else None
                    version = self._version
            if arret_auto:
                self.lecture_changee.emit(False)
            if self._vitesse:
                self.position_changee.emit(cible)
            if compositeur is None or cle == self._derniere_rendue:
                time.sleep(0.004)
                continue
            echelle, proxy = QUALITES[qualite]
            try:
                image = compositeur.image_apercu(projet.sequence, cible, echelle, proxy)
                if avant is not None and projet_avant is not None:
                    image_avant = avant.image_apercu(projet_avant.sequence, cible, echelle,
                                                     proxy)
                    image = image_avant if comparaison == "avant" else (image, image_avant)
            except Exception as e:
                self.erreur.emit(str(e), traceback.format_exc())
                with self._verrou:
                    self._derniere_rendue = cle
                continue
            with self._verrou:
                self._derniere_rendue = cle
            self.image_prete.emit(image, cible)
        for c in (compositeur, avant):
            if c is not None:
                c.fermer()
