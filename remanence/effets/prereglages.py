"""Préréglages : ceux fournis avec chaque effet, et ceux de l'utilisateur.

Un préréglage personnel peut porter un seul effet ou toute une pile ; il est enregistré en JSON
dans `prereglages.json` du dossier de données (%APPDATA%\\Remanence). Les préréglages fournis
ne se suppriment pas.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from remanence.config import dossier_donnees
from remanence import effets as catalogue
from remanence.effets import EFFETS
from remanence.moteurs.codec import scripts
from remanence.projet.modele import Effet, nouvel_id

FAMILLE_PERSONNELS = "Mes préréglages"


@dataclass
class Prereglage:
    nom: str
    # [{"type": clé de l'effet, "params": {...}}, ...] ; plusieurs : une pile d'effets.
    effets: list[dict]
    fourni: bool = True

    @property
    def famille(self) -> str:
        if not self.fourni:
            return FAMILLE_PERSONNELS
        return EFFETS[self.effets[0]["type"]].famille

    @property
    def description(self) -> str:
        """« Effet · temps réel » ou « Effet · moteur codec », ou la liste d'une pile."""
        connus = [EFFETS[e["type"]] for e in self.effets if e["type"] in EFFETS]
        moteur = "moteur codec" if any(d.codec for d in connus) else "temps réel"
        return " + ".join(d.nom for d in connus) + " · " + moteur

    def nouveaux_effets(self) -> list[Effet]:
        """Effets neufs, prêts à poser : chacun garde ses réglages et reste modifiable."""
        return [Effet(nouvel_id(), e["type"], dict(e["params"]), graine=e.get("graine", 1),
                      script=e.get("script", ""))
                for e in self.effets if e["type"] in EFFETS]

    def correspond(self, effets: list[Effet]) -> bool:
        """Vrai si ces effets sont exactement ceux du préréglage (tuile surlignée)."""
        if len(effets) != len(self.effets):
            return False
        return all(e.type == d["type"] and e.script == d.get("script", "")
                   and all(e.params.get(k) == v for k, v in d["params"].items())
                   for e, d in zip(effets, self.effets))


def fournis() -> list[Prereglage]:
    """Préréglages de chaque effet, puis les scripts importés dans la bibliothèque."""
    resultat = []
    for d in EFFETS.values():
        for nom in d.prereglages:
            e = catalogue.nouvel_effet(d.cle, nom)
            p = {"type": d.cle, "params": e.params}
            if e.script:
                p["script"] = e.script
            resultat.append(Prereglage(nom, [p]))
    if "script_ffglitch" in EFFETS:
        for nom, (texte, fourni) in scripts.bibliotheque().items():
            if not fourni:
                e = catalogue.nouvel_effet("script_ffglitch", script=texte)
                resultat.append(Prereglage(nom, [{"type": e.type, "params": e.params,
                                                  "script": texte}]))
    return resultat


def _fichier():
    return dossier_donnees() / "prereglages.json"


def personnels() -> list[Prereglage]:
    try:
        donnees = json.loads(_fichier().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [Prereglage(p["nom"], p["effets"], fourni=False) for p in donnees
            if isinstance(p, dict) and p.get("effets")]


def _ecrire(liste: list[Prereglage]):
    donnees = [{"nom": p.nom, "effets": p.effets} for p in liste]
    _fichier().write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")


def tous() -> list[Prereglage]:
    return fournis() + personnels()


def enregistrer(nom: str, effets: list[Effet]) -> Prereglage:
    """Nouveau préréglage personnel ; un préréglage du même nom est remplacé."""
    p = Prereglage(nom, [{"type": e.type, "params": dict(e.params), "graine": e.graine,
                          **({"script": e.script} if e.script else {})}
                         for e in effets], fourni=False)
    liste = [x for x in personnels() if x.nom != nom]
    liste.append(p)
    _ecrire(liste)
    return p


def supprimer(nom: str):
    _ecrire([p for p in personnels() if p.nom != nom])


def renommer(ancien: str, nouveau: str):
    liste = personnels()
    for p in liste:
        if p.nom == ancien:
            p.nom = nouveau
    _ecrire(liste)


MIME_PREREGLAGE = "application/x-remanence-prereglage"


def vers_mime(p: Prereglage) -> bytes:
    return json.dumps({"nom": p.nom, "effets": p.effets}, ensure_ascii=False).encode("utf-8")


def depuis_mime(donnees: bytes) -> Prereglage:
    d = json.loads(bytes(donnees).decode("utf-8"))
    return Prereglage(d["nom"], d["effets"])
