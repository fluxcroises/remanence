"""Inspecteur : réglages du clip sélectionné, ou fiche technique du média choisi."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QListWidget, QListWidgetItem,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from remanence.media.timecode import images_vers_tc
from remanence.projet.modele import Media, Projet
from remanence.ui.composants import LigneParametre, etiquette


def _effacer(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _effacer(item.layout())


def nom_court_piste(seq, piste) -> str:
    """V1 est la piste vidéo du bas, comme dans Resolve ; A1 la première piste audio."""
    if piste.type == "video":
        pistes = seq.pistes_video
        return f"V{len(pistes) - pistes.index(piste)}"
    return f"A{seq.pistes_audio.index(piste) + 1}"


class PanneauFiche(QWidget):
    """Colonne défilante de titres, sections et lignes libellé-valeur, avec un pied facultatif."""

    def __init__(self, parent=None):
        super().__init__(parent)
        racine = QVBoxLayout(self)
        racine.setContentsMargins(0, 0, 0, 0)
        racine.setSpacing(0)
        defil = QScrollArea()
        defil.setWidgetResizable(True)
        defil.setFrameShape(QScrollArea.NoFrame)
        contenu = QWidget()
        contenu.setProperty("role", "panneau")
        contenu.setAttribute(Qt.WA_StyledBackground, True)
        self._lay = QVBoxLayout(contenu)
        self._lay.setContentsMargins(14, 12, 14, 12)
        self._lay.setSpacing(12)
        self._lay.setAlignment(Qt.AlignTop)
        defil.setWidget(contenu)
        racine.addWidget(defil, 1)
        self._pied = QWidget()
        self._pied.setProperty("role", "pied")
        self._pied.setAttribute(Qt.WA_StyledBackground, True)
        self._lay_pied = QHBoxLayout(self._pied)
        self._lay_pied.setContentsMargins(14, 12, 14, 12)
        racine.addWidget(self._pied)

    def _titre(self, titre: str, sous_titre: str = ""):
        bloc = QVBoxLayout()
        bloc.setSpacing(2)
        t = etiquette(titre, "titre")
        t.setWordWrap(True)
        bloc.addWidget(t)
        if sous_titre:
            s = etiquette(sous_titre, "libelle")
            s.setWordWrap(True)
            bloc.addWidget(s)
        self._lay.addLayout(bloc)

    def _section(self, nom: str):
        self._lay.addWidget(etiquette(nom, "section"))

    def _lignes(self, lignes: list[tuple[str, str]]):
        grille = QGridLayout()
        grille.setHorizontalSpacing(12)
        grille.setVerticalSpacing(6)
        for i, (cle, valeur) in enumerate(lignes):
            e = etiquette(cle, "libelle")
            e.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            # Chasse fixe pour les nombres seulement : ils ne tremblent pas quand ils changent.
            v = etiquette(valeur, "valeur" if valeur[:1].isdigit() else "")
            v.setWordWrap(True)
            v.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grille.addWidget(e, i, 0)
            grille.addWidget(v, i, 1)
        grille.setColumnStretch(1, 1)
        self._lay.addLayout(grille)

    def _note(self, texte: str):
        n = etiquette(texte, "secondaire")
        n.setWordWrap(True)
        self._lay.addWidget(n)

    def _vider(self):
        _effacer(self._lay)
        _effacer(self._lay_pied)
        self._pied.hide()


class Metadonnees(PanneauFiche):
    """Fiche technique du média choisi dans le panneau Média ou du clip sélectionné."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.vide()

    def vide(self):
        self._vider()
        self._titre("Aucun média")
        self._note("Cliquez sur un média ou sur un clip pour lire sa fiche technique : codec, "
                   "profondeur, cadence, timecode, couleur et audio.")

    def afficher(self, media: Media):
        self._vider()
        self._titre(media.nom, "Fichier hors ligne : " + media.chemin if media.hors_ligne
                    else media.infos.conteneur)
        self._section("Fiche technique")
        lignes = [(k, v) for k, v in media.infos.fiche() if k not in ("Fichier", "Attention")]
        self._lignes(lignes)
        alertes = [v for k, v in media.infos.fiche() if k == "Attention"]
        if alertes:
            self._section("Attention")
            for a in alertes:
                n = etiquette(f"Avertissement : {a}", "avertissement")
                n.setWordWrap(True)
                self._lay.addWidget(n)


