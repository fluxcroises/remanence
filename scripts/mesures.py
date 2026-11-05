"""Mesures des critères de la section 8 du cahier des charges.

Fabrique une vidéo UHD ProRes 422 HQ de 10 s (et son proxy) dans tests/medias, puis mesure :
l'aperçu en proxy 1/2 avec trois effets en temps réel, l'export ProRes 422 HQ avec un datamosh
codec et deux effets, le temps entre un réglage modifié et l'image à jour, et le dessin d'une
timeline de 10 pistes et 200 clips. Les réglages et le cache sont dans un dossier temporaire.

    .venv\\Scripts\\python.exe scripts\\mesures.py [aperçu export réactivité timeline superposition]
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from fractions import Fraction
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
TEMP = Path(tempfile.mkdtemp(prefix="remanence_mesures_"))
os.environ.setdefault("REMANENCE_CACHE", str(TEMP / "cache"))
os.environ.setdefault("REMANENCE_DONNEES", str(TEMP / "donnees"))

import av  # noqa: E402
import numpy as np  # noqa: E402

from remanence.effets import EFFETS, nouvel_effet  # noqa: E402
from remanence.media.proxy import chemin_proxy, generer_proxy  # noqa: E402
from remanence.media.sonde import analyser  # noqa: E402
from remanence.projet import edition  # noqa: E402
from remanence.projet.modele import Media, Projet, nouvel_id  # noqa: E402

SOURCE = RACINE / "tests" / "medias" / "mesure_uhd_prores_hq.mov"
CADENCE = Fraction(25)
N = 250


def fabriquer_source() -> Path:
    if SOURCE.exists():
        return SOURCE
    SOURCE.parent.mkdir(parents=True, exist_ok=True)
    partiel = SOURCE.with_name("partiel_" + SOURCE.name)
    g = av.filter.Graph()
    src = g.add("testsrc2", f"size=3840x2160:rate={CADENCE}")
    fmt = g.add("format", "yuv422p10le")
    puits = g.add("buffersink")
    src.link_to(fmt)
    fmt.link_to(puits)
    g.configure()
    with av.open(str(partiel), "w") as c:
        c.metadata["timecode"] = "01:00:00:00"
        v = c.add_stream("prores_ks", rate=CADENCE)
        v.width, v.height, v.pix_fmt = 3840, 2160, "yuv422p10le"
        base_temps = 1 / CADENCE
        v.time_base = base_temps
        v.codec_context.options = {"profile": "3"}
        cc = v.codec_context
        cc.color_primaries = cc.color_trc = cc.colorspace = 1
        cc.color_range = 1
        for i in range(N):
            image = puits.pull()
            image.pts, image.time_base = i, base_temps
            for p in v.encode(image):
                c.mux(p)
        for p in v.encode():
            c.mux(p)
    partiel.replace(SOURCE)
    return SOURCE


def projet_uhd(effets: list[str]) -> tuple[Projet, Media]:
    projet = Projet.nouveau()
    infos, _ = analyser(str(SOURCE))
    m = Media(nouvel_id(), str(SOURCE), infos)
    projet.medias[m.id] = m
    edition.ajouter_media(projet, projet.sequence, m, 0)
    clip = projet.sequence.pistes_video[0].clips[0]
    for cle in effets:
        d = EFFETS[cle]
        prereglage = next(iter(d.prereglages), None)
        clip.effets.append(nouvel_effet(cle, prereglage))
    return projet, m


TEMPS_REEL = ["decalage_rvb", "scanlines", "grain"]


def mesurer_apercu():
    from remanence.rendu.composition import Compositeur
    projet, m = projet_uhd(TEMPS_REEL)
    if not chemin_proxy(m.infos).exists():
        t = time.perf_counter()
        generer_proxy(m.infos)
        print(f"  proxy fabriqué en {time.perf_counter() - t:.1f} s")
    c = Compositeur(projet, apercu=True)
    try:
        c.image_apercu(projet.sequence, 0, 0.5, True)
        durees = []
        for f in range(1, 101):
            t = time.perf_counter()
            c.image_apercu(projet.sequence, f, 0.5, True)
            durees.append(time.perf_counter() - t)
    finally:
        c.fermer()
    d = np.array(durees)
    print(f"Aperçu UHD, proxy 1/2, 3 effets : {1 / d.mean():.1f} images/s "
          f"(moyenne {d.mean() * 1000:.0f} ms, pire {d.max() * 1000:.0f} ms) ; seuil 24 images/s")


def mesurer_export():
    from remanence.moteurs.codec import prerendu
    from remanence.rendu.export import exporter
    projet, _ = projet_uhd(["suppression_cles", "decalage_rvb", "scanlines"])
    prerendu.definir_projet(None)
    sortie = TEMP / "export_uhd.mov"
    t = time.perf_counter()
    rapport = exporter(projet, projet.sequence, sortie, "prores_hq")
    duree = time.perf_counter() - t
    print(f"Export UHD 10 s ProRes 422 HQ, datamosh et 2 effets : {duree:.0f} s "
          f"(conforme : {rapport.conforme}) ; seuil 180 s")


def mesurer_reactivite():
    from PySide6.QtWidgets import QApplication
    from remanence.ui.lecture import MoteurLecture
    # QApplication (et non QCoreApplication) : la mesure de la timeline suit dans le même
    # processus et en a besoin.
    app = QApplication.instance() or QApplication([])
    projet, m = projet_uhd(TEMPS_REEL)
    if not chemin_proxy(m.infos).exists():
        generer_proxy(m.infos)
    moteur = MoteurLecture()
    evenement = threading.Event()
    moteur.image_prete.connect(lambda *_: evenement.set())

    class Attente:
        def clear(self):
            evenement.clear()

        def wait(self, delai):
            # Le signal passe par la boucle d'événements de Qt : on la fait tourner.
            fin = time.perf_counter() + delai
            while not evenement.is_set() and time.perf_counter() < fin:
                app.processEvents()
                time.sleep(0.001)
    pret = Attente()
    effet = projet.sequence.pistes_video[0].clips[0].effets[0]
    cle = next(iter(effet.params))
    try:
        moteur.definir_projet(projet)
        moteur.aller_a(50)
        pret.wait(30)
        durees = []
        for i in range(20):
            effet.params[cle] = effet.params[cle] * 0.9 + 0.001 * (i + 1)
            pret.clear()
            t = time.perf_counter()
            moteur.definir_projet(projet)
            pret.wait(30)
            durees.append(time.perf_counter() - t)
    finally:
        moteur.fermer()
    d = np.array(durees)
    print(f"Réglage modifié, image à jour (UHD, 1/2) : moyenne {d.mean() * 1000:.0f} ms, "
          f"pire {d.max() * 1000:.0f} ms ; seuil 100 ms")


def mesurer_timeline():
    from PySide6.QtCore import QSettings
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(TEMP / "reglages"))
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from remanence.ui.fenetre import FenetrePrincipale
    projet, m = projet_uhd([])
    seq = projet.sequence
    for p in seq.pistes_video + seq.pistes_audio:
        p.clips.clear()
    while len(seq.pistes_video) < 6:
        edition.ajouter_piste(seq, "video")
    while len(seq.pistes_audio) < 4:
        edition.ajouter_piste(seq, "audio")
    from remanence.projet.modele import Clip
    infos, _ = analyser(str(RACINE / "tests" / "medias" / "h264_8bits_30.mp4"))
    son = Media(nouvel_id(), infos.chemin, infos)
    projet.medias[son.id] = son
    longueur = son.nb_images(seq.fraction_cadence)
    for k, piste in enumerate(seq.pistes_video):
        for i in range(20):
            edition.ajouter_media(projet, seq, m, i * 60 + k * 7, duree=50, piste=piste)
    for k, piste in enumerate(seq.pistes_audio):
        for i in range(20):
            piste.clips.append(Clip(nouvel_id(), son.id, i * 60 + k * 7, 0, longueur, None))
        piste.trier()
    nb = sum(len(p.clips) for p in seq.pistes_video + seq.pistes_audio)
    w = FenetrePrincipale()
    w.show()
    w._remplacer_projet(projet)
    w.timeline.tout_voir()
    fin = time.perf_counter() + 5
    while time.perf_counter() < fin:
        app.processEvents()
    tl, vue = w.timeline, w.timeline.vue

    def serie(action, n=60):
        durees = []
        for i in range(n):
            action(i)
            t = time.perf_counter()
            vue.repaint()
            durees.append(time.perf_counter() - t)
            app.processEvents()
        return np.array(durees)

    tout = serie(lambda i: None)
    if os.environ.get("MESURES_PROFIL"):
        import cProfile
        import pstats
        pr = cProfile.Profile()
        pr.enable()
        serie(lambda i: None, 20)
        pr.disable()
        pstats.Stats(pr).sort_stats("tottime").print_stats(15)
    tl.zoomer(8)
    defil = serie(lambda i: tl.barre_h.setValue(i * 60))
    zoom = serie(lambda i: tl.zoomer(1.05 if i < 30 else 1 / 1.05))
    for nom, d in (("tout voir", tout), ("défilement", defil), ("zoom", zoom)):
        print(f"Timeline {len(seq.pistes_video) + len(seq.pistes_audio)} pistes, {nb} clips, "
              f"{nom} : dessin moyen {d.mean() * 1000:.1f} ms, pire {d.max() * 1000:.1f} ms "
              f"(fluide sous 16 ms)")
    w.modifie = False
    w.close()
    from remanence.rendu.composition import Compositeur
    if not chemin_proxy(m.infos).exists():
        generer_proxy(m.infos)
    c = Compositeur(projet, apercu=True)
    try:
        c.image_apercu(seq, 0, 0.5, True)
        durees = []
        for f in range(1, 101):
            t = time.perf_counter()
            c.image_apercu(seq, f, 0.5, True)
            durees.append(time.perf_counter() - t)
    finally:
        c.fermer()
    d = np.array(durees)
    print(f"Lecture de cette séquence (UHD, proxy 1/2, six pistes vidéo) : "
          f"{1 / d.mean():.1f} images/s (pire {d.max() * 1000:.0f} ms) ; il faut 25 images/s")


def mesurer_superposition():
    """Pire cas de lecture : six pistes UHD semi-transparentes, toutes à composer."""
    from remanence.rendu.composition import Compositeur
    projet, m = projet_uhd([])
    seq = projet.sequence
    seq.pistes_video[0].clips.clear()
    while len(seq.pistes_video) < 6:
        edition.ajouter_piste(seq, "video")
    for piste in seq.pistes_video:
        edition.ajouter_media(projet, seq, m, 0, piste=piste)
        piste.niveau = 0.6
    if not chemin_proxy(m.infos).exists():
        generer_proxy(m.infos)
    c = Compositeur(projet, apercu=True)
    try:
        c.image_apercu(seq, 0, 0.5, True)
        durees = []
        for f in range(1, 101):
            t = time.perf_counter()
            c.image_apercu(seq, f, 0.5, True)
            durees.append(time.perf_counter() - t)
    finally:
        c.fermer()
    d = np.array(durees)
    print(f"Six pistes UHD semi-transparentes, proxy 1/2 : {1 / d.mean():.1f} images/s "
          f"(pire {d.max() * 1000:.0f} ms) ; il faut 25 images/s")


MESURES = {"aperçu": mesurer_apercu, "export": mesurer_export,
           "réactivité": mesurer_reactivite, "timeline": mesurer_timeline,
           "superposition": mesurer_superposition}

if __name__ == "__main__":
    t = time.perf_counter()
    fabriquer_source()
    print(f"Source UHD prête ({time.perf_counter() - t:.0f} s)")
    for nom in sys.argv[1:] or list(MESURES):
        MESURES[nom]()
