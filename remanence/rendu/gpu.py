"""Composition sur la carte graphique (OpenGL 4.3 hors écran, un contexte par fil d'exécution).

Les plans YUV sont envoyés tels quels, en textures entières : la carte graphique les convertit
avec la matrice et la plage du fichier, comme `couleur.vers_rvba`, puis fusionne les couches de
bas en haut en flottant 32 bits, alpha prémultiplié. On garde 32 bits plutôt que les 16 du cahier
des charges : en 16 bits flottants, une source 12 bits (ProRes 4444) perdrait de la précision.

Sans effet, le résultat est celui du calcul sur le processeur (`Compositeur` sans carte
graphique) : `tests/test_gpu.py` le vérifie au pixel près.
"""

from __future__ import annotations

import os

import av
import numpy as np

from remanence.effets import COMMUN, EFFETS, valeur
from remanence.media.sonde import Couleur
from remanence.projet.modele import Effet
from remanence.rendu.couleur import _est_yuv, _plage_complete, _plans, coefficients

try:
    import moderngl
except ImportError:  # pragma: no cover
    moderngl = None

SOMMETS = """
#version 430
in vec2 pos;
void main() { gl_Position = vec4(pos, 0.0, 1.0); }
"""

# Une texture entière par plan : texelFetch rend la valeur exacte du fichier.
VERS_RVBA = """
#version 430
uniform usampler2D plan_y;
uniform usampler2D plan_u;
uniform usampler2D plan_v;
uniform usampler2D plan_a;
uniform int yuv;            // 0 : RVBA 16 bits déjà converti (formats RVB)
uniform int a_alpha;
uniform ivec2 sous_ech;     // sous-échantillonnage de la chrominance (x, y)
uniform ivec2 decalage;     // position de la couche dans l'image (couche plus petite, centrée)
uniform ivec2 taille;       // taille de la couche
uniform float y0, ydiv, c0, cdiv, amax;
uniform float cv, cu, kr, kb, kg;
out vec4 sortie;

void main() {
    ivec2 p = ivec2(gl_FragCoord.xy) - decalage;
    if (p.x < 0 || p.y < 0 || p.x >= taille.x || p.y >= taille.y) {
        sortie = vec4(0.0);
        return;
    }
    if (yuv == 0) {
        vec4 v = vec4(texelFetch(plan_y, p, 0)) / 65535.0;
        sortie = vec4(v.rgb * v.a, v.a);
        return;
    }
    ivec2 pc = p / sous_ech;
    float y = (float(texelFetch(plan_y, p, 0).r) - y0) / ydiv;
    float u = (float(texelFetch(plan_u, pc, 0).r) - c0) / cdiv;
    float v = (float(texelFetch(plan_v, pc, 0).r) - c0) / cdiv;
    float r = y + cv * v;
    float b = y + cu * u;
    float g = (y - kr * r - kb * b) / kg;
    float a = 1.0;
    if (a_alpha == 1) {
        a = float(texelFetch(plan_a, p, 0).r) / amax;
    }
    sortie = vec4(vec3(r, g, b) * a, a);
}
"""

