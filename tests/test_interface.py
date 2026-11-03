"""Parcours de l'interface sans affichage : import, montage, lecture, enregistrement."""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from remanence.ui import lecture as module_lecture  # noqa: E402

# Pas de son pendant les tests : l'horloge système remplace la carte son.
module_lecture.sounddevice = None


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _attendre(condition, delai=20.0):
    fin = time.time() + delai
    while time.time() < fin:
        QCoreApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def fenetre(app):
    from remanence.ui.fenetre import FenetrePrincipale
    w = FenetrePrincipale()
    w.show()
    yield w
    w.modifie = False
    w.close()


def test_parcours_complet(fenetre, medias, tmp_path):
    w = fenetre
    w.importer_chemins([str(medias["prores_hq"])])
    assert _attendre(lambda: len(w.projet.medias) == 1)
    mid = next(iter(w.projet.medias))
    w.poser_medias([mid], 0, "")
    seq = w.projet.sequence
    assert seq.duree() == 30 and w.visionneuse.timecode.text() == "01:00:00:00"
    assert _attendre(lambda: w.visionneuse.zone._image is not None), "aucune image affichée"

    w.aller_a(10)
    w.couper()
    assert len(seq.pistes_video[0].clips) == 2
    w.annuler()
    assert len(w.projet.sequence.pistes_video[0].clips) == 1
    w.retablir()
    assert len(w.projet.sequence.pistes_video[0].clips) == 2

    clip = w.projet.sequence.pistes_video[0].clips[1]
    w.timeline.vue.selection = {clip.id}
    w._reglage_clip(clip.id, "fondu_sortie", 5)
    assert w.projet.sequence.pistes_video[0].clips[1].fondu_sortie == 5
    w.supprimer()
    assert len(w.projet.sequence.pistes_video[0].clips) == 1
    assert len(w.projet.sequence.pistes_audio[0].clips) == 1, "le son lié part avec l'image"

    w.chemin = tmp_path / "essai.remanence"
    assert w.enregistrer()
    assert w.chemin.exists() and not w.modifie


def test_lecture_avance(fenetre, medias):
    w = fenetre
    w.importer_chemins([str(medias["h264"])])
    assert _attendre(lambda: len(w.projet.medias) == 1)
    w.poser_medias(list(w.projet.medias), 0, "")
    w.aller_a(0)
    w.lire_pause()
    assert _attendre(lambda: w.lecture.position >= 10, 10)
    w.lire_pause()
    assert not w.lecture.en_lecture
    arret = w.lecture.position
    time.sleep(0.2)
    QCoreApplication.processEvents()
    assert w.lecture.position == arret


def test_lecture_s_arrete_a_la_fin(fenetre, medias):
    w = fenetre
    w.importer_chemins([str(medias["prores_4444"])])
    assert _attendre(lambda: len(w.projet.medias) == 1)
    w.poser_medias(list(w.projet.medias), 0, "")
    w.aller_a(15)
    w.lecture.lire(4.0)
    assert _attendre(lambda: not w.lecture.en_lecture, 10)
    assert w.lecture.position == 19


def test_import_raw_explique(fenetre, tmp_path, monkeypatch):
    messages = []
    monkeypatch.setattr("remanence.ui.fenetre.afficher_erreur",
                        lambda parent, titre, message, detail=None: messages.append(message))
    f = tmp_path / "A001_C002.braw"
    f.write_bytes(b"\0" * 32)
    fenetre.importer_chemins([str(f)])
    assert _attendre(lambda: messages)
    assert "ProRes" in messages[0] and not fenetre.projet.medias


def test_souris_sur_la_timeline(fenetre, medias):
    """Déplacer, rogner et tirer un fondu à la souris, puis annuler chaque geste."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    w = fenetre
    w.importer_chemins([str(medias["prores_hq"])])
    assert _attendre(lambda: len(w.projet.medias) == 1)
    w.timeline.resize(1200, 400)
    w.poser_medias(list(w.projet.medias), 20, "")
    vue = w.timeline.vue
    vue.aimantation = False
    vue.px_par_image = 10.0
    vue.decalage_x = 0.0
    vue.resize(1000, 300)
    piste, y, h = vue.lignes()[0]
    milieu = y + h // 2

    def glisser(x0, y0, x1, y1):
        QTest.mousePress(vue, Qt.LeftButton, Qt.NoModifier, QPoint(x0, y0))
        QTest.mouseMove(vue, QPoint((x0 + x1) // 2, (y0 + y1) // 2))
        QTest.mouseMove(vue, QPoint(x1, y1))
        QTest.mouseRelease(vue, Qt.LeftButton, Qt.NoModifier, QPoint(x1, y1))

    glisser(300, milieu, 400, milieu)
    clip = w.projet.sequence.pistes_video[0].clips[0]
    assert clip.debut == 30
    assert w.projet.sequence.pistes_audio[0].clips[0].debut == 30, "le son suit l'image"

    glisser(int(vue.x_de(clip.fin)) - 1, milieu, int(vue.x_de(clip.fin)) - 51, milieu)
    clip = w.projet.sequence.pistes_video[0].clips[0]
    assert clip.duree == 25

    haut = y + 4
    glisser(int(vue.x_de(clip.debut)) + 1, haut, int(vue.x_de(clip.debut)) + 61, haut)
    assert w.projet.sequence.pistes_video[0].clips[0].fondu_entree == 6

    w.annuler()
    assert w.projet.sequence.pistes_video[0].clips[0].fondu_entree == 0
    w.annuler()
    assert w.projet.sequence.pistes_video[0].clips[0].duree == 30
    w.annuler()
    assert w.projet.sequence.pistes_video[0].clips[0].debut == 20


def test_gestes_ripple_et_marqueurs(fenetre, medias):
    """Fondu enchaîné en posant un clip sur un autre, slip avec Alt, ripple, marqueurs."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from remanence.projet import edition
    from remanence.ui.timeline import HAUTEUR_REGLE
    w = fenetre
    w.importer_chemins([str(medias["prores_hq"])])
    assert _attendre(lambda: len(w.projet.medias) == 1)
    w.timeline.resize(1200, 400)
    mid = next(iter(w.projet.medias))
    w.poser_medias([mid], 0, "")
    w.poser_medias([mid], 30, "")
    vue = w.timeline.vue
    vue.aimantation = False
    vue.px_par_image = 10.0
    vue.decalage_x = 0.0
    vue.resize(1000, 300)
    _, y, h = vue.lignes()[0]
    milieu = y + h // 2

    def glisser(x0, y0, x1, y1, mod=Qt.NoModifier):
        QTest.mousePress(vue, Qt.LeftButton, mod, QPoint(x0, y0))
        QTest.mouseMove(vue, QPoint(x1, y1))
        QTest.mouseRelease(vue, Qt.LeftButton, mod, QPoint(x1, y1))

    def video():
        return sorted(w.projet.sequence.pistes_video[0].clips, key=lambda c: c.debut)

    glisser(450, milieu, 400, milieu)
    a, b = video()
    assert b.debut == 25 and a.fondu_sortie == 5 and b.fondu_entree == 5, "fondu enchaîné"
    w.annuler()

    seq = w.projet.sequence
    edition.rogner(w.projet, seq, video()[0].id, "debut", 10)
    w.valider("Rognage")
    glisser(200, milieu, 250, milieu, Qt.AltModifier)
    a = video()[0]
    assert (a.debut, a.entree, a.duree) == (10, 5, 20), "slip : seul le contenu glisse"

    w.a_ripple.trigger()  # Ctrl+L, menu Montage
    assert w.timeline.b_ripple.isChecked() and w.a_ripple.isChecked()
    w.a_aimant.trigger()
    assert not w.timeline.b_aimant.isChecked()
    w.a_aimant.trigger()
    vue._choisir({video()[0].id})
    w.supprimer()
    assert [c.debut for c in video()] == [10], "le ripple referme le trou"
    w.annuler()
    w.timeline.b_ripple.setChecked(False)

    w.aller_a(15)
    w.marqueur()
    w.aller_a(0)
    w._aller_marqueur(1)
    assert w.lecture.position == 15
    w._aller_coupe(1)
    assert w.lecture.position == 30
    w._aller_coupe(-1)
    assert w.lecture.position == 10
    x = int(vue.x_de(15))
    glisser(x + 4, HAUTEUR_REGLE + 10, x + 104, HAUTEUR_REGLE + 10)
    assert w.projet.sequence.marqueurs[0].position == 25
    w.annuler()
    assert w.projet.sequence.marqueurs[0].position == 15

    w.ajouter_piste("audio")
    a1, a2 = w.projet.sequence.pistes_audio
    w.piste_exclusive(a1.id, "solo")
    assert _attendre(lambda: [p.solo for p in w.projet.sequence.pistes_audio] == [True, False], 2)


