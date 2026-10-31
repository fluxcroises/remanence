"""Thème sombre neutre : des gris sans teinte pour ne pas fausser le jugement des couleurs.

Rose : sélection. Cyan : états actifs (tête de lecture, focus clavier, lecture en cours).
Contrastes vérifiés : texte #e8e8e8 et #a6a6a6 au-dessus de 4,5:1 sur tous les fonds,
rose au-dessus de 3:1 sur les fonds de clip, bordures au-dessus de 3:1 sur les pistes.
"""

from PySide6.QtGui import QColor, QFont, QPalette

ROSE = "#ff3d7f"
CYAN = "#3df2ff"
FOND = "#1e1e1e"
PANNEAU = "#262626"
CHAMP = "#333333"
PISTE = "#232323"
CLIP_VIDEO = "#3a3a3a"
CLIP_AUDIO = "#323232"
BORDURE = "#6e6e6e"
TEXTE = "#e8e8e8"
TEXTE_SECONDAIRE = "#a6a6a6"
SELECTION_FOND = "#5a1f33"
ONDE = "#b4b4b4"
ENVELOPPE = "#c8c8c8"

FEUILLE = f"""
QWidget {{ color: {TEXTE}; background: {PANNEAU}; }}
QMainWindow, QMainWindow::separator {{ background: {FOND}; }}
QMainWindow::separator {{ width: 4px; height: 4px; }}
QDockWidget::title {{ background: {FOND}; padding: 4px 8px; color: {TEXTE_SECONDAIRE}; }}
QLabel[role="secondaire"] {{ color: {TEXTE_SECONDAIRE}; }}
QLabel[role="timecode"] {{ font-family: "Consolas"; font-size: 15pt; color: {TEXTE}; }}
QToolTip {{ background: {CHAMP}; color: {TEXTE}; border: 1px solid {BORDURE}; padding: 4px; }}
QPushButton, QToolButton {{
    background: {CHAMP}; border: 1px solid {BORDURE}; border-radius: 3px;
    padding: 4px 10px; min-height: 22px;
}}
QPushButton:hover, QToolButton:hover {{ background: #3d3d3d; }}
QPushButton:pressed, QToolButton:pressed {{ background: #2c2c2c; }}
QPushButton:checked, QToolButton:checked {{ border-color: {CYAN}; color: {CYAN}; }}
QPushButton:disabled, QToolButton:disabled {{ color: #8c8c8c; border-color: #4a4a4a; }}
QPushButton:default {{ border-color: {TEXTE_SECONDAIRE}; }}
QPushButton:focus, QToolButton:focus, QComboBox:focus, QLineEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QListWidget:focus, QTableWidget:focus, QRadioButton:focus,
QCheckBox:focus {{ border: 1px solid {CYAN}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {CHAMP}; border: 1px solid {BORDURE}; border-radius: 3px; padding: 3px 6px;
    selection-background-color: {SELECTION_FOND};
}}
QComboBox QAbstractItemView {{ background: {CHAMP}; selection-background-color: {SELECTION_FOND}; }}
QListWidget, QTableWidget, QTreeWidget {{
    background: {FOND}; border: 1px solid #3a3a3a; outline: 0;
}}
QListWidget::item, QTableWidget::item {{ padding: 4px; }}
QListWidget::item:selected, QTableWidget::item:selected {{
    background: {SELECTION_FOND}; border: 1px solid {ROSE}; color: {TEXTE};
}}
QListWidget::item:focus {{ border: 1px solid {CYAN}; }}
QHeaderView::section {{ background: {PANNEAU}; color: {TEXTE_SECONDAIRE}; border: 0; padding: 4px; }}
QMenuBar {{ background: {FOND}; }}
QMenuBar::item:selected, QMenu::item:selected {{ background: {SELECTION_FOND}; }}
QMenu {{ background: {PANNEAU}; border: 1px solid {BORDURE}; }}
QMenu::item:disabled {{ color: #8c8c8c; }}
QStatusBar {{ background: {FOND}; color: {TEXTE_SECONDAIRE}; }}
QProgressBar {{ background: {CHAMP}; border: 1px solid {BORDURE}; border-radius: 3px;
    text-align: center; max-height: 14px; }}
QProgressBar::chunk {{ background: {CYAN}; }}
QScrollBar {{ background: {FOND}; }}
QScrollBar::handle {{ background: #4a4a4a; border-radius: 3px; min-width: 24px; min-height: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QTabBar::tab {{ background: {FOND}; padding: 5px 12px; color: {TEXTE_SECONDAIRE}; }}
QTabBar::tab:selected {{ background: {PANNEAU}; color: {TEXTE}; }}
"""


def appliquer(app):
    app.setStyle("Fusion")
    police = QFont("Segoe UI", 9)
    app.setFont(police)
    pal = QPalette()
    for role, couleur in [
        (QPalette.Window, PANNEAU), (QPalette.WindowText, TEXTE), (QPalette.Base, FOND),
        (QPalette.AlternateBase, PANNEAU), (QPalette.Text, TEXTE), (QPalette.Button, CHAMP),
        (QPalette.ButtonText, TEXTE), (QPalette.Highlight, SELECTION_FOND),
        (QPalette.HighlightedText, TEXTE), (QPalette.ToolTipBase, CHAMP),
        (QPalette.ToolTipText, TEXTE), (QPalette.PlaceholderText, TEXTE_SECONDAIRE),
    ]:
        pal.setColor(role, QColor(couleur))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor("#8c8c8c"))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#8c8c8c"))
    app.setPalette(pal)
    app.setStyleSheet(FEUILLE)