# Fusion d'une couche sur ce qui est dessous, opacité comprise. Mode dosage : un effet ou un
# clip d'effet mêle l'image transformée à l'image qu'il a reçue, selon son opacité.
# Modes autres que normal : formules du W3C (Compositing and Blending), sur les couleurs sans
# prémultiplication ; « luminosité seule » et « couleur seule » sont ses modes luminosity et color.
FUSION = """
#version 430
uniform sampler2D couche;
uniform sampler2D dessous;
uniform float opacite;
uniform int dosage;
uniform int mode;
out vec4 sortie;

float lum(vec3 c) { return dot(c, vec3(0.3, 0.59, 0.11)); }
vec3 ramener(vec3 c) {
    float l = lum(c);
    float n = min(c.r, min(c.g, c.b));
    float x = max(c.r, max(c.g, c.b));
    if (n < 0.0) c = l + (c - l) * l / (l - n);
    if (x > 1.0) c = l + (c - l) * (1.0 - l) / (x - l);
    return c;
}
vec3 avec_lum(vec3 c, float l) { return ramener(c + (l - lum(c))); }

vec3 melange(vec3 b, vec3 s) {
    if (mode == 1) return b + s;
    if (mode == 2) return b + s - b * s;
    if (mode == 3) return b * s;
    if (mode == 4) return abs(b - s);
    if (mode == 5) return avec_lum(b, lum(s));
    if (mode == 6) return avec_lum(s, lum(b));
    return s;
}

void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    vec4 c = texelFetch(couche, p, 0);
    vec4 d = texelFetch(dessous, p, 0);
    if (mode == 0) {
        if (dosage == 1) {
            sortie = mix(d, c, opacite);
        } else {
            c *= opacite;
            sortie = c + d * (1.0 - c.a);
        }
        return;
    }
    if (dosage == 0) {
        c *= opacite;
    }
    vec3 cs = c.a > 0.0 ? c.rgb / c.a : vec3(0.0);
    vec3 cb = d.a > 0.0 ? d.rgb / d.a : vec3(0.0);
    vec4 r = vec4(c.rgb * (1.0 - d.a) + d.rgb * (1.0 - c.a) + c.a * d.a * melange(cb, cs),
                  c.a + d.a - c.a * d.a);
    sortie = dosage == 1 ? mix(d, r, opacite) : r;
}
"""

INDEX_MODES = {"normal": 0, "addition": 1, "ecran": 2, "produit": 3, "difference": 4,
               "luminosite": 5, "couleur": 6}


def gpu_demande() -> bool:
    """REMANENCE_RENDU=cpu force le calcul sur le processeur (comparaisons, dépannage)."""
    return moderngl is not None and os.environ.get("REMANENCE_RENDU", "").lower() != "cpu"