def test_boutons_de_piste_et_zoom(fenetre, medias):
    from PySide6.QtWidgets import QToolButton
    w = fenetre
    w.importer_chemins([str(medias["prores_hq"])])
    assert _attendre(lambda: len(w.projet.medias) == 1)
    w.poser_medias(list(w.projet.medias), 0, "")
    entete = w.timeline._entetes[0]
    next(b for b in entete.findChildren(QToolButton)
         if b.accessibleName().startswith("Afficher ou masquer")).click()
    assert w.projet.sequence.pistes_video[0].masquee
    _attendre(lambda: w.timeline._entetes and w.timeline._entetes[0] is not entete, 2)
    entete = w.timeline._entetes[0]
    verrou = next(b for b in entete.findChildren(QToolButton)
                  if b.accessibleName().startswith("Verrouiller"))
    verrou.click()
    assert _attendre(lambda: w.projet.sequence.pistes_video[0].verrouillee, 2)
    avant = w.timeline.vue.px_par_image
    w.timeline.zoomer(0.5)
    assert w.timeline.vue.px_par_image == avant / 2
    w.ajouter_piste("audio")
    assert len(w.projet.sequence.pistes_audio) == 2
    piste = w.projet.sequence.pistes_audio[1]
    w.deplacer_piste(piste.id, -1)
    assert w.projet.sequence.pistes_audio[0].id == piste.id


