"""Transitions glitch et volets : l'allure d'un fondu d'entrée (`Clip.style_fondu`).

Le fondu enchaîné reste le geste de Vegas : deux clips qui se chevauchent sur une piste, ou un
clip qui apparaît sur ce qui est dessous. Le style change seulement la façon dont le clip
entre : au lieu d'un mélange, il arrive par un volet, par blocs, dans un décalage RVB ou après
une coupure de signal. Les deux derniers abîment aussi le clip qui sort.

Les programmes sont des effets en temps réel internes : ils ne paraissent ni dans la
bibliothèque ni dans les menus. Pendant le fondu, le composeur les ajoute aux effets des deux
clips, avec l'avancée du fondu (`effets_du_fondu`).
"""

from __future__ import annotations

import zlib

from remanence.effets import DescriptionEffet, Parametre
from remanence.projet.modele import Clip, Effet

TYPES = {"volet": "Volet", "blocs": "Blocs", "rvb": "Décalage RVB",
         "coupure": "Coupure de signal"}
DIRECTIONS = ["Vers la droite", "Vers la gauche", "Vers le bas", "Vers le haut",
              "Depuis le centre"]
DEFAUTS = {"volet": {"direction": 0, "adoucissement": 4}, "blocs": {"blocs": 16},
           "rvb": {}, "coupure": {}}


def nouveau_style(type_: str) -> dict:
    return {"type": type_, **DEFAUTS[type_]}


def actif(c: Clip, decalage: int) -> bool:
    """Le style s'applique-t-il à cette image du clip (decalage depuis son début) ?"""
    return (c.style_fondu is not None and c.style_fondu.get("type") in TYPES
            and 0 <= decalage < c.fondu_entree)


def effets_du_fondu(c: Clip, decalage: int) -> tuple[float, list[Effet], list[Effet]]:
    """(opacité du clip qui entre, hors fondu ; effets qui s'ajoutent aux siens ; effets du clip
    qui sort). L'avancée suit celle du fondu ordinaire."""
    style = c.style_fondu
    t = (decalage + 1) / (c.fondu_entree + 1)
    graine = zlib.crc32(c.id.encode())

    def effet(type_: str, **params) -> Effet:
        return Effet(f"fondu-{c.id}", type_, params, graine=graine)

    if style["type"] == "volet":
        return 1.0, [effet("tr_volet", progression=t * 100,
                           direction=style.get("direction", 0),
                           adoucissement=style.get("adoucissement", 4))], []
    if style["type"] == "blocs":
        return 1.0, [effet("tr_blocs", progression=t * 100,
                           blocs=style.get("blocs", 16))], []
    # Décalage RVB et coupure : le clip qui sort s'abîme jusqu'au milieu du fondu, puis le clip
    # qui entre prend la place, abîmé lui aussi, et se répare.
    entre = 1.0 if t >= 0.5 else 0.0
    if style["type"] == "rvb":
        k = (1 - abs(2 * t - 1)) * 100
        return entre, [effet("tr_rvb", intensite=k)], [effet("tr_rvb", intensite=k)]
    return entre, [effet("tr_coupure", intensite=min(1.0, 2 * (1 - t)) * 100)], \
        [effet("tr_coupure", intensite=min(1.0, 2 * t) * 100)]


VOLET = DescriptionEffet(
    cle="tr_volet",
    nom="Volet",
    famille="Transitions",
    interne=True,
    parametres=[Parametre("progression", "Avancée", 0, 100, 50, "%"),
                Parametre("direction", "Direction", 0, 4, 0),
                Parametre("adoucissement", "Adoucissement", 0, 50, 4, "%")],
    fragment="""
uniform float p_progression;
uniform float p_direction;
uniform float p_adoucissement;

void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    vec4 c = texelFetch(source, p, 0);
    vec2 uv = (vec2(p) + 0.5) / vec2(taille);
    int d = int(p_direction + 0.5);
    float u;
    if (d == 0) {
        u = uv.x;
    } else if (d == 1) {
        u = 1.0 - uv.x;
    } else if (d == 2) {
        u = uv.y;
    } else if (d == 3) {
        u = 1.0 - uv.y;
    } else {  // un cercle qui s'ouvre depuis le centre, à l'échelle de l'image
        float r = float(taille.x) / float(taille.y);
        u = length((uv - 0.5) * vec2(r, 1.0)) / length(vec2(0.5 * r, 0.5));
    }
    float s = max(p_adoucissement / 100.0, 0.0001);
    float bord = p_progression / 100.0 * (1.0 + s);
    sortie = c * clamp((bord - u) / s, 0.0, 1.0);
}
""")

