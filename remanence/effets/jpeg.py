"""Compression JPEG extrême : l'image découpée en blocs, chaque bloc passé en fréquences (DCT
8 × 8) et quantifié par les tables du standard JPEG, comme un fichier enregistré en qualité
très basse.

Un groupe de calcul par bloc. Le bloc mesure 1/240 de la largeur de l'image (8 pixels en Full
HD), multiplié par le réglage Blocs : l'aperçu en demi-résolution et l'export montrent les mêmes
blocs. La luminance et la couleur (YCbCr) ont chacune leur table ; Couleur durcit celle de la
couleur.
"""

import math

from remanence.effets import DescriptionEffet, Parametre

# Tables de quantification de l'annexe K du standard JPEG (ITU-T T.81).
LUMA = [16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55,
        14, 13, 16, 24, 40, 57, 69, 56, 14, 17, 22, 29, 51, 87, 80, 62,
        18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92,
        49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99]
CHROMA = [17, 18, 24, 47, 99, 99, 99, 99, 18, 21, 26, 66, 99, 99, 99, 99,
          24, 26, 56, 99, 99, 99, 99, 99, 47, 66, 99, 99, 99, 99, 99, 99] + [99] * 32


def taille_bloc(largeur: int, blocs: float) -> float:
    return max(2.0, largeur / 240.0 * max(1.0, blocs))


def _groupes(largeur: int, hauteur: int, valeurs: dict) -> tuple[int, int]:
    b = taille_bloc(largeur, valeurs.get("blocs", 1.0))
    return math.ceil(largeur / b), math.ceil(hauteur / b)


def _table(nom: str, valeurs: list[int]) -> str:
    return f"const float {nom}[64] = float[64](" + ", ".join(f"{v}.0" for v in valeurs) + ");\n"


DESCRIPTION = DescriptionEffet(
    cle="jpeg",
    nom="JPEG extrême",
    famille="Corruption",
    parametres=[Parametre("force", "Force", 0, 100, 60, "%"),
                Parametre("blocs", "Blocs", 1, 8, 1, "×", 1),
                Parametre("couleur", "Couleur", 0, 100, 50, "%")],
    prereglages={"Image trop compressée": {"force": 55},
                 "Envoyé dix fois": {"force": 85, "couleur": 80},
                 "Gros carrés": {"force": 90, "blocs": 4, "couleur": 100}},
    groupes=_groupes,
    calcul="""
layout(local_size_x = 8, local_size_y = 8) in;
layout(rgba32f, binding = 0) uniform writeonly image2D resultat;
uniform float p_force;
uniform float p_blocs;
uniform float p_couleur;
shared vec3 bloc[64];
shared vec3 coef[64];
""" + _table("LUMA", LUMA) + _table("CHROMA", CHROMA) + """
const float PI = 3.14159265358979;

float a_dct(int u) {
    return u == 0 ? 0.70710678 : 1.0;
}
// Y, Cb, Cr de 0 à 255, comme dans un fichier JPEG (BT.601, pleine plage).
vec3 vers_ycc(vec3 c) {
    float y = dot(c, vec3(0.299, 0.587, 0.114));
    return vec3(y, (c.b - y) * 0.564 + 0.5, (c.r - y) * 0.713 + 0.5) * 255.0;
}
vec3 vers_rvb(vec3 v) {
    v /= 255.0;
    float cb = v.y - 0.5, cr = v.z - 0.5;
    return vec3(v.x + 1.403 * cr, v.x - 0.344 * cb - 0.714 * cr, v.x + 1.773 * cb);
}
// Pas de quantification pour une qualité de 1 à 100 (formule de la bibliothèque libjpeg).
float pas(float base, float qualite) {
    float s = qualite < 50.0 ? 5000.0 / qualite : 200.0 - 2.0 * qualite;
    return max(1.0, floor((base * s + 50.0) / 100.0));
}

void main() {
    float b = max(2.0, float(taille.x) / 240.0 * max(1.0, p_blocs));
    ivec2 t = ivec2(gl_LocalInvocationID.xy);
    int i = t.y * 8 + t.x;
    vec2 origine = vec2(gl_WorkGroupID.xy) * b;
    // Les pixels dont le centre tombe dans le bloc.
    ivec2 p0 = ivec2(ceil(origine - 0.5));
    ivec2 p1 = min(ivec2(ceil(origine + b - 0.5)), taille);
    if (p_force <= 0.0) {  // à zéro, l'image reste intacte
        for (int y = p0.y + t.y; y < p1.y; y += 8) {
            for (int x = p0.x + t.x; x < p1.x; x += 8) {
                imageStore(resultat, ivec2(x, y), texelFetch(source, ivec2(x, y), 0));
            }
        }
        return;
    }
    float f = p_force / 100.0;
    // Le bloc ramené à 8 × 8 échantillons (les pixels eux-mêmes quand il en mesure 8).
    vec4 c = lire_lisse(origine + (vec2(t) + 0.5) * b / 8.0);
    bloc[i] = vers_ycc(c.a > 0.0 ? c.rgb / c.a : vec3(0.0)) - 128.0;
    barrier();
    vec3 s = vec3(0.0);
    for (int y = 0; y < 8; y++) {
        for (int x = 0; x < 8; x++) {
            s += bloc[y * 8 + x] * cos(float(2 * x + 1) * float(t.x) * PI / 16.0)
                                 * cos(float(2 * y + 1) * float(t.y) * PI / 16.0);
        }
    }
    s *= 0.25 * a_dct(t.x) * a_dct(t.y);
    float qualite = max(1.0, 100.0 - 99.0 * pow(f, 0.6));
    float durcir = 1.0 + 3.0 * p_couleur / 100.0;
    vec3 q = vec3(pas(LUMA[i], qualite), pas(CHROMA[i] * durcir, qualite),
                  pas(CHROMA[i] * durcir, qualite));
    coef[i] = round(s / q) * q;
    barrier();
    for (int y = p0.y + t.y; y < p1.y; y += 8) {
        for (int x = p0.x + t.x; x < p1.x; x += 8) {
            // Position du pixel dans la grille 8 × 8 du bloc.
            vec2 g = (vec2(x, y) + 0.5 - origine) / b * 8.0 - 0.5;
            vec3 v = vec3(0.0);
            for (int fv = 0; fv < 8; fv++) {
                float cy = a_dct(fv) * cos((2.0 * g.y + 1.0) * float(fv) * PI / 16.0);
                for (int fu = 0; fu < 8; fu++) {
                    v += coef[fv * 8 + fu] * cy * a_dct(fu)
                         * cos((2.0 * g.x + 1.0) * float(fu) * PI / 16.0);
                }
            }
            vec3 rvb = clamp(vers_rvb(v * 0.25 + 128.0), 0.0, 1.0);
            float a = texelFetch(source, ivec2(x, y), 0).a;
            imageStore(resultat, ivec2(x, y), vec4(rvb * a, a));
        }
    }
}
""")
