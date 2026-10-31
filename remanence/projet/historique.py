"""Annuler / rétablir sans limite, par instantanés complets du projet."""

from __future__ import annotations

import json

from remanence.projet.modele import Projet


class Historique:
    def __init__(self, projet: Projet):
        self._etats: list[tuple[str, str]] = [("Ouverture", self._figer(projet))]
        self._position = 0

    @staticmethod
    def _figer(projet: Projet) -> str:
        return json.dumps(projet.vers_dict(), ensure_ascii=False)

    def valider(self, projet: Projet, libelle: str) -> bool:
        """Enregistre l'état courant. Renvoie False si rien n'a changé."""
        etat = self._figer(projet)
        if etat == self._etats[self._position][1]:
            return False
        del self._etats[self._position + 1:]
        self._etats.append((libelle, etat))
        self._position += 1
        return True

    def peut_annuler(self) -> bool:
        return self._position > 0

    def peut_retablir(self) -> bool:
        return self._position < len(self._etats) - 1

    def libelle_annuler(self) -> str:
        return self._etats[self._position][0] if self.peut_annuler() else ""

    def libelle_retablir(self) -> str:
        return self._etats[self._position + 1][0] if self.peut_retablir() else ""

    def annuler(self) -> Projet | None:
        if not self.peut_annuler():
            return None
        self._position -= 1
        return Projet.depuis_dict(json.loads(self._etats[self._position][1]))

    def retablir(self) -> Projet | None:
        if not self.peut_retablir():
            return None
        self._position += 1
        return Projet.depuis_dict(json.loads(self._etats[self._position][1]))
