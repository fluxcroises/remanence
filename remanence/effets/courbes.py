"""Courbes d'images clés : [[temps, valeur, passage, poignées], ...], triées par temps.

Le passage d'une image clé règle le segment jusqu'à la suivante :
- « lineaire » : droite ;
- « palier » : la valeur tient jusqu'à l'image clé suivante ;
- « lisse » : départ et arrivée en douceur ;
- « bezier » : courbe de Bézier réglée par les poignées des deux images clés.

Les poignées sont facultatives : {"g": [dt, dv], "d": [dt, dv]}, décalages depuis l'image
clé (vers la gauche et vers la droite). Sans poignée, la courbe part et arrive à plat, au tiers
du segment. Une valeur peut aussi être une liste (les points d'un masque) : elle s'interpole
alors point par point, Bézier devenant lissé.
"""

from __future__ import annotations

MODES = {"lineaire": "Linéaire", "palier": "Palier", "lisse": "Lissé", "bezier": "Bézier"}


def poignees(cles: list, i: int) -> tuple[list, list]:
    """(gauche, droite) de l'image clé i, en (dt, dv) ; les défauts au tiers du segment."""
    k = cles[i]
    dic = k[3] if len(k) > 3 and isinstance(k[3], dict) else {}
    avant = (k[0] - cles[i - 1][0]) / 3 if i > 0 else 1.0
    apres = (cles[i + 1][0] - k[0]) / 3 if i + 1 < len(cles) else 1.0
    return list(dic.get("g", [-avant, 0.0])), list(dic.get("d", [apres, 0.0]))


def regler_poignee(cles: list, i: int, cote: str, dt: float, dv: float, liees: bool = True):
    """Déplace une poignée ; liées, l'autre poignée reste alignée (tangente continue)."""
    g, d = poignees(cles, i)
    if cote == "d":
        dt = max(0.0, dt)
        d = [dt, dv]
        if liees and dt > 0:
            longueur = -g[0]
            g = [-longueur, -dv * longueur / dt]
    else:
        dt = min(0.0, dt)
        g = [dt, dv]
        if liees and dt < 0:
            longueur = d[0]
            d = [longueur, -dv * longueur / dt]
    k = cles[i]
    while len(k) < 4:
        k.append(None)
    k[3] = {"g": g, "d": d}


def _lisse(s: float) -> float:
    return s * s * (3 - 2 * s)


def _bezier(p0: float, p1: float, p2: float, p3: float, u: float) -> float:
    a = 1 - u
    return a * a * a * p0 + 3 * a * a * u * p1 + 3 * a * u * u * p2 + u * u * u * p3


def _segment_bezier(cles: list, i: int, t: float) -> float:
    k0, k1 = cles[i], cles[i + 1]
    d0 = poignees(cles, i)[1]
    g1 = poignees(cles, i + 1)[0]
    # Les poignées ne débordent pas du segment : le temps reste croissant.
    largeur = k1[0] - k0[0]
    x1 = k0[0] + min(max(d0[0], 0.0), largeur)
    x2 = k1[0] + max(min(g1[0], 0.0), -largeur)
    y1, y2 = k0[1] + d0[1], k1[1] + g1[1]
    bas, haut = 0.0, 1.0
    for _ in range(40):  # le temps croît avec u : dichotomie
        u = (bas + haut) / 2
        if _bezier(k0[0], x1, x2, k1[0], u) < t:
            bas = u
        else:
            haut = u
    return _bezier(k0[1], y1, y2, k1[1], (bas + haut) / 2)


def interpoler(cles: list, t: float):
    """Valeur au temps t. Avant la première image clé, sa valeur ; après la dernière, idem."""
    if t <= cles[0][0]:
        return cles[0][1]
    for i in range(len(cles) - 1):
        (t0, v0, mode), (t1, v1) = cles[i][:3], cles[i + 1][:2]
        if t < t1:
            if mode == "palier" or t1 == t0:
                return v0
            s = (t - t0) / (t1 - t0)
            if isinstance(v0, list):
                if not isinstance(v1, list) or len(v0) != len(v1):
                    return v0  # formes différentes : pas d'entre-deux possible
                s = _lisse(s) if mode in ("lisse", "bezier") else s
                return _melanger(v0, v1, s)
            if mode == "lisse":
                s = _lisse(s)
            elif mode == "bezier":
                return _segment_bezier(cles, i, t)
            return v0 + (v1 - v0) * s
    return cles[-1][1]


def _melanger(a, b, s: float):
    if isinstance(a, list):
        return [_melanger(x, y, s) for x, y in zip(a, b)]
    return a + (b - a) * s


def poser(cles: list, t: float, v, mode: str = "lineaire") -> list:
    """Image clé au temps t : sa valeur change si elle existe, sinon elle s'ajoute avec le
    passage donné. Renvoie la liste triée."""
    for k in cles:
        if k[0] == t:
            k[1] = v
            return cles
    cles.append([t, v, mode])
    cles.sort(key=lambda k: k[0])
    return cles
