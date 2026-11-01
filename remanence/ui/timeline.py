"""Timeline multipiste : règle en timecode, marqueurs, en-têtes de pistes, clips et vumètres.

Pendant un geste (déplacer, rogner, slip, slide, roll, fondu, point d'enveloppe), chaque
mouvement de souris repart de l'état au moment du clic et réapplique l'opération : l'aperçu
montre exactement ce que donnera le relâchement.

Gestes, sur le modèle de Vegas Pro :
- glisser un clip le déplace ; Maj : sans ses clips liés ; Alt : slip ; Ctrl+Alt : slide ;
- glisser un bord le rogne (en mode ripple, la suite suit) ; Ctrl+Alt sur un bord : roll ;
- poser un clip sur la fin d'un autre crée un fondu enchaîné (désactivable).
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QImage, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QHBoxLayout, QInputDialog, QMenu, QScrollBar, QSlider, QToolButton,
                               QVBoxLayout, QWidget)

from remanence.media.lecteur import AudioCache
from remanence.media.proxy import chemin_audio
from remanence.media.timecode import images_vers_tc
from remanence.effets import EFFETS, plage_cles
from remanence.effets.prereglages import MIME_PREREGLAGE, depuis_mime
from remanence.projet import edition
from remanence.projet.modele import Clip, Marqueur, Piste, Projet, valeur_enveloppe
from remanence.ui import charte
from remanence.ui.composants import ChampTimecode, Vumetres, bouton_icone, etiquette
from remanence.ui.inspecteur import nom_court_piste
from remanence.ui.medias import MIME_MEDIA
from remanence.ui.menu_effets import remplir_menu_effets

HAUTEUR_REGLE = 28
HAUTEUR_MARQUEURS = 20
# Piste des images clés de la vidéo : raccords entre clips et coupes dans les clips.
HAUTEUR_CLES = 18
HAUT_CLES = HAUTEUR_REGLE + HAUTEUR_MARQUEURS
HAUT_PISTES = HAUT_CLES + HAUTEUR_CLES
LARGEUR_ENTETE = 200
BANDEAU = 18
MARGE_BORD = 6
SEUIL_AIMANT_PX = 8
ZOOM_MIN, ZOOM_MAX = 0.02, 40.0
HAUTEUR_MIN, HAUTEUR_MAX = 30, 160
# Zone du bas de l'en-tête qui sert à tirer la hauteur de la piste.
POIGNEE_HAUTEUR = 7
COULEURS_MARQUEURS = [("accent-2", "Turquoise"), ("accent", "Mauve"), ("warning", "Jaune"),
                      ("success", "Bleu"), ("danger", "Rouge")]


def hauteur_piste(p: Piste) -> int:
    if p.hauteur:
        return p.hauteur
    return charte.actuelle().px("track-video-h" if p.type == "video" else "track-audio-h")


@dataclass
class Geste:
    type: str
    clip_id: str | None
    x0: float
    y0: float
    etat: list
    rang: int = -1
    marqueurs: list | None = None


class VueTimeline(QWidget):
    modifie = Signal(str)
    tete_changee = Signal(int)
    selection_changee = Signal(set)
    media_depose = Signal(list, int, str)
    # ("raccord" | "coupe", identifiant du clip, image depuis le début du clip)
    cle_basculee = Signal(str, str, int)
    outil_demande = Signal(str)
    # (préréglage, "clip" | "vide", identifiant du clip ou de la piste, image)
    prereglage_depose = Signal(object, str, str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.projet: Projet | None = None
        self.px_par_image = 6.0
        self.decalage_x = 0.0
        self.decalage_y = 0
        self.tete = 0
        self.selection: set[str] = set()
        self.aimantation = True
        self.ripple = False
        self.fondus_auto = True
        self.outil = "selection"
        # media_id -> (vignettes, images source entre deux vignettes)
        self.vignettes: dict[str, tuple[list[QImage], float]] = {}
        self._geste: Geste | None = None
        self._repere: int | None = None
        self._depot: tuple[int, str] | None = None
        # Cible d'un préréglage en cours de glisser : ("clip", id, 0) ou ("vide", piste, image).
        self._cible_fx: tuple[str, str, int] | None = None
        # Clips dont le pré-rendu codec (datamosh) se calcule en arrière-plan.
        self.en_calcul: set[str] = set()
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
        y = HAUT_PISTES - self.decalage_y
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

    def rect_marqueur(self, m: Marqueur, p: QPainter | None = None) -> QRectF:
        largeur = 16
        if m.nom:
            fm = (p.fontMetrics() if p else self.fontMetrics())
            largeur = fm.horizontalAdvance(m.nom) + 14
        return QRectF(self.x_de(m.position) - 1, HAUTEUR_REGLE + 3, largeur, HAUTEUR_MARQUEURS - 6)

    # Dessin

    def paintEvent(self, _e):
        c = charte.actuelle()
        p = QPainter(self)
        p.fillRect(self.rect(), c.c("surface"))
        if self.projet is None:
            return
        seq = self.projet.sequence
        p.save()
        p.setClipRect(QRect(0, HAUT_PISTES, self.width(), self.height() - HAUT_PISTES))
        for piste, y, h in self.lignes():
            p.setPen(c.c("line"))
            p.drawLine(0, y + h - 1, self.width(), y + h - 1)
            for clip in piste.clips:
                self._dessiner_clip(p, piste, clip, y, h)
            self._dessiner_fondus_enchaines(p, piste, y, h)
        if self._cible_fx is not None and self._cible_fx[0] == "vide":
            self._ligne_pointillee(p, self._cible_fx[2], "accent-2", HAUT_PISTES)
        if self._depot is not None:
            self._ligne_pointillee(p, self._depot[0], "accent-2", HAUT_PISTES)
        if self.survol_coupe is not None:
            self._ligne_pointillee(p, self.survol_coupe, "ink", HAUT_PISTES)
        p.restore()
        self._dessiner_regle(p, seq)
        self._dessiner_marqueurs(p, seq)
        self._dessiner_cles_video(p)
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
            p.drawText(QRect(0, HAUT_PISTES, self.width(), self.height() - HAUT_PISTES),
                       Qt.AlignCenter, "Timeline vide")
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
            if pas * self.px_par_image >= 110:
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
            p.drawLine(QPointF(x, HAUTEUR_REGLE - 9), QPointF(x, HAUTEUR_REGLE))
            sous = pas / 5
            if sous * self.px_par_image >= 8:
                for k in range(1, 5):
                    xs = self.x_de(f + k * sous)
                    p.drawLine(QPointF(xs, HAUTEUR_REGLE - 4), QPointF(xs, HAUTEUR_REGLE))
            p.setPen(c.c("ink-muted"))
            p.drawText(QPointF(x + 4, 15), images_vers_tc(seq.tc_debut + f, cad, seq.tc_drop))
        p.setPen(c.c("line"))
        p.drawLine(0, HAUTEUR_REGLE - 1, self.width(), HAUTEUR_REGLE - 1)

    def _dessiner_marqueurs(self, p: QPainter, seq):
        """Bande des marqueurs : une étiquette par marqueur, à sa couleur, avec son nom."""
        c = charte.actuelle()
        p.fillRect(QRect(0, HAUTEUR_REGLE, self.width(), HAUTEUR_MARQUEURS), c.c("surface"))
        p.setFont(c.police("label", 11))
        for m in seq.marqueurs:
            couleur = c.c(m.couleur if m.couleur in c.couleurs else "accent-2")
            r = self.rect_marqueur(m, p)
            if r.right() < 0 or r.left() > self.width():
                continue
            p.fillRect(QRectF(r.left(), r.top(), 2, HAUTEUR_MARQUEURS), couleur)
            if m.nom:
                p.fillRect(r.adjusted(2, 0, 0, 0), c.c("surface-raised"))
                p.setPen(QPen(couleur, 1))
                p.drawRect(r.adjusted(2, 0, -1, -1))
                p.setPen(c.c("ink"))
                p.drawText(r.adjusted(7, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, m.nom)
            else:
                p.fillRect(QRectF(r.left(), r.top(), 8, 8), couleur)
        p.setPen(c.c("line"))
        p.drawLine(0, HAUT_PISTES - 1, self.width(), HAUT_PISTES - 1)

    def reperes_cles(self) -> list[tuple[int, str, str, int, bool]]:
        """Repères de la piste des images clés : (image de la séquence, "raccord" | "coupe",
        clip, image dans le clip, supprimée). Un repère par instant, celui de la piste la plus
        haute s'il y en a plusieurs."""
        reperes = {}
        if self.projet is None:
            return []
        for piste in self.projet.sequence.pistes_video:
            for c in piste.clips:
                if c.est_effet:
                    continue
                media = self.projet.medias.get(c.media_id)
                if media is None:
                    continue
                if edition.precedent(piste, c) is not None:
                    reperes.setdefault(c.debut, (c.debut, "raccord", c.id, 0,
                                                 c.transition is not None))
                for m in media.coupes or []:
                    t = m - c.entree
                    if 0 < t < c.duree:
                        reperes.setdefault(c.debut + t, (c.debut + t, "coupe", c.id, t,
                                                         t in c.cles_supprimees))
        return sorted(reperes.values())

    def _dessiner_cles_video(self, p: QPainter):
        c = charte.actuelle()
        p.fillRect(QRect(0, HAUT_CLES, self.width(), HAUTEUR_CLES), c.c("surface"))
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        for f, _genre, _clip, _t, supprimee in self.reperes_cles():
            x = self.x_de(f)
            if x < -6 or x > self.width() + 6:
                continue
            r = QRectF(x - 3, HAUT_CLES + 4, 6, HAUTEUR_CLES - 8)
            if supprimee:
                p.setPen(Qt.NoPen)
                p.setBrush(c.c("accent"))
            else:
                p.setPen(QPen(c.c("ink-muted"), 1.2))
                p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, 1.5, 1.5)
        p.restore()
        p.setPen(c.c("line"))
        p.drawLine(0, HAUT_PISTES - 1, self.width(), HAUT_PISTES - 1)

    def _repere_a(self, pos):
        if not (HAUT_CLES <= pos.y() < HAUT_PISTES):
            return None
        for repere in self.reperes_cles():
            if abs(self.x_de(repere[0]) - pos.x()) <= 5:
                return repere
        return None

    def _dessiner_clip(self, p: QPainter, piste: Piste, clip: Clip, y: int, h: int):
        c = charte.actuelle()
        r = self.rect_clip(clip, y, h)
        if r.right() < 0 or r.left() > self.width():
            return
        media = self.projet.medias.get(clip.media_id)
        video = piste.type == "video"
        fond = c.c("clip-effect" if clip.est_effet else "clip-video" if video else "clip-audio")
        rayon = c.px("radius-xs")
        forme = QPainterPath()
        forme.addRoundedRect(r, rayon, rayon)
        p.save()
        p.setClipPath(forme, Qt.IntersectClip)
        p.fillRect(r, fond)
        if video and media is not None:
            self._dessiner_vignettes(p, clip, media, r)
        elif media is not None:
            self._dessiner_onde(p, clip, media, r)
        self._dessiner_fondus(p, clip, r)
        self._dessiner_enveloppe(p, clip, r)
        self._dessiner_cles(p, clip, r)
        if clip.transition is not None and edition.precedent(piste, clip) is not None:
            largeur = min(clip.transition.duree, clip.duree) * self.px_par_image
            zone = QRectF(r.left(), r.top() + BANDEAU, largeur, r.height() - BANDEAU)
            p.fillRect(zone, QBrush(c.c("accent", 0.55), Qt.BDiagPattern))
            p.fillRect(QRectF(zone.right() - 2, zone.top(), 2, zone.height()), c.c("accent"))
        # Bandeau du nom, sur la couleur du clip : lisible même par-dessus les vignettes.
        p.fillRect(QRectF(r.left(), r.top(), r.width(), BANDEAU), fond)
        p.setPen(c.c("ink"))
        p.setFont(c.police("label"))
        if clip.est_effet:
            noms = [EFFETS[e.type].nom for e in clip.effets if e.type in EFFETS]
            nom = "Clip d'effet" + (" · " + ", ".join(noms) if noms else "")
        else:
            nom = media.nom if media else "Média manquant"
        if media and media.hors_ligne:
            nom += " (hors ligne)"
        if clip.lien is None and media and media.infos.video and media.infos.audio:
            nom += " · dissocié"
        badge = 0.0
        if clip.effets and not clip.est_effet and r.width() > 60:
            # Badge « fx » de la charte (ton accent : effet actif), à droite du bandeau.
            p.setFont(c.police("caption"))
            texte_badge = "Calcul…" if clip.id in self.en_calcul else "FX"
            badge = p.fontMetrics().horizontalAdvance(texte_badge) + 10
            zone = QRectF(r.right() - badge - 4, r.top() + 2, badge, BANDEAU - 4)
            p.setPen(Qt.NoPen)
            p.setBrush(c.c("accent-soft"))
            p.drawRoundedRect(zone, rayon, rayon)
            p.setPen(c.c("accent" if any(e.actif for e in clip.effets) else "ink-muted"))
            p.drawText(zone, Qt.AlignCenter, texte_badge)
            p.setFont(c.police("label"))
            p.setPen(c.c("ink"))
        p.drawText(QRectF(r.left() + 8, r.top(), r.width() - 16 - badge, BANDEAU),
                   Qt.AlignVCenter | Qt.AlignLeft, nom)
        for gauche in (True, False):
            hx = r.left() + clip.fondu_entree * self.px_par_image if gauche else \
                r.right() - clip.fondu_sortie * self.px_par_image
            p.fillRect(QRectF(hx - (0 if gauche else 6), r.top(), 6, 6), c.c("ink"))
        if piste.masquee or piste.muette:
            p.fillRect(r, c.c("bg-app", 0.55))
        if piste.verrouillee:
            p.fillRect(r, QBrush(c.c("ink-muted", 0.35), Qt.BDiagPattern))
        p.restore()
        if self._cible_fx is not None and self._cible_fx[:2] == ("clip", clip.id):
            p.save()
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setPen(QPen(c.c("accent-2"), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), rayon, rayon)
            p.restore()
        if clip.id in self.selection:
            p.save()
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setPen(QPen(c.c("accent"), 2, Qt.DashLine if self.ripple else Qt.SolidLine))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), rayon, rayon)
            p.restore()

    def _dessiner_fondus_enchaines(self, p: QPainter, piste: Piste, y: int, h: int):
        """Zone commune de deux clips qui se fondent : une croix, comme dans Vegas Pro."""
        c = charte.actuelle()
        clips = sorted(piste.clips, key=lambda x: x.debut)
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(QPen(c.c("ink"), 1))
        for a, b in zip(clips, clips[1:]):
            if b.debut < a.fin:
                x0, x1 = self.x_de(b.debut), self.x_de(min(a.fin, b.fin))
                haut, bas = y + 3 + BANDEAU, y + h - 4
                p.fillRect(QRectF(x0, haut, x1 - x0, bas - haut), c.c("bg-app", 0.35))
                p.drawLine(QPointF(x0, haut), QPointF(x1, bas))
                p.drawLine(QPointF(x0, bas), QPointF(x1, haut))
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

    @staticmethod
    def _temps_cles(clip: Clip) -> list[int]:
        return sorted({k[0] for e in clip.effets for cles in e.cles.values() for k in cles
                       if 0 <= k[0] < clip.duree})

    def _dessiner_cles(self, p: QPainter, clip: Clip, r: QRectF):
        """Losanges keyframe en bas du clip, un par instant qui porte une image clé d'effet."""
        temps = self._temps_cles(clip)
        if not temps:
            return
        c = charte.actuelle()
        p.save()
        # Bande sombre sous les losanges : ils restent lisibles sur les vignettes.
        p.fillRect(QRectF(r.left(), r.bottom() - 13, r.width(), 13), c.c("bg-app", 0.8))
        y = r.bottom() - 6.5
        # Trait entre la première et la dernière image clé : là où l'effet agit.
        p.setPen(QPen(c.c("keyframe"), 2))
        for e in clip.effets:
            plage = plage_cles(e)
            if plage is not None and e.actif:
                x0, x1 = (min(max(self.x_de(clip.debut + t) + self.px_par_image / 2,
                                  r.left() + 6), r.right() - 6) for t in plage)
                p.drawLine(QPointF(x0, y), QPointF(x1, y))
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(QPen(c.c("bg-app"), 1))
        p.setBrush(c.c("keyframe"))
        for t in temps:
            x = self.x_de(clip.debut + t) + self.px_par_image / 2
            x = min(max(x, r.left() + 6), r.right() - 6)
            p.drawPolygon(QPolygonF([QPointF(x, y - 5), QPointF(x + 5, y), QPointF(x, y + 5),
                                     QPointF(x - 5, y)]))
        p.restore()

    def oublier_ondes(self):
        self._ondes.clear()

    # Repérage sous la souris

    def _marqueur_a(self, pos) -> Marqueur | None:
        if not (HAUTEUR_REGLE <= pos.y() < HAUT_PISTES) or self.projet is None:
            return None
        for m in reversed(self.projet.sequence.marqueurs):
            if self.rect_marqueur(m).adjusted(-3, 0, 0, 0).contains(pos):
                return m
        return None

    def _sous(self, pos) -> tuple[str, Piste | None, Clip | None, int]:
        if pos.y() < HAUTEUR_REGLE:
            return "regle", None, None, -1
        if pos.y() < HAUT_PISTES:
            return "marqueurs", None, None, -1
        ligne = self.piste_a(pos.y())
        if ligne is None:
            return "vide", None, None, -1
        piste, y, h = ligne
        # Le clip le plus récent est dessiné au-dessus : il est servi en premier.
        for clip in sorted(piste.clips, key=lambda x: x.debut, reverse=True):
            r = self.rect_clip(clip, y, h)
            if not r.adjusted(-MARGE_BORD, 0, MARGE_BORD, 0).contains(pos):
                continue
            if self.outil == "couper":
                return ("corps", piste, clip, -1) if r.contains(pos) else ("vide", piste, None, -1)
            if clip.transition is not None and pos.y() > r.top() + BANDEAU:
                bord = self.x_de(clip.debut + min(clip.transition.duree, clip.duree))
                if abs(pos.x() - bord) <= 5:
                    return "transition", piste, clip, -1
            if pos.y() >= r.bottom() - 13:
                for t in self._temps_cles(clip):
                    x = self.x_de(clip.debut + t) + self.px_par_image / 2
                    x = min(max(x, r.left() + 6), r.right() - 6)
                    if abs(pos.x() - x) <= 6:
                        return "cle_effet", piste, clip, t
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

    @staticmethod
    def _type_geste(zone: str, modificateurs) -> str:
        ctrl_alt = (modificateurs & Qt.ControlModifier) and (modificateurs & Qt.AltModifier)
        if zone == "corps":
            if ctrl_alt:
                return "slide"
            if modificateurs & Qt.AltModifier:
                return "slip"
            return "deplacer"
        if zone in ("bord_debut", "bord_fin") and ctrl_alt:
            return "roll_" + zone.split("_")[1]
        return zone

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
            type_ = self._type_geste(zone, e.modifiers())
            curseurs = {"bord_debut": Qt.SizeHorCursor, "bord_fin": Qt.SizeHorCursor,
                        "roll_debut": Qt.SplitHCursor, "roll_fin": Qt.SplitHCursor,
                        "fondu_entree": Qt.SizeHorCursor, "fondu_sortie": Qt.SizeHorCursor,
                        "transition": Qt.SizeHorCursor, "cle_effet": Qt.PointingHandCursor,
                        "point": Qt.SizeAllCursor, "deplacer": Qt.OpenHandCursor,
                        "slip": Qt.SizeHorCursor, "slide": Qt.SizeHorCursor}
            repere = self._repere_a(pos)
            if repere is not None:
                self.setCursor(Qt.PointingHandCursor)
                self.setToolTip({("raccord", False): "Transition datamosh",
                                 ("raccord", True): "Retirer la transition datamosh",
                                 ("coupe", False): "Faire baver la coupe",
                                 ("coupe", True): "Rétablir la coupe"}
                                [(repere[1], repere[4])])
                return
            self.setToolTip("")
            if self._marqueur_a(pos) is not None:
                self.setCursor(Qt.PointingHandCursor)
            else:
                self.setCursor(curseurs.get(type_, Qt.ArrowCursor))
            return
        g = self._geste
        seq = self.projet.sequence
        if g.type == "regle":
            self._placer_tete(self.f_de(pos.x()))
            return
        if g.type == "marqueur":
            m = seq.marqueurs[g.rang]
            m.position = self._f_aimantee(pos.x(), set())
            self._repere = m.position
            self.update()
            return
        seq.pistes = copy.deepcopy(g.etat)
        dx_images = round((pos.x() - g.x0) / self.px_par_image)
        self._repere = None
        lies = not (e.modifiers() & Qt.ShiftModifier)
        try:
            self._appliquer_geste(g, seq, pos, dx_images, lies)
        except edition.EditionImpossible:
            seq.pistes = copy.deepcopy(g.etat)
        self.update()

    def _appliquer_geste(self, g: Geste, seq, pos, dx_images: int, lies: bool):
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
                             inclure_lies=lies, fondus_auto=self.fondus_auto)
        elif g.type == "slip":
            # Glisser vers la droite montre ce qui était avant : le contenu recule.
            edition.glisser_contenu(self.projet, seq, g.clip_id, -dx_images, inclure_lies=lies)
        elif g.type == "slide":
            edition.faire_glisser(self.projet, seq, g.clip_id, dx_images, inclure_lies=lies)
        elif g.type in ("roll_debut", "roll_fin"):
            piste, clip = seq.trouver(g.clip_id)
            gauche = clip
            if g.type == "roll_debut":
                gauche = next((o for o in piste.clips if o.fin == clip.debut), None)
            if gauche is not None:
                edition.rouler(self.projet, seq, gauche.id, dx_images, inclure_lies=lies)
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
            edition.rogner(self.projet, seq, clip.id, cote, cible - bord, inclure_lies=lies,
                           ripple=self.ripple)
        elif g.type == "cle_effet":
            _, clip = seq.trouver(g.clip_id)
            t = max(0, min(round(self.f_de(pos.x())) - clip.debut, clip.duree - 1))
            for effet in clip.effets:
                for cle, cles in effet.cles.items():
                    if any(k[0] == g.rang for k in cles):
                        effet.cles[cle] = sorted(
                            [k for k in cles if k[0] not in (t, g.rang)] +
                            [[t, k[1], k[2]] for k in cles if k[0] == g.rang],
                            key=lambda k: k[0])
            self._placer_tete(clip.debut + t)
        elif g.type == "transition":
            _, clip = seq.trouver(g.clip_id)
            clip.transition.duree = max(1, min(round(self.f_de(pos.x())) - clip.debut,
                                               clip.duree))
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
        seq = self.projet.sequence
        repere = self._repere_a(pos)
        if repere is not None and e.button() == Qt.LeftButton:
            self.cle_basculee.emit(repere[1], repere[2], repere[3])
            return
        marqueur = self._marqueur_a(pos)
        if marqueur is not None:
            if e.button() == Qt.RightButton:
                self._menu_marqueur(e, marqueur)
            elif e.button() == Qt.LeftButton:
                self._placer_tete(marqueur.position)
                self._geste = Geste("marqueur", None, pos.x(), pos.y(), [],
                                    rang=seq.marqueurs.index(marqueur),
                                    marqueurs=copy.deepcopy(seq.marqueurs))
            return
        zone, piste, clip, rang = self._sous(pos)
        if e.button() == Qt.RightButton:
            self._menu(e, zone, clip, rang)
            return
        if e.button() != Qt.LeftButton:
            return
        etat = copy.deepcopy(seq.pistes)
        if zone in ("regle", "vide", "marqueurs"):
            if zone == "vide" and not (e.modifiers() & Qt.ControlModifier):
                self._choisir(set())
            self._placer_tete(self.f_de(pos.x()))
            self._geste = Geste("regle", None, pos.x(), pos.y(), etat)
            return
        if self.outil == "couper":
            f = self._f_aimantee(pos.x(), set())
            if not piste.verrouillee and clip.debut < f < clip.fin:
                ids = {clip.id} if e.modifiers() & Qt.ShiftModifier else \
                    edition.avec_lies(seq, {clip.id})
                edition.couper(seq, f, ids)
                self.modifie.emit("Coupe")
            return
        if zone == "cle_effet":
            self._placer_tete(clip.debut + rang)
        if piste.verrouillee:
            self._choisir({clip.id})
            return
        if e.modifiers() & Qt.ControlModifier and not e.modifiers() & Qt.AltModifier:
            self._choisir(self.selection ^ {clip.id})
        elif clip.id not in self.selection:
            self._choisir({clip.id})
        self._geste = Geste(self._type_geste(zone, e.modifiers()), clip.id, pos.x(), pos.y(),
                            etat, rang=rang)
        if self._geste.type == "deplacer":
            self.setCursor(Qt.ClosedHandCursor)

    def mouseReleaseEvent(self, e):
        g = self._geste
        self._geste = None
        self._repere = None
        if g is None:
            return
        libelles = {"deplacer": "Déplacement", "bord_debut": "Rognage", "bord_fin": "Rognage",
                    "fondu_entree": "Fondu d'entrée", "fondu_sortie": "Fondu de sortie",
                    "point": "Point d'enveloppe", "slip": "Slip", "slide": "Slide",
                    "roll_debut": "Roll", "roll_fin": "Roll", "marqueur": "Marqueur déplacé",
                    "transition": "Durée de la transition", "cle_effet": "Image clé déplacée"}
        if g.type == "cle_effet" and round((e.position().x() - g.x0) / self.px_par_image) == 0:
            self.projet.sequence.pistes = copy.deepcopy(g.etat)
            self.update()
            return
        if g.type in libelles:
            if g.type == "marqueur" and g.marqueurs is not None and \
                    [m.position for m in g.marqueurs] == \
                    [m.position for m in self.projet.sequence.marqueurs]:
                return
            self.modifie.emit(libelles[g.type])
        self.update()

    def mouseDoubleClickEvent(self, e):
        marqueur = self._marqueur_a(e.position())
        if marqueur is not None:
            self.renommer_marqueur(marqueur)
            return
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

    # Marqueurs

    def renommer_marqueur(self, m: Marqueur):
        nom, ok = QInputDialog.getText(self, "Renommer le marqueur", "Nom du marqueur :",
                                       text=m.nom)
        if ok and nom.strip() != m.nom:
            m.nom = nom.strip()
            self.modifie.emit("Marqueur renommé")

    def _menu_marqueur(self, e, m: Marqueur):
        menu = QMenu(self)
        seq = self.projet.sequence
        menu.addAction("Renommer…", lambda: self.renommer_marqueur(m))
        couleurs = menu.addMenu("Couleur")
        for token, nom in COULEURS_MARQUEURS:
            a = couleurs.addAction(nom, lambda token=token: (setattr(m, "couleur", token),
                                                             self.modifie.emit("Couleur de marqueur")))
            a.setCheckable(True)
            a.setChecked(m.couleur == token)
        menu.addSeparator()
        menu.addAction("Supprimer le marqueur", lambda: (seq.marqueurs.remove(m),
                                                         self.modifie.emit("Marqueur supprimé")))
        menu.exec(e.globalPosition().toPoint())

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
            piste_clip = self.projet.sequence.trouver(clip.id)[0]
            if piste_clip.type == "video" and edition.precedent(piste_clip, clip) is not None:
                a = menu.addAction("Transition datamosh à l'entrée",
                                   lambda: fenetre.basculer_cle("raccord", clip.id, 0))
                a.setCheckable(True)
                a.setChecked(clip.transition is not None)
            if self.projet.sequence.trouver(clip.id)[0].type == "video":
                effets = menu.addMenu("Ajouter un effet")
                remplir_menu_effets(effets, lambda liste: fenetre.ajouter_effet(
                    "clip", clip.id, liste))
            if clip.lien:
                menu.addAction("Dissocier son et image (U)", fenetre.dissocier)
            elif len(self.selection) > 1:
                menu.addAction("Lier la sélection (G)", fenetre.lier)
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
        """Convention Vegas : molette = zoom autour du pointeur ; Ctrl = défilement vertical ;
        Maj = défilement horizontal."""
        d = e.angleDelta().y() or e.angleDelta().x()
        tl = self.parent()
        if e.modifiers() & Qt.ShiftModifier or (e.angleDelta().x() and not e.angleDelta().y()):
            tl.defiler_x(-d)
        elif e.modifiers() & Qt.ControlModifier:
            tl.defiler_y(-d // 2)
        else:
            tl.zoomer(1.25 if d > 0 else 0.8, e.position().x())

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
            if self.outil != "selection":
                self.outil_demande.emit("selection")
            else:
                self._choisir(set())
        else:
            super().keyPressEvent(e)

    # Dépôt depuis le panneau Média ou le moniteur source

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME_MEDIA) or e.mimeData().hasFormat(MIME_PREREGLAGE):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasFormat(MIME_PREREGLAGE):
            self._cible_fx = self._cible_prereglage(e.position())
            if self._cible_fx is None:
                e.ignore()
            else:
                e.acceptProposedAction()
            self.update()
            return
        if not e.mimeData().hasFormat(MIME_MEDIA):
            return
        f = self._f_aimantee(e.position().x(), set())
        ligne = self.piste_a(e.position().y())
        self._depot = (f, ligne[0].id if ligne else "")
        e.acceptProposedAction()
        self.update()

    def _cible_prereglage(self, pos) -> tuple[str, str, int] | None:
        """Un clip vidéo sous la souris, ou un endroit libre d'une piste vidéo."""
        if self.projet is None:
            return None
        ligne = self.piste_a(pos.y())
        if ligne is None or ligne[0].type != "video" or ligne[0].verrouillee:
            return None
        _, piste, clip, _ = self._sous(pos)
        if clip is not None:
            return "clip", clip.id, 0
        return "vide", piste.id, self._f_aimantee(pos.x(), set())

    def dragLeaveEvent(self, _e):
        self._depot = None
        self._cible_fx = None
        self.update()

    def dropEvent(self, e):
        if e.mimeData().hasFormat(MIME_PREREGLAGE):
            cible, self._cible_fx = self._cible_fx, None
            if cible is not None:
                p = depuis_mime(e.mimeData().data(MIME_PREREGLAGE))
                self.prereglage_depose.emit(p, cible[0], cible[1], cible[2])
                e.acceptProposedAction()
            self.update()
            return
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
    """En-tête compact, comme sur la maquette : nom court (V1, A1), nom de la piste, visibilité
    ou muet et solo, verrou. Le niveau et le solo vidéo sont au clic droit ; tirer le bord du
    bas change la hauteur de la piste ; Ctrl+clic sur M ou S rend la piste exclusive."""

    def __init__(self, timeline: "Timeline", piste: Piste, court: str):
        super().__init__(timeline.zone_entetes)
        self.piste = piste
        self.timeline = timeline
        self.fenetre = timeline.fenetre
        self.court = court
        self.setProperty("role", "entete-piste")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMouseTracking(True)
        video = piste.type == "video"
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(6)
        # Filet de la couleur des clips de la piste : il relie l'en-tête à ses clips.
        filet = QWidget()
        filet.setFixedWidth(3)
        filet.setProperty("role", "filet-video" if video else "filet-audio")
        filet.setAttribute(Qt.WA_StyledBackground, True)
        lay.addWidget(filet)
        badge = etiquette(court, "badge")
        badge.setFixedWidth(30)
        badge.setAlignment(Qt.AlignCenter)
        lay.addWidget(badge)
        if video:
            visible = bouton_icone("eye-off" if piste.masquee else "eye",
                                   f"Afficher ou masquer {court}",
                                   cochable=True, taille=14)
            visible.setFixedSize(24, 24)
            visible.setChecked(not piste.masquee)
            visible.toggled.connect(lambda v: self.fenetre.regler_piste(piste.id, "masquee",
                                                                        not v))
            lay.addWidget(visible)
        self.nom = etiquette(piste.nom, "")

        self.nom.mouseDoubleClickEvent = lambda e: self.renommer()
        lay.addWidget(self.nom, 1)
        if piste.effets:
            fx = etiquette("FX", "badge-accent")
            fx.setToolTip(", ".join(EFFETS[e.type].nom for e in piste.effets if e.type in EFFETS))
            lay.addWidget(fx)
        if not video:
            for lettre, champ, aide in (("M", "muette", "Muet"),
                                        ("S", "solo", "Solo")):
                b = bouton_lettre(lettre, f"{aide} {court} (Ctrl+clic : exclusif)")
                b.setChecked(getattr(piste, champ))
                b.clicked.connect(lambda _=False, b=b, champ=champ: self._bascule(champ, b))
                lay.addWidget(b)
        elif piste.solo:
            solo = etiquette("Solo", "badge-accent")
            solo.setToolTip("Solo")
            lay.addWidget(solo)
        verrou = bouton_icone("lock" if piste.verrouillee else "lock-open",
                              f"Verrouiller {court}",
                              cochable=True, taille=14)
        verrou.setFixedSize(24, 24)
        verrou.setChecked(piste.verrouillee)
        verrou.toggled.connect(lambda v: self.fenetre.regler_piste(piste.id, "verrouillee", v))
        lay.addWidget(verrou)
        if piste.niveau != 1.0:
            self.setToolTip(f"Niveau de la piste : {self._texte_niveau()}")
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.setAcceptDrops(video)
        self._tirer = None

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME_PREREGLAGE) and not self.piste.verrouillee:
            e.acceptProposedAction()

    def dropEvent(self, e):
        p = depuis_mime(e.mimeData().data(MIME_PREREGLAGE))
        self.fenetre.ajouter_effet("piste", self.piste.id, p.nouveaux_effets())
        e.acceptProposedAction()

    def _texte_niveau(self) -> str:
        if self.piste.type == "video":
            return f"{round(self.piste.niveau * 100)} %"
        db = 20 * math.log10(max(self.piste.niveau, 1e-3))
        return f"{db:+.1f} dB".replace(".", ",").replace("-", "−")

    def _bascule(self, champ: str, bouton: QToolButton):
        from PySide6.QtWidgets import QApplication
        exclusif = QApplication.keyboardModifiers() & Qt.ControlModifier
        if exclusif:
            self.fenetre.piste_exclusive(self.piste.id, champ)
        else:
            self.fenetre.regler_piste(self.piste.id, champ, bouton.isChecked())

    def renommer(self):
        nom, ok = QInputDialog.getText(self, "Renommer la piste", f"Nom de la piste {self.court} :",
                                       text=self.piste.nom)
        if ok and nom.strip():
            self.fenetre.regler_piste(self.piste.id, "nom", nom.strip())

    def _menu(self, pos):
        menu = QMenu(self)
        f = self.fenetre
        menu.addAction("Renommer…", self.renommer)
        if self.piste.type == "video":
            effets = menu.addMenu("Ajouter un effet de piste")
            remplir_menu_effets(effets, lambda liste: f.ajouter_effet(
                "piste", self.piste.id, liste))
        menu.addAction(f"Niveau de la piste ({self._texte_niveau()})…", self._regler_niveau)
        if self.piste.type == "video":
            solo = menu.addAction("Solo",
                                  lambda: f.regler_piste(self.piste.id, "solo",
                                                         not self.piste.solo))
            solo.setCheckable(True)
            solo.setChecked(self.piste.solo)
        menu.addAction("Hauteur par défaut", lambda: f.regler_piste(self.piste.id, "hauteur",
                                                                    None))
        menu.addSeparator()
        menu.addAction("Monter la piste", lambda: f.deplacer_piste(self.piste.id, -1))
        menu.addAction("Descendre la piste", lambda: f.deplacer_piste(self.piste.id, 1))
        menu.addSeparator()
        menu.addAction("Supprimer la piste", lambda: f.supprimer_piste(self.piste.id))
        menu.exec(self.mapToGlobal(pos))

    def _regler_niveau(self):
        if self.piste.type == "video":
            v, ok = QInputDialog.getInt(self, "Niveau de la piste", "Opacité (%) :",
                                        round(self.piste.niveau * 100), 0, 100)
            if ok:
                self.fenetre.regler_piste(self.piste.id, "niveau", v / 100)
        else:
            db = 20 * math.log10(max(self.piste.niveau, 1e-3))
            v, ok = QInputDialog.getDouble(self, "Niveau de la piste", "Volume (dB) :",
                                           round(db, 1), -60.0, 12.0, 1)
            if ok:
                self.fenetre.regler_piste(self.piste.id, "niveau", 10 ** (v / 20))

    # Tirer le bord du bas : hauteur de la piste.

    def mouseMoveEvent(self, e):
        if self._tirer is not None:
            h = max(HAUTEUR_MIN, min(HAUTEUR_MAX, self._tirer[1] + round(e.position().y()
                                                                          - self._tirer[0])))
            self.piste.hauteur = h
            self.timeline.placer_entetes()
            self.timeline.bornes()
            self.timeline.vue.update()
            return
        pres_du_bas = e.position().y() >= self.height() - POIGNEE_HAUTEUR
        self.setCursor(Qt.SizeVerCursor if pres_du_bas else Qt.ArrowCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.position().y() >= self.height() - POIGNEE_HAUTEUR:
            self._tirer = (e.position().y(), self.height())
            return
        if e.button() == Qt.LeftButton:
            # Un clic sur l'en-tête montre la piste et ses effets dans l'inspecteur.
            self.fenetre.choisir_piste(self.piste.id)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if self._tirer is not None:
            self._tirer = None
            self.fenetre.valider("Hauteur de piste")
            return
        super().mouseReleaseEvent(e)


class Timeline(QWidget):
    """Conteneur : barre d'outils, en-têtes de pistes, clips, défilement et vumètres."""

    def __init__(self, fenetre, parent=None):
        super().__init__(parent)
        self.fenetre = fenetre
        self.vue = VueTimeline(self)
        self.barre_h = QScrollBar(Qt.Horizontal)
        self.barre_v = QScrollBar(Qt.Vertical)
        self.barre_h.valueChanged.connect(self._sur_defilement_h)
        self.barre_v.valueChanged.connect(self._sur_defilement_v)
        self.zone_entetes = QWidget()
        self.zone_entetes.setProperty("role", "panneau")
        self.zone_entetes.setAttribute(Qt.WA_StyledBackground, True)
        self.zone_entetes.setFixedWidth(LARGEUR_ENTETE)
        self._entetes: list[EntetePiste] = []
        self.timecode = ChampTimecode(20, self.zone_entetes)
        self._nom_cles = etiquette("Coupes", "section")
        self._nom_cles.setParent(self.zone_entetes)
        self._nom_cles.setToolTip("Coupes et raccords (datamosh)")
        self.timecode.position_demandee.connect(fenetre.aller_a)
        self.vumetres = Vumetres(fenetre.lecture.cretes)

        outils = QHBoxLayout()
        outils.setContentsMargins(10, 4, 10, 4)
        outils.setSpacing(2)
        self.b_selection = bouton_icone("mouse-pointer-2", "Sélection (V)", cochable=True)
        self.b_couper = bouton_icone("scissors", "Coupe (C)", cochable=True)
        self.b_selection.setChecked(True)
        self.b_selection.clicked.connect(lambda: self.choisir_outil("selection"))
        self.b_couper.clicked.connect(lambda: self.choisir_outil("couper"))
        self.vue.outil_demande.connect(self.choisir_outil)
        self.b_aimant = bouton_icone("magnet", "Aimantation (F8)",
                                     cochable=True)
        self.b_aimant.setChecked(True)
        self.b_aimant.toggled.connect(lambda v: setattr(self.vue, "aimantation", v))
        self.b_ripple = bouton_icone("arrow-right-from-line", "Ripple (Ctrl+L)",
                                     cochable=True)
        self.b_ripple.toggled.connect(self._ripple)
        self.b_fondus = bouton_icone("blend", "Fondus enchaînés automatiques",
                                     cochable=True)
        self.b_fondus.setChecked(True)
        self.b_fondus.toggled.connect(lambda v: setattr(self.vue, "fondus_auto", v))
        b_lier = bouton_icone("link", "Lier la sélection (G)")
        b_lier.clicked.connect(fenetre.lier)
        b_dissocier = bouton_icone("unlink", "Dissocier son et image (U)")
        b_dissocier.clicked.connect(fenetre.dissocier)
        b_marqueur = bouton_icone("bookmark", "Marqueur (M)")
        b_marqueur.clicked.connect(fenetre.marqueur)
        self.b_piste = bouton_icone("plus", "Ajouter une piste", texte="Piste")
        self.b_piste.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.b_piste)
        menu.addAction("Piste vidéo", lambda: fenetre.ajouter_piste("video"))
        menu.addAction("Piste audio", lambda: fenetre.ajouter_piste("audio"))
        self.b_piste.setMenu(menu)
        self.zoom = QSlider(Qt.Horizontal)
        self.zoom.setRange(0, 1000)
        self.zoom.setFixedWidth(140)
        self.zoom.setToolTip("Zoom")
        self.zoom.setAccessibleName("Zoom de la timeline")
        self.zoom.valueChanged.connect(self._zoom_curseur)
        b_tout = bouton_icone("maximize-2", "Tout voir")
        b_tout.clicked.connect(self.tout_voir)
        for groupe in ((self.b_selection, self.b_couper),
                       (self.b_aimant, self.b_ripple, self.b_fondus),
                       (b_lier, b_dissocier, b_marqueur, self.b_piste)):
            for w in groupe:
                outils.addWidget(w)
            separateur = QWidget()
            separateur.setFixedSize(1, 18)
            separateur.setProperty("role", "filet")
            separateur.setAttribute(Qt.WA_StyledBackground, True)
            outils.addSpacing(6)
            outils.addWidget(separateur)
            outils.addSpacing(6)
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
        centre.addWidget(self.vumetres)
        bas = QHBoxLayout()
        bas.addSpacing(LARGEUR_ENTETE)
        bas.addWidget(self.barre_h)
        bas.addSpacing(64)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(barre_outils)
        lay.addLayout(centre, 1)
        lay.addLayout(bas)
        self._synchroniser_zoom()

    def choisir_outil(self, outil: str):
        self.vue.outil = outil
        self.b_selection.setChecked(outil == "selection")
        self.b_couper.setChecked(outil == "couper")
        self.vue.survol_coupe = None
        self.vue.setCursor(Qt.ArrowCursor)
        self.vue.update()

    def _ripple(self, actif: bool):
        self.vue.ripple = actif
        self.vue.update()
        self.fenetre.message("Ripple activé" if actif
                             else "Ripple désactivé.", 3000)

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
        self.placer_entetes()
        self.bornes()
        self.vue.update()

    def placer_entetes(self):
        lignes = {p.id: (y, h) for p, y, h in self.vue.lignes()}
        for e in self._entetes:
            y, h = lignes.get(e.piste.id, (0, 0))
            e.setGeometry(0, y, LARGEUR_ENTETE, h - 1)
            e.setVisible(y + h > HAUT_PISTES)
        self.timecode.setGeometry(12, 4, self.timecode.width(), HAUT_CLES - 8)
        self.timecode.raise_()
        self._nom_cles.setGeometry(12, HAUT_CLES, LARGEUR_ENTETE - 24, HAUTEUR_CLES)
        self._nom_cles.raise_()

    def bornes(self):
        if self.vue.projet is None:
            return
        duree = max(self.vue.projet.sequence.duree(), self.vue.tete) + 200
        self.barre_h.setRange(0, max(0, int(duree * self.vue.px_par_image - self.vue.width() / 2)))
        self.barre_h.setPageStep(max(1, self.vue.width()))
        self.barre_v.setRange(0, max(0, self.vue.hauteur_totale() + HAUT_PISTES -
                                     self.vue.height()))
        self.barre_v.setPageStep(max(1, self.vue.height()))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.bornes()

    def _sur_defilement_h(self, v):
        self.vue.decalage_x = float(v)
        self.vue.update()

    def _sur_defilement_v(self, v):
        self.vue.decalage_y = int(v)
        self.placer_entetes()
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
        self.bornes()
        self.barre_h.setValue(int(f_ancre * v.px_par_image - x_ancre))
        v.decalage_x = float(self.barre_h.value())
        if synchro:
            self._synchroniser_zoom()
        v.update()

    def tout_voir(self):
        v = self.vue
        duree = max(1, v.projet.sequence.duree() if v.projet else 1)
        v.px_par_image = max(ZOOM_MIN, min(ZOOM_MAX, (v.width() - 40) / duree))
        self.bornes()
        self.barre_h.setValue(0)
        v.decalage_x = 0
        self._synchroniser_zoom()
        v.update()

    def suivre_tete(self, f: int):
        """Fait défiler la vue pendant la lecture pour garder la tête visible."""
        v = self.vue
        v.tete = f
        x = v.x_de(f)
        if x > v.width() - 30 or x < 0:
            self.bornes()
            self.barre_h.setValue(int(f * v.px_par_image - 60))
        v.update()

