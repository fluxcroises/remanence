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
    w.basculer_double_ecran(True)
    assert w._double_ecran is not None
    assert w._docks["timeline"].parent() is w._double_ecran
    w.choisir_espace("media")
    assert w._docks["timeline"].isVisible(), "la timeline reste sur le second écran"
    w.basculer_double_ecran(False)
    assert w._double_ecran is None and w._docks["timeline"].parent() is w
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
    assert p.vue.count() == 0 and "correspond" in p.vide.text()
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
    assert "Séquence" in titres()

    video = w.projet.sequence.pistes_video[0].clips[0]
    w.timeline.vue._choisir({video.id})
    sections = titres()
    assert {"Clip", "Niveau et fondus"} <= set(sections)
    sections["Clip"].titre.click()
    assert not sections["Clip"].ouverte()
    w.timeline.vue._choisir(set())
    w.timeline.vue._choisir({video.id})
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
