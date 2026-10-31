"""Point d'entrée : python -m remanence [projet.remanence]"""

import sys
import time
import traceback

from PySide6.QtCore import QSettings, Qt
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
    debut = time.perf_counter()

    from remanence.ui import charte
    charte.charger_polices()
    charte.definir(QSettings("Remanence", "Remanence").value("theme", "dark"))
    app.setStyleSheet(charte.actuelle().feuille())
    app.setWindowIcon(charte.actuelle().icone_application())

    from remanence.ui.demarrage import EcranDemarrage
    ecran = EcranDemarrage()
    ecran.show()
    ecran.etape("Chargement des polices et de la charte…", 0.2)

    ecran.etape("Démarrage du moteur vidéo (FFmpeg)…", 0.45)
    import av  # noqa: F401  (charge les bibliothèques FFmpeg pendant que l'écran est affiché)
    from remanence.ui.erreurs import afficher_erreur
    from remanence.ui.fenetre import FenetrePrincipale

    ecran.etape("Préparation de l'interface…", 0.75)
    fenetre = FenetrePrincipale()

    def erreur_imprevue(type_, valeur, tb):
        detail = "".join(traceback.format_exception(type_, valeur, tb))
        afficher_erreur(fenetre, "Erreur inattendue",
                        "Remanence a rencontré une erreur imprévue. Votre projet n'est pas perdu : "
                        "enregistrez-le, puis signalez le problème avec le bouton Copier le détail.",
                        detail)
    sys.excepthook = erreur_imprevue

    if len(sys.argv) > 1 and sys.argv[1].endswith(".remanence"):
        ecran.etape("Ouverture du projet…", 0.9)
        fenetre.ouvrir(sys.argv[1])
    ecran.etape("Prêt", 1.0)
    # Laisse l'écran lisible au moins une seconde, même sur une machine rapide.
    while time.perf_counter() - debut < 1.0:
        app.processEvents()
        time.sleep(0.02)
    fenetre.show()
    ecran.close()
    return app.exec()


if __name__ == "__main__":
    sys.exit(principal())
