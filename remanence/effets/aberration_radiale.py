"""Aberration chromatique radiale : comme un objectif bon marché, le rouge et le bleu ne
tombent pas au même endroit, et l'écart grandit en s'éloignant du centre."""

from remanence.effets import DescriptionEffet, Parametre

DESCRIPTION = DescriptionEffet(
    cle="aberration_radiale",
    nom="Aberration radiale",
    famille="Couleur",
    parametres=[Parametre("force", "Force", 0, 100, 40, "%"),
                Parametre("etalement", "Étalement", 0, 100, 30, "%"),
                Parametre("centre_x", "Centre X", 0, 100, 50, "%"),
                Parametre("centre_y", "Centre Y", 0, 100, 50, "%")],
    prereglages={"Objectif bon marché": {"force": 20, "etalement": 0},
                 "Bords irisés": {"force": 50},
                 "Prisme": {"force": 100, "etalement": 80}},
    fragment="""
uniform float p_force;
uniform float p_etalement;
uniform float p_centre_x;
uniform float p_centre_y;

void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    if (p_force <= 0.0) {  // à zéro, l'image reste intacte
        sortie = texelFetch(source, p, 0);
        return;
    }
    float f = p_force / 100.0;
    vec2 centre = vec2(p_centre_x, p_centre_y) / 100.0 * vec2(taille);
    vec2 xy = vec2(p) + 0.5;
    vec2 d = xy - centre;
    float k = 0.035 * f;
    // Étalement : chaque couleur est une traînée le long du rayon, plus qu'un simple décalage.
    int n = 1 + int(p_etalement / 100.0 * 7.0);
    vec4 r = vec4(0.0), b = vec4(0.0);
    for (int i = 0; i < n; i++) {
        float s = k * float(i + 1) / float(n);
        r += lire_lisse(centre + d * (1.0 - s));
        b += lire_lisse(centre + d * (1.0 + s));
    }
    r /= float(n);
    b /= float(n);
    vec4 g = texelFetch(source, p, 0);
    sortie = vec4(r.r, g.g, b.b, max(max(r.a, g.a), b.a));
}
""")
