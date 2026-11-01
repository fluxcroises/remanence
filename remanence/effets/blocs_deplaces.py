"""Blocs de l'image recopiés ailleurs, parfois avec leurs couleurs permutées (prototype Bavure)."""

from remanence.effets import DescriptionEffet, Parametre

DESCRIPTION = DescriptionEffet(
    cle="blocs_deplaces",
    nom="Blocs déplacés",
    famille="Corruption",
    parametres=[Parametre("force", "Force", 0, 100, 40, "%")],
    prereglages={"Quelques éclats": {"force": 20}, "Blocs en fuite": {"force": 50},
                 "Mosaïque brisée": {"force": 90}},
    fragment="""
uniform float p_force;

vec3 permuter(vec3 c, int k) {
    if (k == 0) return c.rgb;
    if (k == 1) return c.rbg;
    if (k == 2) return c.grb;
    if (k == 3) return c.gbr;
    if (k == 4) return c.brg;
    return c.bgr;
}

void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    uint n = uint(numero);
    int w = taille.x, h = taille.y;
    int cote = max(8, w / 40);
    vec4 c = texelFetch(source, p, 0);
    // Chaque bloc recouvre les précédents : le dernier qui contient le pixel l'emporte.
    for (int i = int(p_force * 0.6) - 1; i >= 0; i--) {
        uint k = uint(i);
        int bw = cote * (1 + int(hasard(k, n, 1u) * 5.0));
        int bh = cote * (1 + int(hasard(k, n, 2u) * 2.0));
        int x = int(hasard(k, n, 3u) * float(max(1, w - bw)));
        int y = int(hasard(k, n, 4u) * float(max(1, h - bh)));
        if (p.x >= x && p.x < x + bw && p.y >= y && p.y < y + bh) {
            float x2 = clamp(float(x) + hasard_normal(k, n, 5u) * float(w) * 0.08,
                             0.0, float(max(0, w - bw)));
            float y2 = clamp(float(y) + hasard_normal(k, n, 6u) * float(h) * 0.02,
                             0.0, float(max(0, h - bh)));
            c = lire_borne(ivec2(int(x2), int(y2)) + p - ivec2(x, y));
            if (hasard(k, n, 7u) < 0.3) {
                c.rgb = permuter(c.rgb, int(hasard(k, n, 8u) * 6.0));
            }
            break;
        }
    }
    sortie = c;
}
""")
