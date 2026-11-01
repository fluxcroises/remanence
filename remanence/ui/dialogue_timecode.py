"""Choix du timecode de début de la séquence : 01:00:00:00, celui du premier clip, ou un autre."""

from __future__ import annotations

from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog, QDialogButtonBox, QGridLayout,
                               QLabel, QLineEdit, QRadioButton, QVBoxLayout)

from remanence.config import reglages_interface
from remanence.media.timecode import images_vers_tc, tc_vers_images
from remanence.projet.modele import Sequence

# Choix retenu pour les nouvelles séquences : "heure" (01:00:00:00) ou "clip" ; absent : demander.
CLE_PREFERENCE = "sequence/timecode_debut"


def timecode_une_heure(seq: Sequence) -> int:
    """01:00:00:00, l'usage des logiciels de montage (01:00:00;00 en drop frame)."""
    return tc_vers_images("01:00:00;00" if seq.tc_drop else "01:00:00:00",
                          seq.fraction_cadence)[0]


def preference() -> str:
    return str(reglages_interface().value(CLE_PREFERENCE, "") or "")


class DialogueTimecode(QDialog):
    """tc_clip : timecode du premier clip en images, ou None s'il n'en a pas.
    premiere_fois : proposé à la pose du premier média (on peut alors retenir le choix)."""

    def __init__(self, seq: Sequence, tc_clip: int | None, premiere_fois: bool, parent=None):
        super().__init__(parent)
        self.seq = seq
        self.setWindowTitle("Timecode de début de la séquence")
        cad, drop = seq.fraction_cadence, seq.tc_drop
        lay = QVBoxLayout(self)
        intro = QLabel("À quel timecode la séquence doit-elle commencer ? Il s'affiche sur la "
                       "règle et les moniteurs, et il est écrit dans les fichiers exportés. "
                       "Vous pourrez le changer plus tard (menu Montage).")
        intro.setWordWrap(True)
        intro.setMinimumWidth(440)
        lay.addWidget(intro)

        grille = QGridLayout()
        self.groupe = QButtonGroup(self)
        self.b_heure = QRadioButton(f"{images_vers_tc(timecode_une_heure(seq), cad, drop)}, "
                                    "l'usage des logiciels de montage")
        if tc_clip is not None:
            texte_clip = f"Celui du premier clip : {images_vers_tc(tc_clip, cad, drop)}"
        else:
            texte_clip = "Celui du premier clip (il n'a pas de timecode)"
        self.b_clip = QRadioButton(texte_clip)
        self.b_clip.setEnabled(tc_clip is not None)
        self.b_autre = QRadioButton("Autre :")
        self.saisie = QLineEdit(images_vers_tc(seq.tc_debut, cad, drop))
        self.saisie.setProperty("role", "timecode")
        self.saisie.setAccessibleName("Timecode de début, saisi")
        self.saisie.setToolTip("Format HH:MM:SS:II (point-virgule avant les images en drop frame).")
        self.saisie.textEdited.connect(lambda _t: self.b_autre.setChecked(True))
        for i, b in enumerate((self.b_heure, self.b_clip, self.b_autre)):
            self.groupe.addButton(b, i)
        grille.addWidget(self.b_heure, 0, 0, 1, 2)
        grille.addWidget(self.b_clip, 1, 0, 1, 2)
        grille.addWidget(self.b_autre, 2, 0)
        grille.addWidget(self.saisie, 2, 1)
        grille.setColumnStretch(1, 1)
        lay.addLayout(grille)
        self.tc_clip = tc_clip

        if seq.tc_debut == timecode_une_heure(seq):
            self.b_heure.setChecked(True)
        elif tc_clip is not None and seq.tc_debut == tc_clip:
            self.b_clip.setChecked(True)
        else:
            self.b_autre.setChecked(True)

        self.retenir = QCheckBox("Ne plus demander : faire ce choix pour chaque nouvelle séquence")
        self.retenir.setVisible(premiere_fois)
        self.groupe.idToggled.connect(lambda _i, _v: self.retenir.setEnabled(
            not self.b_autre.isChecked()))
        self.retenir.setEnabled(not self.b_autre.isChecked())
        lay.addWidget(self.retenir)

        self.erreur = QLabel("")
        self.erreur.setProperty("role", "avertissement")
        self.erreur.setWordWrap(True)
        self.erreur.hide()
        lay.addWidget(self.erreur)
        boutons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        boutons.button(QDialogButtonBox.Ok).setText("Valider")
        boutons.button(QDialogButtonBox.Cancel).setText("Annuler")
        boutons.accepted.connect(self._valider)
        boutons.rejected.connect(self.reject)
        lay.addWidget(boutons)

    def valeur(self) -> int | None:
        """Le timecode choisi, en images ; None si la saisie est illisible."""
        if self.b_heure.isChecked():
            return timecode_une_heure(self.seq)
        if self.b_clip.isChecked():
            return self.tc_clip
        try:
            return max(0, tc_vers_images(self.saisie.text(), self.seq.fraction_cadence)[0])
        except ValueError:
            return None

    def _valider(self):
        if self.valeur() is None:
            self.erreur.setText("Timecode illisible. Écrivez-le sous la forme HH:MM:SS:II, "
                                "par exemple 10:00:00:00.")
            self.erreur.show()
            self.saisie.setFocus()
            return
        if self.retenir.isVisible() and self.retenir.isChecked():
            reglages_interface().setValue(CLE_PREFERENCE,
                                          "heure" if self.b_heure.isChecked() else "clip")
        self.accept()
