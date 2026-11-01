"""Cassette VHS : couleur qui bave, lignes qui ondulent, bruit, bande de tracking (prototype
Bavure)."""

from remanence.effets import DescriptionEffet, Parametre

DESCRIPTION = DescriptionEffet(
    cle="vhs",
    nom="Cassette VHS",
    famille="Signal",
    parametres=[Parametre("force", "Force", 0, 100, 50, "%")],
    prereglages={"Cassette usée": {"force": 30}, "Copie de copie": {"force": 60},
                 "Bande massacrée": {"force": 95}},
    fragment="""
uniform float p_force;

// YCrCb comme OpenCV (BT.601), valeurs de 0 à 1, chrominance centrée sur 0,5.
vec3 vers_ycc(vec3 c) {
    float y = dot(c, vec3(0.299, 0.587, 0.114));
    return vec3(y, (c.r - y) * 0.713 + 0.5, (c.b - y) * 0.564 + 0.5);
}
vec3 vers_rvb(vec3 v) {
    float cr = v.y - 0.5, cb = v.z - 0.5;
    return vec3(v.x + 1.403 * cr, v.x - 0.714 * cr - 0.344 * cb, v.x + 1.773 * cb);
}
vec3 droit(vec4 c) {  // couleur sans la prémultiplication par l'alpha
    return c.a > 0.0 ? c.rgb / c.a : vec3(0.0);
}

vec4 cassette(ivec2 p, float f) {
    uint n = uint(numero);
    int w = taille.x, h = taille.y;
    // Lignes qui ondulent.
    float ondulation = sin(float(p.y) / float(h) * 18.0 + float(numero) * 0.35)
                       * float(w) * 0.003 * f
                       + hasard_normal(uint(p.y), n, 11u) * float(w) * 0.0008 * f;
    vec2 xy = vec2(p) + 0.5 + vec2(ondulation, 0.0);
    vec4 ici = lire_lisse(xy);
    vec3 v = vers_ycc(droit(ici));
    // Couleur floutée à l'horizontale et décalée vers la droite.
    int k = max(1, int(float(w) * 0.02 * f)) * 2 + 1;
    float decalage = float(int(float(w) * 0.006 * f));
    vec2 cc = vec2(0.0);
    for (int i = -k / 2; i <= k / 2; i++) {
        cc += vers_ycc(droit(lire_lisse(xy - vec2(decalage - float(i), 0.0)))).yz;
    }
    v.yz = cc / float(k);
    // Bruit et couleur un peu éteinte.
    v.x += hasard_normal(uint(p.x), uint(p.y), n * 7u + 3u) * 9.0 / 255.0 * f;
    v.yz = 0.5 + (v.yz - 0.5) * (1.0 - 0.25 * f);
    return vec4(clamp(vers_rvb(v), 0.0, 1.0) * ici.a, ici.a);
}

void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    if (p_force <= 0.0) {  // à zéro, l'image reste intacte
        sortie = texelFetch(source, p, 0);
        return;
    }
    float f = p_force / 100.0;
    int w = taille.x, h = taille.y;
    vec4 c = cassette(p, f);
    // Bande de tracking qui remonte lentement.
    if (f > 0.2) {
        int hb = max(2, int(float(h) * 0.04 * f));
        int yb = ((h - (numero * 3) % (h + hb)) % h + h) % h;
        if (p.y >= yb && p.y < yb + hb) {
            ivec2 q = ivec2(((p.x - int(float(w) * 0.03)) % w + w) % w, p.y);
            c = cassette(q, f);
            float bruit = (hasard(uint(p.x), uint(p.y), uint(numero) + 91u) * 100.0 - 40.0) / 255.0;
            c.rgb = clamp(c.rgb + bruit * c.a, 0.0, c.a);
        }
    }
    sortie = c;
}
""")
