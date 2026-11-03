"""Grain et bruit : le grain d'une pellicule ou le bruit d'un capteur, renouvelé à chaque image,
plus marqué dans les tons moyens. Couleur ajoute du bruit coloré.

La taille du grain se mesure en pixels d'une image Full HD : il garde la même finesse dans
l'aperçu en demi-résolution et à l'export.
"""

from remanence.effets import DescriptionEffet, Parametre

DESCRIPTION = DescriptionEffet(
    cle="grain",
    nom="Grain et bruit",
    famille="Signal",
    parametres=[Parametre("force", "Force", 0, 100, 40, "%"),
                Parametre("taille", "Taille", 0.5, 4, 1.5, "px", 1),
                Parametre("couleur", "Couleur", 0, 100, 15, "%")],
    prereglages={"Pellicule fine": {"force": 25, "taille": 1},
                 "Pellicule poussée": {"force": 60, "taille": 2.5},
                 "Capteur dans le noir": {"force": 70, "taille": 1, "couleur": 80}},
    fragment="""
uniform float p_force;
uniform float p_taille;
uniform float p_couleur;

// Bruit de valeur : un tirage gaussien à chaque nœud de la grille, lissé entre les nœuds.
float bruit(vec2 q, uint canal) {
    ivec2 i = ivec2(floor(q));
    vec2 t = q - vec2(i);
    t = t * t * (3.0 - 2.0 * t);
    uint n = uint(numero) * 4u + canal;
    float a = hasard_normal(uint(i.x), uint(i.y), n);
    float b = hasard_normal(uint(i.x + 1), uint(i.y), n);
    float c = hasard_normal(uint(i.x), uint(i.y + 1), n);
    float d = hasard_normal(uint(i.x + 1), uint(i.y + 1), n);
    return mix(mix(a, b, t.x), mix(c, d, t.x), t.y);
}

void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    vec4 c = texelFetch(source, p, 0);
    if (p_force <= 0.0 || c.a <= 0.0) {  // à zéro, l'image reste intacte
        sortie = c;
        return;
    }
    float f = p_force / 100.0;
    float grain = max(p_taille, 0.1) * float(taille.x) / 1920.0;
    vec2 q = (vec2(p) + 0.5) / grain;
    vec3 d = c.rgb / c.a;
    float l = clamp(dot(d, vec3(0.299, 0.587, 0.114)), 0.0, 1.0);
    float poids = 0.35 + 0.65 * (1.0 - (2.0 * l - 1.0) * (2.0 * l - 1.0));
    float k = p_couleur / 100.0;
    vec3 n = vec3(bruit(q, 0u)) * (1.0 - 0.5 * k)
             + vec3(bruit(q, 1u), bruit(q, 2u), bruit(q, 3u)) * k;
    d += n * 0.14 * f * poids;
    sortie = vec4(d * c.a, c.a);
}
""")
