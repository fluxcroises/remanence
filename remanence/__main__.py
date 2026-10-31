"""Point d'entrée : python -m remanence [projet.remanence]"""

import sys
import traceback

from PySide6.QtCore import Qt
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

    from remanence.ui import theme
    from remanence.ui.erreurs import afficher_erreur
    from remanence.ui.fenetre import FenetrePrincipale

    theme.appliquer(app)
    fenetre = FenetrePrincipale()

    def erreur_imprevue(type_, valeur, tb):
        detail = "".join(traceback.format_exception(type_, valeur, tb))
        afficher_erreur(fenetre, "Erreur inattendue",
                        "Remanence a rencontré une erreur imprévue. Votre projet n'est pas perdu : "
                        "enregistrez-le, puis signalez le problème avec le bouton Copier le détail.",
                        detail)
    sys.excepthook = erreur_imprevue

    fenetre.show()
    if len(sys.argv) > 1 and sys.argv[1].endswith(".remanence"):
        fenetre.ouvrir(sys.argv[1])
    return app.exec()


if __name__ == "__main__":
    sys.exit(principal())
