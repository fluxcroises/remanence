"""Charte graphique : tout ce qui se voit vient de UI/charte/tokens.json.

Ce module lit les tokens d'un thème, fabrique la feuille de style Qt, les polices
IBM Plex embarquées, les icônes Lucide teintées et le symbole du logo. Aucun autre
fichier de l'interface ne contient de couleur.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QIcon, QPainter, QPainterPath, QPalette,
                           QPixmap)
from PySide6.QtSvg import QSvgRenderer

RACINE = Path(__file__).resolve().parents[2]
FICHIER_TOKENS = RACINE / "UI" / "charte" / "tokens.json"
DOSSIER_LOGOS = RACINE / "UI" / "charte" / "assets" / "Logos"
RESSOURCES = Path(__file__).resolve().parents[1] / "ressources"
# Un seul thème : un logiciel de montage se travaille dans le sombre (décision de Lewis).
THEMES = {"dark": "Sombre"}
POIDS = {400: QFont.Normal, 500: QFont.Medium, 600: QFont.DemiBold}


def _px(valeur: str) -> int:
    return int(float(str(valeur).replace("px", "")))


class Charte:
    def __init__(self, theme: str = "dark", fichier: Path = FICHIER_TOKENS):
        donnees = json.loads(Path(fichier).read_text(encoding="utf-8"))
        self.theme = theme if theme in THEMES else "dark"
        bruts = {t["name"]: t["value"] for t in donnees["color"]["tokens"]}

        def resoudre(nom: str) -> str:
            v = bruts[nom]
            if isinstance(v, str) and v.startswith("{"):
                return resoudre(v.strip("{}"))
            return v[self.theme] if isinstance(v, dict) else v

        self.couleurs = {nom: resoudre(nom) for nom in bruts}
        self.mesures = {}
        for groupe in ("spacing", "radius", "size"):
            for t in donnees[groupe]["tokens"]:
                self.mesures[t["name"]] = _px(t["value"])
        familles = donnees["type"]["families"]
        self.familles = {cle: [f.strip().strip('"') for f in v.split(",")]
                         for cle, v in familles.items()}
        self.styles = {}
        for groupe in donnees["type"]["groups"]:
            for s in groupe["styles"]:
                self.styles[s["name"]] = dict(s, family=groupe["family"])

    # Accès

    def hex(self, nom: str) -> str:
        return self.couleurs[nom]

    def c(self, nom: str, alpha: float | None = None) -> QColor:
        couleur = QColor(self.couleurs[nom])
        if alpha is not None:
            couleur.setAlphaF(alpha)
        return couleur

    def px(self, nom: str) -> int:
        return self.mesures[nom]

    def famille(self, cle: str) -> str:
        """Première famille de la liste qui existe vraiment sur la machine."""
        dispo = set(QFontDatabase.families())
        for f in self.familles[cle]:
            if f in dispo:
                return f
        return self.familles[cle][0]

    def police(self, style: str, taille_px: int | None = None) -> QFont:
        s = self.styles[style]
        f = QFont(self.famille(s["family"]))
        f.setPixelSize(taille_px or _px(s["fontSize"]))
        f.setWeight(POIDS.get(int(s.get("fontWeight", 400)), QFont.Normal))
        if "letterSpacing" in s:
            em = float(s["letterSpacing"].replace("em", ""))
            f.setLetterSpacing(QFont.AbsoluteSpacing, em * f.pixelSize())
        if s.get("textTransform") == "uppercase":
            f.setCapitalization(QFont.AllUppercase)
        return f

    def css_police(self, style: str) -> str:
        s = self.styles[style]
        familles = ", ".join(f'"{f}"' for f in self.familles[s["family"]])
        return f"font-family: {familles}; font-size: {s['fontSize']}; font-weight: {s['fontWeight']};"

    # Feuille de style

    def feuille(self) -> str:
        valeurs = dict(self.couleurs)
        valeurs.update({k.replace("-", "_"): v for k, v in self.couleurs.items()})
        valeurs.update({k.replace("-", "_"): f"{v}px" for k, v in self.mesures.items()})
        valeurs["police_body"] = self.css_police("body")
        valeurs["police_label"] = self.css_police("label")
        valeurs["police_heading"] = self.css_police("heading")
        valeurs["police_title"] = self.css_police("title")
        valeurs["police_timecode"] = self.css_police("timecode")
        valeurs["police_value"] = self.css_police("value")
        valeurs["police_caption"] = self.css_police("caption")
        valeurs["dossier_icones"] = (RESSOURCES / "icones").as_posix()
        feuille = MODELE_QSS.format(**valeurs)
        reste = re.findall(r"\{[a-z_]+\}", feuille)
        if reste:
            raise ValueError(f"Tokens absents de la charte : {sorted(set(reste))}")
        return feuille

    def palette(self) -> QPalette:
        """Palette Qt tirée de la charte : les éléments que la feuille de style ne dessine pas
        (indicateurs, sélection de texte, menus natifs) restent dans le thème."""
        pal = QPalette()
        for role, token in [
            (QPalette.Window, "surface"), (QPalette.WindowText, "ink"), (QPalette.Base, "surface-raised"),
            (QPalette.AlternateBase, "surface"), (QPalette.Text, "ink"), (QPalette.Button, "surface-raised"),
            (QPalette.ButtonText, "ink"), (QPalette.Highlight, "accent-soft"),
            (QPalette.HighlightedText, "ink"), (QPalette.ToolTipBase, "surface-raised"),
            (QPalette.ToolTipText, "ink"), (QPalette.PlaceholderText, "ink-muted"),
            (QPalette.Mid, "control-border"), (QPalette.Dark, "bg-app"), (QPalette.Light, "surface-hover"),
        ]:
            pal.setColor(role, self.c(token))
        for role in (QPalette.Text, QPalette.ButtonText, QPalette.WindowText):
            pal.setColor(QPalette.Disabled, role, self.c("ink-faint"))
        return pal

    def appliquer(self, app):
        # Style natif de Windows : les lettres des menus ne se soulignent qu'avec Alt.
        app.setPalette(self.palette())
        app.setStyleSheet(self.feuille())

    # Icônes et logo

    def icone(self, nom: str, taille: int = 16) -> QIcon:
        """Icône Lucide : ink-muted au repos, ink au survol, accent quand elle est enclenchée."""
        icone = QIcon()
        for mode, etat, couleur in [(QIcon.Normal, QIcon.Off, "ink-muted"),
                                    (QIcon.Active, QIcon.Off, "ink"),
                                    (QIcon.Disabled, QIcon.Off, "ink-faint"),
                                    (QIcon.Normal, QIcon.On, "accent"),
                                    (QIcon.Active, QIcon.On, "accent"),
                                    (QIcon.Disabled, QIcon.On, "ink-faint")]:
            icone.addPixmap(pixmap_icone(nom, self.hex(couleur), taille), mode, etat)
        return icone

    def fichier_symbole(self, taille: int) -> Path:
        if taille <= 20 and self.theme == "dark":
            return DOSSIER_LOGOS / "remanence-icone-petite.svg"
        return DOSSIER_LOGOS / ("remanence-symbole.svg" if self.theme == "dark"
                                else "remanence-symbole-clair.svg")

    def symbole(self, taille: int) -> QPixmap:
        return rendre_symbole(self.fichier_symbole(taille), taille)

    def logo_editeur(self, hauteur: int) -> QPixmap | None:
        """Logo de l'association éditrice, s'il a été déposé dans les logos de la charte."""
        for nom in ("flux-croises-blanc.svg", "flux-croises-blanc.png", "flux-croises.svg",
                    "flux-croises.png"):
            fichier = DOSSIER_LOGOS / nom
            if not fichier.exists():
                continue
            if fichier.suffix == ".svg":
                rendu = QSvgRenderer(str(fichier))
                taille = rendu.defaultSize()
                largeur = round(taille.width() * hauteur / max(1, taille.height()))
                pm = QPixmap(QSize(largeur * 2, hauteur * 2))
                pm.fill(Qt.transparent)
                peintre = QPainter(pm)
                rendu.render(peintre)
                peintre.end()
                pm.setDevicePixelRatio(2.0)
                return pm
            pm = QPixmap(str(fichier)).scaledToHeight(hauteur * 2, Qt.SmoothTransformation)
            pm.setDevicePixelRatio(2.0)
            return pm
        return None

    def icone_application(self) -> QIcon:
        """Le symbole sur surface-raised, carré aux angles arrondis, symbole à 65 % du côté."""
        icone = QIcon()
        for taille in (16, 24, 32, 48, 64, 128, 256):
            pm = QPixmap(taille, taille)
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            chemin = QPainterPath()
            r = max(2.0, taille * 0.18)
            chemin.addRoundedRect(QRectF(0, 0, taille, taille), r, r)
            p.fillPath(chemin, self.c("surface-raised"))
            cote = round(taille * 0.65)
            fichier = DOSSIER_LOGOS / ("remanence-icone-petite.svg" if taille <= 20
                                       else "remanence-symbole.svg")
            p.drawPixmap((taille - cote) // 2, (taille - cote) // 2,
                         rendre_symbole(fichier, cote))
            p.end()
            icone.addPixmap(pm)
        return icone


def rendre_svg(contenu: bytes, taille: int, ratio: float = 2.0) -> QPixmap:
    rendu = QSvgRenderer(QByteArray(contenu))
    pm = QPixmap(QSize(round(taille * ratio), round(taille * ratio)))
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    rendu.render(p)
    p.end()
    pm.setDevicePixelRatio(ratio)
    return pm


def rendre_symbole(fichier: Path, taille: int, ratio: float = 2.0) -> QPixmap:
    """Symbole Tranches : disques découpés en bandes. QtSvg ignore les clipPath du fichier,
    on relit donc ses bandes et ses disques pour les peindre nous-mêmes."""
    ns = {"s": "http://www.w3.org/2000/svg"}
    racine = ET.parse(fichier).getroot()
    bandes = {}
    for cp in racine.iterfind(".//s:clipPath", ns):
        r = cp.find("s:rect", ns)
        bandes[cp.get("id")] = QRectF(*(float(r.get(k)) for k in ("x", "y", "width", "height")))
    pm = QPixmap(QSize(round(taille * ratio), round(taille * ratio)))
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    echelle = taille * ratio / 100.0
    p.scale(echelle, echelle)
    for cercle in racine.iterfind("s:circle", ns):
        cx, cy, r = (float(cercle.get(k)) for k in ("cx", "cy", "r"))
        disque = QPainterPath()
        disque.addEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
        bande = QPainterPath()
        bande.addRect(bandes[re.search(r"#([^)]+)", cercle.get("clip-path")).group(1)])
        couleur = QColor(cercle.get("fill"))
        if cercle.get("fill-opacity"):
            couleur.setAlphaF(float(cercle.get("fill-opacity")))
        p.fillPath(disque.intersected(bande), couleur)
    p.end()
    pm.setDevicePixelRatio(ratio)
    return pm


@lru_cache(maxsize=512)
def pixmap_icone(nom: str, couleur: str, taille: int) -> QPixmap:
    svg = (RESSOURCES / "icones" / f"{nom}.svg").read_text(encoding="utf-8")
    # Trait de 1,5 px demandé par la charte, à la couleur du rôle.
    svg = svg.replace("currentColor", couleur).replace('stroke-width="2"', 'stroke-width="1.5"')
    return rendre_svg(svg.encode("utf-8"), taille)


def charger_polices() -> list[str]:
    familles = []
    for f in sorted((RESSOURCES / "polices").glob("*.ttf")):
        ident = QFontDatabase.addApplicationFont(str(f))
        if ident >= 0:
            familles += QFontDatabase.applicationFontFamilies(ident)
    return sorted(set(familles))


_actuelle: Charte | None = None


def actuelle() -> Charte:
    global _actuelle
    if _actuelle is None:
        _actuelle = Charte()
    return _actuelle


def definir(theme: str) -> Charte:
    global _actuelle
    _actuelle = Charte(theme)
    pixmap_icone.cache_clear()
    return _actuelle


def texte_timecode(tc: str, charte: Charte) -> str:
    """Timecode en texte riche : les images en accent, comme sur la tête de lecture."""
    debut, images = tc[:-2], tc[-2:]
    return f'{debut}<span style="color:{charte.hex("accent")}">{images}</span>'


# Les noms entre accolades sont des tokens de la charte ; {{ et }} sont des accolades QSS.
MODELE_QSS = """
* {{ {police_body} }}
QWidget {{ color: {ink}; background: transparent; }}
QMainWindow, QMainWindow > QWidget {{ background: {bg_app}; }}
QMainWindow::separator {{ background: {bg_app}; width: 3px; height: 3px; }}
QMainWindow::separator:hover {{ background: {line}; }}
QDockWidget > QWidget, QDialog, QMessageBox {{ background: {surface}; }}
QDockWidget {{ color: {ink}; }}
QToolTip {{ background: {surface_raised}; color: {ink}; border: 1px solid {line};
    padding: {space_1} {space_2}; }}

