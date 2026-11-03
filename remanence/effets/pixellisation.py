"""Pixellisation : l'image en gros carrés de couleur unie. La taille des carrés suit la largeur
de l'image ; Proportion n'en pixellise qu'une partie, tirée au hasard toutes les quelques
images.

La couleur d'un carré est la moyenne de 4 × 4 échantillons : un coût fixe, quelle que soit la
taille du carré.
"""

from remanence.effets import DescriptionEffet, Parametre

DESCRIPTION = DescriptionEffet(
    cle="pixellisation",
    nom="Pixellisation",
    famille="Pixels",
    parametres=[Parametre("force", "Force", 0, 100, 40, "%"),
                Parametre("proportion", "Proportion", 0, 100, 100, "%"),
                Parametre("cadence", "Cadence", 1, 30, 3, "images")],
    prereglages={"Mosaïque fine": {"force": 25},
                 "Censure": {"force": 70},
                 "Pixels épars": {"force": 50, "proportion": 30, "cadence": 2}},
    fragment="""
uniform float p_force;
uniform float p_proportion;
uniform float p_cadence;

void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    if (p_force <= 0.0) {  // à zéro, l'image reste intacte
        sortie = texelFetch(source, p, 0);
        return;
    }
    float f = p_force / 100.0;
    float b = max(1.0, float(taille.x) * (0.004 + 0.12 * f * f));
    ivec2 carre = ivec2(floor((vec2(p) + 0.5) / b));
    uint tirage = uint(numero / max(1, int(p_cadence)));
    if (hasard(uint(carre.x), uint(carre.y), tirage * 3u + 1u) >= p_proportion / 100.0) {
        sortie = texelFetch(source, p, 0);
        return;
    }
    vec2 origine = vec2(carre) * b;
    vec4 somme = vec4(0.0);
    for (int j = 0; j < 4; j++) {
        for (int i = 0; i < 4; i++) {
            somme += lire_lisse(origine + (vec2(i, j) + 0.5) * b / 4.0);
        }
    }
    sortie = somme / 16.0;
}
""")
