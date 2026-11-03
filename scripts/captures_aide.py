"""Refait les captures des fiches de prise en main (`remanence/ressources/aide`).

    .venv\\Scripts\\python.exe scripts\\captures_aide.py

Remanence est ouvert hors écran sur les médias de test (générés par les tests), mis dans
l'état de chaque fiche, puis chaque panneau utile est photographié. Les réglages et le cache
vont dans des dossiers temporaires : rien ne touche à ceux de l'utilisateur.
"""

import os
import sys
import tempfile
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
os.environ["REMANENCE_DONNEES"] = tempfile.mkdtemp(prefix="remanence_aide_")
os.environ["REMANENCE_CACHE"] = tempfile.mkdtemp(prefix="remanence_aide_")

from PySide6.QtCore import QSettings  # noqa: E402

QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, tempfile.mkdtemp())

from PySide6.QtWidgets import QApplication  # noqa: E402

DOSSIER = RACINE / "remanence" / "ressources" / "aide"


def attendre(app, condition=lambda: False, delai=0.4):
    fin = time.time() + delai
    while time.time() < fin:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def main():
    app = QApplication([])
    from remanence.config import reglages_interface
    from remanence.effets import nouvel_effet, poser_cle
    from remanence.ui import charte
    from remanence.ui.fenetre import FenetrePrincipale
    from tests.generer_medias import generer

    charte.charger_polices()
    charte.definir("dark")
    charte.actuelle().appliquer(app)
    reglages_interface().setValue("sequence/timecode_debut", "clip")
    medias = generer()
    w = FenetrePrincipale()
    w.resize(1600, 940)
    w.show()
    w.importer_chemins([str(medias["prores_hq"]), str(medias["sans_audio_2997"])])
    attendre(app, lambda: len(w.projet.medias) == 2, 30)
    a, b = list(w.projet.medias)
    w.poser_medias([a], 0, "")
    w.poser_medias([b], w.projet.sequence.duree(), "")
    w.timeline.tout_voir()
    attendre(app)

    def photo(widget, nom, largeur=None, hauteur=None):
        """largeur : seulement la partie gauche (la timeline est très large)."""
        attendre(app)
        image = widget.grab()
        if largeur:
            image = image.copy(0, 0, min(largeur, image.width()),
                               min(hauteur or image.height(), image.height()))
        image.save(str(DOSSIER / nom))

    seq = w.projet.sequence
    premier, second = seq.pistes_video[0].clips[:2]
    photo(w._docks["timeline"], "montage.png", 820, 215)

    # Transition datamosh au raccord.
    w.basculer_cle("raccord", second.id, 0)
    attendre(app, delai=1.0)
    photo(w._docks["timeline"], "transition.png", 820, 215)

    # Effet animé : deux images clés, l'effet n'agit qu'entre elles.
    w.timeline.vue._choisir({premier.id})
    effet = nouvel_effet("blocs_deplaces", "Blocs en fuite")
    poser_cle(effet, "force", 5, 30)
    poser_cle(effet, "force", 15, 80)
    w.ajouter_effet("clip", premier.id, [effet])
    w.aller_a(10)
    attendre(app, delai=1.0)
    barre = w.inspecteur._defil.verticalScrollBar()
    barre.setValue(barre.maximum())
    photo(w._docks["droite"], "inspecteur.png")
    photo(w._docks["timeline"], "images_cles.png", 820, 215)
    effet.cles["force"][0][2] = "bezier"
    w.timeline.b_courbes.setChecked(True)
    attendre(app, delai=0.6)
    w.panneau_courbes.graphe.choisie = 0
    photo(w._docks["courbes"], "courbes.png", 1100)
    w.reglage_modulateur("", "ajouter", ["oscillateur", [effet.id, "force"]])
    attendre(app, delai=0.6)
    w.reglage_modulateur(w.projet.sequence.modulateurs[0].id, "param:frequence", 3.0)
    attendre(app, delai=0.6)
    w.panneau_courbes.liste_modulateurs.setCurrentRow(0)
    photo(w._docks["courbes"], "modulateurs.png", 1100)
    w.reglage_modulateur(w.projet.sequence.modulateurs[0].id, "retirer", None)
    attendre(app, delai=0.6)
    w.timeline.b_courbes.setChecked(False)

    # Script FFglitch dans l'inspecteur.
    w.ajouter_effet("clip", premier.id, [nouvel_effet("script_ffglitch", "Moyenne du mouvement")])
    attendre(app, delai=1.0)
    barre.setValue(barre.maximum())
    photo(w._docks["droite"], "codec.png")

    # Pistes : une piste colorée.
    piste = seq.pistes_video[0]
    w.regler_piste(piste.id, "couleur", "accent-2")
    w.ajouter_piste("video")
    attendre(app, delai=0.6)
    photo(w.timeline.zone_entetes, "pistes.png")

    # Bibliothèque d'effets (espace Effets) et compression.
    w.choisir_espace("effets")
    w.timeline.vue._choisir({premier.id})
    attendre(app, delai=0.6)
    photo(w._docks["medias"], "bibliotheque.png")
    w._docks["analyse"].show()
    attendre(app, lambda: w.panneau_datamosh.bande.analyse is not None, 30)
    photo(w._docks["analyse"], "compression.png")

    w.choisir_espace("export")
    attendre(app, delai=0.6)
    photo(w._docks["export"], "export.png")

    w.modifie = False
    w.close()


if __name__ == "__main__":
    main()