def test_pistes_creees_et_rangees(fenetre, medias):
    """Média lâché ou clip glissé au-dessus des pistes : nouvelle piste vidéo. Ajout au-dessus
    ou en dessous d'une piste, glisser d'un en-tête, couleur."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from remanence.projet.modele import Projet
    from remanence.ui.timeline import HAUTEUR_REGLE, NOUVELLE_PISTE
    w = fenetre
    w.importer_chemins([str(medias["prores_hq"])])
    assert _attendre(lambda: len(w.projet.medias) == 1)
    w.poser_medias(list(w.projet.medias), 0, "")
    seq = lambda: w.projet.sequence
    assert len(seq().pistes_video) == 1
    w.poser_medias(list(w.projet.medias), 40, NOUVELLE_PISTE)
    assert len(seq().pistes_video) == 2 and seq().pistes_video[0].clips[0].debut == 40
    # Clip de V1 glissé dans la bande au-dessus des pistes.
    vue = w.timeline.vue
    vue.px_par_image = 8
    _attendre(lambda: False, 0.2)
    bas = seq().pistes_video[1]
    clip = next(c for c in bas.clips)
    ligne = next(l for l in vue.lignes() if l[0] is bas)
    depart = QPoint(round(vue.x_de(clip.debut + 5)), ligne[1] + ligne[2] // 2)
    arrivee = QPoint(depart.x() + 16, HAUTEUR_REGLE + 6)
    QTest.mousePress(vue, Qt.LeftButton, Qt.NoModifier, depart)
    QTest.mouseMove(vue, arrivee)
    QTest.mouseRelease(vue, Qt.LeftButton, Qt.NoModifier, arrivee)
    assert _attendre(lambda: len(seq().pistes_video) == 3, 2)
    assert seq().pistes_video[0].clips and seq().pistes_video[0].clips[0].id == clip.id
    # Ajout au-dessus et en dessous d'une piste audio.
    a1 = seq().pistes_audio[0]
    w.ajouter_piste("audio", a1.id)
    assert seq().pistes_audio[1].id == a1.id
    w.ajouter_piste("audio", a1.id, dessous=True)
    assert seq().pistes_audio[1].id == a1.id and len(seq().pistes_audio) == 3
    # Glisser l'en-tête de la piste du bas sur celle du haut.
    haut, milieu, bas = seq().pistes_video
    entete = next(e for e in w.timeline._entetes if e.piste.id == bas.id)
    cible = next(l for l in vue.lignes() if l[0].id == haut.id)
    point = vue.mapToGlobal(QPoint(10, cible[1] + 4))
    QTest.mousePress(entete, Qt.LeftButton, Qt.NoModifier, QPoint(40, 6))
    QTest.mouseMove(entete, entete.mapFromGlobal(point))
    QTest.mouseRelease(entete, Qt.LeftButton, Qt.NoModifier, entete.mapFromGlobal(point))
    assert _attendre(lambda: [p.id for p in seq().pistes_video] == [bas.id, haut.id,
                                                                     milieu.id], 2)
    w.regler_piste(haut.id, "couleur", "warning")
    assert _attendre(lambda: next(p for p in seq().pistes if p.id == haut.id).couleur
                     == "warning", 2)
    relu = Projet.depuis_dict(w.projet.vers_dict())
    assert next(p for p in relu.sequence.pistes if p.id == haut.id).couleur == "warning"


def test_ecran_d_accueil(fenetre, medias, tmp_path):
    """Nouveau projet au format choisi, projets récents, fiches de prise en main."""
    from remanence.ui import accueil
    w = fenetre
    d = accueil.Accueil(w)
    assert d.format_choisi() == "auto" and not d.resolution.isEnabled()
    d.tuiles_format["9:16"].click()
    assert d.resolution.isEnabled() and d.resolution.currentData() == (1080, 1920)
    d.cadence.setCurrentIndex(d.cadence.findData("25"))
    d._creer()
    assert d.resultat == ("nouveau", 1080, 1920, "25", True)
    w.nouveau_projet(*d.resultat[1:])
    seq = w.projet.sequence
    assert (seq.largeur, seq.hauteur, seq.cadence, seq.reglee) == (1080, 1920, "25", True)
    assert seq.tc_debut == 25 * 3600, "01:00:00:00"
    w.importer_chemins([str(medias["prores_hq"])])
    assert _attendre(lambda: len(w.projet.medias) == 1)
    w.poser_medias(list(w.projet.medias), 0, "")
    assert (w.projet.sequence.largeur, w.projet.sequence.cadence) == (1080, "25"),         "le premier média ne change plus la séquence"
    projet = tmp_path / "essai.remanence"
    w.chemin = projet
    assert w.enregistrer()
    assert accueil.recents()[0][0] == projet
    d = accueil.Accueil(w)
    ligne = d.liste_recents.topLevelItem(0)
    assert ligne.text(0) == "essai" and ligne.data(0, 0x0100) == str(projet)
    assert ligne.text(1) == str(tmp_path) and ligne.text(2) == "à l'instant"
    maintenant = 1_800_000_000
    assert accueil.date_relative(maintenant - 300, maintenant) == "il y a 5 min"
    assert accueil.date_relative(maintenant - 86400 * 30, maintenant).endswith("2026")
    d._ouvrir_item(ligne)
    assert d.resultat == ("ouvrir", str(projet))
    titres = [b.text() for b in d.boutons_fiches]
    assert "Animer un effet" in titres and len(titres) >= 8
    # Une fiche s'ouvre dans la fenêtre de prise en main, à part.
    from remanence.ui.aide import FenetreAide
    d.boutons_fiches[titres.index("Animer un effet")].click()
    aide = FenetreAide._instance
    assert aide is not None and aide.isVisible() and aide.parent() is None
    assert aide.liste.currentItem().text() == "Animer un effet"
    assert "première et sa dernière image clé" in aide.lecteur.toPlainText()
    aide.close()
    assert FenetreAide.ouvrir(0) is aide and aide.liste.currentRow() == 0
    aide.close()
    from remanence.ui.aide import AIDE
    assert all((AIDE / img).exists() for img in
               ("montage.png", "transition.png", "inspecteur.png", "compression.png"))
    d.au_demarrage.setChecked(False)
    assert not accueil.au_demarrage()
    d.au_demarrage.setChecked(True)


def test_espaces_de_travail(fenetre, medias, tmp_path):
    """Changer d'espace garde la tête de lecture et la sélection ; l'export passe par la file."""
    w = fenetre
    w.importer_chemins([str(medias["prores_hq"])])
    assert _attendre(lambda: len(w.projet.medias) == 1)
    w.poser_medias(list(w.projet.medias), 0, "")
    w.aller_a(7)
    clip = w.projet.sequence.pistes_video[0].clips[0]
    w.timeline.vue._choisir({clip.id})
    for espace in ("media", "export", "montage"):
        w.choisir_espace(espace)
        assert w.barre_espaces.boutons[espace].isChecked()
        assert w.lecture.position == 7 and w.timeline.vue.selection == {clip.id}
    assert w._docks["timeline"].isVisible() and not w._docks["file_export"].isVisible()

    w.choisir_espace("export")
    assert w._docks["file_export"].isVisible() and not w._docks["medias"].isVisible()
    w.formulaire_export.fichier.setText(str(tmp_path / "file.mov"))
    w.formulaire_export.tout.setChecked(True)
    w.formulaire_export.bouton.click()
    lignes = w.file_export.findChildren(type(w.file_export.ajouter("", "", lambda: None)))
    assert _attendre(lambda: (tmp_path / "file.mov").exists() and
                     any("conforme" in l.etat.text() for l in lignes), 30)


def test_historique_et_barre_des_espaces(fenetre, medias):
    w = fenetre
    w.importer_chemins([str(medias["prores_hq"])])
    assert _attendre(lambda: len(w.projet.medias) == 1)
    w.poser_medias(list(w.projet.medias), 0, "")
    w.aller_a(10)
    w.couper()
    assert w.liste_historique.count() == 4
    w.liste_historique.aller.emit(2)
    assert len(w.projet.sequence.pistes_video[0].clips) == 1, "retour avant la coupe"
    w.liste_historique.aller.emit(3)
    assert len(w.projet.sequence.pistes_video[0].clips) == 2
    w.a_barre_espaces.trigger()
    assert not w.barre_bas.isVisibleTo(w)
    w.a_barre_espaces.trigger()
    assert w.barre_bas.isVisibleTo(w)
    assert "Sans titre" in w.barre_titre.projet.text() and "i/s" in w.barre_titre.cadence.text()


def test_moniteur_source_et_montage_depuis_la_source(fenetre, medias):
    w = fenetre
    w.importer_chemins([str(medias["prores_hq"])])
    assert _attendre(lambda: len(w.projet.medias) == 1)
    m = next(iter(w.projet.medias.values()))
    w.choisir_espace("montage")
    w.charger_source(m)
    assert w._actif == "source" and w._docks["source"].isVisible()
    assert _attendre(lambda: w.source.zone._image is not None), "la source ne s'affiche pas"
    w.aller("source", 5)
    w.point_entree()
    w.aller("source", 14)
    w.point_sortie()
    assert (w.projet.medias[m.id].point_entree, w.projet.medias[m.id].point_sortie) == (5, 15)

    w.monter_source(inserer=False)
    clips = w.projet.sequence.pistes_video[0].clips
    assert [(c.debut, c.entree, c.duree) for c in clips] == [(0, 5, 10)]
    assert w._actif == "programme" and w.lecture.position == 10
    w.aller_a(4)
    w.monter_source(inserer=True)
    clips = w.projet.sequence.pistes_video[0].clips
    assert [(c.debut, c.entree, c.duree) for c in clips] == [(0, 5, 4), (4, 5, 10), (14, 9, 6)]

    # I s'adresse au moniteur actif : ici le programme, pas la source.
    w.aller_a(2)
    w.point_entree()
    assert w.projet.sequence.point_entree == 2 and w.projet.medias[m.id].point_entree == 5

    w.poser_medias([f"{m.id}@20:25"], 40, "")
    assert any((c.debut, c.entree, c.duree) == (40, 20, 5)
               for c in w.projet.sequence.pistes_video[0].clips)


def test_double_ecran_et_programme_externe(fenetre, medias):
    w = fenetre
    w.importer_chemins([str(medias["prores_hq"])])
    assert _attendre(lambda: len(w.projet.medias) == 1)
    w.poser_medias(list(w.projet.medias), 0, "")
    w.choisir_double_ecran("timeline")
    assert w._double_ecran is not None
    assert w._docks["timeline"].parent() is w._double_ecran
    w.choisir_espace("media")
    assert w._docks["timeline"].isVisible(), "la timeline reste sur le second écran"
    w.choisir_double_ecran(None)
    assert w._double_ecran is None and w._docks["timeline"].parent() is w

    # Comme Resolve : Média, Métadonnées et Historique sur le second écran.
    w.choisir_espace("montage")
    w.choisir_double_ecran("panneaux")
    second = w._double_ecran
    assert w._docks["medias"].parent() is second
    assert w.metadonnees.window() is second and w.liste_historique.window() is second
    assert w._docks["timeline"].isVisible() and w._docks["timeline"].parent() is w
    assert w.onglets_droite.boutons[1].isHidden(), "plus d'onglet Métadonnées à droite"
    w.choisir_espace("media")
    assert w._docks["medias"].isVisible() and w._barre_espaces_2.boutons["media"].isChecked()
    w.choisir_espace("montage")
    w.choisir_double_ecran(None)
    assert _attendre(lambda: w.metadonnees.window() is w, 2)
    assert w._docks["medias"].parent() is w and not w.onglets_droite.boutons[1].isHidden()
    w.basculer_programme_externe()
    assert w._programme_externe is not None
    w.basculer_programme_externe()
    assert _attendre(lambda: w._programme_externe is None, 2)


def test_panneau_media(fenetre, medias, monkeypatch):
    from PySide6.QtCore import Qt
    w = fenetre
    p = w.medias
    p.nouveau_chutier()
    rushs = w.projet.chutiers[0]
    item = next(i for i in p.arbre.findItems("", Qt.MatchContains | Qt.MatchRecursive)
                if i.data(0, Qt.UserRole) == rushs.id)
    item.setText(0, "Rushs")
    assert w.projet.chutiers[0].nom == "Rushs"
    # Le chutier choisi reçoit les médias importés.
    w.importer_chemins([str(medias["prores_hq"]), str(medias["h264"])])
    assert _attendre(lambda: len(w.projet.medias) == 2)
    assert all(m.chutier == rushs.id for m in w.projet.medias.values())
    assert p.vue.count() == 2

    p.recherche.setText("h264")
    assert p.vue.count() == 1
    p.recherche.setText("")
    p._filtrer("audio")
    assert p.vue.count() == 0 and p.vide.text() == "Aucun résultat"
    p._filtrer("tous")

    h264 = next(m for m in w.projet.medias.values() if m.nom.startswith("h264"))
    p.ranger([h264.id], None)
    assert w.projet.medias[h264.id].chutier is None and p.vue.count() == 1

    w.poser_medias([h264.id], 0, "")
    messages = []
    monkeypatch.setattr("remanence.ui.fenetre.QMessageBox.information",
                        lambda *a: messages.append(a[2]))
    prores = next(m for m in w.projet.medias.values() if m.nom.startswith("prores"))
    w.retirer_medias([h264.id, prores.id])
    assert h264.id in w.projet.medias and prores.id not in w.projet.medias
    assert messages and "h264" in messages[0]

    p.supprimer_chutier(w.projet.chutiers[0].id)
    assert not w.projet.chutiers and p.chutier_courant is None

    p.vue_mode(False)
    assert not p.b_grille.isChecked()
    p.vue_mode(True)
    p.resize(400, 600)
    r = p.vue.visualItemRect(p.vue.item(0))
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent
    pos = QPointF(r.left() + r.width() / 4, r.center().y())
    QApplication.sendEvent(p.vue.viewport(), QMouseEvent(
        QMouseEvent.MouseMove, pos, p.vue.viewport().mapToGlobal(pos), Qt.NoButton, Qt.NoButton,
        Qt.NoModifier))
    assert p.survol is not None and p.survol[0] == h264.id and 0.1 < p.survol[1] < 0.4


def test_inspecteur_sections_repliables(fenetre, medias):
    """Sections repliables retenues d'un clip à l'autre, séquence sans sélection, remise à zéro."""
    from remanence.ui.composants import SectionRepliable
    w = fenetre
    w.importer_chemins([str(medias["prores_hq"])])
    assert _attendre(lambda: len(w.projet.medias) == 1)
    w.poser_medias(list(w.projet.medias), 0, "")
    titres = lambda: {s.titre.text(): s for s in w.inspecteur.findChildren(SectionRepliable)
                      if s.isVisibleTo(w.inspecteur)}
    assert _attendre(lambda: "Séquence" in titres(), 2)

    video = w.projet.sequence.pistes_video[0].clips[0]
    w.timeline.vue._choisir({video.id})
    assert _attendre(lambda: {"Clip", "Niveau et fondus"} <= set(titres()), 2)
    sections = titres()
    sections["Clip"].titre.click()
    assert not sections["Clip"].ouverte()
    w.timeline.vue._choisir(set())
    w.timeline.vue._choisir({video.id})
    assert _attendre(lambda: "Clip" in titres(), 2)
    assert not titres()["Clip"].ouverte(), "l'état replié est retenu"
    titres()["Clip"].titre.click()

    audio = w.projet.sequence.pistes_audio[0].clips[0]
    w.timeline.vue._choisir({video.id, audio.id})
    assert w.badge_inspecteur.text() == ""

    w.timeline.vue._choisir({video.id})
    w.inspecteur.reglage.emit(video.id, "fondu_entree", 5)
    assert _attendre(lambda: w.projet.sequence.pistes_video[0].clips[0].fondu_entree == 5, 2)
    w.inspecteur.reglage.emit(video.id, "reinitialiser", None)
    assert _attendre(lambda: w.projet.sequence.pistes_video[0].clips[0].fondu_entree == 0, 2)


def test_timecode_de_debut_au_choix(fenetre, medias):
    """Premier média posé : 01:00:00:00, celui du clip, ou un timecode saisi librement."""
    from remanence.config import reglages_interface
    from remanence.ui.dialogue_timecode import CLE_PREFERENCE, DialogueTimecode
    w = fenetre
    reglages_interface().setValue(CLE_PREFERENCE, "heure")
    try:
        w.importer_chemins([str(medias["prores_hq"])])
        assert _attendre(lambda: len(w.projet.medias) == 1)
        w.poser_medias(list(w.projet.medias), 0, "")
        seq = w.projet.sequence
        une_heure = 24 * 3600
        assert _attendre(lambda: w.projet.sequence.tc_debut == une_heure, 2)
        assert w.historique.libelles()[-1] == "Ajout à la timeline", "une seule ligne"

        seq = w.projet.sequence
        d = DialogueTimecode(seq, w._timecode_premier_clip(), False, w)
        assert d.b_heure.isChecked() and not d.retenir.isVisibleTo(d)
        d.saisie.setText("10:00:00:00")
        d.b_autre.setChecked(True)
        assert d.valeur() == 10 * une_heure
        d.saisie.setText("n'importe quoi")
        d._valider()
        assert d.erreur.isVisibleTo(d) and d.result() != DialogueTimecode.Accepted
        d.b_clip.setChecked(True)
        assert d.valeur() == w._timecode_premier_clip()
    finally:
        reglages_interface().setValue(CLE_PREFERENCE, "clip")


def test_effets_depuis_l_interface(fenetre, medias):
    """Ajouter un effet sur un clip, une piste, la séquence ; le régler, le retirer, l'annuler."""
    from remanence.effets import nouvel_effet
    from remanence.ui.composants import LigneParametre, SectionRepliable
    w = fenetre
    w.importer_chemins([str(medias["prores_hq"])])
    assert _attendre(lambda: len(w.projet.medias) == 1)
    w.poser_medias(list(w.projet.medias), 0, "")
    clip = w.projet.sequence.pistes_video[0].clips[0]
    w.timeline.vue._choisir({clip.id})
    w.ajouter_effet("clip", clip.id, [nouvel_effet("decalage_rvb", "Anaglyphe")])
    clip = w.projet.sequence.pistes_video[0].clips[0]
    assert [e.type for e in clip.effets] == ["decalage_rvb"]
    assert _attendre(lambda: "Décalage RVB" in {s.titre.text() for s in
                                                w.inspecteur.findChildren(SectionRepliable)
                                                if s.isVisibleTo(w.inspecteur)}, 2)
    force = next(l for l in w.inspecteur.findChildren(LigneParametre) if l.libelle.text() == "Force")
    force.valeur_finale.emit(12.0)
    assert _attendre(lambda: w.projet.sequence.pistes_video[0].clips[0].effets[0].params["force"]
                     == 12.0, 2)
    effet_id = w.projet.sequence.pistes_video[0].clips[0].effets[0].id
    w.reglage_effet(effet_id, "retirer", None)
    assert _attendre(lambda: not w.projet.sequence.pistes_video[0].clips[0].effets, 2)
    w.annuler()
    assert w.projet.sequence.pistes_video[0].clips[0].effets

    piste = w.projet.sequence.pistes_video[0]
    w.choisir_piste(piste.id)
    w.ajouter_effet("piste", piste.id, [nouvel_effet("scanlines")])
    assert w.projet.sequence.pistes_video[0].effets and w._piste_choisie == piste.id
    w.ajouter_effet("sequence", "", [nouvel_effet("vhs", "Cassette usée")])
    w.ajouter_clip_effet([nouvel_effet("blocs_deplaces", "Mosaïque brisée")])
    seq = w.projet.sequence
    assert seq.effets and any(c.est_effet for p in seq.pistes for c in p.clips)
    assert _attendre(lambda: w.visionneuse.zone._image is not None, 5)


