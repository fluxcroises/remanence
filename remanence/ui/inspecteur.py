"""Inspecteur : réglages du clip sélectionné, ou fiche technique du média choisi."""

from __future__ import annotations

import random

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QListWidget, QListWidgetItem,
                               QMenu, QPushButton, QScrollArea, QSizePolicy, QToolButton,
                               QVBoxLayout, QWidget)

from remanence.effets import EFFETS, valeur_a
from remanence.media.timecode import images_vers_tc
from remanence.effets.masques import NOMS_FORMES
from remanence.projet.modele import MODES_FUSION, MODES_MASQUE, Media, Projet
from remanence.ui.composants import (BoutonCle, LigneParametre, SectionRepliable, bouton_icone,
                                     etiquette, poser_icone)
from remanence.ui.menu_effets import remplir_menu_effets


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


# Largeur d'un losange d'image clé et de son espacement : les lignes sans losange s'y alignent.
RETRAIT_LOSANGE = 18 + 8


class Inspecteur(PanneauFiche):
    # (clip_id, champ, valeur) ; la fenêtre applique et enregistre dans l'historique.
    reglage = Signal(str, str, object)
    timecode_demande = Signal()
    # (effet_id, champ, valeur) : un paramètre, "actif", "graine", "reinitialiser", "retirer".
    reglage_effet = Signal(str, str, object)
    # (genre "clip" | "piste" | "sequence", identifiant, liste d'effets neufs)
    ajout_effet = Signal(str, str, object)
    # (effet_id, masque_id, champ, valeur) ; champ "ajouter" (valeur : la forme), "retirer",
    # "mode", "inverse", "adoucissement", "expansion", "points".
    reglage_masque = Signal(str, str, str, object)
    # Effet dont les masques se modifient sur l'image du programme ("" : aucun).
    edition_masques = Signal(str)
    # Effets à enregistrer comme préréglage personnel (un seul, ou toute la pile).
    enregistrer_prereglage = Signal(object)
    # Texte du badge de l'en-tête (« Clip vidéo », « Clip audio »), vide sans sélection.
    badge = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Tête de lecture du programme : les réglages animés montrent leur valeur à cet instant.
        self.temps = 0
        self.masques_edites = ""
        self._animes: list[tuple] = []
        self.vide()

    def _vider(self):
        super()._vider()
        self._animes = []

    def actualiser_temps(self, f: int):
        """La tête de lecture a bougé : valeurs des réglages animés et état des losanges."""
        self.temps = f
        for e, cle, origine, widget, bouton, echelle in self._animes:
            t = f - origine
            anime = cle in e.cles
            if anime:
                v = valeur_a(e, cle, t) * echelle
                if isinstance(widget, QCheckBox):
                    widget.blockSignals(True)
                    widget.setChecked(v > 0.5)
                    widget.blockSignals(False)
                else:
                    widget.montrer(v)
            sur_cle = anime and any(k[0] == t for k in e.cles[cle])
            bouton.definir("cle" if sur_cle else "anime" if anime else "inactif")

    def _bouton_cle(self, e, cle: str, origine: int) -> BoutonCle:
        b = BoutonCle()
        b.clicked.connect(lambda: self.reglage_effet.emit(e.id, "cle:" + cle, None))
        b.setContextMenuPolicy(Qt.CustomContextMenu)

        def menu(pos):
            m = QMenu(b)
            cles = e.cles.get(cle, [])
            t = self.temps - origine
            courante = next((k[2] for k in cles if k[0] <= t), cles[0][2] if cles else "lineaire")
            for mode, nom in (("lineaire", "Linéaire"), ("palier", "Palier")):
                a = m.addAction(nom, lambda mode=mode: self.reglage_effet.emit(
                    e.id, "interp:" + cle, mode))
                a.setCheckable(True)
                a.setChecked(bool(cles) and courante == mode)
                a.setEnabled(bool(cles))
            m.addSeparator()
            a = m.addAction("Supprimer l'animation", lambda: self.reglage_effet.emit(
                e.id, "interp:" + cle, "supprimer"))
            a.setEnabled(bool(cles))
            m.exec(b.mapToGlobal(pos))
        b.customContextMenuRequested.connect(menu)
        return b

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
        self._effets("sequence", seq.id, seq.effets, "Effets de séquence")

    def piste(self, projet: Projet, piste_id: str):
        seq = projet.sequence
        piste = next((p for p in seq.pistes if p.id == piste_id), None)
        if piste is None:
            self.vide(projet)
            return
        self._vider()
        self.badge.emit("Piste")
        self._titre(piste.nom, f"Piste {nom_court_piste(seq, piste)}")
        if piste.type == "video":
            self._effets("piste", piste.id, piste.effets, "Effets de piste")

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
        self.badge.emit("Clip d'effet" if c.est_effet else "Clip vidéo" if video else "Clip audio")
        debut = images_vers_tc(seq.tc_debut + c.debut, cad, seq.tc_drop)
        fin = images_vers_tc(seq.tc_debut + c.fin, cad, seq.tc_drop)
        titre = "Clip d'effet" if c.est_effet else media.nom if media else "Média manquant"
        self._titre(titre, f"Piste {nom_court_piste(seq, piste)} · {debut} à {fin}")

        self._section("Clip", "clip")
        if c.est_effet:
            self._lignes([("Durée", f"{images_vers_tc(c.duree, cad)} · {c.duree} images")])
        elif media and media.infos.video and media.infos.video.tc_debut is not None:
            v = media.infos.video
            entree = images_vers_tc(v.tc_debut + c.entree, v.fraction_cadence, v.tc_drop)
            sortie = images_vers_tc(v.tc_debut + c.entree + c.duree, v.fraction_cadence,
                                    v.tc_drop)
        else:
            entree, sortie = f"image {c.entree}", f"image {c.entree + c.duree}"
        if not c.est_effet:
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
                                100, 1)
        niveau.valeur_finale.connect(lambda v: self.reglage.emit(c.id, "gain", v / 100))
        self._cible.addWidget(niveau)
        if video:
            self._cible.addLayout(self._choix_fusion(
                c.fusion, lambda mode: self.reglage.emit(c.id, "fusion", mode)))
        for champ, nom in (("fondu_entree", "Fondu d'entrée"), ("fondu_sortie", "Fondu de sortie")):
            ligne = LigneParametre(nom, 0, c.duree, getattr(c, champ), "images", 0, 0)
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
        if video:
            self._effets("clip", c.id, c.effets, "Effets", origine=c.debut)

    def _masques(self, e):
        """Masques de l'effet : forme, combinaison, inversion, adoucissement, expansion."""
        for m in e.masques:
            rang = QHBoxLayout()
            rang.setSpacing(8)
            rang.addSpacing(RETRAIT_LOSANGE)
            nom = etiquette(NOMS_FORMES.get(m.forme, m.forme), "libelle")
            nom.setFixedWidth(100)
            rang.addWidget(nom)
            mode = QComboBox()
            mode.setAccessibleName("Combinaison du masque")
            for cle, texte in MODES_MASQUE.items():
                mode.addItem(texte, cle)
            mode.setCurrentIndex(max(0, mode.findData(m.mode)))
            mode.activated.connect(lambda i, m=m, mode=mode: self.reglage_masque.emit(
                e.id, m.id, "mode", mode.itemData(i)))
            rang.addWidget(mode, 1)
            inverse = QCheckBox("Inverser")
            inverse.setChecked(m.inverse)
            inverse.toggled.connect(lambda v, m=m: self.reglage_masque.emit(e.id, m.id,
                                                                            "inverse", v))
            rang.addWidget(inverse)
            retirer = bouton_icone("x", "Retirer le masque", taille=14)
            retirer.clicked.connect(lambda _=False, m=m: self.reglage_masque.emit(
                e.id, m.id, "retirer", None))
            rang.addWidget(retirer)
            self._cible.addLayout(rang)
            for champ, nom_reglage, mini in (("adoucissement", "Adoucissement", 0),
                                             ("expansion", "Expansion", -25)):
                vide = QWidget()
                vide.setFixedSize(18, 18)
                ligne = LigneParametre(nom_reglage, mini, 25, getattr(m, champ), "%", 0, 1,
                                       cle=vide)
                ligne.valeur_finale.connect(lambda v, m=m, champ=champ: self.reglage_masque.emit(
                    e.id, m.id, champ, v))
                self._cible.addWidget(ligne)
        rang = QHBoxLayout()
        rang.setSpacing(8)
        rang.addSpacing(RETRAIT_LOSANGE)
        ajout = QToolButton()
        ajout.setText("Ajouter un masque")
        poser_icone(ajout, "plus", 14)
        ajout.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        ajout.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(ajout)
        for forme, texte in NOMS_FORMES.items():
            menu.addAction(texte, lambda forme=forme: self.reglage_masque.emit(
                e.id, "", "ajouter", forme))
        ajout.setMenu(menu)
        rang.addWidget(ajout)
        if e.masques:
            modifier = QPushButton("Sur l'image")
            modifier.setCheckable(True)
            modifier.setToolTip("Modifier les masques sur le moniteur Programme")
            modifier.setChecked(self.masques_edites == e.id)
            modifier.toggled.connect(lambda v: self.edition_masques.emit(e.id if v else ""))
            rang.addWidget(modifier)
        rang.addStretch(1)
        self._cible.addLayout(rang)

    def _choix_fusion(self, actuel: str, choisir, retrait: bool = False) -> QHBoxLayout:
        """Ligne « Fusion » : les sept modes du cahier des charges. retrait : alignée sur les
        réglages précédés d'un losange."""
        rang = QHBoxLayout()
        rang.setSpacing(8)
        if retrait:
            rang.addSpacing(RETRAIT_LOSANGE)
        libelle = etiquette("Fusion", "libelle")
        libelle.setFixedWidth(100)
        liste = QComboBox()
        liste.setAccessibleName("Mode de fusion")
        for cle, nom in MODES_FUSION.items():
            liste.addItem(nom, cle)
        liste.setCurrentIndex(max(0, liste.findData(actuel)))
        liste.activated.connect(lambda i: choisir(liste.itemData(i)))
        rang.addWidget(libelle)
        rang.addWidget(liste, 1)
        return rang

    # Effets : une section par effet, réglages construits depuis la description de l'effet.

    def _effets(self, genre: str, porteur_id: str, effets: list, titre: str, origine: int = 0):
        """origine : image de la séquence où commence le temps des images clés (début du
        clip, ou 0 pour un effet de piste ou de séquence)."""
        t = self.temps - origine
        for e in effets:
            d = EFFETS.get(e.type)
            if d is None:
                continue
            section = self._section(d.nom, f"effet-{e.type}")
            actif = bouton_icone("eye" if e.actif else "eye-off", "Activer ou couper l'effet",
                                 cochable=True, taille=14)
            actif.setChecked(e.actif)
            actif.toggled.connect(lambda v, e=e: self.reglage_effet.emit(e.id, "actif", v))
            section.ajouter_outil(actif)
            raz = bouton_icone("rotate-ccw", "Réinitialiser", taille=14)
            raz.clicked.connect(lambda _=False, e=e: self.reglage_effet.emit(
                e.id, "reinitialiser", None))
            section.ajouter_outil(raz)
            garder = bouton_icone("bookmark", "Enregistrer comme préréglage", taille=14)
            garder.clicked.connect(lambda _=False, e=e: self.enregistrer_prereglage.emit([e]))
            section.ajouter_outil(garder)
            retirer = bouton_icone("x", "Retirer l'effet", taille=14)
            retirer.clicked.connect(lambda _=False, e=e: self.reglage_effet.emit(
                e.id, "retirer", None))
            section.ajouter_outil(retirer)
            for p in d.parametres:
                bouton = self._bouton_cle(e, p.cle, origine)
                if p.booleen:
                    case = QCheckBox(p.nom)
                    case.setChecked(valeur_a(e, p.cle, t) > 0.5)
                    case.toggled.connect(lambda v, e=e, p=p: self.reglage_effet.emit(
                        e.id, p.cle, 1.0 if v else 0.0))
                    rang = QHBoxLayout()
                    rang.setSpacing(8)
                    rang.addWidget(bouton)
                    rang.addWidget(case, 1)
                    self._cible.addLayout(rang)
                    self._animes.append((e, p.cle, origine, case, bouton, 1.0))
                    continue
                ligne = LigneParametre(p.nom, p.minimum, p.maximum, valeur_a(e, p.cle, t),
                                       p.unite, p.defaut, p.decimales, cle=bouton)
                ligne.valeur_finale.connect(lambda v, e=e, p=p: self.reglage_effet.emit(
                    e.id, p.cle, v))
                self._cible.addWidget(ligne)
                self._animes.append((e, p.cle, origine, ligne, bouton, 1.0))
            bouton = self._bouton_cle(e, "opacite", origine)
            opacite = LigneParametre("Opacité", 0, 100, valeur_a(e, "opacite", t) * 100, "%",
                                     100, 0, cle=bouton)
            opacite.valeur_finale.connect(lambda v, e=e: self.reglage_effet.emit(
                e.id, "opacite", v / 100))
            self._cible.addWidget(opacite)
            self._animes.append((e, "opacite", origine, opacite, bouton, 100.0))
            self._cible.addLayout(self._choix_fusion(
                e.fusion, lambda mode, e=e: self.reglage_effet.emit(e.id, "fusion", mode),
                retrait=True))
            self._masques(e)
            rang = QHBoxLayout()
            rang.setSpacing(8)
            rang.addSpacing(RETRAIT_LOSANGE)
            tirage_nom = etiquette("Tirage", "libelle")
            tirage_nom.setFixedWidth(100)
            rang.addWidget(tirage_nom)
            rang.addWidget(etiquette(str(e.graine), "valeur"), 1)
            tirage = QPushButton("Autre tirage")
            tirage.clicked.connect(lambda _=False, e=e: self.reglage_effet.emit(
                e.id, "graine", random.randrange(1, 1 << 31)))
            rang.addWidget(tirage)
            self._cible.addLayout(rang)
        self._cible = self._lay
        ajout = QToolButton()
        ajout.setText("Ajouter un effet" if not effets else "Ajouter un autre effet")
        poser_icone(ajout, "plus", 14)
        ajout.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        ajout.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(ajout)
        remplir_menu_effets(menu, lambda effets: self.ajout_effet.emit(genre, porteur_id,
                                                                       effets))
        ajout.setMenu(menu)
        rang = QHBoxLayout()
        rang.addWidget(ajout)
        if len(effets) > 1:
            pile = QPushButton("Enregistrer la pile")
            pile.setToolTip("Enregistrer les effets comme un seul préréglage")
            pile.clicked.connect(lambda: self.enregistrer_prereglage.emit(list(effets)))
            rang.addWidget(pile)
        rang.addStretch(1)
        self._lay.addLayout(rang)
