"""Timeline multipiste : règle en timecode, en-têtes de pistes et clips manipulables à la souris.

Pendant un geste (déplacer, rogner, fondu, point d'enveloppe), chaque mouvement de souris
repart de l'état au moment du clic et réapplique l'opération : l'aperçu montre exactement
ce que donnera le relâchement, écrasements compris.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QDoubleSpinBox, QHBoxLayout, QMenu, QScrollBar, QSlider,
                               QToolButton, QVBoxLayout, QWidget)

from remanence.media.lecteur import AudioCache
from remanence.media.proxy import chemin_audio
from remanence.media.timecode import images_vers_tc
from remanence.projet import edition
from remanence.projet.modele import Clip, Piste, Projet, valeur_enveloppe
from remanence.ui import charte
from remanence.ui.composants import ChampTimecode, bouton_icone, etiquette
from remanence.ui.inspecteur import nom_court_piste
from remanence.ui.medias import MIME_MEDIA

HAUTEUR_REGLE = 28
LARGEUR_ENTETE = 220
BANDEAU = 18
MARGE_BORD = 6
SEUIL_AIMANT_PX = 8
ZOOM_MIN, ZOOM_MAX = 0.02, 40.0


def hauteur_piste(p: Piste) -> int:
    return charte.actuelle().px("track-video-h" if p.type == "video" else "track-audio-h")


@dataclass
class Geste:
    type: str
    clip_id: str | None
    x0: float
    y0: float
    etat: list
    rang: int = -1


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
        self.outil = "selection"
        # media_id -> (vignettes, images source entre deux vignettes)
        self.vignettes: dict[str, tuple[list[QImage], float]] = {}
        self._geste: Geste | None = None
        self._repere: int | None = None
        self._depot: tuple[int, str] | None = None
        self.survol_coupe: float | None = None
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
            h = hauteur_piste(p)
            res.append((p, y, h))
            y += h
        return res

    def hauteur_totale(self) -> int:
        return sum(hauteur_piste(p) for p in self.projet.sequence.pistes) if self.projet else 0

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
        return QRectF(self.x_de(c.debut), y + 3, max(2.0, c.duree * self.px_par_image), h - 7)

    def _y_enveloppe(self, r: QRectF, valeur: float) -> float:
        haut = r.top() + BANDEAU
        return haut + (1 - valeur) * (r.bottom() - 3 - haut)

    # Dessin

    def paintEvent(self, _e):
        c = charte.actuelle()
        p = QPainter(self)
        p.fillRect(self.rect(), c.c("surface"))
        if self.projet is None:
            return
        seq = self.projet.sequence
        for piste, y, h in self.lignes():
            p.setPen(c.c("line"))
            p.drawLine(0, y + h - 1, self.width(), y + h - 1)
            for clip in piste.clips:
                self._dessiner_clip(p, piste, clip, y, h)
        if self._depot is not None:
            self._ligne_pointillee(p, self._depot[0], "accent-2", HAUTEUR_REGLE)
        if self.survol_coupe is not None:
            self._ligne_pointillee(p, self.survol_coupe, "ink", HAUTEUR_REGLE)
        self._dessiner_regle(p, seq)
        if self._repere is not None:
            self._ligne_pointillee(p, self._repere, "accent-2", 0)
        xt = round(self.x_de(self.tete))
        p.fillRect(QRectF(xt - 1, 0, 2, self.height()), c.c("playhead"))
        tri = QPainterPath()
        tri.moveTo(xt - 6, 0)
        tri.lineTo(xt + 6, 0)
        tri.lineTo(xt, 8)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillPath(tri, c.c("playhead"))
        if not any(cl for pi in seq.pistes for cl in pi.clips):
            p.setPen(c.c("ink-muted"))
            p.setFont(c.police("body"))
            p.drawText(QRect(0, HAUTEUR_REGLE, self.width(), self.height() - HAUTEUR_REGLE),
                       Qt.AlignCenter, "Glissez un média depuis le panneau Médias pour commencer "
                                       "le montage.")
        if self.hasFocus():
            p.setPen(QPen(c.c("focus"), 2))
            p.drawRect(QRectF(1, 1, self.width() - 2, self.height() - 2))
        p.end()

    def _ligne_pointillee(self, p: QPainter, f: float, couleur: str, y0: int):
        x = self.x_de(f)
        p.setPen(QPen(charte.actuelle().c(couleur), 1, Qt.DashLine))
        p.drawLine(QPointF(x, y0), QPointF(x, self.height()))

    def _pas_graduation(self) -> int:
        cad = max(1, round(float(self.projet.sequence.fraction_cadence)))
        for pas in (1, 2, 5, 10, cad, 2 * cad, 5 * cad, 10 * cad, 30 * cad, 60 * cad,
                    300 * cad, 600 * cad, 1800 * cad, 3600 * cad):
            if pas * self.px_par_image >= 96:
                return pas
        return 3600 * cad

    def _dessiner_regle(self, p: QPainter, seq):
        c = charte.actuelle()
        p.fillRect(QRect(0, 0, self.width(), HAUTEUR_REGLE), c.c("surface"))
        if seq.point_entree is not None or seq.point_sortie is not None:
            a = self.x_de(seq.point_entree or 0)
            b = self.x_de(seq.point_sortie if seq.point_sortie is not None else seq.duree())
            p.fillRect(QRectF(a, 0, max(1.0, b - a), HAUTEUR_REGLE), c.c("surface-hover"))
            p.fillRect(QRectF(a, 0, 1, HAUTEUR_REGLE), c.c("ink-muted"))
            p.fillRect(QRectF(b - 1, 0, 1, HAUTEUR_REGLE), c.c("ink-muted"))
        pas = self._pas_graduation()
        premier = max(0, int(self.f_de(0)) // pas * pas)
        dernier = int(self.f_de(self.width())) + pas
        cad = seq.fraction_cadence
        p.setFont(c.police("value", 11))
        for f in range(premier, dernier, pas):
            x = self.x_de(f)
            p.setPen(c.c("ink-faint"))
            p.drawLine(QPointF(x, HAUTEUR_REGLE - 8), QPointF(x, HAUTEUR_REGLE))
            sous = pas / 5
            if sous * self.px_par_image >= 8:
                for k in range(1, 5):
                    xs = self.x_de(f + k * sous)
                    p.drawLine(QPointF(xs, HAUTEUR_REGLE - 4), QPointF(xs, HAUTEUR_REGLE))
            p.setPen(c.c("ink-muted"))
            p.drawText(QPointF(x + 3, 14), images_vers_tc(seq.tc_debut + f, cad, seq.tc_drop))
        for m in seq.marqueurs:
            x = self.x_de(m.position)
            p.fillRect(QRectF(x - 3, HAUTEUR_REGLE - 10, 6, 10),
                       c.c(m.couleur if m.couleur in c.couleurs else "accent-2"))
        p.setPen(c.c("line"))
        p.drawLine(0, HAUTEUR_REGLE - 1, self.width(), HAUTEUR_REGLE - 1)

    def _dessiner_clip(self, p: QPainter, piste: Piste, clip: Clip, y: int, h: int):
        c = charte.actuelle()
        r = self.rect_clip(clip, y, h)
        if r.right() < 0 or r.left() > self.width():
            return
        media = self.projet.medias.get(clip.media_id)
        video = piste.type == "video"
        fond = c.c("clip-video" if video else "clip-audio")
        rayon = c.px("radius-xs")
        forme = QPainterPath()
        forme.addRoundedRect(r, rayon, rayon)
        p.save()
        p.setClipPath(forme)
        p.fillRect(r, fond)
        if video and media is not None:
            self._dessiner_vignettes(p, clip, media, r)
        elif media is not None:
            self._dessiner_onde(p, clip, media, r)
        self._dessiner_fondus(p, clip, r)
        self._dessiner_enveloppe(p, clip, r)
        # Bandeau du nom, sur la couleur du clip : lisible même par-dessus les vignettes.
        p.fillRect(QRectF(r.left(), r.top(), r.width(), BANDEAU), fond)
        p.setPen(c.c("ink"))
        p.setFont(c.police("label"))
        nom = media.nom if media else "Média manquant"
        if media and media.hors_ligne:
            nom += " (hors ligne)"
        if clip.lien is None and media and media.infos.video and media.infos.audio:
            nom += " · dissocié"
        p.drawText(QRectF(r.left() + 8, r.top(), r.width() - 16, BANDEAU),
                   Qt.AlignVCenter | Qt.AlignLeft, nom)
        for gauche in (True, False):
            hx = r.left() + clip.fondu_entree * self.px_par_image if gauche else \
                r.right() - clip.fondu_sortie * self.px_par_image
            p.fillRect(QRectF(hx - (0 if gauche else 6), r.top(), 6, 6), c.c("ink"))
        if piste.masquee or piste.muette:
            p.fillRect(r, c.c("bg-app", 0.55))
        p.restore()
        if clip.id in self.selection:
            p.save()
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setPen(QPen(c.c("accent"), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), rayon, rayon)
            p.restore()

    def _dessiner_vignettes(self, p: QPainter, clip: Clip, media, r: QRectF):
        donnees = self.vignettes.get(media.id)
        if not donnees or not donnees[0]:
            return
        images, pas = donnees
        haut = r.top() + BANDEAU
        hauteur = r.bottom() - haut
        if hauteur < 8:
            return
        l = images[0].width() * hauteur / images[0].height()
        x = r.left() + max(0.0, math.floor(-r.left() / l)) * l
        while x < min(r.right(), self.width()):
            f_source = clip.entree + (self.f_de(x) - clip.debut)
            k = max(0, min(len(images) - 1, int(f_source / pas)))
            p.drawImage(QRectF(x, haut, l, hauteur), images[k])
            x += l

    def _dessiner_onde(self, p: QPainter, clip: Clip, media, r: QRectF):
        cache = self._ondes.get(media.id)
        if cache is None:
            fichier = chemin_audio(media.infos)
            if not fichier.exists():
                return
            try:
                ac = AudioCache(fichier)
            except Exception:
                return
            cache = self._ondes[media.id] = (ac.cretes(4000), ac.nb, ac.decalage_s)
        cretes, nb, decalage = cache
        if nb == 0 or len(cretes) == 0:
            return
        cad = float(self.projet.sequence.fraction_cadence)
        cad_media = float(media.infos.video.fraction_cadence) if media.infos.video else cad
        par_case = nb / len(cretes)
        milieu = (r.top() + BANDEAU + r.bottom()) / 2
        demi = (r.bottom() - r.top() - BANDEAU) / 2 - 1
        p.setPen(QPen(charte.actuelle().c("ink-muted"), 1))
        for x in range(max(int(r.left()), 0), min(int(r.right()), self.width())):
            f = self.f_de(x) - clip.debut
            t = (clip.entree / cad_media) + f / cad - decalage
            k = int(t * 48000 / par_case)
            if 0 <= k < len(cretes):
                a = float(cretes[k]) * demi * clip.facteur(clip.debut + int(f))
                p.drawLine(QPointF(x, milieu - a), QPointF(x, milieu + a))

    def _dessiner_fondus(self, p: QPainter, clip: Clip, r: QRectF):
        c = charte.actuelle()
        corps_haut = r.top() + BANDEAU
        p.setPen(QPen(c.c("ink"), 1))
        for longueur, gauche in ((clip.fondu_entree, True), (clip.fondu_sortie, False)):
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
            p.fillPath(chemin, c.c("bg-app", 0.45))
            if gauche:
                p.drawLine(QPointF(x0, r.bottom()), QPointF(x0 + l, corps_haut))
            else:
                p.drawLine(QPointF(x0, corps_haut), QPointF(x0 + l, r.bottom()))

    def _dessiner_enveloppe(self, p: QPainter, clip: Clip, r: QRectF):
        if not clip.enveloppe and clip.gain == 1.0:
            return
        c = charte.actuelle()
        pts = clip.enveloppe or [[0, 1.0]]
        chemin = QPainterPath()
        chemin.moveTo(r.left(), self._y_enveloppe(r, pts[0][1] * clip.gain))
        for x, v in pts:
            chemin.lineTo(self.x_de(clip.debut + x), self._y_enveloppe(r, v * clip.gain))
        chemin.lineTo(r.right(), self._y_enveloppe(r, pts[-1][1] * clip.gain))
        p.setPen(QPen(c.c("ink"), 1))
        p.drawPath(chemin)
        for x, v in clip.enveloppe:
            px, py = self.x_de(clip.debut + x), self._y_enveloppe(r, v * clip.gain)
            p.fillRect(QRectF(px - 3, py - 3, 6, 6), c.c("ink"))

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
        for clip in piste.clips:
            r = self.rect_clip(clip, y, h)
            if not r.adjusted(-MARGE_BORD, 0, MARGE_BORD, 0).contains(pos):
                continue
            if self.outil == "couper":
                return ("corps", piste, clip, -1) if r.contains(pos) else ("vide", piste, None, -1)
            for rang, (x, v) in enumerate(clip.enveloppe):
                px, py = self.x_de(clip.debut + x), self._y_enveloppe(r, v * clip.gain)
                if abs(pos.x() - px) <= 5 and abs(pos.y() - py) <= 5:
                    return "point", piste, clip, rang
            if pos.y() <= r.top() + 9:
                hg = r.left() + clip.fondu_entree * self.px_par_image
                hd = r.right() - clip.fondu_sortie * self.px_par_image
                if abs(pos.x() - hg) <= 7:
                    return "fondu_entree", piste, clip, -1
                if abs(pos.x() - hd) <= 7:
                    return "fondu_sortie", piste, clip, -1
            if abs(pos.x() - r.left()) <= MARGE_BORD:
                return "bord_debut", piste, clip, -1
            if abs(pos.x() - r.right()) <= MARGE_BORD:
                return "bord_fin", piste, clip, -1
            if r.contains(pos):
                return "corps", piste, clip, -1
        return "vide", piste, None, -1

    def _seuil(self) -> int:
        return max(1, math.ceil(SEUIL_AIMANT_PX / self.px_par_image)) if self.aimantation else 0

    def _f_aimantee(self, x: float, exclure: set[str]) -> int:
        f = max(0, round(self.f_de(x)))
        if self._seuil():
            f = edition.aimanter(f, edition.cibles_aimantation(self.projet.sequence, exclure,
                                                               self.tete), self._seuil())
        return f

    # Souris

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._geste is None:
            zone, _, clip, _ = self._sous(pos)
            if self.outil == "couper":
                self.survol_coupe = self._f_aimantee(pos.x(), set()) if clip else None
                self.setCursor(Qt.SplitHCursor if clip else Qt.ArrowCursor)
                self.update()
                return
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
        self._repere = None
        lies = not (e.modifiers() & Qt.AltModifier)
        try:
            if g.type == "deplacer":
                _, clip = seq.trouver(g.clip_id)
                delta = self._aimanter_deplacement(clip, dx_images)
                ligne = self.piste_a(pos.y())
                ligne0 = self.piste_a(g.y0)
                delta_piste = 0
                if ligne and ligne0 and ligne[0].type == ligne0[0].type:
                    meme = [q for q in seq.pistes if q.type == ligne0[0].type]
                    delta_piste = meme.index(ligne[0]) - meme.index(ligne0[0])
                edition.deplacer(seq, self.selection | {g.clip_id}, delta, delta_piste,
                                 inclure_lies=lies)
            elif g.type in ("bord_debut", "bord_fin"):
                _, clip = seq.trouver(g.clip_id)
                cote = "debut" if g.type == "bord_debut" else "fin"
                bord = clip.debut if cote == "debut" else clip.fin
                cible = bord + dx_images
                if self._seuil():
                    cible2 = edition.aimanter(cible, edition.cibles_aimantation(
                        seq, {clip.id}, self.tete), self._seuil())
                    if cible2 != cible:
                        self._repere = cible2
                    cible = cible2
                edition.rogner(self.projet, seq, clip.id, cote, cible - bord, inclure_lies=lies)
            elif g.type in ("fondu_entree", "fondu_sortie"):
                _, clip = seq.trouver(g.clip_id)
                f = round(self.f_de(pos.x()))
                longueur = f - clip.debut if g.type == "fondu_entree" else clip.fin - f
                edition.regler_fondu(seq, clip.id,
                                     "entree" if g.type == "fondu_entree" else "sortie", longueur)
            elif g.type == "point":
                piste, clip = seq.trouver(g.clip_id)
                ligne = next(l for l in self.lignes() if l[0].id == piste.id)
                r = self.rect_clip(clip, ligne[1], ligne[2])
                haut = r.top() + BANDEAU
                valeur = 1 - (pos.y() - haut) / max(1.0, r.bottom() - 3 - haut)
                valeur = max(0.0, min(1.0, valeur / max(clip.gain, 1e-6)))
                x = self.f_de(pos.x()) - clip.debut
                del clip.enveloppe[g.rang]
                g.rang = edition.poser_point(seq, clip.id, round(x), valeur)
                g.etat = copy.deepcopy(seq.pistes)
                g.x0 = pos.x()
        except edition.EditionImpossible:
            seq.pistes = copy.deepcopy(g.etat)
        self.update()

    def _aimanter_deplacement(self, clip: Clip, delta: int) -> int:
        seuil = self._seuil()
        if not seuil:
            return delta
        exclus = edition.avec_lies(self.projet.sequence, self.selection | {clip.id})
        cibles = edition.cibles_aimantation(self.projet.sequence, exclus, self.tete)
        meilleur = delta
        ecart = seuil + 1
        for bord in (clip.debut, clip.fin):
            cible = edition.aimanter(bord + delta, cibles, seuil)
            if cible != bord + delta and abs(cible - bord - delta) < ecart:
                ecart = abs(cible - bord - delta)
                meilleur = cible - bord
                self._repere = cible
        return meilleur

    def leaveEvent(self, _e):
        if self.survol_coupe is not None:
            self.survol_coupe = None
            self.update()

    def mousePressEvent(self, e):
        self.setFocus()
        if self.projet is None:
            return
        pos = e.position()
        zone, piste, clip, rang = self._sous(pos)
        if e.button() == Qt.RightButton:
            self._menu(e, zone, clip, rang)
            return
        if e.button() != Qt.LeftButton:
            return
        etat = copy.deepcopy(self.projet.sequence.pistes)
        if zone in ("regle", "vide"):
            if zone == "vide" and not (e.modifiers() & Qt.ControlModifier):
                self._choisir(set())
            self._placer_tete(self.f_de(pos.x()))
            self._geste = Geste("regle", None, pos.x(), pos.y(), etat)
            return
        if self.outil == "couper":
            f = self._f_aimantee(pos.x(), set())
            if not piste.verrouillee and clip.debut < f < clip.fin:
                ids = {clip.id} if e.modifiers() & Qt.AltModifier else \
                    edition.avec_lies(self.projet.sequence, {clip.id})
                edition.couper(self.projet.sequence, f, ids)
                self.modifie.emit("Coupe")
            return
        if piste.verrouillee:
            self._choisir({clip.id})
            return
        if e.modifiers() & Qt.ControlModifier:
            self._choisir(self.selection ^ {clip.id})
        elif clip.id not in self.selection:
            self._choisir({clip.id})
        types = {"corps": "deplacer", "bord_debut": "bord_debut", "bord_fin": "bord_fin",
                 "fondu_entree": "fondu_entree", "fondu_sortie": "fondu_sortie", "point": "point"}
        self._geste = Geste(types[zone], clip.id, pos.x(), pos.y(), etat, rang=rang)
        if zone == "corps":
            self.setCursor(Qt.ClosedHandCursor)

    def mouseReleaseEvent(self, e):
        g = self._geste
        self._geste = None
        self._repere = None
        if g is None:
            return
        libelles = {"deplacer": "Déplacement", "bord_debut": "Rognage", "bord_fin": "Rognage",
                    "fondu_entree": "Fondu d'entrée", "fondu_sortie": "Fondu de sortie",
                    "point": "Point d'enveloppe"}
        if g.type in libelles:
            self.modifie.emit(libelles[g.type])
        self.update()

    def mouseDoubleClickEvent(self, e):
        if self.outil != "selection":
            return
        zone, piste, clip, _ = self._sous(e.position())
        if zone != "corps" or piste.verrouillee:
            return
        x = round(self.f_de(e.position().x())) - clip.debut
        if not clip.enveloppe:
            clip.enveloppe = [[0, 1.0], [clip.duree - 1, 1.0]]
        edition.poser_point(self.projet.sequence, clip.id, x,
                            valeur_enveloppe(clip.enveloppe, x))
        self.modifie.emit("Point d'enveloppe")
        self.update()

    def _menu(self, e, zone, clip, rang):
        menu = QMenu(self)
        seq = self.projet.sequence
        fenetre = self.parent().fenetre
        if zone == "point":
            menu.addAction("Retirer ce point", lambda: (edition.retirer_point(seq, clip.id, rang),
                                                        self.modifie.emit("Point retiré")))
        if clip is not None:
            if clip.id not in self.selection:
                self._choisir({clip.id})
            menu.addAction("Couper à la tête de lecture (S)", fenetre.couper)
            menu.addAction("Supprimer (Suppr)", fenetre.supprimer)
            if clip.lien:
                menu.addAction("Dissocier son et image (U)", fenetre.dissocier)
            elif len(self.selection) > 1:
                menu.addAction("Lier la sélection", fenetre.lier)
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
        tl = self.parent()
        if e.modifiers() & Qt.ControlModifier:
            tl.zoomer(1.25 if d > 0 else 0.8, e.position().x())
        elif e.modifiers() & Qt.ShiftModifier or e.angleDelta().x():
            tl.defiler_x(-d)
        else:
            tl.defiler_y(-d // 2)

    def keyPressEvent(self, e):
        seq = self.projet.sequence if self.projet else None
        if seq is None:
            return
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            sous = {cl.id for p in seq.pistes for cl in p.clips if cl.contient(self.tete)}
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
        f = self._f_aimantee(e.position().x(), set())
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


def bouton_lettre(lettre: str, aide: str) -> QToolButton:
    b = QToolButton()
    b.setText(lettre)
    b.setProperty("variante", "lettre")
    b.setCheckable(True)
    b.setToolTip(aide)
    b.setAccessibleName(aide)
    return b


class EntetePiste(QWidget):
    """En-tête d'une piste : nom court (V1, A1), M, S, verrou, et niveau de la piste."""

    def __init__(self, timeline: "Timeline", piste: Piste, nom: str):
        super().__init__(timeline.zone_entetes)
        self.piste = piste
        self.fenetre = timeline.fenetre
        self.setProperty("role", "entete-piste")
        self.setAttribute(Qt.WA_StyledBackground, True)
        video = piste.type == "video"
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(8)
        # Filet de la couleur des clips de la piste : il relie l'en-tête à ses clips.
        filet = QWidget()
        filet.setFixedWidth(4)
        filet.setProperty("role", "filet-video" if video else "filet-audio")
        filet.setAttribute(Qt.WA_StyledBackground, True)
        lay.addWidget(filet)
        colonne = QVBoxLayout()
        colonne.setSpacing(4)
        colonne.setContentsMargins(0, 4, 0, 4)
        ligne = QHBoxLayout()
        ligne.setSpacing(2)
        self.nom = etiquette(nom, "section")
        ligne.addWidget(self.nom, 1)
        if not video:
            self.niveau_db = QDoubleSpinBox()
            self.niveau_db.setButtonSymbols(QDoubleSpinBox.NoButtons)
            self.niveau_db.setRange(-60.0, 12.0)
            self.niveau_db.setDecimals(1)
            self.niveau_db.setSuffix(" dB")
            self.niveau_db.setFixedWidth(78)
            self.niveau_db.setProperty("variante", "compact")
            self.niveau_db.setValue(20 * math.log10(max(piste.niveau, 1e-3)))
            self.niveau_db.setToolTip("Volume de la piste, en décibels (molette ou saisie).")
            self.niveau_db.setAccessibleName(f"Volume de la piste {nom}")
            self.niveau_db.editingFinished.connect(
                lambda: self.fenetre.regler_piste(piste.id, "niveau",
                                                  10 ** (self.niveau_db.value() / 20)))
            ligne.addWidget(self.niveau_db)
        for lettre, champ, aide in (
                ("M", "masquee" if video else "muette",
                 "Masquer la piste dans l'aperçu et l'export" if video else
                 "Couper le son de la piste dans la lecture et l'export"),
                ("S", "solo", "Solo : seule cette piste est vue" if video
                 else "Solo : seule cette piste est entendue")):
            b = bouton_lettre(lettre, f"{aide} (piste {nom})")
            b.setChecked(getattr(piste, champ))
            b.toggled.connect(lambda v, champ=champ: self.fenetre.regler_piste(piste.id, champ, v))
            ligne.addWidget(b)
        verrou = bouton_icone("lock" if piste.verrouillee else "lock-open",
                              f"Verrouiller la piste {nom} : ses clips ne bougent plus",
                              cochable=True, taille=14)
        verrou.setFixedSize(22, 22)
        verrou.setChecked(piste.verrouillee)
        verrou.toggled.connect(lambda v: self.fenetre.regler_piste(piste.id, "verrouillee", v))
        ligne.addWidget(verrou)
        colonne.addLayout(ligne)
        if video:
            bas = QHBoxLayout()
            bas.setSpacing(6)
            bas.addWidget(etiquette("Opacité", "libelle"))
            self.niveau = QSlider(Qt.Horizontal)
            self.niveau.setRange(0, 100)
            self.niveau.setValue(round(piste.niveau * 100))
            self.niveau.setToolTip("Opacité de toute la piste.")
            self.niveau.setAccessibleName(f"Opacité de la piste {nom}")
            self.niveau.sliderReleased.connect(self._niveau_video)
            self.niveau.actionTriggered.connect(lambda _a: QTimer.singleShot(0, self._si_relache))
            bas.addWidget(self.niveau, 1)
            colonne.addLayout(bas)
        lay.addLayout(colonne, 1)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def _si_relache(self):
        if not self.niveau.isSliderDown():
            self._niveau_video()

    def _niveau_video(self):
        self.fenetre.regler_piste(self.piste.id, "niveau", self.niveau.value() / 100)

    def _menu(self, pos):
        menu = QMenu(self)
        f = self.fenetre
        menu.addAction("Monter la piste", lambda: f.deplacer_piste(self.piste.id, -1))
        menu.addAction("Descendre la piste", lambda: f.deplacer_piste(self.piste.id, 1))
        menu.addSeparator()
        menu.addAction("Supprimer la piste", lambda: f.supprimer_piste(self.piste.id))
        menu.exec(self.mapToGlobal(pos))