QLabel[role="secondaire"] {{ color: {ink_muted}; }}
QLabel[role="libelle"] {{ color: {ink_muted}; {police_label} }}
QLabel[role="titre"] {{ {police_heading} }}
QLabel[role="dialogue"] {{ {police_title} }}
QLabel[role="section"] {{ color: {ink_muted}; }}
QLabel[role="valeur"] {{ {police_value} color: {ink}; }}
QLabel[role="etat"] {{ {police_value} color: {ink_muted}; }}
QLabel[role="badge"] {{ color: {ink_muted}; background: {surface_raised};
    border-radius: {radius_xs}; padding: 0 6px; }}
QLabel[role="badge-accent"] {{ color: {accent}; background: {accent_soft};
    border-radius: {radius_xs}; padding: 0 6px; }}
QLabel[role="succes"] {{ color: {success}; background: {surface_raised}; }}
QLabel[role="avertissement"] {{ color: {warning}; }}
QLabel[role="erreur"] {{ color: {danger}; }}

QWidget[role="entete"] {{ background: {surface}; border-bottom: 1px solid {line}; }}
QWidget[role="barre-haut"] {{ background: {bg_app}; border-bottom: 1px solid {line}; }}
QWidget[role="barre-bas"] {{ background: {bg_app}; border-top: 1px solid {line}; }}
QWidget[role="onglets"] {{ background: {surface}; border-bottom: 1px solid {line}; }}
QLabel[role="info"] {{ color: {ink_muted}; {police_label} }}
QLabel[role="info-valeur"] {{ color: {ink_muted}; {police_value} }}
QToolButton[variante="fenetre"] {{ background: transparent; border: 0; border-radius: 0;
    min-width: 44px; max-width: 44px; min-height: 36px; max-height: 36px; padding: 0; }}
