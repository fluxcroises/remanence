"""Catalogue des effets en temps réel.

Un effet = un module de ce dossier qui déclare DESCRIPTION : ses paramètres (plages, valeurs
par défaut), ses préréglages et son programme pour la carte graphique. L'inspecteur et les
menus se construisent à partir de ces descriptions ; ajouter un effet ne demande rien d'autre.

Les intensités sont relatives à la taille de l'image : l'aperçu en demi-résolution et l'export
donnent le même rendu.
"""

from __future__ import annotations

import copy
import importlib
import pkgutil
from dataclasses import dataclass, field

from remanence.effets import courbes
from remanence.projet.modele import Effet, Masque, nouvel_id


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
    # Calcul : groupes(largeur, hauteur, valeurs des réglages) -> (x, y), le nombre de groupes
    # lancés ; sans lui, un groupe par ligne (ou par colonne si le réglage vertical est mis).
    groupes: object = None
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
    # Script de la bibliothèque : réglages lus dans le texte de l'effet (parametres_de(effet)),
    # et texte de chaque préréglage fourni.
    parametres_de: object = None
    textes: dict[str, str] = field(default_factory=dict)
    # Moteur flux optique : flux(images RVB float, valeurs de chaque image) rend les images
    # traitées. Pré-rendu comme le moteur codec, mais en 16 bits.
    flux: object = None
    # Programme interne (transitions des fondus) : ni bibliothèque, ni menus, ni inspecteur.
    interne: bool = False
    # Moteur audio : son(lire, valeurs, graine, fréquence) rend un lecteur du son traité (voir
    # rendu/son.py). Sur les clips et les pistes audio seulement.
    son: object = None

    @property
    def audio(self) -> bool:
        return self.moteur == "audio"

    @property
    def codec(self) -> bool:
        """Calculé à part et gardé en cache (moteur codec ou flux optique), sur un clip de
        média seulement."""
        return self.moteur in ("codec", "flux")

    @property
    def ffglitch(self) -> bool:
        return self.script is not None or self.transfert

    @property
    def animable(self) -> bool:
        """Images clés possibles : en temps réel, et pour les effets FFglitch générés (le
        script reçoit la valeur de chaque image). Un script de la bibliothèque ne lit ses
        réglages qu'une fois."""
        return not self.codec or self.moteur == "flux" or             (self.ffglitch and self.parametres_de is None)

    def parametres_pour(self, effet: Effet | None) -> list[Parametre]:
        return self.parametres_de(effet) if self.parametres_de else self.parametres

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
        m = importlib.import_module(f"{__name__}.{module.name}")
        # Les autres modules du dossier ne sont pas des effets ; certains en déclarent deux.
        for d in [getattr(m, "DESCRIPTION", None)] + [v for k, v in vars(m).items()
                                                       if isinstance(v, DescriptionEffet)
                                                       and k != "DESCRIPTION"]:
            if d is not None:
                EFFETS[d.cle] = d


_charger()

FAMILLES = ["Datamosh", "Corruption", "Couleur", "Pixels", "Signal", "Scripts"]
# Effets audio : une famille à part, proposée sur les clips et les pistes audio seulement.
FAMILLES_SON = ["Son"]


def nouvel_effet(cle: str, prereglage: str | None = None, script: str | None = None) -> Effet:
    """script : texte d'un Script FFglitch (sinon celui du préréglage fourni)."""
    d = EFFETS[cle]
    e = Effet(nouvel_id(), cle, d.valeurs(prereglage) if prereglage in d.prereglages
              else d.valeurs())
    # Sans préréglage (menus d'effets, qui ne proposent plus que l'effet), le premier script
    # fourni : un Script FFglitch vide ne ferait rien.
    defaut = next(iter(d.textes.values()), "")
    e.script = script if script is not None else d.textes.get(prereglage, defaut)         if prereglage else defaut
    if d.parametres_de:
        e.params = {**{p.cle: p.defaut for p in d.parametres_de(e)}, **e.params}
    return e


def valeur(effet: Effet, cle: str) -> float:
    """Valeur d'un paramètre ; celle par défaut s'il manque (effet enregistré avant un ajout)."""
    if cle in effet.params:
        return effet.params[cle]
    return next(p.defaut for p in EFFETS[effet.type].parametres_pour(effet) if p.cle == cle)


def valeur_a(effet: Effet, cle: str, t: float) -> float:
    """Valeur d'un paramètre (ou de l'opacité) au temps t, en suivant ses images clés."""
    cles = effet.cles.get(cle)
    if not cles:
        return effet.opacite if cle == "opacite" else valeur(effet, cle)
    return courbes.interpoler(cles, t)


# Réglages d'un masque qui s'animent : sa forme (tous ses points), son adoucissement, son
# expansion. Leurs images clés sont dans Masque.cles, au même temps que celles de l'effet.
CLES_MASQUE = ("points", "adoucissement", "expansion")


def masque_a(m: Masque, t: float) -> Masque:
    """Le masque tel qu'il est au temps t."""
    if not m.cles:
        return m
    copie = copy.copy(m)
    for champ in CLES_MASQUE:
        if m.cles.get(champ):
            setattr(copie, champ, copy.deepcopy(courbes.interpoler(m.cles[champ], t)))
    return copie


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


def valeur_modulee(effet: Effet, p: Parametre | None, t: float, decalage: float = 0.0) -> float:
    """Valeur au temps t (images clés), plus le décalage des modulateurs (en fraction de la
    plage), ramenée dans la plage du réglage (une Bézier ou un modulateur peut déborder).
    p None : l'opacité."""
    mini, maxi = (0.0, 1.0) if p is None else (p.minimum, p.maximum)
    v = valeur_a(effet, "opacite" if p is None else p.cle, t) + decalage * (maxi - mini)
    return min(maxi, max(mini, v))


def instantane(effet: Effet, t: float, decalages: dict | None = None) -> Effet:
    """L'effet tel qu'il est au temps t : paramètres et opacité fixés, prêt pour le rendu.
    decalages : ceux des modulateurs à cet instant ((effet, réglage) -> fraction)."""
    module = {cle: v for (eid, cle), v in (decalages or {}).items() if eid == effet.id}
    if not effet.cles and not module and not any(m.cles for m in effet.masques):
        return effet
    d = EFFETS.get(effet.type)
    params = dict(effet.params)
    for p in (d.parametres if d else []):
        if p.cle in effet.cles or p.cle in module:
            params[p.cle] = valeur_modulee(effet, p, t, module.get(p.cle, 0.0))
    return Effet(effet.id, effet.type, params, effet.actif, effet.graine,
                 valeur_modulee(effet, None, t, module.get("opacite", 0.0)), effet.fusion,
                 masques=[masque_a(m, t) for m in effet.masques], script=effet.script)


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
