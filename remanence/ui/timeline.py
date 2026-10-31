"""Timeline multipiste : règle en timecode, en-têtes de pistes et clips manipulables à la souris.

Pendant un geste (déplacer, rogner, fondu, point d'enveloppe), chaque mouvement de souris
repart de l'état au moment du clic et réapplique l'opération : l'aperçu montre exactement
ce que donnera le relâchement, écrasements compris.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMenu, QPushButton, QScrollBar, QToolButton,
                               QVBoxLayout, QWidget)

from remanence.media.lecteur import AudioCache
from remanence.media.proxy import chemin_audio
from remanence.media.timecode import images_vers_tc
from remanence.projet import edition
from remanence.projet.modele import Clip, Piste, Projet, valeur_enveloppe
from remanence.ui import theme
from remanence.ui.medias import MIME_MEDIA

HAUTEUR_REGLE = 28
HAUTEUR_VIDEO = 64
HAUTEUR_AUDIO = 48
LARGEUR_ENTETE = 216
BANDEAU = 15
MARGE_BORD = 6
SEUIL_AIMANT_PX = 8


@dataclass
class Geste:
    type: str
    clip_id: str | None
    x0: float
    y0: float
    etat: list
    cote: str = ""
    rang: int = -1
    origine: int = 0


class VueTimeline(QWidget):
    modifie = Signal(str)
    tete_changee = Signal(int)
    selection_changee = Signal(set)
    media_depose = Signal(list, int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.projet: Projet | None = None
        self.px_par_image = 6.0
        self.decalage_x = 0.0
        self.decalage_y = 0
        self.tete = 0
        self.selection: set[str] = set()
        self.aimantation = True
        self._geste: Geste | None = None
        self._repere_aimant: int | None = None
        self._depot: tuple[int, str] | None = None
        self._ondes: dict[str, object] = {}
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumHeight(140)
        self.setAccessibleName("Timeline")

    # Géométrie

    def lignes(self) -> list[tuple[Piste, int, int]]:
        if self.projet is None:
            return []
        y = HAUTEUR_REGLE - self.decalage_y
        res = []
        for p in self.projet.sequence.pistes:
            h = HAUTEUR_VIDEO if p.type == "video" else HAUTEUR_AUDIO
            res.append((p, y, h))
            y += h
        return res

    def hauteur_totale(self) -> int:
        if self.projet is None:
            return 0
        return sum(HAUTEUR_VIDEO if p.type == "video" else HAUTEUR_AUDIO
                   for p in self.projet.sequence.pistes)

    def x_de(self, f: float) -> float:
        return f * self.px_par_image - self.decalage_x

    def f_de(self, x: float) -> float:
        return (x + self.decalage_x) / self.px_par_image

    def piste_a(self, y: float) -> tuple[Piste, int, int] | None:
        for ligne in self.lignes():
            if ligne[1] <= y < ligne[1] + ligne[2]:
                return ligne
        return None

    def rect_clip(self, c: Clip, y: int, h: int) -> QRectF:
        return QRectF(self.x_de(c.debut), y + 2, max(2.0, c.duree * self.px_par_image), h - 4)

    def _y_enveloppe(self, r: QRectF, valeur: float) -> float:
        haut = r.top() + BANDEAU
        return haut + (1 - valeur) * (r.bottom() - 3 - haut)

    # Dessin

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.FOND))
        if self.projet is None:
            return
        seq = self.projet.sequence
        police = QFont(self.font())
        police.setPointSizeF(8.5)
        p.setFont(police)
        for piste, y, h in self.lignes():
            p.fillRect(QRect(0, y, self.width(), h - 1), QColor(theme.PISTE))
            p.setPen(QColor("#2e2e2e"))
            p.drawLine(0, y + h - 1, self.width(), y + h - 1)
            for c in piste.clips:
                self._dessiner_clip(p, piste, c, y, h)
        if self._depot is not None:
            x = self.x_de(self._depot[0])
            p.setPen(QPen(QColor(theme.CYAN), 1, Qt.DashLine))
            p.drawLine(QPointF(x, HAUTEUR_REGLE), QPointF(x, self.height()))
        self._dessiner_regle(p, seq)
        if self._repere_aimant is not None:
            x = self.x_de(self._repere_aimant)
            p.setPen(QPen(QColor(theme.CYAN), 1, Qt.DashLine))
            p.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        xt = self.x_de(self.tete)
        p.setPen(QPen(QColor(theme.CYAN), 1))
        p.drawLine(QPointF(xt, 0), QPointF(xt, self.height()))
        tri = QPainterPath()
        tri.moveTo(xt - 6, 0)
        tri.lineTo(xt + 6, 0)
        tri.lineTo(xt, 8)
        p.fillPath(tri, QColor(theme.CYAN))
        if not seq.pistes or not any(c for pi in seq.pistes for c in pi.clips):
            p.setPen(QColor(theme.TEXTE_SECONDAIRE))
            p.drawText(QRect(0, HAUTEUR_REGLE, self.width(), self.height() - HAUTEUR_REGLE),
                       Qt.AlignCenter, "Glissez un média depuis le panneau Médias pour commencer "
                                       "le montage.")
        if self.hasFocus():
            p.setPen(QPen(QColor(theme.CYAN), 1))
            p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        p.end()

    def _pas_graduation(self) -> int:
        cad = max(1, round(float(self.projet.sequence.fraction_cadence)))
        for pas in (1, 2, 5, 10, cad, 2 * cad, 5 * cad, 10 * cad, 30 * cad, 60 * cad,
                    300 * cad, 600 * cad, 1800 * cad, 3600 * cad):
            if pas * self.px_par_image >= 90:
                return pas
        return 3600 * cad

    def _dessiner_regle(self, p: QPainter, seq):
        p.fillRect(QRect(0, 0, self.width(), HAUTEUR_REGLE), QColor(theme.PANNEAU))
        if seq.point_entree is not None or seq.point_sortie is not None:
            a = self.x_de(seq.point_entree or 0)
            b = self.x_de(seq.point_sortie if seq.point_sortie is not None else seq.duree())
            p.fillRect(QRectF(a, 0, max(1.0, b - a), HAUTEUR_REGLE), QColor("#3a3a3a"))
            p.setPen(QPen(QColor(theme.TEXTE), 1))
            p.drawLine(QPointF(a, 0), QPointF(a, HAUTEUR_REGLE))
            p.drawLine(QPointF(b, 0), QPointF(b, HAUTEUR_REGLE))
        pas = self._pas_graduation()
        premier = max(0, int(self.f_de(0)) // pas * pas)
        dernier = int(self.f_de(self.width())) + pas
        cad = seq.fraction_cadence
        p.setPen(QColor(theme.TEXTE_SECONDAIRE))
        for f in range(premier, dernier, pas):
            x = self.x_de(f)
            p.drawLine(QPointF(x, HAUTEUR_REGLE - 8), QPointF(x, HAUTEUR_REGLE))
            p.drawText(QPointF(x + 3, 13), images_vers_tc(seq.tc_debut + f, cad, seq.tc_drop))
            sous = pas / 5
            if sous * self.px_par_image >= 8:
                for k in range(1, 5):
                    xs = self.x_de(f + k * sous)
                    p.drawLine(QPointF(xs, HAUTEUR_REGLE - 4), QPointF(xs, HAUTEUR_REGLE))
        for m in seq.marqueurs:
            x = self.x_de(m.position)
            p.fillRect(QRectF(x - 3, HAUTEUR_REGLE - 10, 6, 10), QColor(m.couleur))
        p.setPen(QColor("#3a3a3a"))
        p.drawLine(0, HAUTEUR_REGLE - 1, self.width(), HAUTEUR_REGLE - 1)

    def _dessiner_clip(self, p: QPainter, piste: Piste, c: Clip, y: int, h: int):
        r = self.rect_clip(c, y, h)
        if r.right() < 0 or r.left() > self.width():
            return
        media = self.projet.medias.get(c.media_id)
        video = piste.type == "video"
        fond = QColor(theme.CLIP_VIDEO if video else theme.CLIP_AUDIO)
        if piste.masquee or piste.muette:
            fond = fond.darker(130)
        p.fillRect(r, fond)
        p.fillRect(QRectF(r.left(), r.top(), r.width(), BANDEAU), QColor("#2c2c2c"))
        if not video and media is not None:
            self._dessiner_onde(p, c, media, r)
        # Fondus : zone assombrie et courbe, poignées aux coins supérieurs.
        corps_haut = r.top() + BANDEAU
        p.setPen(QPen(QColor(theme.ENVELOPPE), 1))
        for longueur, gauche in ((c.fondu_entree, True), (c.fondu_sortie, False)):
            if longueur <= 0:
                continue
            l = longueur * self.px_par_image
            x0 = r.left() if gauche else r.right() - l
            chemin = QPainterPath()
            if gauche:
                chemin.moveTo(x0, r.bottom())
                chemin.lineTo(x0 + l, corps_haut)
                chemin.lineTo(x0, corps_haut)
            else:
                chemin.moveTo(x0, corps_haut)
                chemin.lineTo(x0 + l, r.bottom())
                chemin.lineTo(x0 + l, corps_haut)
            chemin.closeSubpath()
            p.fillPath(chemin, QColor(0, 0, 0, 90))
            if gauche:
                p.drawLine(QPointF(x0, r.bottom()), QPointF(x0 + l, corps_haut))
            else:
                p.drawLine(QPointF(x0, corps_haut), QPointF(x0 + l, r.bottom()))
        if c.enveloppe or c.gain != 1.0:
            pts = c.enveloppe or [[0, 1.0]]
            chemin = QPainterPath()
            chemin.moveTo(r.left(), self._y_enveloppe(r, pts[0][1] * c.gain))
            for x, v in pts:
                chemin.lineTo(self.x_de(c.debut + x), self._y_enveloppe(r, v * c.gain))
            chemin.lineTo(r.right(), self._y_enveloppe(r, pts[-1][1] * c.gain))
            p.setPen(QPen(QColor(theme.ENVELOPPE), 1))
            p.drawPath(chemin)
            for x, v in c.enveloppe:
                px, py = self.x_de(c.debut + x), self._y_enveloppe(r, v * c.gain)
                p.fillRect(QRectF(px - 3, py - 3, 6, 6), QColor(theme.ENVELOPPE))
        selectionne = c.id in self.selection
        for gauche in (True, False):
            hx = r.left() + c.fondu_entree * self.px_par_image if gauche else \
                r.right() - c.fondu_sortie * self.px_par_image
            p.fillRect(QRectF(hx - (0 if gauche else 6), r.top(), 6, 6), QColor(theme.ENVELOPPE))
        p.setPen(QColor(theme.TEXTE))
        nom = media.nom if media else "Média manquant"
        if media and media.hors_ligne:
            nom += " (hors ligne)"
        if c.lien is None and media and media.infos.video and media.infos.audio:
            nom += " · dissocié"
        p.save()
        p.setClipRect(r.adjusted(8, 0, -8, 0))
        p.drawText(QPointF(r.left() + 9, r.top() + 11), nom)
        p.restore()
        if selectionne:
            p.setPen(QPen(QColor(theme.ROSE), 2))
            p.drawRect(r.adjusted(1, 1, -1, -1))
        else:
            p.setPen(QPen(QColor(theme.BORDURE), 1))
            p.drawRect(r.adjusted(0, 0, -1, -1))

    def _dessiner_onde(self, p: QPainter, c: Clip, media, r: QRectF):
        cache = self._ondes.get(media.id)
        if cache is None:
            fichier = chemin_audio(media.infos)
            if not fichier.exists():
                return
            try:
                ac = AudioCache(fichier)
            except Exception:
                return
            cretes = ac.cretes(4000)
            cache = self._ondes[media.id] = (cretes, ac.nb, ac.decalage_s)
        cretes, nb, decalage = cache
        if nb == 0 or len(cretes) == 0:
            return
        cad = float(self.projet.sequence.fraction_cadence)
        cad_media = float(media.infos.video.fraction_cadence) if media.infos.video else cad
        par_case = nb / len(cretes)
        milieu = (r.top() + BANDEAU + r.bottom()) / 2
        demi = (r.bottom() - r.top() - BANDEAU) / 2 - 2
        p.setPen(QPen(QColor(theme.ONDE), 1))
        x_debut = max(int(r.left()), 0)
        x_fin = min(int(r.right()), self.width())
        for x in range(x_debut, x_fin):
            f = self.f_de(x) - c.debut
            t = (c.entree / cad_media) + f / cad - decalage
            k = int(t * 48000 / par_case)
            if 0 <= k < len(cretes):
                a = float(cretes[k]) * demi * c.facteur(c.debut + int(f))
                p.drawLine(QPointF(x, milieu - a), QPointF(x, milieu + a))

    def oublier_ondes(self):
        self._ondes.clear()

    # Repérage sous la souris

    def _sous(self, pos) -> tuple[str, Piste | None, Clip | None, int]:
        if pos.y() < HAUTEUR_REGLE:
            return "regle", None, None, -1
        ligne = self.piste_a(pos.y())
        if ligne is None:
            return "vide", None, None, -1
        piste, y, h = ligne
        for c in piste.clips:
            r = self.rect_clip(c, y, h)
            if not r.adjusted(-MARGE_BORD, 0, MARGE_BORD, 0).contains(pos):
                continue
            for rang, (x, v) in enumerate(c.enveloppe):
                px, py = self.x_de(c.debut + x), self._y_enveloppe(r, v * c.gain)
                if abs(pos.x() - px) <= 5 and abs(pos.y() - py) <= 5:
                    return "point", piste, c, rang
            if pos.y() <= r.top() + 9:
                hg = r.left() + c.fondu_entree * self.px_par_image
                hd = r.right() - c.fondu_sortie * self.px_par_image
                if abs(pos.x() - hg) <= 7:
                    return "fondu_entree", piste, c, -1
                if abs(pos.x() - hd) <= 7:
                    return "fondu_sortie", piste, c, -1
            if abs(pos.x() - r.left()) <= MARGE_BORD:
                return "bord_debut", piste, c, -1
            if abs(pos.x() - r.right()) <= MARGE_BORD:
                return "bord_fin", piste, c, -1
            if r.contains(pos):
                return "corps", piste, c, -1
        return "vide", piste, None, -1

    def _seuil(self) -> int:
        return max(1, math.ceil(SEUIL_AIMANT_PX / self.px_par_image)) if self.aimantation else 0

    # Souris

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._geste is None:
            zone = self._sous(pos)[0]
            curseurs = {"bord_debut": Qt.SizeHorCursor, "bord_fin": Qt.SizeHorCursor,
                        "fondu_entree": Qt.SizeHorCursor, "fondu_sortie": Qt.SizeHorCursor,
                        "point": Qt.SizeAllCursor, "corps": Qt.OpenHandCursor}
            self.setCursor(curseurs.get(zone, Qt.ArrowCursor))
            return
        g = self._geste
        seq = self.projet.sequence
        if g.type == "regle":
            self._placer_tete(self.f_de(pos.x()))
            return
        seq.pistes = copy.deepcopy(g.etat)
        dx_images = round((pos.x() - g.x0) / self.px_par_image)
        self._repere_aimant = None
        try:
            if g.type == "deplacer":
                _, c = seq.trouver(g.clip_id)
                delta = self._aimanter_deplacement(c, dx_images)
                ligne = self.piste_a(pos.y())
                ligne0 = self.piste_a(g.y0)
                delta_piste = 0
                if ligne and ligne0 and ligne[0].type == ligne0[0].type:
                    meme = [q for q in seq.pistes if q.type == ligne0[0].type]
                    delta_piste = meme.index(ligne[0]) - meme.index(ligne0[0])
                edition.deplacer(seq, self.selection | {g.clip_id}, delta, delta_piste,
                                 inclure_lies=not (e.modifiers() & Qt.AltModifier))
            elif g.type in ("bord_debut", "bord_fin"):
                _, c = seq.trouver(g.clip_id)
                cote = "debut" if g.type == "bord_debut" else "fin"
                bord = c.debut if cote == "debut" else c.fin
                cible = bord + dx_images
                if self._seuil():
                    cible2 = edition.aimanter(cible, edition.cibles_aimantation(
                        seq, {c.id}, self.tete), self._seuil())
                    if cible2 != cible:
                        self._repere_aimant = cible2
                    cible = cible2
                edition.rogner(self.projet, seq, c.id, cote, cible - bord,
                               inclure_lies=not (e.modifiers() & Qt.AltModifier))
            elif g.type in ("fondu_entree", "fondu_sortie"):
                _, c = seq.trouver(g.clip_id)
                f = round(self.f_de(pos.x()))
                longueur = f - c.debut if g.type == "fondu_entree" else c.fin - f
                edition.regler_fondu(seq, c.id, "entree" if g.type == "fondu_entree" else "sortie",
                                     longueur)
            elif g.type == "point":
                piste, c = seq.trouver(g.clip_id)
                ligne = next(l for l in self.lignes() if l[0].id == piste.id)
                r = self.rect_clip(c, ligne[1], ligne[2])
                haut = r.top() + BANDEAU
                valeur = 1 - (pos.y() - haut) / max(1.0, r.bottom() - 3 - haut)
                valeur = max(0.0, min(1.0, valeur / max(c.gain, 1e-6)))
                x = self.f_de(pos.x()) - c.debut
                del c.enveloppe[g.rang]
                g.rang = edition.poser_point(seq, c.id, round(x), valeur)
                g.etat = copy.deepcopy(seq.pistes)
                g.x0 = pos.x()
        except edition.EditionImpossible:
            seq.pistes = copy.deepcopy(g.etat)
        self.update()

    def _aimanter_deplacement(self, c: Clip, delta: int) -> int:
        seuil = self._seuil()
        if not seuil:
            return delta
        exclus = edition.avec_lies(self.projet.sequence, self.selection | {c.id})
        cibles = edition.cibles_aimantation(self.projet.sequence, exclus, self.tete)
        meilleur = delta
        ecart = seuil + 1
        for bord in (c.debut, c.fin):
            cible = edition.aimanter(bord + delta, cibles, seuil)
            if cible != bord + delta and abs(cible - bord - delta) < ecart:
                ecart = abs(cible - bord - delta)
                meilleur = cible - bord
                self._repere_aimant = cible
        return meilleur

    def mousePressEvent(self, e):
        self.setFocus()
        if self.projet is None:
            return
        pos = e.position()
        zone, piste, c, rang = self._sous(pos)
        if e.button() == Qt.RightButton:
            self._menu(e, zone, c, rang)
            return
        if e.button() != Qt.LeftButton:
            return
        etat = copy.deepcopy(self.projet.sequence.pistes)
        if zone == "regle" or zone == "vide":
            if zone == "vide" and not (e.modifiers() & Qt.ControlModifier):
                self._choisir(set())
            self._placer_tete(self.f_de(pos.x()))
            self._geste = Geste("regle", None, pos.x(), pos.y(), etat)
            return
        if piste.verrouillee:
            self._choisir({c.id})
            return
        if e.modifiers() & Qt.ControlModifier:
            self._choisir(self.selection ^ {c.id})
        elif c.id not in self.selection:
            self._choisir({c.id})
        types = {"corps": "deplacer", "bord_debut": "bord_debut", "bord_fin": "bord_fin",
                 "fondu_entree": "fondu_entree", "fondu_sortie": "fondu_sortie", "point": "point"}
        self._geste = Geste(types[zone], c.id, pos.x(), pos.y(), etat, rang=rang)
        if zone == "corps":
            self.setCursor(Qt.ClosedHandCursor)

    def mouseReleaseEvent(self, e):
        g = self._geste
        self._geste = None
        self._repere_aimant = None
        if g is None:
            return
        libelles = {"deplacer": "Déplacement", "bord_debut": "Rognage", "bord_fin": "Rognage",
                    "fondu_entree": "Fondu d'entrée", "fondu_sortie": "Fondu de sortie",
                    "point": "Point d'enveloppe"}
        if g.type in libelles:
            self.modifie.emit(libelles[g.type])
        self.update()

    def mouseDoubleClickEvent(self, e):
        zone, piste, c, _ = self._sous(e.position())
        if zone != "corps" or piste.verrouillee:
            return
        ligne = next(l for l in self.lignes() if l[0].id == piste.id)
        r = self.rect_clip(c, ligne[1], ligne[2])
        x = round(self.f_de(e.position().x())) - c.debut
        if not c.enveloppe:
            c.enveloppe = [[0, 1.0], [c.duree - 1, 1.0]]
        edition.poser_point(self.projet.sequence, c.id, x, valeur_enveloppe(c.enveloppe, x))
        self.modifie.emit("Point d'enveloppe")
        self.update()

    def _menu(self, e, zone, c, rang):
        menu = QMenu(self)
        seq = self.projet.sequence
        if zone == "point":
            menu.addAction("Retirer ce point", lambda: (edition.retirer_point(seq, c.id, rang),
                                                        self.modifie.emit("Point retiré")))
        if c is not None:
            if c.id not in self.selection:
                self._choisir({c.id})
            menu.addAction("Couper à la tête de lecture (S)", self.parent().couper)
            menu.addAction("Supprimer (Suppr)", self.parent().supprimer)
            if c.lien:
                menu.addAction("Dissocier son et image (U)", self.parent().dissocier)
            elif len(self.selection) > 1:
                menu.addAction("Lier la sélection", self.parent().lier)
        if menu.actions():
            menu.exec(e.globalPosition().toPoint())

    def _choisir(self, ids: set[str]):
        self.selection = set(ids)
        self.selection_changee.emit(self.selection)
        self.update()

    def _placer_tete(self, f: float):
        f = max(0, round(f))
        self.tete = f
        self.tete_changee.emit(f)
        self.update()

    # Molette et clavier

    def wheelEvent(self, e):
        d = e.angleDelta().y() or e.angleDelta().x()
        if e.modifiers() & Qt.ControlModifier:
            self.parent().zoomer(1.25 if d > 0 else 0.8, e.position().x())
        elif e.modifiers() & Qt.ShiftModifier or e.angleDelta().x():
            self.parent().defiler_x(-d)
        else:
            self.parent().defiler_y(-d // 2)

    def keyPressEvent(self, e):
        seq = self.projet.sequence if self.projet else None
        if seq is None:
            return
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            sous = {c.id for p in seq.pistes for c in p.clips if c.contient(self.tete)}
            self._choisir(self.selection ^ sous if sous else set())
        elif e.key() in (Qt.Key_Left, Qt.Key_Right) and e.modifiers() & Qt.AltModifier \
                and self.selection:
            try:
                edition.deplacer(seq, self.selection, -1 if e.key() == Qt.Key_Left else 1)
                self.modifie.emit("Déplacement")
            except edition.EditionImpossible:
                pass
        elif e.key() == Qt.Key_Escape:
            self._choisir(set())
        else:
            super().keyPressEvent(e)

    # Dépôt depuis le panneau Médias

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME_MEDIA):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if not e.mimeData().hasFormat(MIME_MEDIA):
            return
        f = max(0, round(self.f_de(e.position().x())))
        if self._seuil():
            f = edition.aimanter(f, edition.cibles_aimantation(self.projet.sequence, set(),
                                                               self.tete), self._seuil())
        ligne = self.piste_a(e.position().y())
        self._depot = (f, ligne[0].id if ligne else "")
        e.acceptProposedAction()
        self.update()

    def dragLeaveEvent(self, _e):
        self._depot = None
        self.update()

    def dropEvent(self, e):
        if self._depot is None:
            return
        ids = bytes(e.mimeData().data(MIME_MEDIA)).decode().split(",")
        f, piste_id = self._depot
        self._depot = None
        self.media_depose.emit(ids, f, piste_id)
        e.acceptProposedAction()
        self.update()


class EntetePiste(QWidget):
    def __init__(self, timeline: "Timeline", piste: Piste):
        super().__init__(timeline)
        self.piste = piste
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 3, 4, 3)
        lay.setSpacing(2)
        nom = QLabel(piste.nom)
        nom.setStyleSheet("background: transparent; font-weight: 600;")
        lay.addWidget(nom)
        boutons = QHBoxLayout()
        boutons.setSpacing(3)
        video = piste.type == "video"
        bascule = QToolButton()
        bascule.setCheckable(True)
        if video:
            bascule.setText("Masquée")
            bascule.setChecked(piste.masquee)
            bascule.setToolTip("Masque la piste dans l'aperçu et dans l'export.")
        else:
            bascule.setText("Muette")
            bascule.setChecked(piste.muette)
            bascule.setToolTip("Coupe le son de la piste dans la lecture et dans l'export.")
        bascule.toggled.connect(lambda v: timeline.basculer(piste.id, "masquee" if video
                                                            else "muette", v))
        verrou = QToolButton()
        verrou.setText("Verrou")
        verrou.setCheckable(True)
        verrou.setChecked(piste.verrouillee)
        verrou.setToolTip("Empêche toute modification des clips de cette piste.")
        verrou.toggled.connect(lambda v: timeline.basculer(piste.id, "verrouillee", v))
        monter = QToolButton()
        monter.setText("↑")
        monter.setToolTip("Monter la piste")
        monter.setAccessibleName("Monter la piste")
        monter.clicked.connect(lambda: timeline.deplacer_piste(piste.id, -1))
        descendre = QToolButton()
        descendre.setText("↓")
        descendre.setToolTip("Descendre la piste")
        descendre.setAccessibleName("Descendre la piste")
        descendre.clicked.connect(lambda: timeline.deplacer_piste(piste.id, 1))
        for b in (bascule, verrou, monter, descendre):
            b.setStyleSheet("padding: 1px 5px; min-height: 18px;")
            boutons.addWidget(b)
        boutons.addStretch(1)
        lay.addLayout(boutons)
        lay.addStretch(1)
        self.setAutoFillBackground(True)


class Timeline(QWidget):
    """Conteneur : barre d'outils, en-têtes de pistes, vue des clips et barres de défilement."""

    def __init__(self, fenetre, parent=None):
        super().__init__(parent)
        self.fenetre = fenetre
        self.vue = VueTimeline(self)
        self.barre_h = QScrollBar(Qt.Horizontal)
        self.barre_v = QScrollBar(Qt.Vertical)
        self.barre_h.valueChanged.connect(self._sur_defilement_h)
        self.barre_v.valueChanged.connect(self._sur_defilement_v)
        self.zone_entetes = QWidget()
        self.zone_entetes.setFixedWidth(LARGEUR_ENTETE)
        self._entetes: list[EntetePiste] = []

        outils = QHBoxLayout()
        b_video = QPushButton("Ajouter une piste vidéo")
        b_video.clicked.connect(lambda: self._ajouter_piste("video"))
        b_audio = QPushButton("Ajouter une piste audio")
        b_audio.clicked.connect(lambda: self._ajouter_piste("audio"))
        self.b_aimant = QPushButton("Aimantation")
        self.b_aimant.setCheckable(True)
        self.b_aimant.setChecked(True)
        self.b_aimant.setToolTip("Les bords des clips s'accrochent aux autres clips, à la tête de "
                                 "lecture, aux marqueurs et aux points d'entrée et de sortie.")
        self.b_aimant.toggled.connect(self._aimant)
        b_moins = QPushButton("Zoom −")
        b_moins.setToolTip("Dézoomer (Ctrl + molette)")
        b_moins.clicked.connect(lambda: self.zoomer(0.67))
        b_plus = QPushButton("Zoom +")
        b_plus.setToolTip("Zoomer (Ctrl + molette)")
        b_plus.clicked.connect(lambda: self.zoomer(1.5))
        b_tout = QPushButton("Tout voir")
        b_tout.setToolTip("Ajuste le zoom pour voir toute la séquence.")
        b_tout.clicked.connect(self.tout_voir)
        for b in (b_video, b_audio, self.b_aimant):
            outils.addWidget(b)
        outils.addStretch(1)
        for b in (b_moins, b_plus, b_tout):
            outils.addWidget(b)

        centre = QHBoxLayout()
        centre.setSpacing(0)
        centre.addWidget(self.zone_entetes)
        centre.addWidget(self.vue, 1)
        centre.addWidget(self.barre_v)
        bas = QHBoxLayout()
        bas.addSpacing(LARGEUR_ENTETE)
        bas.addWidget(self.barre_h)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(2)
        lay.addLayout(outils)
        lay.addLayout(centre, 1)
        lay.addLayout(bas)

    # Relais vers la fenêtre (menu contextuel des clips)

    def couper(self):
        self.fenetre.couper()

    def supprimer(self):
        self.fenetre.supprimer()

    def dissocier(self):
        self.fenetre.dissocier()

    def lier(self):
        self.fenetre.lier()

    def basculer(self, piste_id: str, champ: str, valeur: bool):
        self.fenetre.regler_piste(piste_id, champ, valeur)

    def deplacer_piste(self, piste_id: str, sens: int):
        self.fenetre.deplacer_piste(piste_id, sens)

    def _ajouter_piste(self, type_):
        self.fenetre.ajouter_piste(type_)

    def _aimant(self, actif: bool):
        self.vue.aimantation = actif

    # Affichage

    def afficher(self, projet: Projet):
        self.vue.projet = projet
        ids = {c.id for _, c in projet.sequence.tous_les_clips()}
        self.vue.selection &= ids
        for e in self._entetes:
            e.deleteLater()
        self._entetes = [EntetePiste(self, p) for p in projet.sequence.pistes]
        for e in self._entetes:
            e.setParent(self.zone_entetes)
            e.show()
        self._placer_entetes()
        self._bornes()
        self.vue.update()

    def _placer_entetes(self):
        lignes = {p.id: (y, h) for p, y, h in self.vue.lignes()}
        for e in self._entetes:
            y, h = lignes.get(e.piste.id, (0, 0))
            e.setGeometry(0, y, LARGEUR_ENTETE, h - 1)

    def _bornes(self):
        if self.vue.projet is None:
            return
        duree = max(self.vue.projet.sequence.duree(), self.vue.tete) + 200
        self.barre_h.setRange(0, max(0, int(duree * self.vue.px_par_image - self.vue.width() / 2)))
        self.barre_h.setPageStep(max(1, self.vue.width()))
        self.barre_v.setRange(0, max(0, self.vue.hauteur_totale() + HAUTEUR_REGLE -
                                     self.vue.height()))
        self.barre_v.setPageStep(max(1, self.vue.height()))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._bornes()

    def _sur_defilement_h(self, v):
        self.vue.decalage_x = float(v)
        self.vue.update()

    def _sur_defilement_v(self, v):
        self.vue.decalage_y = int(v)
        self._placer_entetes()
        self.vue.update()

    def defiler_x(self, d: int):
        self.barre_h.setValue(self.barre_h.value() + d)

    def defiler_y(self, d: int):
        self.barre_v.setValue(self.barre_v.value() + d)

    def zoomer(self, facteur: float, x_ancre: float | None = None):
        v = self.vue
        x_ancre = v.width() / 2 if x_ancre is None else x_ancre
        f_ancre = v.f_de(x_ancre)
        v.px_par_image = max(0.02, min(40.0, v.px_par_image * facteur))
        self._bornes()
        self.barre_h.setValue(int(f_ancre * v.px_par_image - x_ancre))
        v.decalage_x = float(self.barre_h.value())
        v.update()

    def tout_voir(self):
        v = self.vue
        duree = max(1, v.projet.sequence.duree() if v.projet else 1)
        v.px_par_image = max(0.02, min(40.0, (v.width() - 40) / duree))
        self._bornes()
        self.barre_h.setValue(0)
        v.decalage_x = 0
        v.update()

    def suivre_tete(self, f: int):
        """Fait défiler la vue pendant la lecture pour garder la tête visible."""
        v = self.vue
        v.tete = f
        x = v.x_de(f)
        if x > v.width() - 30 or x < 0:
            self._bornes()
            self.barre_h.setValue(int(f * v.px_par_image - 60))
        v.update()