QToolButton[variante="fenetre"]:hover {{ background: {surface_hover}; }}
QToolButton[variante="fenetre-fermer"] {{ background: transparent; border: 0; border-radius: 0;
    min-width: 44px; max-width: 44px; min-height: 36px; max-height: 36px; padding: 0; }}
QToolButton[variante="fenetre-fermer"]:hover {{ background: {danger}; }}
QToolButton[variante="espace"] {{ background: transparent; border: 0; border-radius: 0;
    border-bottom: 2px solid transparent; color: {ink_muted}; padding: 0 14px;
    min-height: 34px; max-height: 34px; }}
QToolButton[variante="espace"]:hover {{ color: {ink}; }}
QToolButton[variante="espace"]:checked {{ color: {ink}; border-bottom: 2px solid {accent}; }}
QToolButton[variante="onglet"] {{ background: transparent; border: 0; border-radius: 0;
    border-bottom: 2px solid transparent; color: {ink_muted}; padding: 0 12px;
    min-height: 34px; max-height: 34px; }}
QToolButton[variante="onglet"]:hover {{ color: {ink}; }}
QToolButton[variante="onglet"]:checked {{ color: {ink}; font-weight: 500;
    border-bottom: 2px solid {accent}; }}
QWidget[role="panneau"] {{ background: {surface}; }}
QWidget[role="pied"] {{ background: {surface}; border-top: 1px solid {line}; }}
QWidget[role="entete-piste"] {{ background: {surface_raised}; border-bottom: 1px solid {line}; }}
QWidget[role="noir"] {{ background: {viewer_bg}; }}
QWidget[role="filet"] {{ background: {line}; }}
QWidget[role="filet-video"] {{ background: {clip_video}; }}
QWidget[role="filet-audio"] {{ background: {clip_audio}; }}
QDoubleSpinBox[variante="compact"] {{ background: transparent; border: 1px solid transparent;
    color: {ink_muted}; min-height: 22px; max-height: 22px; padding: 0 2px; {police_value} }}
