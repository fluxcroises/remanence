"""Inversion par bandes : des bandes de l'image passent en négatif, tirées au hasard, et le
tirage change toutes les quelques images."""

from remanence.effets import DescriptionEffet, Parametre

DESCRIPTION = DescriptionEffet(
    cle="inversion_bandes",
    nom="Inversion par bandes",
    famille="Couleur",
    parametres=[Parametre("force", "Force", 0, 100, 40, "%"),
                Parametre("bandes", "Bandes", 2, 64, 12),
                Parametre("cadence", "Cadence", 1, 30, 4, "images"),
                Parametre("vertical", "Vertical", 0, 1, 0, booleen=True)],
    prereglages={"Quelques négatifs": {"force": 20, "bandes": 16, "cadence": 6},
                 "Stroboscope": {"force": 50, "bandes": 4, "cadence": 1},
                 "Code-barres": {"force": 60, "bandes": 48, "cadence": 2, "vertical": 1}},
    fragment="""
uniform float p_force;
uniform float p_bandes;
uniform float p_cadence;
uniform float p_vertical;

void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    vec4 c = texelFetch(source, p, 0);
    bool vertical = p_vertical > 0.5;
    int n = max(1, int(p_bandes));
    int axe = vertical ? p.x : p.y;
    int longueur = vertical ? taille.x : taille.y;
    int bande = min(n - 1, axe * n / longueur);
    uint tirage = uint(numero / max(1, int(p_cadence)));
    // À zéro, aucun tirage n'est sous la force : l'image reste intacte.
    if (hasard(uint(bande), tirage, 5u) < p_force / 100.0) {
        vec3 d = c.a > 0.0 ? c.rgb / c.a : vec3(0.0);
        c.rgb = (1.0 - clamp(d, 0.0, 1.0)) * c.a;
    }
    sortie = c;
}
""")
