# Remanence

Logiciel Windows de montage vidéo orienté datamosh et glitch art, dans l'esprit de Vegas Pro (Python, PySide6, PyAV, OpenGL, FFglitch).

## À lire avant tout

- `CAHIER_DES_CHARGES.md` : le besoin complet. La section 7 fixe l'ordre de développement, en six étapes. (Celui de `prototype/` concerne le prototype Bavure.)
- `UI/charte/README.md` et `UI/charte/tokens.json` : la charte graphique (couleurs des thèmes sombre et clair, typographie IBM Plex, espacements, arrondis). Les fiches de `UI/charte/components/` décrivent chaque composant d'interface ; les fichiers `preview.html` sont des références visuelles, à reproduire en widgets Qt. Les logos sont dans `UI/charte/assets/Logos/`.
- `UI/maquettes/` : maquettes validées de l'écran principal et de l'écran de démarrage (à lire comme références visuelles, couleur d'accent : mauve). L'interface s'inspire de Vegas Pro (en-têtes de pistes, enveloppes sous les pistes, badge fx sur les clips) et de DaVinci Resolve (interface plate, vue d'ensemble de la séquence, inspecteur à droite, espaces de travail en bas).
- `prototype/` : le prototype Bavure (tkinter). Ses algorithmes de datamosh (`moteur_mosh.py`) et ses effets (`effets.py`) sont validés et réutilisables ; son interface ne l'est pas.

## Éditeur

- Remanence est édité par l'association de Lewis, Flux Croisés (`EDITEUR` dans `remanence/__init__.py`) : mentionné sur l'écran de démarrage et dans À propos. Son logo, blanc sur fond transparent, est `UI/charte/assets/Logos/flux-croises-blanc.png` (fourni par Lewis le 1er novembre 2026) ; sans ce fichier, le nom est écrit en texte.
- Écran de démarrage volontairement sobre, comme celui d'After Effects : symbole et nom centrés l'un sur l'autre, sans sous-titre, ligne de chargement, « © 2026 Flux Croisés · Version » (demandé par Lewis), logo de l'éditeur. Les licences sont dans À propos.

## Règles de travail

- L'utilisateur, Lewis, ne programme pas. Explique simplement ce que tu fais et comment tester, sans jargon.
- Une étape à la fois : à la fin de chaque étape, démonstration, tests au vert, puis attendre la validation de Lewis avant la suivante.
- Tout en français : interface, messages, commentaires du code, commits. Dans les textes français, jamais de tiret cadratin : utiliser deux-points, virgule, parenthèses ou une nouvelle phrase.
- Les couleurs, polices et tailles de l'interface viennent de `UI/charte/tokens.json`, générées en feuille de style Qt (QSS) ; aucune couleur codée en dur ailleurs.
- Chaque bibliothèque ajoutée est inscrite avec sa licence dans `LICENCES.md`.
- Tiens ce fichier à jour : décisions prises, état d'avancement, commandes utiles.

## État d'avancement

- Étape 1 (socle et visionneuse) : codée, avec la charte graphique intégrée (31 octobre 2026). Refonte de l'interface en cours (lots ci-dessous) ; lots 1 et 2 faits le 1er novembre 2026, 81 tests au vert. En attente de la validation de Lewis.
- Captures de référence de l'état actuel : `UI/captures/`.
- Étapes 2 à 6 : non commencées. Ne pas passer à l'étape suivante sans validation explicite.

## Commandes

- Lancer l'appli : double-clic sur `Remanence.bat`, ou `.venv\Scripts\python.exe -m remanence`
- Tests : `.venv\Scripts\python.exe -m pytest -q` (le jeu de test se génère dans `tests/medias/` au premier lancement)
- Installer sur une autre machine : `Installer.bat` (uv, Python 3.12 privé dans `.venv`)
- Python 3.12 est installé DANS le projet (`.python/`, ignoré par git), et `.venv` est créé à partir de lui. Raison : les commandes de Claude Code tournent dans un bac à sable, et ce qu'elles écrivent dans `%APPDATA%` n'est pas visible depuis la session Windows de Lewis (erreur « No Python » au double-clic, 31 octobre 2026). Ne jamais faire dépendre l'appli d'un fichier hors du dossier du projet.
- `uv` (pour Claude Code) : `%APPDATA%\Python\Python314\Scripts\uv.exe`. Réinstaller Python : `UV_PYTHON_INSTALL_DIR=<projet>\.python uv python install 3.12`, puis `uv venv --python <projet>\.python\cpython-3.12.16-windows-x86_64-none\python.exe .venv` et `uv pip install --python .venv\Scripts\python.exe -r requirements.txt`.

## Décisions