def test_bibliotheque_d_effets(fenetre, medias, monkeypatch):
    """Tuiles, filtre, recherche, préréglage personnel, application et dépôt sur la timeline."""
    from PySide6.QtWidgets import QInputDialog
    from remanence.effets import prereglages as pr
    w = fenetre
    b = w.bibliotheque
    assert b.vue.count() == len(pr.fournis())
    b._filtrer("Signal")
    assert b.vue.count() == 6
    b._filtrer("")
    b.recherche.setText("cassette")
    assert b.vue.count() == 3, "les trois préréglages de Cassette VHS"
    b.recherche.setText("")
    assert b.vignette(0).width() == 256

    w.importer_chemins([str(medias["prores_hq"])])
    assert _attendre(lambda: len(w.projet.medias) == 1)
    w.poser_medias(list(w.projet.medias), 0, "")
    clip = w.projet.sequence.pistes_video[0].clips[0]
    w.timeline.vue._choisir({clip.id})
    anaglyphe = next(p for p in b.prereglages if p.nom == "Anaglyphe")
    w.appliquer_prereglage(anaglyphe, "selection")
    clip = w.projet.sequence.pistes_video[0].clips[0]
    assert [e.type for e in clip.effets] == ["decalage_rvb"]
    assert "Anaglyphe" in b.actifs, "tuile surlignée pour le clip sélectionné"

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Mon décalage", True)))
    w.enregistrer_prereglage(clip.effets)
    assert any(p.nom == "Mon décalage" and not p.fourni for p in b.prereglages)
    assert b.vue.count() == len(pr.fournis()) + 1

    piste = w.projet.sequence.pistes_video[0]
    w._prereglage_depose(anaglyphe, "vide", piste.id, 40)
    seq = w.projet.sequence
    effet = next(c for p in seq.pistes for c in p.clips if c.est_effet)
    assert effet.debut == 40
    w._prereglage_depose(anaglyphe, "clip", clip.id, 0)
    assert len(w.projet.sequence.trouver(clip.id)[1].effets) == 2
    pr.supprimer("Mon décalage")


