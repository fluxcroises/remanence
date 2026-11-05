"""Transformation d'un clip : position, taille, rotation, recadrage, retournement.

Elle est rangée dans `Clip.transformation`, sous la forme d'un effet interne : images clés,
courbes et modulateurs s'y appliquent comme aux autres effets. Le composeur la place après
les effets du clip et avant ceux de sa piste (`composition.couches`) : un clip glitché et
réduit garde son glitch dans son cadre, comme dans Vegas.

Repères : position en % de la largeur (X) et de la hauteur (Y) de la séquence, vers la droite
et vers le bas ; taille en %, multipliée par la largeur et la hauteur ; rotation en degrés,
positive dans le sens inverse des aiguilles d'une montre ; recadrage en % du cadre de l'image
(l'image du média telle qu'elle tient dans la séquence), rogné de chaque côté avant la
transformation. Le centre de rotation et de taille est le centre de la séquence.

Sans transformation (tous les réglages à leur valeur de départ), le clip n'en reçoit aucune :
ses pixels restent ceux de la source, au bit près.
"""

from __future__ import annotations

from remanence.effets import DescriptionEffet, Parametre
from remanence.projet.modele import Effet, nouvel_id

CLE = "transformation"

# Cadre de l'image du clip dans la séquence, en fraction : posé par le composeur à chaque
# image, jamais montré dans l'inspecteur.
CADRE = ("cadre_x", "cadre_y", "cadre_l", "cadre_h")

DESCRIPTION = DescriptionEffet(
    cle=CLE,
    nom="Transformation",
    famille="Transformation",
    interne=True,
    parametres=[
        Parametre("x", "Position X", -200, 200, 0, "%", 1),
        Parametre("y", "Position Y", -200, 200, 0, "%", 1),
        Parametre("taille", "Taille", 0, 1000, 100, "%", 1),
        Parametre("largeur", "Largeur", 0, 1000, 100, "%", 1),
        Parametre("hauteur", "Hauteur", 0, 1000, 100, "%", 1),
        Parametre("rotation", "Rotation", -720, 720, 0, "°", 1),
        Parametre("rognage_gauche", "Rognage gauche", 0, 100, 0, "%", 1),
        Parametre("rognage_droite", "Rognage droite", 0, 100, 0, "%", 1),
        Parametre("rognage_haut", "Rognage haut", 0, 100, 0, "%", 1),
        Parametre("rognage_bas", "Rognage bas", 0, 100, 0, "%", 1),
        Parametre("miroir_h", "Miroir horizontal", 0, 1, 0, booleen=True),
        Parametre("miroir_v", "Miroir vertical", 0, 1, 0, booleen=True),
        Parametre("cadre_x", "Cadre X", 0, 1, 0, decimales=6),
        Parametre("cadre_y", "Cadre Y", 0, 1, 0, decimales=6),
        Parametre("cadre_l", "Cadre L", 0, 1, 1, decimales=6),
        Parametre("cadre_h", "Cadre H", 0, 1, 1, decimales=6),
    ],
    fragment="""
uniform float p_x;
uniform float p_y;
uniform float p_taille;
uniform float p_largeur;
uniform float p_hauteur;
uniform float p_rotation;
uniform float p_rognage_gauche;
uniform float p_rognage_droite;
uniform float p_rognage_haut;
uniform float p_rognage_bas;
uniform float p_miroir_h;
uniform float p_miroir_v;
uniform float p_cadre_x;
uniform float p_cadre_y;
uniform float p_cadre_l;
uniform float p_cadre_h;

// Hors de l'image : transparent (on voit les pistes du dessous).
vec4 texel(ivec2 i) {
    if (any(lessThan(i, ivec2(0))) || any(greaterThanEqual(i, taille)))
        return vec4(0.0);
    return texelFetch(source, i, 0);
}

vec4 bilineaire(vec2 q) {
    vec2 c = q - 0.5;
    ivec2 i = ivec2(floor(c));
    vec2 t = c - vec2(i);
    return mix(mix(texel(i), texel(i + ivec2(1, 0)), t.x),
               mix(texel(i + ivec2(0, 1)), texel(i + ivec2(1, 1)), t.x), t.y);
}

// Catmull-Rom : une position entière rend le pixel exact (poids 0, 1, 0, 0).
vec4 poids(float t) {
    float t2 = t * t, t3 = t2 * t;
    return vec4(-0.5 * t3 + t2 - 0.5 * t, 1.5 * t3 - 2.5 * t2 + 1.0,
                -1.5 * t3 + 2.0 * t2 + 0.5 * t, 0.5 * t3 - 0.5 * t2);
}

vec4 bicubique(vec2 q) {
    vec2 c = q - 0.5;
    ivec2 i = ivec2(floor(c));
    vec2 t = c - vec2(i);
    vec4 wx = poids(t.x), wy = poids(t.y);
    vec4 r = vec4(0.0);
    for (int y = 0; y < 4; y++) {
        vec4 ligne = vec4(0.0);
        for (int x = 0; x < 4; x++)
            ligne += wx[x] * texel(i + ivec2(x - 1, y - 1));
        r += wy[y] * ligne;
    }
    return r;
}

void main() {
    vec2 T = vec2(taille);
    vec2 centre = T * 0.5;
    float sx = p_taille * p_largeur / 10000.0 * (p_miroir_h > 0.5 ? -1.0 : 1.0);
    float sy = p_taille * p_hauteur / 10000.0 * (p_miroir_v > 0.5 ? -1.0 : 1.0);
    if (abs(sx) < 1e-6 || abs(sy) < 1e-6) {
        sortie = vec4(0.0);
        return;
    }
    // Rotation positive dans le sens inverse des aiguilles d'une montre (y vers le bas).
    float a = radians(p_rotation);
    float ca = cos(a), sa = sin(a);
    vec2 d = gl_FragCoord.xy - centre - vec2(p_x, p_y) / 100.0 * T;
    vec2 r = vec2(ca * d.x - sa * d.y, sa * d.x + ca * d.y);
    vec2 q = centre + r / vec2(sx, sy);
    // Recadrage, en part du cadre de l'image.
    vec2 c0 = vec2(p_cadre_x, p_cadre_y) * T, cl = vec2(p_cadre_l, p_cadre_h) * T;
    vec2 bas = c0 + cl * vec2(p_rognage_gauche, p_rognage_haut) / 100.0;
    vec2 haut = c0 + cl * (1.0 - vec2(p_rognage_droite, p_rognage_bas) / 100.0);
    if (q.x < bas.x || q.y < bas.y || q.x >= haut.x || q.y >= haut.y) {
        sortie = vec4(0.0);
        return;
    }
    // Réduction : moyenne de k × k échantillons, sinon l'image scintille.
    int k = int(clamp(ceil(1.0 / min(abs(sx), abs(sy))), 1.0, 4.0));
    vec4 v;
    if (k == 1) {
        v = bicubique(q);
    } else {
        v = vec4(0.0);
        for (int j = 0; j < k; j++)
            for (int i = 0; i < k; i++) {
                vec2 e = (vec2(i, j) + 0.5) / float(k) - 0.5;
                vec2 de = vec2(ca * e.x - sa * e.y, sa * e.x + ca * e.y);
                v += bilineaire(q + de / vec2(sx, sy));
            }
        v /= float(k * k);
    }
    v.a = clamp(v.a, 0.0, 1.0);
    sortie = v;
}
""")