class VueEnsemble(QWidget):
    """Toute la séquence en miniature, avec la partie visible et la tête de lecture.
    Un clic place la tête et amène la timeline à cet endroit."""
    aller = Signal(int)

    def __init__(self, vue: VueTimeline, parent=None):
        super().__init__(parent)
        self.vue = vue
        self.setFixedHeight(28)
        self.setToolTip("Vue d'ensemble de la séquence : cliquez pour y aller.")

    def _echelle(self) -> float:
        duree = max(1, self.vue.projet.sequence.duree() if self.vue.projet else 1)
        return (self.width() - 8) / duree

    def paintEvent(self, _e):
        c = charte.actuelle()
        p = QPainter(self)
        p.fillRect(self.rect(), c.c("surface"))
        if self.vue.projet is None:
            return
        seq = self.vue.projet.sequence
        k = self._echelle()
        lignes = [(pi, 6, 6, "clip-video") for pi in seq.pistes_video] + \
                 [(pi, 21, 4, "clip-audio") for pi in seq.pistes_audio]
        for piste, y, h, couleur in lignes:
            for clip in piste.clips:
                p.fillRect(QRectF(4 + clip.debut * k, y, max(1.0, clip.duree * k), h),
                           c.c(couleur))
        v = self.vue
        f0, f1 = v.f_de(0), v.f_de(v.width())
        p.setPen(QPen(c.c("ink-muted"), 1))
        p.drawRect(QRectF(4 + f0 * k, 2, max(4.0, (f1 - f0) * k), self.height() - 4))
        p.fillRect(QRectF(4 + v.tete * k - 1, 0, 2, self.height()), c.c("playhead"))
        p.end()

    def mousePressEvent(self, e):
        self._aller(e.position().x())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._aller(e.position().x())

    def _aller(self, x: float):
        self.aller.emit(max(0, round((x - 4) / self._echelle())))