def test_images_cles_depuis_l_inspecteur(fenetre, medias):
    from remanence.effets import nouvel_effet
    from remanence.ui.composants import BoutonCle
    w = fenetre
    w.importer_chemins([str(medias["prores_hq"])])
    assert _attendre(lambda: len(w.projet.medias) == 1)
    w.poser_medias(list(w.projet.medias), 0, "")
    clip = w.projet.sequence.pistes_video[0].clips[0]
    w.timeline.vue._choisir({clip.id})
    w.ajouter_effet("clip", clip.id, [nouvel_effet("scanlines")])
    effet_id = w.projet.sequence.pistes_video[0].clips[0].effets[0].id

    def effet():
        return w.projet.sequence.pistes_video[0].clips[0].effets[0]
    w.aller_a(2)
    w.reglage_effet(effet_id, "cle:force", None)
    assert _attendre(lambda: effet().cles.get("force") == [[2, 40, "lineaire"]], 2)
    w.aller_a(12)
    w.reglage_effet(effet_id, "force", 90.0)
    assert _attendre(lambda: len(effet().cles["force"]) == 2, 2)
    w.aller_a(7)
    assert _attendre(lambda: any(b.etat == "anime" for b in w.inspecteur.findChildren(BoutonCle)
                                 if b.isVisibleTo(w.inspecteur)), 2)
    w.aller_a(12)
    assert _attendre(lambda: any(b.etat == "cle" for b in w.inspecteur.findChildren(BoutonCle)
                                 if b.isVisibleTo(w.inspecteur)), 2)
    w.reglage_effet(effet_id, "fusion", "ecran")
    assert _attendre(lambda: effet().fusion == "ecran", 2)
    w.reglage_effet(effet_id, "interp:force", "supprimer")
    assert _attendre(lambda: "force" not in effet().cles, 2)
    w._reglage_clip(clip.id, "fusion", "produit")
    assert _attendre(lambda: w.projet.sequence.pistes_video[0].clips[0].fusion == "produit", 2)


def test_effets_ffglitch_dans_l_inspecteur(fenetre, medias, monkeypatch):
    """Vecteurs de mouvement : losanges d'images clés (le script suit l'animation) ; transfert :
    la source affichée ; sans FFglitch, l'avertissement."""
    from PySide6.QtWidgets import QLabel
    from remanence.effets import nouvel_effet
    from remanence.moteurs.codec import ffglitch
    from remanence.ui.composants import BoutonCle
    w = fenetre
    w.importer_chemins([str(medias["prores_hq"])])
    assert _attendre(lambda: len(w.projet.medias) == 1)
    w.poser_medias(list(w.projet.medias), 0, "")
    clip = w.projet.sequence.pistes_video[0].clips[0]
    w.timeline.vue._choisir({clip.id})
    w.ajouter_effet("clip", clip.id, [nouvel_effet("vecteurs"),
                                      nouvel_effet("transfert_mouvement")])
    textes = lambda: [l.text() for l in w.inspecteur.findChildren(QLabel)
                      if l.isVisibleTo(w.inspecteur)]
    assert _attendre(lambda: "aucun clip au-dessus" in textes(), 2)
    # Vecteurs : 7 réglages et l'opacité ; transfert : 2 réglages et l'opacité.
    assert _attendre(lambda: len([b for b in w.inspecteur.findChildren(BoutonCle)
                                  if b.isVisibleTo(w.inspecteur)]) == 11, 2)
    effet_id = w.projet.sequence.pistes_video[0].clips[0].effets[0].id
    w.aller_a(4)
    w.reglage_effet(effet_id, "cle:horizontal", None)
    assert _attendre(lambda: "horizontal" in
                     w.projet.sequence.pistes_video[0].clips[0].effets[0].cles, 2)
    assert _attendre(lambda: not w._prerendus, 30), "calcul en arrière-plan terminé"
    monkeypatch.setenv(ffglitch.VARIABLE, "")
    w.timeline.vue._choisir(set())
    w.timeline.vue._choisir({clip.id})
    assert _attendre(lambda: "FFglitch absent : effet sans action" in textes(), 2)


