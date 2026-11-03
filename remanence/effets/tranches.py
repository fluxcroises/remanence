"""Tranches décalées : l'image coupée en tranches qui glissent chacune de son côté, d'une part
de la largeur tirée au hasard ; le tirage change toutes les quelques images."""

from remanence.effets import DescriptionEffet, Parametre

DESCRIPTION = DescriptionEffet(
    cle="tranches",
    nom="Tranches décalées",
    famille="Pixels",
    parametres=[Parametre("force", "Force", 0, 100, 40, "%"),
                Parametre("tranches", "Tranches", 2, 80, 24),
                Parametre("proportion", "Proportion", 0, 100, 60, "%"),
                Parametre("cadence", "Cadence", 1, 30, 2, "images"),
                Parametre("vertical", "Vertical", 0, 1, 0, booleen=True)],
    prereglages={"Légère cassure": {"force": 15, "proportion": 30},
                 "Image en lamelles": {"force": 50, "tranches": 40, "proportion": 80},
                 "Coupe franche": {"force": 90, "tranches": 6, "proportion": 50, "cadence": 6}},
    fragment="""
uniform float p_force;
uniform float p_tranches;
uniform float p_proportion;
uniform float p_cadence;
uniform float p_vertical;

void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    if (p_force <= 0.0) {  // à zéro, l'image reste intacte
        sortie = texelFetch(source, p, 0);
        return;
    }
    bool vertical = p_vertical > 0.5;
    int n = max(1, int(p_tranches));
    int axe = vertical ? p.x : p.y;
    int longueur = vertical ? taille.x : taille.y;
    int tranche = min(n - 1, axe * n / longueur);
    uint tirage = uint(numero / max(1, int(p_cadence)));
    ivec2 d = ivec2(0);
    if (hasard(uint(tranche), tirage, 7u) < p_proportion / 100.0) {
        // Jusqu'à un quart de la largeur (ou de la hauteur), dans un sens ou dans l'autre.
        float part = (hasard(uint(tranche), tirage, 8u) * 2.0 - 1.0) * 0.25 * p_force / 100.0;
        int pas = int(round(part * float(vertical ? taille.y : taille.x)));
        d = vertical ? ivec2(0, pas) : ivec2(pas, 0);
    }
    sortie = lire(p - d);
}
""")
