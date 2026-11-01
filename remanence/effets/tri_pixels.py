"""Tri de pixels : dans les zones claires, les pixels de chaque ligne (ou colonne) sont rangés
par luminosité, à la façon de Kim Asendorf (prototype Bavure).

Un groupe de calcul par ligne : la ligne entière tient en mémoire partagée (4096 pixels au plus,
l'UHD compris), triée d'un bloc par un tri bitonique. Clé de tri sur 32 bits : numéro de segment
(12 bits), luminosité (8 bits), position d'origine (12 bits). C'est le tri stable du prototype
(np.lexsort par segment puis luminosité).
"""

from remanence.effets import DescriptionEffet, Parametre

LONGUEUR_MAX = 4096

DESCRIPTION = DescriptionEffet(
    cle="tri_pixels",
    nom="Tri de pixels",
    famille="Pixels",
    parametres=[Parametre("force", "Force", 0, 100, 40, "%"),
                Parametre("vertical", "Vertical", 0, 1, 0, booleen=True)],
    prereglages={"Léger": {"force": 30}, "Fort": {"force": 70},
                 "Vertical": {"force": 60, "vertical": 1}},
    calcul="""
layout(local_size_x = 1024) in;
layout(rgba32f, binding = 0) uniform writeonly image2D resultat;
uniform float p_force;
uniform float p_vertical;
shared uint cles[4096];

void main() {
    bool vertical = p_vertical > 0.5;
    int ligne = int(gl_WorkGroupID.x);
    int n = vertical ? taille.y : taille.x;
    int t = int(gl_LocalInvocationID.x);
    if (n > 4096) {  // au-delà de 4096 pixels par ligne : image laissée telle quelle
        for (int i = t; i < n; i += 1024) {
            ivec2 q = vertical ? ivec2(ligne, i) : ivec2(i, ligne);
            imageStore(resultat, q, texelFetch(source, q, 0));
        }
        return;
    }
    for (int i = t; i < 4096; i += 1024) {
        if (i < n) {
            vec4 c = texelFetch(source, vertical ? ivec2(ligne, i) : ivec2(i, ligne), 0);
            vec3 d = c.a > 0.0 ? c.rgb / c.a : vec3(0.0);
            cles[i] = uint(clamp(round(dot(d, vec3(0.299, 0.587, 0.114)) * 255.0), 0.0, 255.0));
        } else {
            cles[i] = 0xFFFFFFFFu;
        }
    }
    barrier();
    if (t == 0) {
        // Segments : suites de pixels assez clairs ; un pixel sombre est un segment à lui seul.
        int seuil = int(255.0 - p_force * 2.2);
        uint segment = 0u;
        bool precedent = false;
        for (int i = 0; i < n; i++) {
            uint l = cles[i];
            bool clair = int(l) >= seuil;
            if (i > 0 && (!clair || !precedent)) {
                segment++;
            }
            precedent = clair;
            cles[i] = (segment << 20) | (l << 12) | uint(i);
        }
    }
    barrier();
    for (uint k = 2u; k <= 4096u; k <<= 1u) {
        for (uint j = k >> 1u; j > 0u; j >>= 1u) {
            for (uint i = uint(t); i < 4096u; i += 1024u) {
                uint partenaire = i ^ j;
                if (partenaire > i) {
                    uint a = cles[i], b = cles[partenaire];
                    bool croissant = (i & k) == 0u;
                    if ((a > b) == croissant) {
                        cles[i] = b;
                        cles[partenaire] = a;
                    }
                }
            }
            barrier();
        }
    }
    for (int i = t; i < n; i += 1024) {
        int origine = int(cles[i] & 0xFFFu);
        ivec2 qs = vertical ? ivec2(ligne, origine) : ivec2(origine, ligne);
        ivec2 qd = vertical ? ivec2(ligne, i) : ivec2(i, ligne);
        imageStore(resultat, qd, texelFetch(source, qs, 0));
    }
}
""")
