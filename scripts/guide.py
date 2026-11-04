"""Fabrique le guide utilisateur : remanence/ressources/guide/index.html, ouvert par Aide > Guide.

    .venv\\Scripts\\python.exe scripts\\guide.py              (captures, puis le guide)
    .venv\\Scripts\\python.exe scripts\\guide.py --sans-captures

Le guide réunit les chapitres du dossier guide (bienvenue, écran, courbes, dépannage) et les
fiches de prise en main (ressources/aide), dans l'ordre de leurs noms, plus deux parties
fabriquées ici : le catalogue des effets, avec une vignette de chaque effet rendue comme dans la
bibliothèque, et la liste des raccourcis, relevée dans les menus de la fenêtre.

Les captures demandent une vraie fenêtre (les moniteurs passent par OpenGL) : Remanence s'ouvre
quelques secondes, sur les médias de test, avec des réglages et un cache temporaires.
"""

import html
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
RESSOURCES = RACINE / "remanence" / "ressources"
GUIDE = RESSOURCES / "guide"
IMAGES = GUIDE / "images"
NB = " "

# Les fiches de prise en main viennent après l'écran ; les courbes et le dépannage à la fin.
ORDRE = ["guide/00-bienvenue.md", "guide/01-ecran.md", "aide/*", "guide/20-courbes.md",
         "catalogue", "raccourcis", "guide/90-depannage.md"]


# Captures

def attendre(app, condition=lambda: False, delai=0.4):
    fin = time.time() + delai
    while time.time() < fin:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def capture_fenetre(w):
    """La fenêtre, avec l'image de chaque moniteur collée à sa place : la capture d'une
    fenêtre ne voit pas ce qu'OpenGL dessine."""
    import numpy as np
    from PySide6.QtCore import QPoint, QRectF, Qt
    from PySide6.QtGui import QImage, QPainter
    from remanence.ui import charte
    image = w.grab()
    p = QPainter(image)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    for zone in (w.visionneuse.zone, w.source.zone):
        if not zone.isVisible() or zone._image is None:
            continue
        rvb = np.ascontiguousarray((np.clip(zone.image_affichee(), 0, 1) * 255 + 0.5)
                                   .astype(np.uint8))
        h, l = rvb.shape[:2]
        trame = QImage(rvb.data, l, h, 3 * l, QImage.Format_RGB888).copy()
        r = zone._rect_image(zone.width(), zone.height())
        coin = zone.mapTo(w, QPoint(0, 0))
        p.fillRect(QRectF(coin.x(), coin.y(), zone.width(), zone.height()),
                   charte.actuelle().c("viewer-bg"))
        p.drawImage(QRectF(coin.x() + r.x(), coin.y() + r.y(), r.width(), r.height()), trame)
    p.end()
    return image


