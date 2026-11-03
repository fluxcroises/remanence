"""Postérisation et tramage : moins de niveaux de couleur, et une trame ordonnée (matrice de
Bayer 8 × 8) qui remplace les dégradés par des motifs de points, comme les vieilles consoles.

La trame se mesure en pixels d'une image Full HD : l'aperçu en demi-résolution et l'export ont
le même motif.
"""

from remanence.effets import DescriptionEffet, Parametre

DESCRIPTION = DescriptionEffet(
    cle="posterisation",
    nom="Postérisation et tramage",
    famille="Couleur",
    parametres=[Parametre("force", "Force", 0, 100, 60, "%"),
                Parametre("tramage", "Tramage", 0, 100, 50, "%"),
                Parametre("trame", "Trame", 1, 8, 2, "px")],
    prereglages={"Affiche": {"force": 60, "tramage": 0},
                 "Console 8 bits": {"force": 80, "tramage": 60, "trame": 3},
                 "Journal": {"force": 95, "tramage": 100, "trame": 2}},
    fragment="""
uniform float p_force;
uniform float p_tramage;
uniform float p_trame;

// Seuil de la matrice de Bayer 8 × 8, de 0 à 1.
float bayer(ivec2 q) {
    int x = q.x & 7, y = q.y & 7;
    int xy = x ^ y;
    int v = ((xy & 1) << 5) | ((x & 1) << 4) | ((xy & 2) << 2) | ((x & 2) << 1)
            | ((xy & 4) >> 1) | ((x & 4) >> 2);
    return (float(v) + 0.5) / 64.0;
}

void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    vec4 c = texelFetch(source, p, 0);
    if (p_force <= 0.0 || c.a <= 0.0) {  // à zéro, l'image reste intacte
        sortie = c;
        return;
    }
    float f = p_force / 100.0;
    float niveaux = max(2.0, round(2.0 + 62.0 * (1.0 - f) * (1.0 - f)));
    float cellule = max(p_trame, 0.01) * float(taille.x) / 1920.0;
    ivec2 q = ivec2(floor((vec2(p) + 0.5) / max(cellule, 0.0001)));
    float seuil = (bayer(q) - 0.5) * p_tramage / 100.0;
    vec3 d = clamp(c.rgb / c.a, 0.0, 1.0);
    d = floor(d * (niveaux - 1.0) + seuil + 0.5) / (niveaux - 1.0);
    sortie = vec4(clamp(d, 0.0, 1.0) * c.a, c.a);
}
""")