class Timeline(QWidget):
    """Conteneur : vue d'ensemble, barre d'outils, en-têtes de pistes, clips et défilement."""

    def __init__(self, fenetre, parent=None):
        super().__init__(parent)
        self.fenetre = fenetre
        self.vue = VueTimeline(self)
        self.vue_ensemble = VueEnsemble(self.vue)
        self.vue_ensemble.aller.connect(self._aller_ensemble)
        self.barre_h = QScrollBar(Qt.Horizontal)
        self.barre_v = QScrollBar(Qt.Vertical)
        self.barre_h.valueChanged.connect(self._sur_defilement_h)
        self.barre_v.valueChanged.connect(self._sur_defilement_v)
        self.zone_entetes = QWidget()
        self.zone_entetes.setProperty("role", "panneau")
        self.zone_entetes.setAttribute(Qt.WA_StyledBackground, True)
        self.zone_entetes.setFixedWidth(LARGEUR_ENTETE)
        self._entetes: list[EntetePiste] = []
        self.timecode = ChampTimecode(18, self.zone_entetes)
        self.timecode.position_demandee.connect(fenetre.aller_a)

        ensemble = QHBoxLayout()
        ensemble.setContentsMargins(0, 0, 0, 0)
        ensemble.setSpacing(0)
        titre_ensemble = etiquette("Vue d'ensemble", "section")
        titre_ensemble.setFixedWidth(LARGEUR_ENTETE)
        titre_ensemble.setContentsMargins(12, 0, 0, 0)
        ensemble.addWidget(titre_ensemble)
        ensemble.addWidget(self.vue_ensemble, 1)
        barre_ensemble = QWidget()
        barre_ensemble.setProperty("role", "entete")
        barre_ensemble.setAttribute(Qt.WA_StyledBackground, True)
        barre_ensemble.setLayout(ensemble)

        outils = QHBoxLayout()
        outils.setContentsMargins(12, 4, 12, 4)
        outils.setSpacing(4)
        self.b_selection = bouton_icone("mouse-pointer-2", "Outil de sélection : déplacer, "
                                        "rogner, régler les fondus (V)", cochable=True)
        self.b_couper = bouton_icone("scissors", "Outil de coupe : cliquez sur un clip pour le "
                                     "couper à cet endroit (C)", cochable=True)
        self.b_selection.setChecked(True)
        self.b_selection.clicked.connect(lambda: self.choisir_outil("selection"))
        self.b_couper.clicked.connect(lambda: self.choisir_outil("couper"))
        self.b_aimant = bouton_icone("magnet", "Aimantation : les bords des clips s'accrochent "
                                     "aux autres clips, à la tête de lecture, aux marqueurs et "
                                     "aux points d'entrée et de sortie", cochable=True)
        self.b_aimant.setChecked(True)
        self.b_aimant.toggled.connect(self._aimant)
        self.b_piste = bouton_icone("plus", "Ajouter une piste vidéo ou audio", texte="Piste")
        self.b_piste.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.b_piste)
        menu.addAction("Piste vidéo", lambda: fenetre.ajouter_piste("video"))
        menu.addAction("Piste audio", lambda: fenetre.ajouter_piste("audio"))
        self.b_piste.setMenu(menu)
        self.zoom = QSlider(Qt.Horizontal)
        self.zoom.setRange(0, 1000)
        self.zoom.setFixedWidth(140)
        self.zoom.setToolTip("Zoom de la timeline (aussi Ctrl + molette)")
        self.zoom.setAccessibleName("Zoom de la timeline")
        self.zoom.valueChanged.connect(self._zoom_curseur)
        b_tout = bouton_icone("maximize-2", "Tout voir : ajuste le zoom à toute la séquence")
        b_tout.clicked.connect(self.tout_voir)
        outils.addWidget(self.b_selection)
        outils.addWidget(self.b_couper)
        separateur = QWidget()
        separateur.setFixedSize(1, 18)
        separateur.setProperty("role", "filet")
        separateur.setAttribute(Qt.WA_StyledBackground, True)
        outils.addSpacing(6)
        outils.addWidget(separateur)
        outils.addSpacing(6)
        outils.addWidget(self.b_aimant)
        outils.addWidget(self.b_piste)
        outils.addStretch(1)
        outils.addWidget(etiquette("Zoom", "libelle"))
        outils.addWidget(self.zoom)
        outils.addWidget(b_tout)
        barre_outils = QWidget()
        barre_outils.setProperty("role", "entete")
        barre_outils.setAttribute(Qt.WA_StyledBackground, True)
        barre_outils.setLayout(outils)

        centre = QHBoxLayout()
        centre.setSpacing(0)
        centre.addWidget(self.zone_entetes)
        centre.addWidget(self.vue, 1)
        centre.addWidget(self.barre_v)
        bas = QHBoxLayout()
        bas.addSpacing(LARGEUR_ENTETE)
        bas.addWidget(self.barre_h)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(barre_ensemble)
        lay.addWidget(barre_outils)
        lay.addLayout(centre, 1)
        lay.addLayout(bas)
        self._synchroniser_zoom()

    def choisir_outil(self, outil: str):
        self.vue.outil = outil
        self.b_selection.setChecked(outil == "selection")
        self.b_couper.setChecked(outil == "couper")
        self.vue.survol_coupe = None
        self.vue.update()

    def _aimant(self, actif: bool):
        self.vue.aimantation = actif

    def _aller_ensemble(self, f: int):
        self.fenetre.aller_a(f)
        v = self.vue
        self.barre_h.setValue(int(f * v.px_par_image - v.width() / 2))

    # Affichage

    def afficher(self, projet: Projet):
        self.vue.projet = projet
        ids = {cl.id for _, cl in projet.sequence.tous_les_clips()}
        self.vue.selection &= ids
        for e in self._entetes:
            e.deleteLater()
        seq = projet.sequence
        self._entetes = [EntetePiste(self, p, nom_court_piste(seq, p)) for p in seq.pistes]
        for e in self._entetes:
            e.show()
        self._placer_entetes()
        self._bornes()
        self.vue.update()
        self.vue_ensemble.update()

    def _placer_entetes(self):
        lignes = {p.id: (y, h) for p, y, h in self.vue.lignes()}
        for e in self._entetes:
            y, h = lignes.get(e.piste.id, (0, 0))
            e.setGeometry(0, y, LARGEUR_ENTETE, h)
            e.setVisible(y + h > HAUTEUR_REGLE)
        self.timecode.setGeometry(12, 0, self.timecode.width(), HAUTEUR_REGLE)
        self.timecode.raise_()

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
        self.vue_ensemble.update()

    def _sur_defilement_v(self, v):
        self.vue.decalage_y = int(v)
        self._placer_entetes()
        self.vue.update()

    def defiler_x(self, d: int):
        self.barre_h.setValue(self.barre_h.value() + d)

    def defiler_y(self, d: int):
        self.barre_v.setValue(self.barre_v.value() + d)

    def _synchroniser_zoom(self):
        pos = math.log(self.vue.px_par_image / ZOOM_MIN) / math.log(ZOOM_MAX / ZOOM_MIN) * 1000
        self.zoom.blockSignals(True)
        self.zoom.setValue(round(pos))
        self.zoom.blockSignals(False)

    def _zoom_curseur(self, valeur: int):
        cible = ZOOM_MIN * (ZOOM_MAX / ZOOM_MIN) ** (valeur / 1000)
        self.zoomer(cible / self.vue.px_par_image, self.vue.x_de(self.vue.tete), synchro=False)

    def zoomer(self, facteur: float, x_ancre: float | None = None, synchro: bool = True):
        v = self.vue
        x_ancre = v.width() / 2 if x_ancre is None else x_ancre
        f_ancre = v.f_de(x_ancre)
        v.px_par_image = max(ZOOM_MIN, min(ZOOM_MAX, v.px_par_image * facteur))
        self._bornes()
        self.barre_h.setValue(int(f_ancre * v.px_par_image - x_ancre))
        v.decalage_x = float(self.barre_h.value())
        if synchro:
            self._synchroniser_zoom()
        v.update()
        self.vue_ensemble.update()

    def tout_voir(self):
        v = self.vue
        duree = max(1, v.projet.sequence.duree() if v.projet else 1)
        v.px_par_image = max(ZOOM_MIN, min(ZOOM_MAX, (v.width() - 40) / duree))
        self._bornes()
        self.barre_h.setValue(0)
        v.decalage_x = 0
        self._synchroniser_zoom()
        v.update()
        self.vue_ensemble.update()

    def suivre_tete(self, f: int):
        """Fait défiler la vue pendant la lecture pour garder la tête visible."""
        v = self.vue
        v.tete = f
        x = v.x_de(f)
        if x > v.width() - 30 or x < 0:
            self._bornes()
            self.barre_h.setValue(int(f * v.px_par_image - 60))
        v.update()
        self.vue_ensemble.update()
