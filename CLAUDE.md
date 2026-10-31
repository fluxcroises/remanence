# Remanence

Logiciel Windows de montage vidéo orienté datamosh et glitch art, dans l'esprit de Vegas Pro (Python, PySide6, PyAV, OpenGL, FFglitch).

## À lire avant tout

- `CAHIER_DES_CHARGES.md` : le besoin complet. La section 7 fixe l'ordre de développement, en six étapes. (Celui de `prototype/` concerne le prototype Bavure.)
- `UI/charte/README.md` et `UI/charte/tokens.json` : la charte graphique (couleurs des thèmes sombre et clair, typographie IBM Plex, espacements, arrondis). Les fiches de `UI/charte/components/` décrivent chaque composant d'interface ; les fichiers `preview.html` sont des références visuelles, à reproduire en widgets Qt. Les logos sont dans `UI/charte/assets/Logos/`.
- `UI/maquettes/` : maquettes validées de l'écran principal et de l'écran de démarrage (à lire comme références visuelles, couleur d'accent : mauve). L'interface s'inspire de Vegas Pro (en-têtes de pistes, enveloppes sous les pistes, badge fx sur les clips) et de DaVinci Resolve (interface plate, vue d'ensemble de la séquence, inspecteur à droite, espaces de travail en bas).
- `prototype/` : le prototype Bavure (tkinter). Ses algorithmes de datamosh (`moteur_mosh.py`) et ses effets (`effets.py`) sont validés et réutilisables ; son interface ne l'est pas.

## Règles de travail

- L'utilisateur, Lewis, ne programme pas. Explique simplement ce que tu fais et comment tester, sans jargon.
- Une étape à la fois : à la fin de chaque étape, démonstration, tests au vert, puis attendre la validation de Lewis avant la suivante.
- Tout en français : interface, messages, commentaires du code, commits. Dans les textes français, jamais de tiret cadratin : utiliser deux-points, virgule, parenthèses ou une nouvelle phrase.
- Les couleurs, polices et tailles de l'interface viennent de `UI/charte/tokens.json`, générées en feuille de style Qt (QSS) ; aucune couleur codée en dur ailleurs.
- Chaque bibliothèque ajoutée est inscrite avec sa licence dans `LICENCES.md`.
- Tiens ce fichier à jour : décisions prises, état d'avancement, commandes utiles.

## État d'avancement

- Étape 1 (socle et visionneuse) : codée, 46 tests au vert. Pas encore validée : Lewis a annoncé des retours, et l'interface doit d'abord passer à la charte graphique.
- Intégration de la charte (31 octobre 2026) : écarts listés et plan proposé ; attendre la validation de Lewis avant de modifier l'interface. L'interface actuelle utilise encore l'ancienne palette (rose et cyan, Segoe UI) dans `remanence/ui/theme.py`.
- Étapes 2 à 6 : non commencées. Ne pas passer à l'étape suivante sans validation explicite.

## Commandes

- Lancer l'appli : double-clic sur `Remanence.bat`, ou `.venv\Scripts\python.exe -m remanence`
- Tests : `.venv\Scripts\python.exe -m pytest -q` (le jeu de test se génère dans `tests/medias/` au premier lancement)
- Installer sur une autre machine : `Installer.bat` (uv, Python 3.12 privé dans `.venv`)
- `uv` est dans `%APPDATA%\Python\Python314\Scripts\uv.exe`. `uv venv --python 3.12` échoue sur cette machine (lien de version mineure) : passer le chemin donné par `uv python find 3.12`.

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
- Écarts de la maquette à ne pas reproduire sans accord : `ink-faint` utilisé pour du texte à lire (3,7:1, sous le seuil de 4,5:1), couleurs hors tokens (`#4a3220`, `#5a7bb8`, `#4f8f72`).
- Pas d'onglet Effets tant que les effets n'existent pas (étape 2).

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