def test_l_inspecteur_ne_saute_pas_apres_un_reglage(fenetre, medias):
    """Un clic sur un losange reconstruit l'inspecteur : il reste où il était."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from remanence.effets import nouvel_effet
    from remanence.ui.composants import BoutonCle
    w = fenetre
    w.resize(1400, 700)
    w.importer_chemins([str(medias["prores_hq"])])
    assert _attendre(lambda: len(w.projet.medias) == 1)
    w.poser_medias(list(w.projet.medias), 0, "")
    clip = w.projet.sequence.pistes_video[0].clips[0]
    w.timeline.vue._choisir({clip.id})
    w.ajouter_effet("clip", clip.id, [nouvel_effet("blocs_deplaces")])
    barre = w.inspecteur._defil.verticalScrollBar()
    assert _attendre(lambda: barre.maximum() > 40, 2)
    for depart in (0, 40):
        barre.setValue(depart)
        b = [b for b in w.inspecteur.findChildren(BoutonCle) if b.isVisibleTo(w.inspecteur)][0]
        QTest.mouseClick(b, Qt.LeftButton)
        _attendre(lambda: False, 0.5)
        assert barre.value() == depart


def test_scripts_depuis_l_interface(fenetre, medias, tmp_path):
    """Import d'un dossier de scripts, script choisi dans l'inspecteur : les réglages
    suivent le script."""
    from PySide6.QtWidgets import QComboBox
    from remanence.effets import nouvel_effet
    from remanence.ui.composants import LigneParametre
    w = fenetre
    (tmp_path / "Tremblement.js").write_text("var ampleur = 4;\nfunction glitch_frame(f) {}\n",
                                             encoding="utf-8")
    w.importer_scripts(str(tmp_path))
    assert any(p.nom == "Tremblement" for p in w.bibliotheque.prereglages)
    w.importer_chemins([str(medias["prores_hq"])])
    assert _attendre(lambda: len(w.projet.medias) == 1)
    w.poser_medias(list(w.projet.medias), 0, "")
    clip = w.projet.sequence.pistes_video[0].clips[0]
    w.timeline.vue._choisir({clip.id})
    w.ajouter_effet("clip", clip.id, [nouvel_effet("script_ffglitch", "Moyenne du mouvement")])
    effet = lambda: w.projet.sequence.pistes_video[0].clips[0].effets[0]
    assert effet().params["tail_length"] == 10
    liste = lambda: next((c for c in w.inspecteur.findChildren(QComboBox)
                          if c.accessibleName() == "Script" and c.isVisibleTo(w.inspecteur)),
                         None)
    texte = lambda: liste().currentText() if liste() is not None else None
    assert _attendre(lambda: texte() == "Moyenne du mouvement", 2)
    w.reglage_effet(effet().id, "script", liste().itemData(liste().findText("Tremblement")))
    assert _attendre(lambda: effet().params == {"ampleur": 4, "blocs": 2}, 2)
    assert _attendre(lambda: any(isinstance(l, LigneParametre) and l.isVisibleTo(w.inspecteur)
                                 for l in w.inspecteur.findChildren(LigneParametre)), 2)
    assert _attendre(lambda: texte() == "Tremblement", 2)
    # Script modifié : la nouvelle valeur écrite dans le script remplace l'ancienne.
    w.reglage_effet(effet().id, "script", "var ampleur = 9;\nfunction glitch_frame(f) {}\n")
    assert _attendre(lambda: effet().params["ampleur"] == 9, 2)
    assert _attendre(lambda: texte() == "Script modifié", 2)


def test_espace_effets(fenetre, medias):
    """Espace Effets : bibliothèque en avant ; panneau Compression ouvert à la demande (clip
    choisi analysé en arrière-plan, vecteurs sur le programme, double-clic sur une image clé
    de coupe : supprimée)."""
    w = fenetre
    w.importer_chemins([str(medias["prores_hq"])])
    assert _attendre(lambda: len(w.projet.medias) == 1)
    w.poser_medias(list(w.projet.medias), 0, "")
    clip = w.projet.sequence.pistes_video[0].clips[0]
    media = w.projet.medias[clip.media_id]
    media.coupes = [12]  # un changement de plan, comme s'il avait été analysé
    w.choisir_espace("effets")
    assert not w._docks["analyse"].isVisible() and not w._docks["source"].isVisible()
    assert w.onglets_gauche.currentIndex() == 1, "la bibliothèque d'effets"
    w._docks["analyse"].show()
    assert w.panneau_datamosh.titre.text() == "Aucun clip vidéo sélectionné"
    w.timeline.vue._choisir({clip.id})
    assert _attendre(lambda: w.panneau_datamosh.bande.analyse is not None, 30)
    a = w.panneau_datamosh.bande.analyse
    assert len(a.types) == clip.duree and a.types[0] == "I" and a.types[12] == "I"
    assert "images" in w.panneau_datamosh.infos.text()
    w.aller_a(5)
    w.panneau_datamosh.bouton_vecteurs.setChecked(True)
    calque = w.visionneuse.zone.vecteurs
    assert _attendre(lambda: calque.isVisible() and calque.vecteurs is not None, 2)
    w.panneau_datamosh.cle_basculee.emit(12)
    assert _attendre(lambda: w.projet.sequence.pistes_video[0].clips[0].cles_supprimees == [12],
                     2)
    assert _attendre(lambda: 12 in w.panneau_datamosh.bande.supprimees, 30)
    w.panneau_datamosh.image_cliquee.emit(20)
    assert _attendre(lambda: w.lecture.position == clip.debut + 20, 2)
    w.choisir_espace("montage")
    assert not calque.isVisible() and not w._docks["analyse"].isVisible()


def test_panneau_courbes_et_masques_animes(fenetre, medias):
    """Courbes : onglet de la timeline ; double-clic, glisser, passage, Suppr. Masque : la
    forme s'anime depuis l'inspecteur et l'image."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from remanence.effets import nouvel_effet
    w = fenetre
    w.importer_chemins([str(medias["prores_hq"])])
    assert _attendre(lambda: len(w.projet.medias) == 1)
    w.poser_medias(list(w.projet.medias), 0, "")
    clip = w.projet.sequence.pistes_video[0].clips[0]
    w.ajouter_effet("clip", clip.id, [nouvel_effet("decalage_rvb")])
    w.timeline.vue._choisir({clip.id})
    w.timeline.b_courbes.setChecked(True)
    assert _attendre(lambda: w._docks["courbes"].isVisible(), 2)
    panneau = w.panneau_courbes
    assert panneau.liste.count() >= 2 and panneau.liste.currentRow() == 0
    g = panneau.graphe
    effet = lambda: w.projet.sequence.pistes_video[0].clips[0].effets[0]
    _attendre(lambda: False, 0.3)
    QTest.mouseDClick(g, Qt.LeftButton, Qt.NoModifier,
                      QPoint(round(g.x_de(5)), round(g.y_de(g.courbe(), 80))))
    assert _attendre(lambda: len(effet().cles.get("force", [])) == 1, 2)
    QTest.mouseDClick(g, Qt.LeftButton, Qt.NoModifier,
                      QPoint(round(g.x_de(20)), round(g.y_de(g.courbe(), 20))))
    assert _attendre(lambda: len(effet().cles.get("force", [])) == 2, 2)
    assert abs(effet().cles["force"][0][1] - 80) < 3
    # Glisser la première image clé.
    depart = QPoint(round(g.x_de(5)), round(g.y_de(g.courbe(), effet().cles["force"][0][1])))
    arrivee = QPoint(round(g.x_de(8)), round(g.y_de(g.courbe(), 50)))
    QTest.mousePress(g, Qt.LeftButton, Qt.NoModifier, depart)
    QTest.mouseMove(g, arrivee)
    QTest.mouseRelease(g, Qt.LeftButton, Qt.NoModifier, arrivee)
    assert _attendre(lambda: effet().cles["force"][0][0] == 8, 2)
    assert abs(effet().cles["force"][0][1] - 50) < 3
    g.choisie = 0
    g._passage("bezier")
    assert _attendre(lambda: effet().cles["force"][0][2] == "bezier", 2)
    assert "Passage de l'image clé" in w.historique.libelles()
    g.choisie = 0
    QTest.keyClick(g, Qt.Key_Delete)
    assert _attendre(lambda: len(effet().cles["force"]) == 1, 2)
    # Masque animé : losange de la forme, puis la forme change à un autre instant.
    w.reglage_masque(effet().id, "", "ajouter", "rectangle")
    assert _attendre(lambda: len(effet().masques) == 1, 2)
    m_id = effet().masques[0].id
    w.aller_a(2)
    w.reglage_masque(effet().id, m_id, "cle:points", None)
    assert _attendre(lambda: len(effet().masques[0].cles.get("points", [])) == 1, 2)
    w.aller_a(12)
    w.reglage_masque(effet().id, m_id, "points", [[0.5, 0.5], [0.9, 0.9]])
    assert _attendre(lambda: [k[0] for k in effet().masques[0].cles["points"]] == [2, 12], 2)
    w.aller_a(7)
    assert _attendre(lambda: w.visionneuse.zone.calque.masques
                     and w.visionneuse.zone.calque.masques[0].points[1][0] != 0.9, 2),         "le calque montre le masque à la tête de lecture"
    w.timeline.b_courbes.setChecked(False)
    assert _attendre(lambda: not w._docks["courbes"].isVisible(), 2)


