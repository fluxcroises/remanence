"""Inspecteur : réglages du clip sélectionné, ou fiche technique du média choisi."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDoubleSpinBox, QFormLayout, QLabel, QPushButton, QSpinBox,
                               QVBoxLayout, QWidget)

from remanence.media.timecode import images_vers_tc
from remanence.projet.modele import Media, Projet


def _effacer(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _effacer(item.layout())


class Inspecteur(QWidget):
    # (clip_id, champ, valeur) ; la fenêtre applique et enregistre dans l'historique.
    reglage = Signal(str, str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(8, 8, 8, 8)
        self._lay.setAlignment(Qt.AlignTop)
        self.vide()

    def _titre(self, texte):
        t = QLabel(texte)
        t.setStyleSheet("font-size: 11pt; font-weight: 600;")
        t.setWordWrap(True)
        self._lay.addWidget(t)

    def _note(self, texte):
        n = QLabel(texte)
        n.setWordWrap(True)
        n.setProperty("role", "secondaire")
        self._lay.addWidget(n)

    def vide(self):
        _effacer(self._lay)
        self._titre("Aucune sélection")
        self._note("Cliquez sur un clip de la timeline pour régler ses fondus et son niveau, "
                   "ou sur un média pour lire sa fiche technique.")

    def fiche_media(self, media: Media):
        _effacer(self._lay)
        self._titre(media.nom)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        for cle, valeur in media.infos.fiche():
            v = QLabel(valeur)
            v.setWordWrap(True)
            v.setTextInteractionFlags(Qt.TextSelectableByMouse)
            etiquette = QLabel(cle)
            etiquette.setProperty("role", "secondaire")
            form.addRow(etiquette, v)
        self._lay.addLayout(form)
        if media.hors_ligne:
            self._note(f"Fichier introuvable : {media.chemin}")

    def clip(self, projet: Projet, clip_id: str):
        seq = projet.sequence
        piste, c = seq.trouver(clip_id)
        if c is None:
            self.vide()
            return
        _effacer(self._lay)
        media = projet.medias.get(c.media_id)
        video = piste.type == "video"
        cad = seq.fraction_cadence
        self._titre(media.nom if media else "Média manquant")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        def ligne(nom, valeur):
            e = QLabel(nom)
            e.setProperty("role", "secondaire")
            v = QLabel(valeur)
            v.setTextInteractionFlags(Qt.TextSelectableByMouse)
            form.addRow(e, v)

        ligne("Piste", piste.nom)
        ligne("Position", images_vers_tc(seq.tc_debut + c.debut, cad, seq.tc_drop))
        ligne("Durée", f"{images_vers_tc(c.duree, cad)} ({c.duree} images)")
        if media and media.infos.video and media.infos.video.tc_debut is not None:
            v = media.infos.video
            ligne("Entrée source", images_vers_tc(v.tc_debut + c.entree, v.fraction_cadence,
                                                  v.tc_drop))
        else:
            ligne("Entrée source", f"image {c.entree}")
        ligne("Liaison", "liée au son ou à l'image" if c.lien else "indépendante")

        niveau = QDoubleSpinBox()
        niveau.setRange(0, 100)
        niveau.setDecimals(1)
        niveau.setSuffix(" %")
        niveau.setValue(c.gain * 100)
        niveau.setToolTip("Opacité du clip vidéo." if video else "Volume du clip audio.")
        niveau.editingFinished.connect(
            lambda: self.reglage.emit(c.id, "gain", niveau.value() / 100))
        form.addRow(QLabel("Opacité" if video else "Volume"), niveau)

        for champ, nom in (("fondu_entree", "Fondu d'entrée"), ("fondu_sortie", "Fondu de sortie")):
            s = QSpinBox()
            s.setRange(0, c.duree)
            s.setSuffix(" images")
            s.setValue(getattr(c, champ))
            s.setToolTip("Se règle aussi en tirant la poignée au coin supérieur du clip.")
            s.editingFinished.connect(lambda s=s, champ=champ: self.reglage.emit(c.id, champ,
                                                                                 s.value()))
            form.addRow(QLabel(nom), s)
        self._lay.addLayout(form)

        if c.enveloppe:
            b = QPushButton("Effacer l'enveloppe")
            b.setToolTip(f"Retire les {len(c.enveloppe)} points de l'enveloppe "
                         f"{'d’opacité' if video else 'de volume'} de ce clip.")
            b.clicked.connect(lambda: self.reglage.emit(c.id, "enveloppe", []))
            self._lay.addWidget(b)
        self._note("Double-cliquez sur le clip pour ajouter un point d'enveloppe, puis tirez-le. "
                   "Clic droit sur un point pour le retirer.")
