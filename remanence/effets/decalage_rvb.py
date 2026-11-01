"""Décalage RVB : le rouge et le bleu glissent en sens contraires (prototype Bavure)."""

from remanence.effets import DescriptionEffet, Parametre

DESCRIPTION = DescriptionEffet(
    cle="decalage_rvb",
    nom="Décalage RVB",
    famille="Couleur",
    parametres=[Parametre("force", "Force", 0, 100, 40, "%")],
    prereglages={"Léger": {"force": 20}, "Moyen": {"force": 50}, "Fort": {"force": 90}},
    fragment="""
uniform float p_force;

void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    float f = p_force / 100.0;
    uint n = uint(numero);
    // Au-delà de 50 %, le décalage tremble d'un pixel d'une image à l'autre.
    int tremble = p_force > 50.0 ? int(floor(hasard(1u, n, 0u) * 3.0)) - 1 : 0;
    int d = int(float(taille.x) * 0.03 * f) + tremble;
    int sens = int(floor(hasard(2u, n, 0u) * 3.0)) - 1;
    int dy = int(float(sens) * float(taille.y) * 0.004 * f);
    vec4 r = lire(p - ivec2(d, dy));
    vec4 g = lire(p);
    vec4 b = lire(p + ivec2(d, dy));
    sortie = vec4(r.r, g.g, b.b, max(max(r.a, g.a), b.a));
}
""")
