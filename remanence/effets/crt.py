"""Écran CRT : verre bombé, grille de luminophores rouges, verts et bleus, lignes de balayage
et coins assombris d'un vieux téléviseur.

La grille et les lignes se mesurent sur une image Full HD (640 triplets, 540 lignes), sans
descendre sous 3 pixels par triplet et 2 pixels par ligne : en dessous, le motif se brouille.
"""

from remanence.effets import DescriptionEffet, Parametre

DESCRIPTION = DescriptionEffet(
    cle="crt",
    nom="Écran CRT",
    famille="Signal",
    parametres=[Parametre("force", "Force", 0, 100, 60, "%"),
                Parametre("courbure", "Courbure", 0, 100, 40, "%"),
                Parametre("masque", "Luminophores", 0, 100, 60, "%")],
    prereglages={"Moniteur de contrôle": {"force": 40, "courbure": 10, "masque": 40},
                 "Téléviseur du salon": {"force": 70, "courbure": 50},
                 "Borne d'arcade": {"force": 100, "courbure": 70, "masque": 90}},
    fragment="""
uniform float p_force;
uniform float p_courbure;
uniform float p_masque;

void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    if (p_force <= 0.0) {  // à zéro, l'image reste intacte
        sortie = texelFetch(source, p, 0);
        return;
    }
    float f = p_force / 100.0;
    vec2 xy = vec2(p) + 0.5;
    vec2 cc = xy / vec2(taille) * 2.0 - 1.0;
    // Verre bombé : le centre grossit, les bords fuient ; hors du verre, du noir.
    float k = 0.22 * f * p_courbure / 100.0;
    vec2 v = cc * (1.0 + k * dot(cc, cc)) / (1.0 + k);
    if (abs(v.x) > 1.0 || abs(v.y) > 1.0) {
        sortie = vec4(0.0, 0.0, 0.0, 1.0);
        return;
    }
    vec4 c = lire_lisse((v * 0.5 + 0.5) * vec2(taille));
    vec3 d = c.a > 0.0 ? c.rgb / c.a : vec3(0.0);
    // Luminophores : bandes rouge, vert, bleu côte à côte.
    float triplets = min(640.0, float(taille.x) / 3.0);
    int sous = int(floor(xy.x / float(taille.x) * triplets * 3.0)) % 3;
    vec3 grille = vec3(sous == 0 ? 1.0 : 0.0, sous == 1 ? 1.0 : 0.0, sous == 2 ? 1.0 : 0.0);
    vec3 masque = mix(vec3(1.0), 0.4 + grille * 1.2, f * p_masque / 100.0);
    // Lignes de balayage.
    float lignes = min(540.0, float(taille.y) / 2.0);
    float ligne = 0.5 + 0.5 * cos(xy.y / float(taille.y) * lignes * 6.2831853);
    float balayage = mix(1.0, 0.65 + 0.35 * ligne, f);
    // Coins assombris, et un peu de lumière en plus pour compenser la grille.
    float vignette = mix(1.0, clamp(1.0 - 0.3 * dot(v, v) * dot(v, v), 0.0, 1.0), f);
    d = d * masque * balayage * vignette * (1.0 + 0.3 * f);
    sortie = vec4(d * c.a, c.a);
}
""")