REGLAGES = [p.cle for p in DESCRIPTION.parametres if p.cle not in CADRE]
DEFAUTS = {p.cle: p.defaut for p in DESCRIPTION.parametres}


def id_pour(clip_id: str) -> str:
    """L'identifiant de la transformation d'un clip, connu avant qu'elle n'existe : la section
    de l'inspecteur, les courbes et les modulateurs la visent, le premier réglage la crée."""
    return "tr-" + clip_id


def nouvelle(clip_id: str | None = None) -> Effet:
    return Effet(id_pour(clip_id) if clip_id else nouvel_id(), CLE,
                 {k: DEFAUTS[k] for k in REGLAGES})


def neutre(valeurs: dict) -> bool:
    """Aucun changement de l'image : le composeur n'applique rien."""
    return all(abs(float(valeurs.get(k, DEFAUTS[k])) - DEFAUTS[k]) < 1e-9 for k in REGLAGES)


def cadre(largeur_media: int, hauteur_media: int, largeur: int, hauteur: int) -> dict:
    """Le cadre de l'image du média dans la séquence, en fraction : l'image tient entière,
    centrée, comme la place le composeur."""
    s = min(largeur / largeur_media, hauteur / hauteur_media)
    lp, hp = max(2, round(largeur_media * s)), max(2, round(hauteur_media * s))
    return {"cadre_x": (largeur - lp) // 2 / largeur, "cadre_y": (hauteur - hp) // 2 / hauteur,
            "cadre_l": lp / largeur, "cadre_h": hp / hauteur}


def matrice(valeurs: dict, largeur: int, hauteur: int):
    """La transformation en matrice 3 × 3, du calque (pixels de la séquence, image du clip
    avant transformation) vers l'image de la séquence : le calcul inverse de celui du
    programme. Sert aux poignées et aux masques posés sur l'image."""
    import math

    import numpy as np
    v = {**DEFAUTS, **valeurs}
    sx = v["taille"] * v["largeur"] / 10000.0 * (-1 if v["miroir_h"] > 0.5 else 1)
    sy = v["taille"] * v["hauteur"] / 10000.0 * (-1 if v["miroir_v"] > 0.5 else 1)
    a = math.radians(v["rotation"])
    ca, sa = math.cos(a), math.sin(a)
    cx, cy = largeur / 2, hauteur / 2
    centre = np.array([[1, 0, cx], [0, 1, cy], [0, 0, 1]], float)
    retour = np.array([[1, 0, -cx], [0, 1, -cy], [0, 0, 1]], float)
    echelle = np.diag([sx, sy, 1.0])
    # Sens inverse des aiguilles d'une montre à l'écran (y vers le bas).
    rotation = np.array([[ca, sa, 0], [-sa, ca, 0], [0, 0, 1]], float)
    deplacement = np.array([[1, 0, v["x"] / 100 * largeur], [0, 1, v["y"] / 100 * hauteur],
                            [0, 0, 1]], float)
    return deplacement @ centre @ rotation @ echelle @ retour


def coins(valeurs: dict, largeur: int, hauteur: int) -> list[tuple[float, float]]:
    """Les quatre coins de l'image recadrée, dans le calque (pixels de la séquence) : haut
    gauche, haut droit, bas droit, bas gauche."""
    v = {**DEFAUTS, **valeurs}
    x0, y0 = v["cadre_x"] * largeur, v["cadre_y"] * hauteur
    l, h = v["cadre_l"] * largeur, v["cadre_h"] * hauteur
    g = x0 + l * v["rognage_gauche"] / 100
    d = x0 + l * (1 - v["rognage_droite"] / 100)
    hh = y0 + h * v["rognage_haut"] / 100
    b = y0 + h * (1 - v["rognage_bas"] / 100)
    return [(g, hh), (d, hh), (d, b), (g, b)]
