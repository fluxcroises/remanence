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
    # Moteur codec : pas de programme pour la carte graphique, mais traiter(paquets, valeurs,
    # graine) qui abîme le flux MPEG-4 du clip ; calculé en arrière-plan, gardé en cache.
    moteur: str = "temps_reel"
    traiter: object = None
    # Effets codec FFglitch : script(valeurs de chaque image, graine) rend le script
    # JavaScript qui réécrit les vecteurs de mouvement ; transfert : les vecteurs viennent du
    # clip de la piste au-dessus. Sans FFglitch, ils restent sans action.
    script: object = None
    transfert: bool = False

    @property
    def codec(self) -> bool:
        return self.moteur == "codec"

    @property
    def ffglitch(self) -> bool:
        return self.script is not None or self.transfert

    @property
    def animable(self) -> bool:
        """Images clés possibles : en temps réel, et pour les effets FFglitch (le script
        reçoit la valeur de chaque image)."""
        return not self.codec or self.ffglitch

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

FAMILLES = ["Datamosh", "Corruption", "Couleur", "Pixels", "Signal"]


def nouvel_effet(cle: str, prereglage: str | None = None) -> Effet:
    return Effet(nouvel_id(), cle, EFFETS[cle].valeurs(prereglage))


def valeur(effet: Effet, cle: str) -> float:
    """Valeur d'un paramètre ; celle par défaut s'il manque (effet enregistré avant un ajout)."""
    if cle in effet.params:
        return effet.params[cle]
    return next(p.defaut for p in EFFETS[effet.type].parametres if p.cle == cle)


def valeur_a(effet: Effet, cle: str, t: float) -> float:
    """Valeur d'un paramètre (ou de l'opacité) au temps t, en suivant ses images clés."""
    cles = effet.cles.get(cle)
    if not cles:
        return effet.opacite if cle == "opacite" else valeur(effet, cle)
    if t <= cles[0][0]:
        return cles[0][1]
    for (t0, v0, mode), (t1, v1, _) in zip(cles, cles[1:]):
        if t < t1:
            if mode == "palier" or t1 == t0:
                return v0
            return v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return cles[-1][1]


def plage_cles(effet: Effet) -> tuple[float, float] | None:
    """Première et dernière image clé de l'effet, tous réglages confondus ; None s'il en a
    moins de deux instants (pas encore de plage : l'effet agit partout)."""
    temps = {k[0] for cles in effet.cles.values() for k in cles}
    if len(temps) < 2:
        return None
    return min(temps), max(temps)


def agit_a(effet: Effet, t: float) -> bool:
    """Un effet animé n'agit qu'entre sa première et sa dernière image clé (choix de Lewis,
    1er novembre 2026 : des bouffées de glitch, pas un effet qui tient sa valeur hors des
    clés comme dans After Effects)."""
    plage = plage_cles(effet)
    return plage is None or plage[0] <= t <= plage[1]


def instantane(effet: Effet, t: float) -> Effet:
    """L'effet tel qu'il est au temps t : paramètres et opacité fixés, prêt pour le rendu."""
    if not effet.cles:
        return effet
    d = EFFETS.get(effet.type)
    params = dict(effet.params)
    for p in (d.parametres if d else []):
        if p.cle in effet.cles:
            params[p.cle] = valeur_a(effet, p.cle, t)
    return Effet(effet.id, effet.type, params, effet.actif, effet.graine,
                 valeur_a(effet, "opacite", t), effet.fusion, masques=effet.masques)


def poser_cle(effet: Effet, cle: str, t: int, v: float, mode: str | None = None):
    """Image clé au temps t : remplacée si elle existe, ajoutée sinon."""
    cles = effet.cles.setdefault(cle, [])
    for k in cles:
        if k[0] == t:
            k[1] = v
            if mode:
                k[2] = mode
            return
    booleen = any(p.cle == cle and p.booleen for p in EFFETS[effet.type].parametres) \
        if effet.type in EFFETS else False
    cles.append([t, v, mode or ("palier" if booleen else "lineaire")])
    cles.sort(key=lambda k: k[0])


def retirer_cle(effet: Effet, cle: str, t: int):
    """Retire l'image clé au temps t ; sans image clé, le paramètre redevient fixe à sa
    dernière valeur."""
    cles = effet.cles.get(cle, [])
    reste = [k for k in cles if k[0] != t]
    if reste:
        effet.cles[cle] = reste
        return
    valeur_fixe = valeur_a(effet, cle, t)
    effet.cles.pop(cle, None)
    if cle == "opacite":
        effet.opacite = valeur_fixe
    else:
        effet.params[cle] = valeur_fixe