BLOCS = DescriptionEffet(
    cle="tr_blocs",
    nom="Blocs",
    famille="Transitions",
    interne=True,
    parametres=[Parametre("progression", "Avancée", 0, 100, 50, "%"),
                Parametre("blocs", "Blocs", 4, 64, 16)],
    fragment="""
uniform float p_progression;
uniform float p_blocs;

void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    float b = float(taille.x) / max(p_blocs, 1.0);
    ivec2 k = ivec2(floor((vec2(p) + 0.5) / b));
    float arrivee = hasard(uint(k.x), uint(k.y), 21u);
    float t = p_progression / 100.0;
    if (arrivee >= t) {  // ce bloc n'est pas encore là
        sortie = vec4(0.0);
        return;
    }
    if (t - arrivee < 0.12) {  // tout juste arrivé : il tremble de côté
        float h = hasard(uint(k.x), uint(k.y), uint(numero) * 2u + 41u) * 2.0 - 1.0;
        sortie = lire(p + ivec2(int(h * b * 2.0), 0));
        return;
    }
    sortie = texelFetch(source, p, 0);
}
""")

RVB = DescriptionEffet(
    cle="tr_rvb",
    nom="Décalage RVB",
    famille="Transitions",
    interne=True,
    parametres=[Parametre("intensite", "Intensité", 0, 100, 50, "%")],
    fragment="""
uniform float p_intensite;

void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    if (p_intensite <= 0.0) {
        sortie = texelFetch(source, p, 0);
        return;
    }
    float f = p_intensite / 100.0;
    uint n = uint(numero);
    int d = int(float(taille.x) * 0.08 * f) + int(floor(hasard(1u, n, 3u) * 3.0)) - 1;
    int bande = p.y * 12 / taille.y;
    int dx = int((hasard(uint(bande), n, 4u) * 2.0 - 1.0) * float(taille.x) * 0.05 * f * f);
    ivec2 q = p - ivec2(dx, 0);
    vec4 r = lire(q - ivec2(d, 0));
    vec4 g = lire(q);
    vec4 b = lire(q + ivec2(d, 0));
    sortie = vec4(r.r, g.g, b.b, max(max(r.a, g.a), b.a));
}
""")

COUPURE = DescriptionEffet(
    cle="tr_coupure",
    nom="Coupure de signal",
    famille="Transitions",
    interne=True,
    parametres=[Parametre("intensite", "Intensité", 0, 100, 50, "%")],
    fragment="""
uniform float p_intensite;

void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    if (p_intensite <= 0.0) {
        sortie = texelFetch(source, p, 0);
        return;
    }
    float f = p_intensite / 100.0;
    uint n = uint(numero);
    // L'image saute à la verticale et se délave.
    int dy = int(float(taille.y) * (hasard(n, 7u, 1u) * 2.0 - 1.0) * 0.15 * f * f);
    vec4 c = lire(p + ivec2(0, dy));
    vec3 d = c.a > 0.0 ? c.rgb / c.a : vec3(0.0);
    d = mix(d, vec3(dot(d, vec3(0.299, 0.587, 0.114))), f);
    // Neige, lignes perdues, puis le noir.
    float neige = hasard(uint(p.x), uint(p.y), n * 3u + 2u);
    d = mix(d, vec3(neige), clamp(f * f * 1.2, 0.0, 1.0));
    int ligne = p.y * 90 / taille.y;
    if (hasard(uint(ligne), n, 9u) < f * 0.5) {
        d = vec3(neige * 0.5);
    }
    d *= 1.0 - 0.6 * f * f * f;
    sortie = vec4(d * c.a, c.a);
}
""")