QDoubleSpinBox[variante="compact"]:hover {{ border-color: {control_border}; }}
QToolBar {{ background: {bg_app}; border: 0; border-top: 1px solid {line}; padding: 0; spacing: 0; }}

QPushButton, QToolButton {{
    background: {surface_raised}; color: {ink}; border: 1px solid {control_border};
    border-radius: {radius_sm}; padding: 0 {space_2}; min-height: {control_h};
    max-height: {control_h};
}}
QPushButton:hover, QToolButton:hover {{ background: {surface_hover}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {surface_hover}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {ink_faint}; border-color: {line}; }}
QPushButton[variante="principal"] {{ background: {accent}; color: {on_accent};
    border: 1px solid {accent}; font-weight: 600; padding: 0 14px; }}
QPushButton[variante="principal"]:hover {{ background: {accent}; }}
QToolButton[variante="discret"], QPushButton[variante="discret"] {{
    background: transparent; border: 1px solid transparent; color: {ink_muted};
    padding: 0 {space_1}; }}
QToolButton[variante="discret"]:hover, QPushButton[variante="discret"]:hover {{
    background: {surface_hover}; color: {ink}; }}
QToolButton[variante="discret"]:checked {{ background: {accent_soft}; color: {accent}; }}
QToolButton[variante="lecture"] {{ background: {surface_hover}; border: 1px solid transparent;
    min-height: 32px; max-height: 32px; }}