def captures():
    os.environ["REMANENCE_DONNEES"] = tempfile.mkdtemp(prefix="remanence_guide_")
    os.environ["REMANENCE_CACHE"] = tempfile.mkdtemp(prefix="remanence_guide_")
    from PySide6.QtCore import QSettings
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, tempfile.mkdtemp())
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    from remanence.config import reglages_interface
    from remanence.effets import EFFETS, nouvel_effet
    from remanence.ui import charte
    from remanence.ui.fenetre import FenetrePrincipale
    from tests.generer_medias import generer

    charte.charger_polices()
    charte.definir("dark")
    charte.actuelle().appliquer(app)
    reglages_interface().setValue("sequence/timecode_debut", "clip")
    medias = generer()
    w = FenetrePrincipale()
    w.resize(1600, 900)
    w.show()
    w.importer_chemins([str(medias["prores_hq"]), str(medias["sans_audio_2997"])])
    attendre(app, lambda: len(w.projet.medias) == 2, 30)
    a, b = list(w.projet.medias)
    w.poser_medias([a], 0, "")
    w.poser_medias([b], w.projet.sequence.duree(), "")
    clip = w.projet.sequence.pistes_video[0].clips[0]
    w.ajouter_effet("clip", clip.id, [nouvel_effet("decalage_rvb", "Couleurs dédoublées")])
    w.timeline.tout_voir()
    w.charger_source(w.projet.medias[b])
    w.aller_a(8)
    IMAGES.mkdir(parents=True, exist_ok=True)
    for espace in ("media", "montage", "effets", "export"):
        w.choisir_espace(espace)
        if espace in ("montage", "effets"):
            clip = w.projet.sequence.pistes_video[0].clips[0]
            w.timeline.vue._choisir({clip.id})
        attendre(app, delai=2.0)
        capture_fenetre(w).save(str(IMAGES / f"espace-{espace}.png"))

    # Catalogue : la vignette du premier préréglage fourni de chaque effet.
    dossier_effets = IMAGES / "effets"
    dossier_effets.mkdir(exist_ok=True)
    biblio = w.bibliotheque
    vus = set()
    for i, p in enumerate(biblio.prereglages):
        cle = p.effets[0]["type"]
        if not p.fourni or cle in vus or len(p.effets) != 1 or EFFETS[cle].interne:
            continue
        vus.add(cle)
        biblio.vignette(i).save(str(dossier_effets / f"{cle}.png"))
        app.processEvents()

    # Raccourcis : les actions des menus qui en ont un.
    menus = []
    for action in w.barre_titre.menus.actions():
        menu = action.menu()
        if menu is None:
            continue
        lignes = []

        def parcourir(m, chemin):
            for a in m.actions():
                if a.menu() is not None:
                    parcourir(a.menu(), chemin + [a.text().replace("&", "")])
                elif not a.isSeparator() and not a.shortcut().isEmpty():
                    lignes.append([" > ".join(chemin + [a.text().replace("&", "")]),
                                   a.shortcut().toString()])
        parcourir(menu, [])
        if lignes:
            menus.append([action.text().replace("&", ""), lignes])
    (GUIDE / "raccourcis.json").write_text(json.dumps(menus, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    w.modifie = False
    w.close()


# Markdown (le sous-ensemble des fiches) vers HTML

def en_ligne(texte: str, base: str) -> str:
    t = html.escape(texte, quote=False)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)",
               lambda m: f'<img alt="{m.group(1)}" src="{base}{m.group(2)}">', t)
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', t)
    t = re.sub(r"(?<![\"=/])(https?://[^\s<)]+)", r'<a href="\1">\1</a>', t)
    return t


def markdown(texte: str, base: str, ancre: str) -> tuple[str, str]:
    """(titre, HTML) d'un chapitre ; ses titres descendent d'un niveau sous le titre du guide."""
    sortie, liste, paragraphe, titre = [], None, [], ""

    def fermer():
        nonlocal liste
        if paragraphe:
            sortie.append(f"<p>{en_ligne(' '.join(paragraphe), base)}</p>")
            paragraphe.clear()
        if liste:
            sortie.append(f"</{liste}>")
            liste = None

    for ligne in texte.splitlines():
        brute = ligne.strip()
        if not brute:
            fermer()
            continue
        m = re.match(r"(#+)\s+(.*)", brute)
        if m:
            fermer()
            niveau = len(m.group(1)) + 1
            if niveau == 2 and not titre:
                titre = m.group(2)
                sortie.append(f'<h2 id="{ancre}">{html.escape(titre)}</h2>')
            else:
                sortie.append(f"<h{niveau}>{en_ligne(m.group(2), base)}</h{niveau}>")
            continue
        m = re.match(r"(-|\d+\.)\s+(.*)", brute)
        if m:
            if paragraphe:
                sortie.append(f"<p>{en_ligne(' '.join(paragraphe), base)}</p>")
                paragraphe.clear()
            genre = "ul" if m.group(1) == "-" else "ol"
            if liste != genre:
                if liste:
                    sortie.append(f"</{liste}>")
                sortie.append(f"<{genre}>")
                liste = genre
            sortie.append(f"<li>{en_ligne(m.group(2), base)}</li>")
            continue
        if brute.startswith("!["):
            fermer()
            sortie.append(f"<figure>{en_ligne(brute, base)}</figure>")
            continue
        if liste:
            sortie[-1] = sortie[-1][:-5] + " " + en_ligne(brute, base) + "</li>"
            continue
        paragraphe.append(brute)
    fermer()
    return titre, "\n".join(sortie)


