"""Lignes de balayage assombries et bandes horizontales qui sautent (prototype Bavure)."""

from remanence.effets import DescriptionEffet, Parametre

DESCRIPTION = DescriptionEffet(
    cle="scanlines",
    nom="Scanlines",
    famille="Signal",
    parametres=[Parametre("force", "Force", 0, 100, 40, "%")],
    prereglages={"Discrètes": {"force": 25}, "Écran": {"force": 55}, "Instable": {"force": 90}},
    fragment="""
uniform float p_force;

void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    float f = p_force / 100.0;
    uint n = uint(numero);
    int h = taille.y;
    int dx = 0;
    int bandes = int(p_force / 12.0);
    for (int i = 0; i < bandes; i++) {
        int y = int(hasard(uint(i), n, 1u) * float(h));
        int hb = 1 + int(hasard(uint(i), n, 2u) * float(max(1, h / 30 - 1)));
        if (p.y >= y && p.y < y + hb) {
            dx += int(hasard_normal(uint(i), n, 3u) * float(taille.x) * 0.04 * f);
        }
    }
    vec4 c = lire(p - ivec2(dx, 0));
    int pas = max(2, h / 240);
    if (p.y % (pas * 2) == 0) {
        c.rgb *= 1.0 - 0.45 * f;
    }
    sortie = c;
}
""")