QToolButton[variante="badge"] {{ background: {surface_raised}; border: 1px solid transparent;
    color: {ink_muted}; {police_label} min-height: 22px; max-height: 22px; padding: 0 {space_2}; }}
QToolButton[variante="badge"]::menu-indicator {{ image: none; width: 0; }}
QToolButton[variante="badge"]:hover {{ background: {surface_hover}; color: {ink}; }}
QToolButton[variante="panneau"]:checked {{ background: {surface_raised}; color: {ink}; }}
QToolButton[variante="panneau"] {{ background: transparent; border: 1px solid transparent;
    color: {ink_muted}; }}
QToolButton[variante="panneau"]:hover {{ background: {surface_hover}; color: {ink}; }}
QToolButton[variante="lettre"] {{ background: transparent; border: 1px solid transparent;
    color: {ink_muted}; font-weight: 600; padding: 0; min-width: 22px; max-width: 22px;
    min-height: 22px; max-height: 22px; }}
QToolButton[variante="lettre"]:hover {{ background: {surface_hover}; color: {ink}; }}
QToolButton[variante="lettre"]:checked {{ background: {accent_soft}; color: {accent}; }}
QPushButton[variante="onglet"], QToolButton[variante="onglet"] {{
    background: transparent; border: 0; border-radius: 0; color: {ink_muted};
    padding: 0 16px; }}
QPushButton[variante="onglet"]:checked, QToolButton[variante="onglet"]:checked {{
    color: {ink}; font-weight: 600; border-bottom: 2px solid {accent}; }}
QPushButton[variante="onglet"]:hover, QToolButton[variante="onglet"]:hover {{ color: {ink}; }}

