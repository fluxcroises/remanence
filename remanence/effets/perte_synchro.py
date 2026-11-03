"""Perte de synchro TV : l'image défile de haut en bas avec la bande noire du retour de
trame, se déchire à l'horizontale près de cette bande et vacille, comme un téléviseur qui
décroche."""

from remanence.effets import DescriptionEffet, Parametre

DESCRIPTION = DescriptionEffet(
    cle="perte_synchro",
    nom="Perte de synchro TV",
    famille="Signal",
    parametres=[Parametre("force", "Force", 0, 100, 50, "%"),
                Parametre("defilement", "Défilement", 0, 100, 40, "%"),
                Parametre("dechirement", "Déchirement", 0, 100, 50, "%")],
    prereglages={"Image qui flotte": {"force": 30, "defilement": 15, "dechirement": 20},
                 "Antenne mal réglée": {"force": 60},
                 "Plus de signal": {"force": 100, "defilement": 80, "dechirement": 90}},
    fragment="""
uniform float p_force;
uniform float p_defilement;
uniform float p_dechirement;

void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    if (p_force <= 0.0) {  // à zéro, l'image reste intacte
        sortie = texelFetch(source, p, 0);
        return;
    }
    float f = p_force / 100.0;
    int w = taille.x, h = taille.y;
    uint n = uint(numero);
    // Défilement vertical : jusqu'à 8 % de la hauteur par image.
    float vitesse = p_defilement / 100.0 * 0.08 * f;
    int decalage = int(float(h) * fract(float(numero) * vitesse + 0.37 * f));
    int y = (p.y + decalage) % h;
    // Bande noire du retour de trame, là où l'image recommence.
    int barre = int(float(h) * 0.07 * f);
    if (y < barre) {
        float bruit = hasard(uint(p.x), uint(p.y), n * 5u + 1u) * 0.08 * f;
        sortie = vec4(vec3(bruit), 1.0);
        return;
    }
    // Déchirement : ondulation lente partout, arrachement sous la bande.
    float t = p_dechirement / 100.0 * f;
    float dx = sin(float(y) / float(h) * 12.566 + float(numero) * 0.7) * 0.015 * t;
    float zone = float(h) * 0.18;
    float pres = float(y - barre);
    if (pres < zone) {
        float u = 1.0 - pres / zone;
        dx += u * u * (0.12 + 0.05 * hasard_normal(uint(y), n, 3u)) * t;
    }
    vec4 c = lire(ivec2(p.x - int(dx * float(w)), y));
    // Vacillement de la lumière.
    c.rgb *= 1.0 - 0.15 * f * hasard(n, 9u, 2u);
    sortie = c;
}
""")