class Historique(QListWidget):
    """Toutes les actions de la session ; un clic ramène le projet à cet état."""
    aller = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAccessibleName("Historique des actions")
        self.itemActivated.connect(lambda item: self.aller.emit(self.row(item)))
        self.itemClicked.connect(lambda item: self.aller.emit(self.row(item)))

    def afficher(self, libelles: list[str], position: int):
        self.blockSignals(True)
        self.clear()
        for i, libelle in enumerate(libelles):
            texte = libelle if i else "Ouverture du projet"
            item = QListWidgetItem(texte + ("  ·  état actuel" if i == position else ""))
            if i > position:
                item.setToolTip("Action annulée : cliquez pour la rétablir.")
            self.addItem(item)
        self.setCurrentRow(position)
        self.blockSignals(False)


class Inspecteur(PanneauFiche):
    # (clip_id, champ, valeur) ; la fenêtre applique et enregistre dans l'historique.
    reglage = Signal(str, str, object)
    # Texte du badge de l'en-tête (« Clip vidéo », « Clip audio »), vide sans sélection.
    badge = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.vide()

    def vide(self):
        self._vider()
        self.badge.emit("")
        self._titre("Aucune sélection")
        self._note("Cliquez sur un clip de la timeline pour régler son niveau et ses fondus.")

    def clip(self, projet: Projet, clip_id: str):
        seq = projet.sequence
        piste, c = seq.trouver(clip_id)
        if c is None:
            self.vide()
            return
        self._vider()
        media = projet.medias.get(c.media_id)
        video = piste.type == "video"
        cad = seq.fraction_cadence
        self.badge.emit("Clip vidéo" if video else "Clip audio")
        debut = images_vers_tc(seq.tc_debut + c.debut, cad, seq.tc_drop)
        fin = images_vers_tc(seq.tc_debut + c.fin, cad, seq.tc_drop)
        self._titre(media.nom if media else "Média manquant",
                    f"Piste {nom_court_piste(seq, piste)} · {debut} à {fin}")

        self._section("Clip")
        if media and media.infos.video and media.infos.video.tc_debut is not None:
            v = media.infos.video
            entree = images_vers_tc(v.tc_debut + c.entree, v.fraction_cadence, v.tc_drop)
        else:
            entree = f"image {c.entree}"
        self._lignes([("Durée", f"{images_vers_tc(c.duree, cad)} · {c.duree} images"),
                      ("Entrée source", entree),
                      ("Liaison", "liée au son ou à l'image" if c.lien else "indépendante")])

        self._section("Niveau et fondus")
        niveau = LigneParametre("Opacité" if video else "Volume", 0, 100, c.gain * 100, "%",
                                100, 1, "Opacité du clip vidéo." if video
                                else "Volume du clip audio.")
        niveau.valeur_finale.connect(lambda v: self.reglage.emit(c.id, "gain", v / 100))
        self._lay.addWidget(niveau)
        for champ, nom in (("fondu_entree", "Fondu d'entrée"), ("fondu_sortie", "Fondu de sortie")):
            ligne = LigneParametre(nom, 0, c.duree, getattr(c, champ), "images", 0, 0,
                                   "Se règle aussi en tirant la poignée au coin supérieur du clip.")
            ligne.champ.setFixedWidth(96)
            ligne.valeur_finale.connect(lambda v, champ=champ: self.reglage.emit(c.id, champ,
                                                                                 round(v)))
            self._lay.addWidget(ligne)
        self._note("Double-cliquez sur le clip pour ajouter un point d'enveloppe, puis tirez-le. "
                   "Clic droit sur un point pour le retirer.")
        if c.enveloppe:
            b = QPushButton("Effacer l'enveloppe")
            b.setToolTip(f"Retire les {len(c.enveloppe)} points de l'enveloppe "
                         f"{'d’opacité' if video else 'de volume'} de ce clip.")
            b.clicked.connect(lambda: self.reglage.emit(c.id, "enveloppe", []))
            self._lay_pied.addWidget(b)
            self._lay_pied.addStretch(1)
            self._pied.show()