- Python 3.12 dans `.venv` (le Python système est en 3.14). FFmpeg est utilisé uniquement via PyAV, qui l'embarque avec x264 et x265 ; pas de ffmpeg.exe pour l'instant (son exécution depuis un téléchargement a été refusée par la sécurité de session).
- Recopie des images non modifiées (smart rendering) : c'est elle qui garantit « mêmes pixels que la source », car ProRes, DNxHR, H.264 et HEVC sont avec perte. Codecs intra : recopie image par image. Codecs à GOP : recopie seulement si l'export reprend le média entier sans modification, sinon tout est réencodé.
- Composition interne en float32 RVBA prémultiplié ; conversion YUV vers RVB explicite avec la matrice et la plage du fichier, sans toucher à la courbe de transfert.
- Proxies : ProRes 422 Proxy en demi-résolution (4444 si alpha), seulement au-delà de 1280 px de large et pour les sources YUV, dans `%LOCALAPPDATA%\Remanence\cache`. Cache audio : float32 stéréo 48 kHz au même endroit.
- Cadence variable : intermédiaire ProRes 422 HQ à la cadence standard la plus proche de la moyenne, niveaux ramenés en plage vidéo.
- Historique : instantanés JSON complets du projet (annulation illimitée). Le moteur de lecture travaille sur une copie du projet.
- Le premier média posé règle la séquence (taille, cadence, timecode de départ). Un média de cadence différente est posé image pour image (la vitesse viendra à l'étape 5).
- Pièges PyAV et FFmpeg 8 rencontrés :
  - la base de temps d'un flux change à la première écriture, donc garder sa propre variable `base_temps` pour horodater les images ;
  - les métadonnées couleur sont lues sur chaque image encodée (voir `appliquer_couleur`) ;
  - un flux recopié depuis un gabarit perd sa cadence et son étiquette de codec, à remettre sinon MOV n'écrit ni timecode ni le bon profil ProRes ;
  - le décodeur ProRes sort le 4444 en 12 bits ;
  - un paquet recopié doit recevoir `duration = 1` dans la base de temps de sortie.

## Interface (antislop, mode « pendant »)

- Design Read : logiciel de montage Windows pour monteurs, outil de postproduction sombre et neutre, dial ENERGY 1 / RHYTHM 1 / MOTION 1.
- La direction visuelle est la charte de `UI/charte/` (mauve pour l'action, la sélection et la tête de lecture ; turquoise pour l'animation et le focus ; IBM Plex). Vérifier les contrastes avec `contrast-check.py` avant d'utiliser une paire de couleurs.
- `remanence/ui/charte.py` lit `tokens.json`, génère la feuille de style des deux thèmes (`MODELE_QSS`), charge les polices de `remanence/ressources/polices` et teinte les icônes Lucide de `remanence/ressources/icones`. Les widgets dessinés à la main lisent `charte.actuelle()` à chaque dessin. `tests/test_charte.py` refuse toute couleur écrite ailleurs et vérifie les contrastes des paires utilisées.
- QtSvg ignore les `clipPath` : le symbole du logo est dessiné par `rendre_symbole`, qui relit la géométrie du fichier SVG.
- La feuille de style Qt ne sait pas mettre en capitales : le style `caption` passe par `etiquette(..., "section")` qui pose la police.
- Décisions validées par Lewis le 31 octobre 2026 : texte lisible en `ink-muted` (jamais `ink-faint`, 3,7:1), couleurs de `tokens.json` à la place des couleurs hors charte de la maquette (`#4a3220`, `#5a7bb8`, `#4f8f72`), étoile du bouton Effets remplacée par l'icône `layers` (antislop R-04), titre de l'écran de démarrage à 40 px comme la maquette, espaces de travail limités à Médias et Montage tant que les autres n'existent pas.
- Défaut de la charte signalé : `success` en thème clair donne 4,499:1 sur `surface`. Il n'est posé que sur `surface-raised`.
- Les éléments de la maquette qui dépendent des étapes suivantes (onglets Effets, Transitions, Scripts ; onglets Masque, Fusion, Modulateurs ; images clés ; badges fx ; Avant/Après ; Ripple et Slip ; espaces Glitch et Export) ne sont pas affichés tant qu'ils ne fonctionnent pas.
- Typographie : espace insécable avant « : ; ? ! % » et entre un nombre et son unité, dans tous les textes.
- Refonte de l'interface (1er novembre 2026). Référence : `UI/refonte/maquette-refonte.webp` et `UI/refonte/refonte.md` (proposition de Lewis, pas à reproduire à l'identique ; nom « MoshStudio Pro » de la maquette remplacé par Remanence). Se rapprocher de DaVinci Resolve, esprit logiciel professionnel, dense.
  - Décisions de Lewis : thème clair supprimé ; on garde le mauve de la charte (pas le violet vif de la maquette) ; barre du haut sur une seule ligne avec les boutons de fenêtre intégrés ; deux moniteurs côte à côte (source, programme) dans l'espace Montage ; espaces de travail selon l'avancement (Média, Montage, Export maintenant ; Cut quand le montage rapide existera ; Datamosh à l'étape 3 ; Couleur et Fusion seulement s'ils entrent au cahier des charges) ; convention Vegas pour la molette et les raccourcis (flèches seules pour une image) ; fondu enchaîné automatique au chevauchement (désactivable).
  - Navigation du bas : 36 px, centrée, icônes et libellés, soulignement mauve sous l'espace actif, sans logo ni version, masquable (Affichage).
  - Double écran comme dans Resolve (demande du 1er novembre 2026) : timeline et vumètres sur le second écran, programme en plein écran possible ; prévu au lot 2.
  - Fait au lot 1 : fenêtre sans cadre (`barres.py` : BarreTitre avec startSystemMove/startSystemResize, bords de 5 px), navigation `BarreEspaces`, espaces Média/Montage/Export (`PANNEAUX_ESPACE` dans `fenetre.py`, dispositions mémorisées par espace avec `VERSION_DISPOSITION`), panneaux à onglets (`panneau_onglets`), onglets Inspecteur/Métadonnées/Historique, espace Export (`panneau_export.py` : formulaire et file d'export ; l'ancienne boîte de dialogue d'export est supprimée), palette Qt générée par la charte, style natif Windows conservé (Fusion soulignait les lettres des menus).
  - Fait au lot 2 : `Moniteur` commun (`visionneuse.py` : zoom Adapter à 200 %, barre de défilement avec E et S, transport de la maquette, timecode) pour la source et le programme ; source avec son propre `MoteurLecture` sur un mini-projet ; points E et S de la source mémorisés sur le `Media` (clé « points » du projet, facultative) ; moniteur actif (filet mauve sous l'en-tête, Q pour basculer, commandes de lecture routées) ; F9 insère (`edition.inserer_media`, qui pousse la suite), F10 écrase ; glisser l'image source vers la timeline (MIME « id@entree:sortie ») ; « Un seul moniteur » ; double écran (fenêtre sans parent, sinon restoreState la rapatrie) ; programme en plein écran (Ctrl+F, Échap). V1 = piste vidéo du bas par défaut.
  - Réglages de l'interface : toujours passer par `config.reglages_interface()`. `QSettings("Remanence", "Remanence")` écrit dans le registre même quand les tests demandent un fichier temporaire (les tests polluaient le dernier espace actif).
  - QDockWidget règle la hauteur de la barre de titre sur sa taille suggérée : les barres héritent de `BarreTitrePanneau` (36 px), sinon le contenu recouvre leur bas.
  - Lots : 1 fondations visuelles (thème, barre du haut, navigation, espaces, onglets) ; 2 moniteurs source et programme ; 3 médias (chutiers, grille, liste, recherche, survol) ; 4 timeline (en-têtes compacts, barre d'outils, marqueurs nommés, vumètres à droite, gestes) ; 5 inspecteur (sections repliables, Métadonnées, Historique).

<!-- antislop:start -->
## antislop
For UI, copy, people, mobile layout, or code comments work, read these installed skill files directly (use these paths even if a same-named global skill exists):
- Core filter, always on: `antislop`: `.claude/skills/antislop/SKILL.md`
- UI / visual: `antislop-ui`: `.claude/skills/antislop-ui/SKILL.md`
- Copy & text: `antislop-copywriting`: `.claude/skills/antislop-copywriting/SKILL.md`
- People: `antislop-human`: `.claude/skills/antislop-human/SKILL.md`
- Mobile / responsive: `antislop-layoutmobile`: `.claude/skills/antislop-layoutmobile/SKILL.md`
- Code comments: `antislop-code`: `.claude/skills/antislop-code/SKILL.md`
Before starting, follow the core's "Two Usage Modes" section in strict order: explicit session instruction first, then global preference, then ask. A session instruction always wins. For a resolved mode, say `antislop active: <mode> (session override).` or `antislop active: <mode> (global preference).` once before presenting findings or making edits, using the actual mode and source. Acknowledging the user's request without naming the source does not replace this notice.
Only an explicit choice of antislop during or after selects a session mode. A request to review, audit, or avoid file edits does not select a mode; read the global preference in that case. Another skill's mode does not select antislop's mode.
If the mode is unresolved, ask during/after and end the response; wait for the answer before any UI review, planning, or concept. For read-only tasks, put the active-mode notice only at the start of the final answer, never in progress messages. For editing tasks, announce before the first edit and omit it from the final answer.
To update antislop later: `npx antislop-ai --update`, or run `npx antislop-ai` and pick Overwrite them.
<!-- antislop:end -->