def test_modulateurs_dans_le_panneau_courbes(fenetre, medias):
    from remanence.effets import nouvel_effet
    w = fenetre
    w.importer_chemins([str(medias["prores_hq"])])
    assert _attendre(lambda: len(w.projet.medias) == 1)
    w.poser_medias(list(w.projet.medias), 0, "")
    clip = w.projet.sequence.pistes_video[0].clips[0]
    effet = nouvel_effet("decalage_rvb")
    w.ajouter_effet("clip", clip.id, [effet])
    w.timeline.vue._choisir({clip.id})
    w.timeline.b_courbes.setChecked(True)
    assert _attendre(lambda: w._docks["courbes"].isVisible(), 2)
    seq = lambda: w.projet.sequence
    w.reglage_modulateur("", "ajouter", ["tempo", [effet.id, "force"]])
    assert _attendre(lambda: len(seq().modulateurs) == 1, 2)
    m = seq().modulateurs[0]
    assert m.cibles == [[effet.id, "force", 25.0]] and m.nom == "Tempo 1"
    panneau = w.panneau_courbes
    assert _attendre(lambda: panneau.liste_modulateurs.count() == 1, 2)
    panneau.liste_modulateurs.setCurrentRow(0)
    assert panneau.fiche.isVisibleTo(panneau) and panneau.graphe.modulateur is not None
    w.reglage_modulateur(m.id, "param:bpm", 90.0)
    assert _attendre(lambda: seq().modulateurs[0].params["bpm"] == 90.0, 2)
    w.reglage_modulateur(m.id, "profondeur:0", -60.0)
    assert _attendre(lambda: seq().modulateurs[0].cibles[0][2] == -60.0, 2)
    assert _attendre(lambda: panneau.graphe.modulateur is not None, 2), "il reste choisi"
    w.reglage_modulateur(m.id, "cible+", [effet.id, "opacite"])
    assert _attendre(lambda: len(seq().modulateurs[0].cibles) == 2, 2)
    w.reglage_modulateur(m.id, "cible-", 0)
    assert _attendre(lambda: seq().modulateurs[0].cibles == [[effet.id, "opacite", 25.0]], 2)
    w.annuler()
    assert _attendre(lambda: len(seq().modulateurs[0].cibles) == 2, 2), "Ctrl+Z"
    w.reglage_modulateur(seq().modulateurs[0].id, "retirer", None)
    assert _attendre(lambda: not seq().modulateurs, 2)


def test_enregistrement_midi(fenetre, medias):
    """Le premier contrôle bougé est retenu ; ses valeurs deviennent des images clés à la
    tête de lecture ; un autre contrôle est ignoré ; l'arrêt valide une action."""
    import mido
    from remanence.effets import nouvel_effet
    w = fenetre
    w.importer_chemins([str(medias["prores_hq"])])
    assert _attendre(lambda: len(w.projet.medias) == 1)
    w.poser_medias(list(w.projet.medias), 0, "")
    clip = w.projet.sequence.pistes_video[0].clips[0]
    w.ajouter_effet("clip", clip.id, [nouvel_effet("decalage_rvb")])
    w.timeline.vue._choisir({clip.id})
    w.timeline.b_courbes.setChecked(True)
    assert _attendre(lambda: w._docks["courbes"].isVisible(), 2)
    barre = w.panneau_courbes.barre_midi
    barre.actualiser_ports([])
    assert not barre.bouton.isEnabled() and barre.port.currentText() == "Aucun contrôleur"
    w.enregistrer_midi(True, "")
    effet = lambda: w.projet.sequence.pistes_video[0].clips[0].effets[0]
    for position, valeur in ((0, 0), (5, 127), (10, 64)):
        w.aller_a(clip.debut + position)
        w.enregistreur_midi.recevoir(mido.Message("control_change", control=21, value=valeur))
        w.enregistreur_midi.recevoir(mido.Message("control_change", control=7, value=99))
    assert _attendre(lambda: [k[0] for k in effet().cles.get("force", [])] == [0, 5, 10], 2)
    assert [round(k[1]) for k in effet().cles["force"]] == [0, 100, 50]
    assert barre.controle.text() == "CC 21"
    w.enregistrer_midi(False)
    assert _attendre(lambda: w.historique.libelles()[-1] == "Enregistrement MIDI", 2)


def test_suivi_du_masque_depuis_l_inspecteur(fenetre, tmp_path):
    from remanence.effets import nouvel_effet
    from tests.test_effets import carre_mobile
    w = fenetre
    w.importer_chemins([str(carre_mobile(tmp_path / "carre.mov"))])
    assert _attendre(lambda: len(w.projet.medias) == 1)
    w.poser_medias(list(w.projet.medias), 0, "")
    clip = w.projet.sequence.pistes_video[0].clips[0]
    w.ajouter_effet("clip", clip.id, [nouvel_effet("decalage_rvb")])
    effet = lambda: w.projet.sequence.pistes_video[0].clips[0].effets[0]
    w.reglage_masque(effet().id, "", "ajouter", "rectangle")
    assert _attendre(lambda: len(effet().masques) == 1, 2)
    m_id = effet().masques[0].id
    w.reglage_masque(effet().id, m_id, "points", [[20 / 320, 60 / 180], [52 / 320, 92 / 180]])
    assert _attendre(lambda: effet().masques[0].points[0][0] == 20 / 320, 2)
    w.aller_a(0)
    w.reglage_masque(effet().id, m_id, "suivre", "avant")
    assert _attendre(lambda: "Suivi du masque" in w.historique.libelles(), 30)
    cles = effet().masques[0].cles["points"]
    assert [k[0] for k in cles] == list(range(40)), "de la tête de lecture à la fin du clip"
    assert abs(cles[-1][1][0][0] * 320 - (20 + 6 * 39)) < 4, "le masque suit le carré"


def test_losanges_de_la_timeline_et_echap(fenetre, medias):
    """Clic sur un losange d'un clip : la tête y va ; le glisser déplace l'image clé.
    Échap quitte l'outil de coupe."""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtTest import QTest
    from remanence.effets import nouvel_effet, poser_cle
    w = fenetre
    w.importer_chemins([str(medias["prores_hq"])])
    assert _attendre(lambda: len(w.projet.medias) == 1)
    w.poser_medias(list(w.projet.medias), 0, "")
    clip = w.projet.sequence.pistes_video[0].clips[0]
    effet = nouvel_effet("scanlines")
    poser_cle(effet, "force", 4, 10)
    poser_cle(effet, "force", 20, 80)
    w.ajouter_effet("clip", clip.id, [effet])
    vue = w.timeline.vue
    vue.px_par_image = 12
    vue.update()
    _attendre(lambda: False, 0.3)
    x = vue.x_de(clip.debut + 4) + vue.px_par_image / 2
    y = next(y for y in range(vue.height()) if vue._sous(QPointF(x, y))[0] == "cle_effet")
    QTest.mouseClick(vue, Qt.LeftButton, Qt.NoModifier, QPoint(round(x), y))
    assert _attendre(lambda: w.lecture.position == clip.debut + 4, 2), "la tête va au losange"
    QTest.mousePress(vue, Qt.LeftButton, Qt.NoModifier, QPoint(round(x), y))
    QTest.mouseMove(vue, QPoint(round(x + 6 * vue.px_par_image), y))
    QTest.mouseRelease(vue, Qt.LeftButton, Qt.NoModifier,
                       QPoint(round(x + 6 * vue.px_par_image), y))
    cles = lambda: w.projet.sequence.pistes_video[0].clips[0].effets[0].cles["force"]
    assert _attendre(lambda: [k[0] for k in cles()] == [10, 20], 2), "image clé déplacée"
    w.timeline.choisir_outil("couper")
    vue.setFocus()
    QTest.keyClick(vue, Qt.Key_Escape)
    assert vue.outil == "selection" and w.timeline.b_selection.isChecked()


