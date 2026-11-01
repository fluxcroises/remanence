"""Point d'entrée : python -m remanence [projet.remanence]"""

import sys
import time
import traceback

from PySide6.QtCore import QLibraryInfo, QLocale, Qt, QTimer, QTranslator
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication


def principal() -> int:
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    QSurfaceFormat.setDefaultFormat(fmt)
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("Remanence")
    app.setOrganizationName("Remanence")
    QLocale.setDefault(QLocale(QLocale.French, QLocale.France))
    traduction = QTranslator(app)
    if traduction.load(QLocale(QLocale.French), "qtbase", "_",
                       QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(traduction)
    debut = time.perf_counter()

    from remanence.ui import charte
    charte.charger_polices()
    charte.definir("dark")
    charte.actuelle().appliquer(app)
    app.setWindowIcon(charte.actuelle().icone_application())

    from remanence.ui.demarrage import EcranDemarrage
    ecran = EcranDemarrage()
    ecran.show()
    ecran.etape("Chargement des polices et de la charte…")

    ecran.etape("Démarrage du moteur vidéo (FFmpeg)…")
    import av  # noqa: F401  (charge les bibliothèques FFmpeg pendant que l'écran est affiché)
    from remanence.ui.erreurs import afficher_erreur
    from remanence.ui.fenetre import FenetrePrincipale

    ecran.etape("Préparation de l'interface…")
    fenetre = FenetrePrincipale()

    def erreur_imprevue(type_, valeur, tb):
        detail = "".join(traceback.format_exception(type_, valeur, tb))
        afficher_erreur(fenetre, "Erreur inattendue",
                        "Erreur imprévue. Le projet n'est pas perdu : enregistrez-le.",
                        detail)
    sys.excepthook = erreur_imprevue

    ecran.etape("Prêt")
    # Laisse l'écran lisible au moins une seconde, même sur une machine rapide.
    while time.perf_counter() - debut < 1.0:
        app.processEvents()
        time.sleep(0.02)
    # Toujours en plein écran au lancement, comme les logiciels de montage (demande de Lewis).
    fenetre.showMaximized()
    QTimer.singleShot(0, fenetre.focus_initial)
    ecran.close()
    if len(sys.argv) > 1 and sys.argv[1].endswith(".remanence"):
        # Après l'écran de démarrage : une question (sauvegarde automatique plus récente) ne
        # doit pas rester cachée derrière lui.
        QTimer.singleShot(0, lambda: fenetre.ouvrir(sys.argv[1]))
    return app.exec()


if __name__ == "__main__":
    sys.exit(principal())
