"""Inspecteur : réglages du clip sélectionné, ou fiche technique du média choisi."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QListWidget, QListWidgetItem,
                               QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from remanence.media.timecode import images_vers_tc
from remanence.projet.modele import Media, Projet
from remanence.ui.composants import LigneParametre, SectionRepliable, bouton_icone, etiquette


def _effacer(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w:
            # Détaché tout de suite : l'ancien contenu ne reste pas visible jusqu'à sa destruction.
            w.hide()
            w.setParent(None)
            w.deleteLater()
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
        defil.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        contenu = QWidget()
        contenu.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
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
        self._cible = self._lay

    def _section(self, nom: str, cle: str) -> SectionRepliable:
        """Ouvre une section repliable : les lignes et notes suivantes s'y rangent."""
        section = SectionRepliable(nom, cle)
        self._lay.addWidget(section)
        self._cible = section.contenu
        return section

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
        grille.setColumnMinimumWidth(0, 100)
        grille.setColumnStretch(1, 1)
        self._cible.addLayout(grille)

    def _note(self, texte: str):
        n = etiquette(texte, "secondaire")
        n.setWordWrap(True)
        self._cible.addWidget(n)

    def _vider(self):
        _effacer(self._lay)
        _effacer(self._lay_pied)
        self._pied.hide()
        self._cible = self._lay


class Metadonnees(PanneauFiche):
    """Fiche technique du média choisi dans le panneau Média ou du clip sélectionné."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.vide()

    def vide(self):
        self._vider()
        self._titre("Aucun média")

    def afficher(self, media: Media):
        self._vider()
        self._titre(media.nom, "Fichier hors ligne : " + media.chemin if media.hors_ligne
                    else media.chemin)
        fiche = media.infos.fiche()
        groupes = {"Fichier": [], "Vidéo": [], "Audio": []}
        for k, v in fiche:
            if k in ("Fichier", "Attention"):
                continue
            if k in ("Conteneur", "Durée"):
                groupes["Fichier"].append((k, v))
            elif k.startswith("Audio"):
                groupes["Audio"].append((k, v))
            else:
                groupes["Vidéo"].append((k, v))
        alertes = [v for k, v in fiche if k == "Attention"]
        if alertes:
            self._section("Attention", "meta-attention")
            for alerte in alertes:
                n = etiquette(f"Avertissement : {alerte}", "avertissement")
                n.setWordWrap(True)
                self._cible.addWidget(n)
        for nom, lignes in groupes.items():
            if lignes:
                self._section(nom, f"meta-{nom}")
                self._lignes(lignes)


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
                item.setToolTip("Action annulée")
            self.addItem(item)
        self.setCurrentRow(position)
        self.blockSignals(False)


class Inspecteur(PanneauFiche):
    # (clip_id, champ, valeur) ; la fenêtre applique et enregistre dans l'historique.
    reglage = Signal(str, str, object)
    timecode_demande = Signal()
    # Texte du badge de l'en-tête (« Clip vidéo », « Clip audio »), vide sans sélection.
    badge = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.vide()

    def vide(self, projet: Projet | None = None, nombre: int = 0):
        """Sans clip unique choisi : la séquence, et le nombre de clips s'il y en a plusieurs."""
        self._vider()
        self.badge.emit("")
        if nombre > 1:
            self._titre(f"{nombre} clips sélectionnés",
                        "")
        else:
            self._titre("Aucune sélection",
                        "")
        if projet is None:
            return
        seq = projet.sequence
        cad = seq.fraction_cadence
        self._section("Séquence", "sequence")
        self._lignes([
            ("Nom", seq.nom),
            ("Image", f"{seq.largeur} × {seq.hauteur}"),
            ("Cadence", f"{float(cad):.3f} i/s".replace(".", ",")),
            ("Début", images_vers_tc(seq.tc_debut, cad, seq.tc_drop)),
            ("Durée", images_vers_tc(seq.duree(), cad)),
            ("Pistes", f"{len(seq.pistes_video)} vidéo, {len(seq.pistes_audio)} audio"),
            ("Clips", str(sum(len(p.clips) for p in seq.pistes))),
            ("Marqueurs", str(len(seq.marqueurs)))])
        b = QPushButton("Changer le timecode de début…")

        b.clicked.connect(self.timecode_demande.emit)
        rang = QHBoxLayout()
        rang.addWidget(b)
        rang.addStretch(1)
        self._cible.addLayout(rang)

    def clip(self, projet: Projet, clip_id: str):
        seq = projet.sequence
        piste, c = seq.trouver(clip_id)
        if c is None:
            self.vide(projet)
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

        self._section("Clip", "clip")
        if media and media.infos.video and media.infos.video.tc_debut is not None:
            v = media.infos.video
            entree = images_vers_tc(v.tc_debut + c.entree, v.fraction_cadence, v.tc_drop)
            sortie = images_vers_tc(v.tc_debut + c.entree + c.duree, v.fraction_cadence,
                                    v.tc_drop)
        else:
            entree, sortie = f"image {c.entree}", f"image {c.entree + c.duree}"
        self._lignes([("Durée", f"{images_vers_tc(c.duree, cad)} · {c.duree} images"),
                      ("Entrée source", entree),
                      ("Sortie source", sortie),
                      ("Liaison", "liée au son ou à l'image" if c.lien else "indépendante")])

        section = self._section("Niveau et fondus", "niveau")
        if c.gain != 1.0 or c.fondu_entree or c.fondu_sortie:
            raz = bouton_icone("rotate-ccw", "Réinitialiser",
                               taille=14)
            raz.clicked.connect(lambda: self.reglage.emit(c.id, "reinitialiser", None))
            section.ajouter_outil(raz)
        niveau = LigneParametre("Opacité" if video else "Volume", 0, 100, c.gain * 100, "%",
                                100, 1, "" if video
                                else "")
        niveau.valeur_finale.connect(lambda v: self.reglage.emit(c.id, "gain", v / 100))
        self._cible.addWidget(niveau)
        for champ, nom in (("fondu_entree", "Fondu d'entrée"), ("fondu_sortie", "Fondu de sortie")):
            ligne = LigneParametre(nom, 0, c.duree, getattr(c, champ), "images", 0, 0,
                                   "")
            ligne.champ.setFixedWidth(96)
            ligne.valeur_finale.connect(lambda v, champ=champ: self.reglage.emit(c.id, champ,
                                                                                 round(v)))
            self._cible.addWidget(ligne)

        self._section("Enveloppe d'opacité" if video else "Enveloppe de volume", "enveloppe")
        if c.enveloppe:
            self._lignes([("Points", str(len(c.enveloppe)))])
            b = QPushButton("Effacer l'enveloppe")
            b.clicked.connect(lambda: self.reglage.emit(c.id, "enveloppe", []))
            rang = QHBoxLayout()
            rang.addWidget(b)
            rang.addStretch(1)
            self._cible.addLayout(rang)