def test_masques_depuis_l_interface(fenetre, medias):
    """Ajouter un masque, le régler, le déplacer à la souris sur le programme, le retirer."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from remanence.effets import nouvel_effet
    w = fenetre
    w.importer_chemins([str(medias["prores_hq"])])
    assert _attendre(lambda: len(w.projet.medias) == 1)
    w.poser_medias(list(w.projet.medias), 0, "")
    clip = w.projet.sequence.pistes_video[0].clips[0]
    w.timeline.vue._choisir({clip.id})
    w.ajouter_effet("clip", clip.id, [nouvel_effet("vhs")])

    def effet():
        return w.projet.sequence.pistes_video[0].clips[0].effets[0]
    w.reglage_masque(effet().id, "", "ajouter", "rectangle")
    assert _attendre(lambda: len(effet().masques) == 1, 2)
    calque = w.visionneuse.zone.calque
    assert w._masques_effet == effet().id and calque.isVisible()
    m = effet().masques[0]
    w.reglage_masque(effet().id, m.id, "adoucissement", 4.0)
    assert _attendre(lambda: effet().masques[0].adoucissement == 4.0, 2)
    assert _attendre(lambda: w.visionneuse.zone._image is not None, 5)
    r = calque._rect()
    centre = QPoint(int(r.center().x()), int(r.center().y()))
    QTest.mousePress(calque, Qt.LeftButton, Qt.NoModifier, centre)
    QTest.mouseMove(calque, centre + QPoint(int(r.width() * 0.1), 0))
    QTest.mouseRelease(calque, Qt.LeftButton, Qt.NoModifier, centre + QPoint(int(r.width() * 0.1), 0))
    assert _attendre(lambda: abs(effet().masques[0].points[0][0] - 0.35) < 0.02, 2), "déplacé"
    w.reglage_masque(effet().id, effet().masques[0].id, "retirer", None)
    assert _attendre(lambda: not effet().masques and not calque.isVisible(), 2)


def test_datamosh_calcule_en_arriere_plan(fenetre, medias):
    """Un effet codec posé : le pré-rendu se calcule seul, le badge le dit, puis il est prêt."""
    from remanence.effets import nouvel_effet
    from remanence.moteurs.codec import prerendu
    w = fenetre
    w.importer_chemins([str(medias["prores_hq"])])
    assert _attendre(lambda: len(w.projet.medias) == 1)
    w.poser_medias(list(w.projet.medias), 0, "")
    clip = w.projet.sequence.pistes_video[0].clips[0]
    w.ajouter_effet("clip", clip.id, [nouvel_effet("bloom", "Fonte courte")])
    seq = w.projet.sequence
    clip = seq.pistes_video[0].clips[0]
    assert clip.id in w.timeline.vue.en_calcul or prerendu.pret(w.projet, seq, clip)
    assert _attendre(lambda: prerendu.pret(w.projet, w.projet.sequence,
                                           w.projet.sequence.pistes_video[0].clips[0]), 10)
    assert _attendre(lambda: not w.timeline.vue.en_calcul, 5)


def test_piste_des_images_cles_et_transition(fenetre, medias):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from remanence.ui.timeline import HAUT_CLES
    w = fenetre
    w.importer_chemins([str(medias["prores_hq"])])
    assert _attendre(lambda: len(w.projet.medias) == 1)
    mid = next(iter(w.projet.medias))
    assert _attendre(lambda: w.projet.medias[mid].coupes is not None, 10), "coupes analysées"
    w.poser_medias([mid], 0, "")
    w.poser_medias([mid], 30, "")
    vue = w.timeline.vue
    raccord = next(r for r in vue.reperes_cles() if r[1] == "raccord")
    assert raccord[0] == 30 and not raccord[4]
    vue.px_par_image, vue.decalage_x = 10.0, 0.0
    x = int(vue.x_de(30))
    QTest.mouseClick(vue, Qt.LeftButton, Qt.NoModifier, QPoint(x, HAUT_CLES + 9))
    b = w.projet.sequence.pistes_video[0].clips[1]
    assert b.transition is not None and b.transition.duree == 24
    assert any(r[4] for r in vue.reperes_cles() if r[1] == "raccord")
    assert len(w.historique.libelles()) > 1 and w.historique.libelles()[-1] == "Transition datamosh"
    w._reglage_clip(b.id, "transition_duree", 10.0)
    assert _attendre(lambda: w.projet.sequence.pistes_video[0].clips[1].transition.duree == 10, 2)
    w._reglage_clip(b.id, "transition_retirer", None)
    assert _attendre(lambda: w.projet.sequence.pistes_video[0].clips[1].transition is None, 2)


def test_ergonomie_presse_papiers_zoom_et_reperes(fenetre, medias):
    """Copier, coller, dupliquer, tout sélectionner ; zoom au clavier ; projets récents ;
    repère du panneau qui a le clavier ; inspecteur dans l'espace Effets."""
    w = fenetre
    w.importer_chemins([str(medias["prores_hq"])])
    assert _attendre(lambda: len(w.projet.medias) == 1)
    w.poser_medias(list(w.projet.medias), 0, "")
    seq = w.projet.sequence
    clip = seq.pistes_video[0].clips[0]
    duree = clip.duree
    w.timeline.vue._choisir({clip.id})
    w.copier()
    w.aller_a(duree + 10)
    w.coller()
    videos = seq.pistes_video[0].clips
    assert [c.debut for c in videos] == [0, duree + 10]
    assert len({c.id for c in videos}) == 2
    colle = videos[1]
    assert w.timeline.vue.selection >= {colle.id}, "les clips collés sont choisis"
    audio = [c for c in seq.pistes_audio[0].clips if c.debut == duree + 10]
    assert audio and audio[0].lien == colle.lien and colle.lien != clip.lien, \
        "le son suit, avec un lien neuf"
    w.timeline.vue._choisir({clip.id})
    w.dupliquer()
    assert [c.debut for c in seq.pistes_video[0].clips][:2] == [0, duree], "copie juste après"
    w.tout_selectionner()
    assert w.timeline.vue.selection == {c.id for _, c in seq.tous_les_clips()}
    avant = w.timeline.vue.px_par_image
    w._zoom_clavier(0.8)
    assert w.timeline.vue.px_par_image < avant
    w._remplir_recents()
    assert w._menu_recents.actions()
    w.timeline.vue.setFocus()
    assert _attendre(lambda: w.timeline.barre_outils.property("clavier") is True, 2)
    w.choisir_espace("effets")
    assert w.onglets_droite.currentIndex() == 0, "l'inspecteur dans l'espace Effets"