QPushButton:focus, QToolButton:focus, QComboBox:focus, QLineEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QListWidget:focus, QTableWidget:focus, QTextBrowser:focus,
QRadioButton:focus, QCheckBox:focus, QSlider:focus {{ border: 2px solid {focus}; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {surface_raised}; color: {ink}; border: 1px solid {control_border};
    border-radius: {radius_sm}; padding: 0 {space_2}; min-height: {control_h};
    selection-background-color: {accent_soft}; selection-color: {ink};
}}
QSpinBox, QDoubleSpinBox {{ {police_value} }}
QLineEdit[role="timecode"] {{ {police_timecode} }}
QComboBox QAbstractItemView {{ background: {surface_raised}; border: 1px solid {line};
    selection-background-color: {accent_soft}; selection-color: {ink}; }}
QComboBox::drop-down {{ border: 0; width: 20px; }}
QComboBox::down-arrow {{ image: url({dossier_icones}/chevron-down.svg); width: 12px; height: 12px; }}

QSlider::groove:horizontal {{ height: 4px; background: {line}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ height: 4px; background: {ink_muted}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {ink}; width: 10px; height: 10px; margin: -3px 0;
    border-radius: 5px; }}
QSlider {{ min-height: 16px; border: 2px solid transparent; }}

QListWidget, QTableWidget, QTextBrowser, QScrollArea {{
    background: {surface}; color: {ink}; border: 0; outline: 0; }}
QListWidget::item {{ padding: {space_1}; border-radius: {radius_xs}; }}
QListWidget::item:hover {{ background: {surface_hover}; }}
QListWidget::item:selected, QTableWidget::item:selected {{
    background: {accent_soft}; color: {ink}; }}
QHeaderView::section {{ background: {surface}; color: {ink_muted}; border: 0;
    border-bottom: 1px solid {line}; padding: {space_1} {space_2}; {police_caption} }}
QTableWidget {{ gridline-color: {line}; }}

QMenuBar {{ background: transparent; color: {ink}; min-height: 36px; max-height: 36px;
    padding: 0; spacing: 0; }}
QMenuBar::item {{ padding: 0 9px; margin: 0; background: transparent; }}
QMenuBar::item:selected {{ background: {surface_hover}; color: {ink}; border-radius: {radius_sm}; }}
QMenu {{ background: {surface_raised}; border: 1px solid {line}; border-radius: {radius_md};
    padding: {space_1}; }}
QMenu::item {{ padding: 5px 24px 5px 12px; border-radius: {radius_sm}; color: {ink}; }}
QMenu::item:selected {{ background: {surface_hover}; }}
QMenu::item:disabled {{ color: {ink_faint}; }}
QMenu::separator {{ height: 1px; background: {line}; margin: {space_1} 0; }}

QStatusBar {{ background: {bg_app}; color: {ink_muted}; border-top: 1px solid {line}; }}
QStatusBar::item {{ border: 0; }}
QProgressBar {{ background: {line}; border: 0; border-radius: 1px; max-height: 3px;
    min-height: 3px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 1px; }}

QScrollBar {{ background: {surface}; border: 0; }}
QScrollBar:horizontal {{ height: 10px; }}
QScrollBar:vertical {{ width: 10px; }}
QScrollBar::handle {{ background: {surface_hover}; border-radius: {radius_sm}; min-width: 24px;
    min-height: 24px; margin: 2px; }}
QScrollBar::handle:hover {{ background: {control_border}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    width: 0; height: 0; background: transparent; }}

QRadioButton, QCheckBox {{ spacing: {space_2}; border: 2px solid transparent; }}
QRadioButton::indicator, QCheckBox::indicator {{ width: 12px; height: 12px;
    border: 1px solid {control_border}; background: {surface_raised}; }}
QRadioButton::indicator {{ border-radius: 7px; }}
QCheckBox::indicator {{ border-radius: {radius_xs}; }}
QRadioButton::indicator:checked, QCheckBox::indicator:checked {{ background: {accent};
    border-color: {accent}; }}
QRadioButton::indicator:disabled, QCheckBox::indicator:disabled {{ border-color: {line}; }}
QDialogButtonBox QPushButton {{ min-width: 96px; }}
"""