class RenduGPU:
    """Contexte OpenGL hors écran et ses programmes. À créer et utiliser dans un seul fil."""

    def __init__(self):
        self.ctx = moderngl.create_standalone_context(require=430)
        quad = np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype="f4")
        self._vbo = self.ctx.buffer(quad.tobytes())
        self._conv = self.ctx.program(vertex_shader=SOMMETS, fragment_shader=VERS_RVBA)
        self._fusion = self.ctx.program(vertex_shader=SOMMETS, fragment_shader=FUSION)
        self._vao_conv = self.ctx.vertex_array(self._conv, [(self._vbo, "2f", "pos")])
        self._vao_fusion = self.ctx.vertex_array(self._fusion, [(self._vbo, "2f", "pos")])
        for nom, unite in (("plan_y", 0), ("plan_u", 1), ("plan_v", 2), ("plan_a", 3)):
            self._conv[nom].value = unite
        self._fusion["couche"].value = 0
        self._fusion["dessous"].value = 1
        self._textures: dict[tuple, moderngl.Texture] = {}
        self._cibles: dict[tuple, tuple] = {}
        self._programmes: dict[str, tuple] = {}
        self._taille = (0, 0)
        self._courant = 0

    def fermer(self):
        self.ctx.release()

    def _texture(self, cle: str, taille: tuple[int, int], composantes: int,
                 dtype: str) -> moderngl.Texture:
        k = (cle, taille, composantes, dtype)
        t = self._textures.get(k)
        if t is None:
            t = self.ctx.texture(taille, composantes, dtype=dtype, alignment=1)
            t.filter = (moderngl.NEAREST, moderngl.NEAREST)
            self._textures[k] = t
        return t

    def _cible(self, nom: str, taille: tuple[int, int]):
        k = (nom, taille)
        if k not in self._cibles:
            t = self.ctx.texture(taille, 4, dtype="f4")
            t.filter = (moderngl.NEAREST, moderngl.NEAREST)
            self._cibles[k] = (t, self.ctx.framebuffer(color_attachments=[t]))
        return self._cibles[k]

    # Une image : commencer, ajouter les couches de bas en haut, lire.

    def commencer(self, largeur: int, hauteur: int):
        self._taille = (largeur, hauteur)
        self._courant = 0
        _, fbo = self._cible("accu0", self._taille)
        fbo.use()
        self.ctx.viewport = (0, 0, largeur, hauteur)
        fbo.clear(0.0, 0.0, 0.0, 0.0)

    def ajouter(self, image: av.VideoFrame, couleur: Couleur, opacite: float,
                x0: int = 0, y0: int = 0, effets: list[Effet] = (), numero: int = 0,
                fusion: str = "normal"):
        """Une couche de média : conversion, ses effets (clip puis piste), fusion dessus."""
        self._convertir(image, couleur, x0, y0)
        couche = self.effets("couche", effets, numero)
        self._fusionner(couche, opacite, dosage=False, fusion=fusion)

    def effet_dessous(self, effets: list[Effet], opacite: float, numero: int,
                      fusion: str = "normal"):
        """Clip d'effet : transforme tout ce qui est dessous, dosé par son opacité."""
        if not any(e.actif for e in effets):
            return
        self._copier(f"accu{self._courant}", "couche")
        couche = self.effets("couche", effets, numero)
        self._fusionner(couche, opacite, dosage=True, fusion=fusion)

    def _fusionner(self, nom_couche: str, opacite: float, dosage: bool, fusion: str = "normal"):
        _, fbo = self._cible(f"accu{1 - self._courant}", self._taille)
        self._melanger(nom_couche, f"accu{self._courant}", fbo, opacite, dosage, fusion)
        self._courant = 1 - self._courant

    def _melanger(self, nom_couche: str, nom_dessous: str, fbo, opacite: float, dosage: bool,
                  fusion: str):
        couche, _ = self._cible(nom_couche, self._taille)
        dessous, _ = self._cible(nom_dessous, self._taille)
        fbo.use()
        self.ctx.viewport = (0, 0, *self._taille)
        couche.use(0)
        dessous.use(1)
        self._fusion["opacite"].value = float(opacite)
        self._fusion["dosage"].value = int(dosage)
        self._fusion["mode"].value = INDEX_MODES.get(fusion, 0)
        self._vao_fusion.render(moderngl.TRIANGLE_STRIP)

    def _copier(self, de: str, vers: str):
        self.ctx.copy_framebuffer(self._cible(vers, self._taille)[1],
                                  self._cible(de, self._taille)[1])

    # Effets

    def effets(self, nom: str, effets: list[Effet], numero: int) -> str:
        """Applique les effets actifs, dans l'ordre, à la texture nom ; renvoie le nom de la
        texture qui porte le résultat (nom ou son double, nom + "_b")."""
        noms = [nom, nom + "_b", nom + "_c"]
        courant = nom
        for effet in effets:
            if not effet.actif or effet.type not in EFFETS:
                continue
            sortie = next(n for n in noms if n != courant)
            self._effet(effet, courant, sortie, numero)
            if effet.opacite < 1.0 or effet.fusion != "normal":
                # L'effet dosé ou mêlé à l'image qu'il a reçue.
                melange = next(n for n in noms if n not in (courant, sortie))
                _, fbo = self._cible(melange, self._taille)
                self._melanger(sortie, courant, fbo, effet.opacite, True, effet.fusion)
                sortie = melange
            courant = sortie
        return courant

    def _programme(self, cle: str):
        if cle not in self._programmes:
            d = EFFETS[cle]
            entete = "#version 430\n" + COMMUN
            if d.calcul:
                prog = self.ctx.compute_shader(entete + d.calcul)
                self._programmes[cle] = (prog, None)
            else:
                prog = self.ctx.program(vertex_shader=SOMMETS,
                                        fragment_shader=entete + "out vec4 sortie;\n" + d.fragment)
                vao = self.ctx.vertex_array(prog, [(self._vbo, "2f", "pos")])
                self._programmes[cle] = (prog, vao)
        return self._programmes[cle]

    def _effet(self, effet: Effet, de: str, vers: str, numero: int):
        d = EFFETS[effet.type]
        prog, vao = self._programme(effet.type)
        source, _ = self._cible(de, self._taille)
        cible, fbo = self._cible(vers, self._taille)
        source.use(0)
        reglages = {"source": 0, "taille": self._taille, "numero": int(numero),
                    "graine": int(effet.graine) & 0xFFFFFFFF}
        for p in d.parametres:
            reglages[f"p_{p.cle}"] = float(valeur(effet, p.cle))
        for nom, val in reglages.items():
            # Le compilateur retire les réglages inutilisés : ils n'existent plus dans le programme.
            if nom in prog:
                prog[nom].value = val
        if vao is None:
            cible.bind_to_image(0, read=False, write=True)
            l, h = self._taille
            vertical = (any(p.cle == "vertical" for p in d.parametres)
                        and float(valeur(effet, "vertical")) > 0.5)
            prog.run(group_x=l if vertical else h)
            self.ctx.memory_barrier()
        else:
            fbo.use()
            self.ctx.viewport = (0, 0, *self._taille)
            vao.render(moderngl.TRIANGLE_STRIP)

    def effets_sequence(self, effets: list[Effet], numero: int):
        """Effets de séquence, sur l'image entière, après toutes les pistes."""
        nom = f"accu{self._courant}"
        resultat = self.effets(nom, effets, numero)
        if resultat != nom:
            self._copier(resultat, nom)

    def traiter(self, rvba: np.ndarray, effets: list[Effet], numero: int) -> np.ndarray:
        """Effets appliqués à une image en mémoire (H×L×4 float32 prémultiplié) : vignettes
        de la bibliothèque d'effets."""
        h, l = rvba.shape[:2]
        self._taille = (l, h)
        couche, _ = self._cible("couche", self._taille)
        couche.write(np.ascontiguousarray(rvba, dtype=np.float32).tobytes())
        resultat = self.effets("couche", effets, numero)
        _, fbo = self._cible(resultat, self._taille)
        brut = fbo.read(components=4, dtype="f4", alignment=1)
        return np.frombuffer(brut, np.float32).reshape(h, l, 4).copy()

    def lire(self) -> np.ndarray:
        """L'image composée, H×L×4 float32, première ligne en haut."""
        _, fbo = self._cible(f"accu{self._courant}", self._taille)
        l, h = self._taille
        brut = fbo.read(components=4, dtype="f4", alignment=1)
        return np.frombuffer(brut, np.float32).reshape(h, l, 4).copy()

    def _convertir(self, image: av.VideoFrame, couleur: Couleur, x0: int, y0: int):
        fmt = image.format
        h, l = image.height, image.width
        prog = self._conv
        prog["decalage"].value = (x0, y0)
        prog["taille"].value = (l, h)
        if not _est_yuv(fmt) or len(image.planes) < 3:
            brut = np.ascontiguousarray(image.reformat(format="rgba64le").to_ndarray())
            t = self._texture("rvba", (l, h), 4, "u2")
            t.write(brut.tobytes())
            t.use(0)
            prog["yuv"].value = 0
        else:
            bits = max(c.bits for c in fmt.components)
            dtype = "u2" if bits > 8 else "u1"
            plans = _plans(image)
            for i, plan in enumerate(plans[:4]):
                ph, pl = plan.shape
                t = self._texture(f"plan{i}", (pl, ph), 1, dtype)
                t.write(np.ascontiguousarray(plan).tobytes())
                t.use(i)
            alpha = len(plans) >= 4 and any(c.is_alpha for c in fmt.components)
            if not alpha:
                self._texture("plan0", (l, h), 1, dtype).use(3)
            ch, cl = plans[1].shape
            # Mêmes valeurs, calculées de la même façon, que dans couleur.vers_rvba.
            echelle = float(1 << (bits - 8))
            maxv = float((1 << bits) - 1)
            if _plage_complete(fmt, couleur):
                y0v, ydiv, c0, cdiv = 0.0, maxv, 128.0 * echelle, maxv
            else:
                y0v, ydiv = 16.0 * echelle, 219.0 * echelle
                c0, cdiv = 128.0 * echelle, 224.0 * echelle
            kr, kb = coefficients(couleur.matrice, h)
            for nom, val in (("y0", y0v), ("ydiv", ydiv), ("c0", c0), ("cdiv", cdiv),
                             ("amax", maxv), ("cv", 2.0 * (1.0 - kr)), ("cu", 2.0 * (1.0 - kb)),
                             ("kr", kr), ("kb", kb), ("kg", 1.0 - kr - kb)):
                prog[nom].value = val
            prog["sous_ech"].value = (-(-l // cl), -(-h // ch))
            prog["a_alpha"].value = int(alpha)
            prog["yuv"].value = 1
        _, fbo = self._cible("couche", self._taille)
        fbo.use()
        self._vao_conv.render(moderngl.TRIANGLE_STRIP)
