"""Boîte de réglages d'un script de glitch (Scramble, Layer, Automator). Les derniers réglages
de chaque script sont retenus ; la graine se change d'un clic (« Autre tirage »)."""

from __future__ import annotations

import random

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QGridLayout,
                               QHBoxLayout, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from remanence.config import reglages_interface
from remanence.effets import EFFETS, courbes
from remanence.projet.modele import MODES_FUSION
from remanence.ui.composants import elargir_boutons, etiquette


def nombre(mini: int, maxi: int, defaut: int, suffixe: str = "") -> QSpinBox:
    s = QSpinBox()
    s.setRange(mini, maxi)
    s.setValue(defaut)
    if suffixe:
        s.setSuffix(" " + suffixe)
    return s


def liste(elements: list[tuple[object, str]], defaut=None) -> QComboBox:
    c = QComboBox()
    for cle, texte in elements:
        c.addItem(texte, cle)
    c.setCurrentIndex(max(0, c.findData(defaut)))
    return c


class DialogueScript(QDialog):
    """champs : [(clé, libellé, widget)]. valeurs() : clé -> valeur, plus « graine » pour un
    script qui tire au hasard."""

    def __init__(self, nom: str, champs: list[tuple[str, str, QWidget]], parent=None,
                 hasard: bool = True):
        super().__init__(parent)
        self.nom = nom
        self.setWindowTitle(nom)
        self.champs = champs
        lay = QVBoxLayout(self)
        self.grille = QGridLayout()
        self.grille.setHorizontalSpacing(12)
        self.grille.setVerticalSpacing(8)
        lay.addLayout(self.grille)
        reglages = reglages_interface()
        for rang, (cle, libelle, w) in enumerate(champs):
            w.setAccessibleName(libelle)
            memoire = reglages.value(f"scripts/{nom}/{cle}")
            if memoire is not None:
                if isinstance(w, QSpinBox):
                    w.setValue(int(memoire))
                elif isinstance(w, QComboBox) and w.findData(memoire) >= 0:
                    w.setCurrentIndex(w.findData(memoire))
            self.grille.addWidget(etiquette(libelle, "libelle"), rang, 0)
            self.grille.addWidget(w, rang, 1)
        self.graine = nombre(0, 999_999, int(reglages.value(f"scripts/{nom}/graine", 1)))
        self.graine.setAccessibleName("Graine")
        if hasard:
            tirage = QPushButton("Autre tirage")
            tirage.clicked.connect(lambda: self.graine.setValue(random.randint(0, 999_999)))
            rang_graine = QHBoxLayout()
            rang_graine.addWidget(self.graine, 1)
            rang_graine.addWidget(tirage)
            self.grille.addWidget(etiquette("Graine", "libelle"), len(champs), 0)
            self.grille.addLayout(rang_graine, len(champs), 1)
        self.grille.setColumnStretch(1, 1)
        self.setMinimumWidth(400)
        boutons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        boutons.button(QDialogButtonBox.Ok).setText("Appliquer")
        boutons.button(QDialogButtonBox.Cancel).setText("Annuler")
        boutons.accepted.connect(self._valider)
        boutons.rejected.connect(self.reject)
        lay.addWidget(boutons)
        elargir_boutons(boutons)

    def valeurs(self) -> dict:
        v = {}
        for cle, _libelle, w in self.champs:
            v[cle] = w.value() if isinstance(w, QSpinBox) else w.currentData()
        v["graine"] = self.graine.value()
        return v

    def _valider(self):
        reglages = reglages_interface()
        for cle, valeur in self.valeurs().items():
            if isinstance(valeur, (int, str)):
                reglages.setValue(f"scripts/{self.nom}/{cle}", valeur)
        self.accept()


def dialogue_scramble(parent) -> DialogueScript:
    return DialogueScript("Scramble", [("longueur", "Morceaux", nombre(1, 600, 12, "images"))],
                          parent)


def dialogue_layer(parent) -> DialogueScript:
    return DialogueScript("Layer", [
        ("copies", "Copies", nombre(1, 8, 3)),
        ("decalage", "Décalage", nombre(1, 250, 4, "images")),
        ("attenuation", "Atténuation", nombre(0, 90, 30, "%")),
        ("fusion", "Fusion", liste(list(MODES_FUSION.items()), "normal"))], parent,
        hasard=False)


class DialogueAutomator(DialogueScript):
    """effets : [(libellé, effet)], effets animables seulement. Les réglages de l'effet choisi
    sont des cases à cocher, toutes cochées sauf les interrupteurs."""

    def __init__(self, effets: list, parent=None):
        self.effets = effets
        self.choix_effet = liste([(i, nom) for i, (nom, _e) in enumerate(effets)])
        passages = [(cle, nom) for cle, nom in courbes.MODES.items() if cle != "bezier"]
        super().__init__("Automator", [
            ("effet", "Effet", self.choix_effet),
            ("intervalle", "Intervalle", nombre(1, 600, 6, "images")),
            ("amplitude", "Amplitude", nombre(1, 100, 100, "%")),
            ("passage", "Passage", liste(passages, "lineaire"))], parent)
        self.cases: list[QCheckBox] = []
        self._premier_rang = self.grille.rowCount()
        self.grille.addWidget(etiquette("Réglages", "libelle"), self._premier_rang, 0)
        self.choix_effet.currentIndexChanged.connect(lambda _i: self._cases())
        self._cases()

    def effet(self):
        return self.effets[self.choix_effet.currentData()][1]

    def _cases(self):
        for c in self.cases:
            c.setParent(None)
        self.cases = []
        d = EFFETS[self.effet().type]
        for i, p in enumerate(d.parametres_pour(self.effet())):
            c = QCheckBox(p.nom)
            c.setProperty("cle", p.cle)
            c.setChecked(not p.booleen)
            self.grille.addWidget(c, self._premier_rang + i, 1)
            self.cases.append(c)

    def reglages_choisis(self) -> list[str]:
        return [c.property("cle") for c in self.cases if c.isChecked()]
