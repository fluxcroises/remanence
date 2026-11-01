"""Composition sur la carte graphique (OpenGL 4.3 hors écran, un contexte par fil d'exécution).

Les plans YUV sont envoyés tels quels, en textures entières : la carte graphique les convertit
avec la matrice et la plage du fichier, comme `couleur.vers_rvba`, puis fusionne les couches de
bas en haut en flottant 32 bits, alpha prémultiplié. On garde 32 bits plutôt que les 16 du cahier
des charges : en 16 bits flottants, une source 12 bits (ProRes 4444) perdrait de la précision.

Sans effet, le résultat est celui du calcul sur le processeur (`Compositeur` sans carte
graphique) : `tests/test_gpu.py` le vérifie au pixel près.
"""

from __future__ import annotations

import os

import av
import numpy as np

from remanence.media.sonde import Couleur
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

# Fusion « normal » d'une couche sur ce qui est dessous, opacité comprise.
FUSION = """
#version 430
uniform sampler2D couche;
uniform sampler2D dessous;
uniform float opacite;
out vec4 sortie;

void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    vec4 c = texelFetch(couche, p, 0) * opacite;
    vec4 d = texelFetch(dessous, p, 0);
    sortie = c + d * (1.0 - c.a);
}
"""


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
                x0: int = 0, y0: int = 0):
        self._convertir(image, couleur, x0, y0)
        couche, _ = self._cible("couche", self._taille)
        dessous, _ = self._cible(f"accu{self._courant}", self._taille)
        _, fbo = self._cible(f"accu{1 - self._courant}", self._taille)
        fbo.use()
        couche.use(0)
        dessous.use(1)
        self._fusion["opacite"].value = float(opacite)
        self._vao_fusion.render(moderngl.TRIANGLE_STRIP)
        self._courant = 1 - self._courant

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
