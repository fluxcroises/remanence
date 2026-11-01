"""Catalogue des effets en temps réel.

Un effet = un module de ce dossier qui déclare DESCRIPTION : ses paramètres (plages, valeurs
par défaut), ses préréglages et son programme pour la carte graphique. L'inspecteur et les
menus se construisent à partir de ces descriptions ; ajouter un effet ne demande rien d'autre.

Les intensités sont relatives à la taille de l'image : l'aperçu en demi-résolution et l'export
donnent le même rendu.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field

from remanence.projet.modele import Effet, nouvel_id


@dataclass
class Parametre:
    cle: str
    nom: str
    minimum: float = 0.0
    maximum: float = 100.0
    defaut: float = 0.0
    unite: str = ""
    decimales: int = 0
    booleen: bool = False


@dataclass
class DescriptionEffet:
    cle: str
    nom: str
    famille: str
    parametres: list[Parametre]
    # Corps du programme GLSL : fragment (une sortie par pixel) ou calcul (compute shader,
    # pour les traitements qui lisent toute une ligne, comme le tri de pixels).
    fragment: str = ""
    calcul: str = ""
    prereglages: dict[str, dict] = field(default_factory=dict)

    def valeurs(self, prereglage: str | None = None) -> dict:
        v = {p.cle: p.defaut for p in self.parametres}
        if prereglage:
            v.update(self.prereglages[prereglage])
        return v


# Fonctions communes aux programmes : lecture de l'image, hasard reproductible.
# La même graine et la même image donnent toujours le même résultat (aperçu = export).
COMMUN = """
uniform sampler2D source;
uniform ivec2 taille;
uniform int numero;   // numéro de l'image dans la séquence
uniform uint graine;

uint pcg(uint v) {
    uint s = v * 747796405u + 2891336453u;
    uint w = ((s >> ((s >> 28u) + 4u)) ^ s) * 277803737u;
    return (w >> 22u) ^ w;
}
// Nombre au hasard dans [0, 1[, fixé par (a, b, c) et la graine de l'effet.
float hasard(uint a, uint b, uint c) {
    return float(pcg(a ^ pcg(b ^ pcg(c ^ pcg(graine))))) / 4294967296.0;
}
float hasard_normal(uint a, uint b, uint c) {
    float u1 = max(hasard(a, b, c * 2u), 1e-7);
    float u2 = hasard(a, b, c * 2u + 1u);
    return sqrt(-2.0 * log(u1)) * cos(6.2831853 * u2);
}
vec4 lire(ivec2 p) {  // l'image se répète au-delà des bords, comme np.roll
    return texelFetch(source, ((p % taille) + taille) % taille, 0);
}
vec4 lire_borne(ivec2 p) {
    return texelFetch(source, clamp(p, ivec2(0), taille - 1), 0);
}
vec4 lire_lisse(vec2 xy) {  // interpolation bilinéaire, bords répétés en miroir
    vec2 q = xy - 0.5;
    ivec2 i = ivec2(floor(q));
    vec2 t = q - vec2(i);
    vec4 a = mix(lire_borne(i), lire_borne(i + ivec2(1, 0)), t.x);
    vec4 b = mix(lire_borne(i + ivec2(0, 1)), lire_borne(i + ivec2(1, 1)), t.x);
    return mix(a, b, t.y);
}
"""

EFFETS: dict[str, DescriptionEffet] = {}


def _charger():
    for module in pkgutil.iter_modules(__path__):
        d = getattr(importlib.import_module(f"{__name__}.{module.name}"), "DESCRIPTION", None)
        if d is not None:  # les autres modules du dossier ne sont pas des effets
            EFFETS[d.cle] = d


_charger()

FAMILLES = ["Corruption", "Couleur", "Pixels", "Signal"]


def nouvel_effet(cle: str, prereglage: str | None = None) -> Effet:
    return Effet(nouvel_id(), cle, EFFETS[cle].valeurs(prereglage))


def valeur(effet: Effet, cle: str) -> float:
    """Valeur d'un paramètre ; celle par défaut s'il manque (effet enregistré avant un ajout)."""
    if cle in effet.params:
        return effet.params[cle]
    return next(p.defaut for p in EFFETS[effet.type].parametres if p.cle == cle)