def catalogue() -> tuple[str, str]:
    from remanence.effets import EFFETS, FAMILLES
    morceaux = ['<h2 id="catalogue">Catalogue des effets</h2>',
                f"<p>Chaque effet se règle dans l'inspecteur{NB}; ses préréglages sont dans la "
                f"bibliothèque d'effets. « Temps réel »{NB}: calculé à l'image, à la lecture. "
                f"« Calculé à part »{NB}: calculé en arrière-plan, gardé en cache.</p>"]
    for famille in FAMILLES:
        effets = sorted((d for d in EFFETS.values() if d.famille == famille and not d.interne),
                        key=lambda d: d.nom)
        if not effets:
            continue
        morceaux.append(f"<h3>{html.escape(famille)}</h3>")
        morceaux.append('<div class="effets">')
        for d in effets:
            image = IMAGES / "effets" / f"{d.cle}.png"
            vignette = f'<img alt="{html.escape(d.nom)}" src="images/effets/{d.cle}.png">' \
                if image.exists() else ""
            moteur = "Calculé à part" if d.codec else "Temps réel"
            reglages = ", ".join(p.nom for p in d.parametres_pour(None)) if not d.parametres_de \
                else "les réglages du script"
            prereglages = ", ".join(d.prereglages)
            morceaux.append(
                f'<div class="effet">{vignette}<h4>{html.escape(d.nom)}</h4>'
                f'<p class="moteur">{moteur}</p>'
                f"<p>Réglages{NB}: {html.escape(reglages)}.</p>"
                + (f"<p>Préréglages{NB}: {html.escape(prereglages)}.</p>" if prereglages else "")
                + "</div>")
        morceaux.append("</div>")
    return "Catalogue des effets", "\n".join(morceaux)


def raccourcis() -> tuple[str, str]:
    fichier = GUIDE / "raccourcis.json"
    menus = json.loads(fichier.read_text(encoding="utf-8")) if fichier.exists() else []
    morceaux = ['<h2 id="raccourcis">Raccourcis clavier</h2>',
                f"<p>Ils sont aussi écrits dans les menus, à côté de chaque commande. Convention de "
                f"Vegas Pro{NB}: les flèches avancent d'une image, la molette zoome la timeline.</p>"]
    for menu, lignes in menus:
        morceaux.append(f"<h3>{html.escape(menu)}</h3><table>")
        for commande, touche in lignes:
            touches = html.escape(touche).replace("Shift", "Maj").replace("Del", "Suppr")
            morceaux.append(f"<tr><td>{html.escape(commande)}</td><td><kbd>{touches}</kbd>"
                            "</td></tr>")
        morceaux.append("</table>")
    return "Raccourcis clavier", "\n".join(morceaux)


def couleurs() -> dict:
    tokens = json.loads((RACINE / "UI" / "charte" / "tokens.json").read_text(encoding="utf-8"))
    return {t["name"]: (t["value"]["dark"] if isinstance(t["value"], dict) else t["value"])
            for t in tokens["color"]["tokens"]}


def construire():
    from remanence import __version__
    chapitres = []
    for element in ORDRE:
        if element == "catalogue":
            chapitres.append(("catalogue",) + catalogue())
        elif element == "raccourcis":
            chapitres.append(("raccourcis",) + raccourcis())
        elif element == "aide/*":
            for f in sorted((RESSOURCES / "aide").glob("*.md")):
                ancre = "aide-" + f.stem
                chapitres.append((ancre,) + markdown(f.read_text(encoding="utf-8"),
                                                     "../aide/", ancre))
        else:
            f = RESSOURCES / element
            ancre = f.stem
            chapitres.append((ancre,) + markdown(f.read_text(encoding="utf-8"), "", ancre))
    c = couleurs()
    # Les couleurs nommées d'après d'autres (alias {nom}) prennent la valeur visée.
    c = {k: (c[v[1:-1]] if v.startswith("{") else v) for k, v in c.items()}
    sommaire = "\n".join(f'<li><a href="#{a}">{html.escape(t)}</a></li>'
                         for a, t, _h in chapitres)
    corps = "\n".join(f"<section>{h}</section>" for _a, _t, h in chapitres)
    page = f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Guide de Remanence</title>
