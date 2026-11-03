"""Panneau Courbes, en onglet de la timeline : les courbes des réglages animables des effets
du clip choisi (ou de la piste, ou de la séquence), et de leurs masques.

À gauche, les réglages ; à droite, le graphe du réglage choisi, les autres en gris. Glisser
une image clé la déplace (temps et valeur) ; double-clic : une image clé de plus ; Suppr :
la retirer ; clic droit : son passage (linéaire, palier, lissé, Bézier). En Bézier, les
poignées de l'image clé choisie se tirent ; Alt les détache l'une de l'autre. Un clic dans le
vide déplace la tête de lecture.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QListWidget, QListWidgetItem,
                               QMenu, QPushButton, QToolButton, QVBoxLayout, QWidget)

from remanence.effets import EFFETS, courbes, modulateurs, valeur
from remanence.ui import charte
from remanence.ui.composants import LigneParametre, bouton_icone, etiquette, poser_icone

MARGE_X, MARGE_Y = 14, 16
RAYON = 5


@dataclass
class Courbe:
    """Un réglage animable : ses images clés (liste partagée avec le projet), sa valeur fixe
    sans animation, sa plage."""
    nom: str
    lire: Callable[[], list | None]
    creer: Callable[[], list]
    fixe: Callable[[], float]
    vider: Callable[[float], None]
    mini: float
    maxi: float
    palier: bool = False
    # Pour les modulateurs : l'effet et son réglage ("opacite" pour l'opacité) ; None pour
    # les réglages des masques, qui ne se modulent pas.
    effet_id: str | None = None
    cle: str | None = None

    def valeur_a(self, t: float) -> float:
        cles = self.lire()
        return courbes.interpoler(cles, t) if cles else self.fixe()


def courbes_de(porteur) -> list[Courbe]:
    """Les réglages animables des effets d'un clip, d'une piste ou de la séquence."""
    resultat = []
    for e in porteur.effets:
        d = EFFETS.get(e.type)
        if d is None or not d.animable:
            continue
        for p in d.parametres_pour(e):
            resultat.append(Courbe(
                f"{d.nom} · {p.nom}",
                lambda e=e, c=p.cle: e.cles.get(c),
                lambda e=e, c=p.cle: e.cles.setdefault(c, []),
                lambda e=e, c=p.cle: valeur(e, c),
                lambda v, e=e, c=p.cle: (e.cles.pop(c, None), e.params.__setitem__(c, v)),
                p.minimum, p.maximum, p.booleen, e.id, p.cle))
        resultat.append(Courbe(
            f"{d.nom} · Opacité",
            lambda e=e: e.cles.get("opacite"),
            lambda e=e: e.cles.setdefault("opacite", []),
            lambda e=e: e.opacite,
            lambda v, e=e: (e.cles.pop("opacite", None), setattr(e, "opacite", v)),
            0.0, 1.0, False, e.id, "opacite"))
        for i, m in enumerate(e.masques, 1):
            for champ, nom, mini in (("adoucissement", "Adoucissement", 0.0),
                                     ("expansion", "Expansion", -25.0)):
                resultat.append(Courbe(
                    f"{d.nom} · Masque {i} · {nom}",
                    lambda m=m, c=champ: m.cles.get(c),
                    lambda m=m, c=champ: m.cles.setdefault(c, []),
                    lambda m=m, c=champ: getattr(m, c),
                    lambda v, m=m, c=champ: (m.cles.pop(c, None), setattr(m, c, v)),
                    mini, 25.0))
    return resultat


class Graphe(QWidget):
    modifie = Signal(str)
    tete_demandee = Signal(int)  # image depuis l'origine du porteur

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(140)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.courbes: list[Courbe] = []
        self.active: int = -1
        self.duree = 1
        self.tete: int | None = None
        self.choisie: int | None = None  # rang de l'image clé choisie dans la courbe active
        self._prise = None  # ("cle" | "g" | "d", rang)
        # La séquence (ses modulateurs) et l'image où commence le temps du porteur.
        self.seq = None
        self.origine = 0
        self.modulateur = None  # modulateur montré à la place des courbes

    def module_a(self, courbe: Courbe, t: float) -> float | None:
        """La valeur finale avec les modulateurs, ou None si rien ne module ce réglage."""
        if self.seq is None or courbe.effet_id is None or not self.seq.modulateurs:
            return None
        cle = (courbe.effet_id, courbe.cle)
        if not any(tuple(c[:2]) == cle for m in self.seq.modulateurs for c in m.cibles):
            return None
        decalage = modulateurs.decalages(self.seq, self.origine + t).get(cle, 0.0)
        v = courbe.valeur_a(t) + decalage * (courbe.maxi - courbe.mini)
        return min(courbe.maxi, max(courbe.mini, v))

    # Géométrie

    def _zone(self) -> QRectF:
        return QRectF(MARGE_X, MARGE_Y, max(1, self.width() - 2 * MARGE_X),
                      max(1, self.height() - 2 * MARGE_Y))

    def x_de(self, t: float) -> float:
        z = self._zone()
        return z.left() + t / max(1, self.duree - 1) * z.width()

    def t_de(self, x: float) -> float:
        z = self._zone()
        return (x - z.left()) / z.width() * max(1, self.duree - 1)

    def y_de(self, c: Courbe, v: float) -> float:
        z = self._zone()
        s = (v - c.mini) / (c.maxi - c.mini) if c.maxi > c.mini else 0.5
        return z.bottom() - s * z.height()

    def v_libre(self, c: Courbe, y: float) -> float:
        z = self._zone()
        return c.mini + (z.bottom() - y) / z.height() * (c.maxi - c.mini)

    def v_de(self, c: Courbe, y: float) -> float:
        """La valeur sous la souris, dans la plage du réglage."""
        return min(c.maxi, max(c.mini, self.v_libre(c, y)))

    def courbe(self) -> Courbe | None:
        return self.courbes[self.active] if 0 <= self.active < len(self.courbes) else None

    # Dessin

    def paintEvent(self, _e):
        c = charte.actuelle()
        p = QPainter(self)
        p.fillRect(self.rect(), c.c("viewer-bg"))
        z = self._zone()
        p.setPen(QPen(c.c("line"), 1))
        for i in range(5):
            y = z.top() + i * z.height() / 4
            p.drawLine(QPointF(z.left(), y), QPointF(z.right(), y))
        if self.tete is not None and 0 <= self.tete < self.duree:
            p.setPen(QPen(c.c("playhead"), 1))
            x = self.x_de(self.tete)
            p.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        p.setRenderHint(QPainter.Antialiasing, True)
        if self.modulateur is not None:
            self._dessiner_modulateur(p)
            p.end()
            return
        for i, courbe in enumerate(self.courbes):
            if i != self.active and not courbe.lire():
                continue
            self._dessiner(p, courbe, active=(i == self.active))
        active = self.courbe()
        if active is not None:
            p.setFont(c.police("label"))
            p.setPen(c.c("ink-muted"))
            for v, y in ((active.maxi, z.top()), (active.mini, z.bottom())):
                texte = f"{v:g}".replace(".", ",")
                p.drawText(QRectF(z.left() + 4, y - 14 if y > z.top() else y, 120, 14),
                           Qt.AlignLeft | Qt.AlignVCenter, texte)
        p.end()

    def _chemin(self, valeur_a, y_de) -> QPainterPath:
        chemin = QPainterPath()
        pas = max(1, int(self._zone().width() // 2))
        for k in range(pas + 1):
            t = k / pas * max(1, self.duree - 1)
            pt = QPointF(self.x_de(t), y_de(valeur_a(t)))
            chemin.moveTo(pt) if k == 0 else chemin.lineTo(pt)
        return chemin

    def _dessiner_modulateur(self, p: QPainter):
        """Le signal du modulateur choisi, de -1 (bas) à 1 (haut), sur la durée montrée."""
        c = charte.actuelle()
        z = self._zone()
        cadence = float(self.seq.fraction_cadence) if self.seq is not None else 25.0
        chemin = self._chemin(
            lambda t: modulateurs.valeur(self.modulateur, self.origine + t, cadence),
            lambda v: z.bottom() - (v + 1) / 2 * z.height())
        p.setPen(QPen(c.c("focus"), 2))
        p.setBrush(Qt.NoBrush)
        p.drawPath(chemin)

    def _dessiner(self, p: QPainter, courbe: Courbe, active: bool):
        c = charte.actuelle()
        chemin = self._chemin(courbe.valeur_a, lambda v: self.y_de(courbe, v))
        module = self.module_a(courbe, 0) is not None
        if active and module:
            # Réglage modulé : les images clés en pointillé, le résultat en trait plein.
            p.setPen(QPen(c.c("ink-muted"), 1, Qt.DashLine))
            p.drawPath(chemin)
            chemin = self._chemin(lambda t: self.module_a(courbe, t),
                                  lambda v: self.y_de(courbe, v))
        p.setPen(QPen(c.c("focus" if active else "ink-faint"), 2 if active else 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(chemin)
        cles = courbe.lire() or []
        if active and self.choisie is not None and self.choisie < len(cles):
            self._dessiner_poignees(p, courbe, cles, self.choisie)
        for i, k in enumerate(cles):
            x, y = self.x_de(k[0]), self.y_de(courbe, k[1])
            r = RAYON + (1 if active and i == self.choisie else 0)
            forme = QPolygonF([QPointF(x, y - r), QPointF(x + r, y), QPointF(x, y + r),
                               QPointF(x - r, y)])
            p.setPen(QPen(c.c("bg-app"), 1))
            p.setBrush(c.c("ink" if active and i == self.choisie else
                           "keyframe" if active else "ink-faint"))
            p.drawPolygon(forme)

    def _points_poignees(self, courbe: Courbe, cles: list, i: int):
        g, d = courbes.poignees(cles, i)
        k = cles[i]
        return (QPointF(self.x_de(k[0] + g[0]), self.y_de(courbe, k[1] + g[1])),
                QPointF(self.x_de(k[0] + d[0]), self.y_de(courbe, k[1] + d[1])))

    def _bezier_autour(self, cles: list, i: int) -> tuple[bool, bool]:
        """(gauche, droite) : la poignée sert si le segment de ce côté est en Bézier."""
        gauche = i > 0 and cles[i - 1][2] == "bezier"
        droite = i + 1 < len(cles) and cles[i][2] == "bezier"
        return gauche, droite

    def _dessiner_poignees(self, p: QPainter, courbe: Courbe, cles: list, i: int):
        c = charte.actuelle()
        gauche, droite = self._bezier_autour(cles, i)
        centre = QPointF(self.x_de(cles[i][0]), self.y_de(courbe, cles[i][1]))
        pg, pd = self._points_poignees(courbe, cles, i)
        for actif, pt in ((gauche, pg), (droite, pd)):
            if actif:
                p.setPen(QPen(c.c("ink-muted"), 1))
                p.drawLine(centre, pt)
                p.setBrush(c.c("ink"))
                p.drawEllipse(pt, 3.5, 3.5)

    # Souris et clavier

    def _sous(self, pos) -> tuple[str, int] | None:
        courbe = self.courbe()
        cles = (courbe.lire() if courbe else None) or []
        if courbe is None:
            return None
        if self.choisie is not None and self.choisie < len(cles):
            gauche, droite = self._bezier_autour(cles, self.choisie)
            pg, pd = self._points_poignees(courbe, cles, self.choisie)
            for actif, cote, pt in ((gauche, "g", pg), (droite, "d", pd)):
                if actif and (pt - pos).manhattanLength() <= 8:
                    return cote, self.choisie
        for i, k in enumerate(cles):
            pt = QPointF(self.x_de(k[0]), self.y_de(courbe, k[1]))
            if (pt - pos).manhattanLength() <= 9:
                return "cle", i
        return None

    def mousePressEvent(self, e):
        self.setFocus()
        pos = e.position()
        if self.modulateur is not None:
            if e.button() == Qt.LeftButton:
                self.tete_demandee.emit(max(0, min(self.duree - 1, round(self.t_de(pos.x())))))
            return
        sous = self._sous(pos)
        if e.button() == Qt.RightButton:
            if sous is not None and sous[0] == "cle":
                self.choisie = sous[1]
                self._menu(e.globalPosition().toPoint())
            return
        if e.button() != Qt.LeftButton:
            return
        if sous is None:
            self.choisie = None
            self.tete_demandee.emit(max(0, min(self.duree - 1, round(self.t_de(pos.x())))))
            self.update()
            return
        self.choisie = sous[1]
        self._prise = sous
        self.update()

    def mouseMoveEvent(self, e):
        courbe = self.courbe()
        if self._prise is None or courbe is None:
            sous = self._sous(e.position())
            self.setCursor(Qt.PointingHandCursor if sous else Qt.ArrowCursor)
            return
        cles = courbe.lire()
        genre, i = self._prise
        pos = e.position()
        if genre == "cle":
            bas = cles[i - 1][0] + 1 if i > 0 else 0
            haut = cles[i + 1][0] - 1 if i + 1 < len(cles) else self.duree - 1
            cles[i][0] = int(max(bas, min(haut, round(self.t_de(pos.x())))))
            v = self.v_de(courbe, pos.y())
            cles[i][1] = (1.0 if v > (courbe.mini + courbe.maxi) / 2 else 0.0) \
                if courbe.palier else v
        else:
            k = cles[i]
            # Une poignée peut sortir de la plage : seule la courbe y est ramenée au rendu.
            courbes.regler_poignee(cles, i, genre, self.t_de(pos.x()) - k[0],
                                   self.v_libre(courbe, pos.y()) - k[1],
                                   liees=not (e.modifiers() & Qt.AltModifier))
        self.update()

    def mouseReleaseEvent(self, e):
        if self._prise is not None:
            genre = self._prise[0]
            self._prise = None
            self.modifie.emit("Image clé déplacée" if genre == "cle" else "Courbe de Bézier")

    def mouseDoubleClickEvent(self, e):
        courbe = self.courbe()
        if self.modulateur is not None or courbe is None or e.button() != Qt.LeftButton or self._sous(e.position()):
            return
        t = int(max(0, min(self.duree - 1, round(self.t_de(e.position().x())))))
        v = self.v_de(courbe, e.position().y())
        cles = courbe.lire()
        if not cles:
            # Première image clé : la valeur fixe devient une courbe.
            cles = courbe.creer()
        mode = "palier" if courbe.palier else "lineaire"
        courbes.poser(cles, t, v, mode)
        self.choisie = next(i for i, k in enumerate(cles) if k[0] == t)
        self.modifie.emit("Image clé")

    def event(self, e):
        # Suppr retire l'image clé choisie, pas les clips sélectionnés (raccourci de la fenêtre).
        if e.type() == QEvent.ShortcutOverride and self.choisie is not None                 and e.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            e.accept()
            return True
        return super().event(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.choisie is not None:
            self.retirer()
        else:
            super().keyPressEvent(e)

    def retirer(self):
        courbe = self.courbe()
        cles = courbe.lire() if courbe else None
        if not cles or self.choisie is None or self.choisie >= len(cles):
            return
        k = cles.pop(self.choisie)
        if not cles:
            courbe.vider(copy.deepcopy(k[1]))
        self.choisie = None
        self.modifie.emit("Image clé retirée")

    def _menu(self, ou):
        courbe = self.courbe()
        cles = courbe.lire()
        k = cles[self.choisie]
        menu = QMenu(self)
        for mode, nom in courbes.MODES.items():
            a = menu.addAction(nom, lambda mode=mode: self._passage(mode))
            a.setCheckable(True)
            a.setChecked(k[2] == mode)
        menu.addSeparator()
        menu.addAction("Supprimer l'image clé", self.retirer)
        menu.exec(ou)

    def _passage(self, mode: str):
        cles = self.courbe().lire()
        cles[self.choisie][2] = mode
        self.modifie.emit("Passage de l'image clé")


class FicheModulateur(QWidget):
    """Réglages du modulateur choisi et ses cibles (profondeur en % de la plage)."""
    reglage = Signal(str, str, object)  # identifiant, champ, valeur

    def __init__(self):
        super().__init__()
        self.setProperty("role", "panneau")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(12, 8, 12, 8)
        self._lay.setSpacing(6)

    def afficher(self, m, noms_cibles: dict):
        while self._lay.count():
            item = self._lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
            elif item.layout() is not None:
                _vider(item.layout())
        haut = QHBoxLayout()
        haut.addWidget(etiquette(m.nom, "titre-section"))
        actif = QCheckBox("Actif")
        actif.setChecked(m.actif)
        actif.toggled.connect(lambda v: self.reglage.emit(m.id, "actif", v))
        haut.addWidget(actif)
        haut.addStretch(1)
        if m.type == "oscillateur":
            haut.addWidget(self._choix("Forme", modulateurs.FORMES, m, "forme"))
        elif m.type == "tempo":
            haut.addWidget(self._choix("Division", modulateurs.DIVISIONS, m, "division"))
        elif m.type == "aleatoire":
            tirage = QPushButton("Autre tirage")
            tirage.clicked.connect(lambda: self.reglage.emit(
                m.id, "param:graine", int(m.params.get("graine", 1)) + 1))
            haut.addWidget(tirage)
        retirer = bouton_icone("x", "Supprimer le modulateur", taille=14)
        retirer.clicked.connect(lambda: self.reglage.emit(m.id, "retirer", None))
        haut.addWidget(retirer)
        self._lay.addLayout(haut)
        grille = QHBoxLayout()
        grille.setSpacing(16)
        for p in modulateurs.PARAMETRES[m.type]:
            ligne = LigneParametre(p.nom, p.minimum, p.maximum, m.params.get(p.cle, p.defaut),
                                   p.unite, p.defaut, p.decimales)
            ligne.valeur_finale.connect(lambda v, c=p.cle: self.reglage.emit(m.id, "param:" + c, v))
            grille.addWidget(ligne, 1)
        self._lay.addLayout(grille)
        if not m.cibles:
            self._lay.addWidget(etiquette("Aucun réglage piloté", "secondaire"))
        for i, (effet_id, cle, profondeur) in enumerate(m.cibles):
            rang = QHBoxLayout()
            nom = etiquette(noms_cibles.get((effet_id, cle), cle), "")
            nom.setMinimumWidth(220)
            rang.addWidget(nom)
            ligne = LigneParametre("Profondeur", -100, 100, profondeur, "%", 25, 0)
            ligne.valeur_finale.connect(lambda v, i=i: self.reglage.emit(m.id, f"profondeur:{i}", v))
            rang.addWidget(ligne, 1)
            enlever = bouton_icone("x", "Ne plus piloter ce réglage", taille=14)
            enlever.clicked.connect(lambda _=False, i=i: self.reglage.emit(m.id, "cible-", i))
            rang.addWidget(enlever)
            self._lay.addLayout(rang)

    def _choix(self, nom: str, choix: dict, m, champ: str) -> QComboBox:
        liste = QComboBox()
        liste.setAccessibleName(nom)
        for cle, texte in choix.items():
            liste.addItem(texte, cle)
        liste.setCurrentIndex(max(0, liste.findData(m.params.get(champ))))
        liste.activated.connect(lambda i: self.reglage.emit(m.id, "param:" + champ,
                                                            liste.itemData(i)))
        return liste


def _vider(lay):
    while lay.count():
        item = lay.takeAt(0)
        if item.widget() is not None:
            item.widget().setParent(None)
            item.widget().deleteLater()
        elif item.layout() is not None:
            _vider(item.layout())


class PanneauCourbes(QWidget):
    modifie = Signal(str)
    tete_demandee = Signal(int)  # image de la séquence
    reglage_modulateur = Signal(str, str, object)  # identifiant, champ, valeur

    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        gauche = QVBoxLayout()
        gauche.setContentsMargins(0, 0, 0, 6)
        gauche.setSpacing(4)
        self.liste = QListWidget()
        self.liste.setAccessibleName("Réglages animables")
        self.liste.setContextMenuPolicy(Qt.CustomContextMenu)
        self.liste.customContextMenuRequested.connect(self._menu_reglage)
        gauche.addWidget(self.liste, 3)
        marge = QHBoxLayout()
        marge.setContentsMargins(8, 4, 8, 0)
        marge.addWidget(etiquette("Modulateurs", "section"))
        marge.addStretch(1)
        ajout = QToolButton()
        ajout.setText("Ajouter")
        poser_icone(ajout, "plus", 14)
        ajout.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        ajout.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(ajout)
        for cle, nom in modulateurs.TYPES.items():
            menu.addAction(nom, lambda cle=cle: self.reglage_modulateur.emit("", "ajouter", cle))
        ajout.setMenu(menu)
        self.bouton_ajout = ajout
        marge.addWidget(ajout)
        gauche.addLayout(marge)
        self.liste_modulateurs = QListWidget()
        self.liste_modulateurs.setAccessibleName("Modulateurs")
        gauche.addWidget(self.liste_modulateurs, 1)
        colonne = QWidget()
        colonne.setFixedWidth(250)
        colonne.setLayout(gauche)
        lay.addWidget(colonne)
        droite = QVBoxLayout()
        droite.setContentsMargins(0, 0, 0, 0)
        droite.setSpacing(0)
        self.fiche = FicheModulateur()
        self.fiche.reglage.connect(self.reglage_modulateur)
        self.fiche.hide()
        self.graphe = Graphe()
        droite.addWidget(self.fiche)
        droite.addWidget(self.graphe, 1)
        lay.addLayout(droite, 1)
        self.origine = 0
        self.seq = None
        self.liste.currentRowChanged.connect(self._choisir)
        self.liste.itemPressed.connect(lambda _i: self._choisir(self.liste.currentRow()))
        self.liste_modulateurs.currentRowChanged.connect(self._choisir_modulateur)
        self.graphe.modifie.connect(self.modifie)
        self.graphe.tete_demandee.connect(lambda t: self.tete_demandee.emit(t + self.origine))

    def afficher(self, porteur, origine: int, duree: int, seq=None):
        """Les courbes du porteur (clip, piste ou séquence ; None : rien) ; origine : image
        de la séquence où commence le temps de ses images clés ; seq : ses modulateurs."""
        nom_actif = self.liste.currentItem().text() if self.liste.currentItem() else None
        mod_actif = self.graphe.modulateur.id if self.graphe.modulateur is not None else None
        self.origine = origine
        self.seq = seq
        self.graphe.seq, self.graphe.origine = seq, origine
        self.graphe.duree = max(1, duree)
        self.graphe.courbes = courbes_de(porteur) if porteur is not None else []
        self.liste.blockSignals(True)
        self.liste.clear()
        for courbe in self.graphe.courbes:
            item = QListWidgetItem(courbe.nom)
            if courbe.lire() or self.graphe.module_a(courbe, 0) is not None:
                item.setForeground(charte.actuelle().c("focus"))
            self.liste.addItem(item)
        noms = [c.nom for c in self.graphe.courbes]
        rang = noms.index(nom_actif) if nom_actif in noms else \
            next((i for i, c in enumerate(self.graphe.courbes) if c.lire()), 0 if noms else -1)
        self.liste.setCurrentRow(rang)
        self.liste.blockSignals(False)
        self.liste_modulateurs.blockSignals(True)
        self.liste_modulateurs.clear()
        for m in (seq.modulateurs if seq is not None else []):
            item = QListWidgetItem(m.nom)
            item.setData(Qt.UserRole, m.id)
            self.liste_modulateurs.addItem(item)
        self.liste_modulateurs.blockSignals(False)
        ids = [m.id for m in (seq.modulateurs if seq is not None else [])]
        if mod_actif in ids:
            self.liste_modulateurs.setCurrentRow(ids.index(mod_actif))
        else:
            self._choisir(rang, garder=True)

    def _noms_cibles(self) -> dict:
        """(effet, réglage) -> nom, pour tous les effets de la séquence."""
        noms = {}
        if self.seq is None:
            return noms
        porteurs = [self.seq] + self.seq.pistes + [c for p in self.seq.pistes for c in p.clips]
        for porteur in porteurs:
            for courbe in courbes_de(porteur):
                if courbe.effet_id is not None:
                    noms[(courbe.effet_id, courbe.cle)] = courbe.nom
        return noms

    def _choisir(self, rang: int, garder: bool = False):
        self.liste_modulateurs.blockSignals(True)
        self.liste_modulateurs.clearSelection()
        self.liste_modulateurs.setCurrentRow(-1)
        self.liste_modulateurs.blockSignals(False)
        self.graphe.modulateur = None
        self.fiche.hide()
        if self.graphe.active != rang or not garder:
            self.graphe.choisie = None
        self.graphe.active = rang
        self.graphe.update()

    def _choisir_modulateur(self, rang: int):
        mods = self.seq.modulateurs if self.seq is not None else []
        if not 0 <= rang < len(mods):
            self._choisir(self.liste.currentRow(), garder=True)
            return
        self.graphe.modulateur = mods[rang]
        self.fiche.afficher(mods[rang], self._noms_cibles())
        self.fiche.show()
        self.graphe.update()

    def _menu_reglage(self, pos):
        """Clic droit sur un réglage : le faire piloter par un modulateur."""
        rang = self.liste.row(self.liste.itemAt(pos)) if self.liste.itemAt(pos) else -1
        if not 0 <= rang < len(self.graphe.courbes):
            return
        courbe = self.graphe.courbes[rang]
        if courbe.effet_id is None or self.seq is None:
            return
        cible = (courbe.effet_id, courbe.cle)
        menu = QMenu(self)
        piloter = menu.addMenu("Moduler par")
        for m in self.seq.modulateurs:
            a = piloter.addAction(m.nom, lambda m=m: self.reglage_modulateur.emit(
                m.id, "cible+", list(cible)))
            a.setEnabled(not any(tuple(c[:2]) == cible for c in m.cibles))
        piloter.addSeparator()
        for cle, nom in modulateurs.TYPES.items():
            piloter.addAction(f"Nouveau : {nom}", lambda cle=cle: self.reglage_modulateur.emit(
                "", "ajouter", [cle, list(cible)]))
        menu.exec(self.liste.mapToGlobal(pos))

    def suivre(self, f: int):
        self.graphe.tete = f - self.origine
        self.graphe.update()
