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

    def valider(self, projet: Projet, libelle: str, fusionner: bool = False) -> bool:
        """Enregistre l'état courant. Renvoie False si rien n'a changé.

        fusionner : si la dernière action porte le même libellé et qu'on n'a rien annulé
        depuis, elle est remplacée au lieu d'ajouter une ligne (import de plusieurs fichiers).
        """
        etat = self._figer(projet)
        if etat == self._etats[self._position][1]:
            return False
        if fusionner and self._position > 0 and self._position == len(self._etats) - 1 \
                and self._etats[-1][0] == libelle:
            self._etats[-1] = (libelle, etat)
            return True
        del self._etats[self._position + 1:]
        self._etats.append((libelle, etat))
        self._position += 1
        return True

    @property
    def position(self) -> int:
        return self._position

    def retoucher(self, modifier):
        """Applique une donnée calculée après coup (coupes d'un média) à tous les états
        retenus, sans créer d'action : annuler ne doit pas la faire disparaître."""
        etats = []
        for libelle, etat in self._etats:
            p = Projet.depuis_dict(json.loads(etat))
            modifier(p)
            etats.append((libelle, self._figer(p)))
        self._etats = etats

    def libelles(self) -> list[str]:
        return [libelle for libelle, _ in self._etats]

    def aller(self, position: int) -> Projet | None:
        """Revient directement à un état de la liste (onglet Historique)."""
        if not 0 <= position < len(self._etats) or position == self._position:
            return None
        self._position = position
        return Projet.depuis_dict(json.loads(self._etats[position][1]))

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