<style>
@font-face {{ font-family: "IBM Plex Sans"; src: url("../polices/IBMPlexSans-Regular.ttf"); }}
@font-face {{ font-family: "IBM Plex Sans"; font-weight: 600;
  src: url("../polices/IBMPlexSans-SemiBold.ttf"); }}
@font-face {{ font-family: "IBM Plex Mono"; src: url("../polices/IBMPlexMono-Regular.ttf"); }}
:root {{ --fond: {c['bg-app']}; --surface: {c['surface']}; --ligne: {c['line']};
  --texte: {c['ink']}; --discret: {c['ink-muted']}; --accent: {c['accent']}; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--fond); color: var(--texte);
  font: 16px/1.6 "IBM Plex Sans", "Segoe UI", sans-serif; }}
nav {{ position: fixed; top: 0; bottom: 0; left: 0; width: 260px; overflow-y: auto;
  padding: 28px 20px; background: var(--surface); border-right: 1px solid var(--ligne); }}
nav h1 {{ font-size: 20px; margin: 0 0 4px; }}
nav p {{ color: var(--discret); margin: 0 0 20px; font-size: 14px; }}
nav ol {{ padding-left: 20px; margin: 0; }}
nav li {{ margin: 6px 0; }}
nav a {{ color: var(--texte); text-decoration: none; }}
nav a:hover {{ color: var(--accent); }}
main {{ margin-left: 260px; padding: 32px 48px 80px; max-width: 1100px; }}
section {{ border-bottom: 1px solid var(--ligne); padding-bottom: 32px; }}
h2 {{ font-size: 26px; font-weight: 600; margin: 40px 0 12px; }}
h3 {{ font-size: 19px; font-weight: 600; margin: 28px 0 8px; }}
p, li {{ max-width: 72ch; }}
a {{ color: var(--accent); }}
code, kbd {{ font-family: "IBM Plex Mono", Consolas, monospace; font-size: 14px;
  background: var(--surface); border: 1px solid var(--ligne); border-radius: 4px;
  padding: 1px 5px; }}
figure {{ margin: 16px 0; }}
img {{ max-width: 100%; border: 1px solid var(--ligne); border-radius: 4px; }}
table {{ border-collapse: collapse; margin: 8px 0 16px; }}
td {{ padding: 6px 16px 6px 0; border-bottom: 1px solid var(--ligne); vertical-align: top; }}
.effets {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  gap: 16px; }}
.effet {{ background: var(--surface); border: 1px solid var(--ligne); border-radius: 6px;
  padding: 12px; }}
.effet img {{ width: 100%; border: 0; }}
.effet h4 {{ margin: 8px 0 0; font-size: 16px; }}
.effet p {{ margin: 4px 0; font-size: 14px; }}
.effet .moteur {{ color: var(--discret); }}
@media (max-width: 800px) {{ nav {{ position: static; width: auto; }}
  main {{ margin-left: 0; padding: 16px; }} }}
</style>
</head>
<body>
<nav><h1>Remanence</h1><p>Guide · version {__version__}</p><ol>
{sommaire}
</ol></nav>
<main>
{corps}
</main>
</body>
</html>
"""
    (GUIDE / "index.html").write_text(page, encoding="utf-8")
    print(f"index.html : {len(chapitres)} chapitres, {len(page) // 1024} Ko")


if __name__ == "__main__":
    if "--sans-captures" not in sys.argv:
        captures()
    construire()
