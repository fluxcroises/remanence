"""Remanence.exe --diagnostic : vérifie que le programme construit a tout ce qu'il lui faut,
l'écrit au journal et dans diagnostic.txt (à côté du journal), puis se ferme.

Chaque ligne dit « ok » ou ce qui manque : effets chargés, ressources, formats d'échange,
traductions de Qt, FFmpeg et ses codecs, carte graphique, FFglitch.
"""

from __future__ import annotations

import traceback


def lignes() -> list[tuple[str, bool, str]]:
    """(vérification, réussie, détail)."""
    resultats = []

    def verifier(nom, fonction):
        try:
            detail = fonction()
            resultats.append((nom, True, str(detail)))
        except Exception as e:  # chaque échec est noté, le diagnostic continue
            resultats.append((nom, False, f"{e}\n{traceback.format_exc(limit=3)}"))

    def effets():
        from remanence.effets import EFFETS
        visibles = [d for d in EFFETS.values() if not d.interne]
        if len(visibles) < 20:
            raise RuntimeError(f"seulement {len(visibles)} effets")
        return f"{len(visibles)} effets"

    def ressources():
        from remanence.ui import aide, charte
        polices = charte.charger_polices()
        if not charte.FICHIER_TOKENS.exists() or not aide.fiches():
            raise RuntimeError("charte ou fiches d'aide introuvables")
        if not (charte.RESSOURCES / "guide" / "index.html").exists():
            raise RuntimeError("guide introuvable")
        return f"{len(polices)} polices, {len(aide.fiches())} fiches, guide"

    def echanges():
        import opentimelineio as otio
        noms = otio.adapters.available_adapter_names()
        manquants = {"cmx_3600", "fcp_xml"} - set(noms)
        if manquants:
            raise RuntimeError(f"formats absents : {', '.join(sorted(manquants))}")
        return "EDL et FCP XML"

    def traductions():
        from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
        t = QTranslator()
        if not t.load(QLocale(QLocale.French), "qtbase", "_",
                      QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
            raise RuntimeError("qtbase_fr introuvable")
        return "qtbase_fr"

    def ffmpeg():
        import av
        for codec in ("prores_ks", "libx264", "libx265", "ffv1", "mpeg4", "exr", "png"):
            av.codec.Codec(codec, "w")
        return f"FFmpeg {av.ffmpeg_version_info}"

    def carte():
        from remanence.rendu.gpu import RenduGPU
        g = RenduGPU()
        try:
            return g.ctx.info.get("GL_RENDERER", "?")
        finally:
            g.fermer()

    def interface():
        # La fenêtre est construite sans être montrée ni fermée, avec des réglages dans un
        # dossier temporaire : les dispositions de l'utilisateur ne bougent pas.
        import tempfile
        from PySide6.QtCore import QSettings
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, tempfile.mkdtemp())
        from remanence.ui.fenetre import FenetrePrincipale
        f = FenetrePrincipale()
        menus = len(f.barre_titre.menus.actions())
        f.lecture.fermer()
        f.deleteLater()
        return f"fenêtre principale, {menus} menus"

    def montage():
        """Le parcours complet, dans un dossier temporaire : une vidéo fabriquée, un projet
        avec un effet, enregistré puis rouvert, exporté et vérifié."""
        import shutil
        import tempfile
        from fractions import Fraction
        from pathlib import Path
        import av
        import numpy as np
        from remanence.effets import nouvel_effet
        from remanence.media.sonde import analyser
        from remanence.projet import edition, serialisation
        from remanence.projet.modele import Media, Projet, nouvel_id
        from remanence.rendu.export import exporter
        dossier = Path(tempfile.mkdtemp(prefix="remanence_diagnostic_"))
        source = dossier / "essai.mov"
        with av.open(str(source), "w") as sortie:
            flux = sortie.add_stream("prores_ks", rate=Fraction(25))
            flux.width, flux.height, flux.pix_fmt = 320, 180, "yuv422p10le"
            for i in range(25):
                x = np.linspace(0, 1, 320, dtype=np.float32)[None, :, None]
                image = np.broadcast_to(((x + i / 25) % 1) * 255, (180, 320, 3))
                trame = av.VideoFrame.from_ndarray(image.astype(np.uint8), format="rgb24")
                trame.pts = i
                for paquet in flux.encode(trame):
                    sortie.mux(paquet)
            for paquet in flux.encode():
                sortie.mux(paquet)
        projet = Projet.nouveau()
        infos, _ = analyser(str(source))
        media = Media(nouvel_id(), str(source), infos)
        projet.medias[media.id] = media
        edition.ajouter_media(projet, projet.sequence, media, 0)
        clip = projet.sequence.pistes_video[0].clips[0]
        clip.effets.append(nouvel_effet("decalage_rvb"))
        try:
            fichier = dossier / "essai.remanence"
            serialisation.enregistrer(projet, fichier)
            projet = serialisation.ouvrir(fichier)
            rapport = exporter(projet, projet.sequence, dossier / "export.mov", "prores_hq")
            if not rapport.conforme:
                raise RuntimeError("export non conforme")
            return f"{rapport.images_calculees} images calculées, export conforme"
        finally:
            shutil.rmtree(dossier, ignore_errors=True)

    def ffglitch_():
        from remanence.moteurs.codec import ffglitch
        d = ffglitch.dossier()
        return str(d) if d else "absent (moteur de secours)"

    for nom, fonction in (("Effets", effets), ("Ressources", ressources),
                          ("Échanges", echanges), ("Traductions", traductions),
                          ("FFmpeg", ffmpeg), ("Carte graphique", carte),
                          ("Interface", interface), ("Montage et export", montage),
                          ("FFglitch", ffglitch_)):
        verifier(nom, fonction)
    return resultats


def lancer() -> int:
    from remanence import journal
    resultats = lignes()
    texte = "\n".join(f"{'ok' if ok else 'ÉCHEC'} · {nom} : {detail}"
                      for nom, ok, detail in resultats)
    journal.info("Diagnostic\n" + texte)
    try:
        (journal.dossier() / "diagnostic.txt").write_text(texte + "\n", encoding="utf-8")
    except OSError:
        pass
    return 0 if all(ok for _, ok, _ in resultats) else 1
