Remanence est un logiciel de montage vidéo dédié au datamosh et au glitch art. Son identité tient en une idée : **l'image qui persiste**. Comme dans les logiciels de montage professionnels, l'interface s'efface devant l'image : gris neutres, angles presque droits, aucune décoration. Deux accents désaturés seulement, un mauve et un turquoise, utilisés avec parcimonie. Le logo, un disque découpé en tranches décalées, porte seul la part de glitch.

## Principes

- **L'image d'abord.** Rien dans l'interface ne doit concurrencer la vidéo : gris sans teinte, pas de dégradés, pas d'ombres sur les panneaux, couleurs d'accent rares.
- **Chaque couleur a un rôle.** `accent` (mauve) désigne l'action principale, la sélection et la tête de lecture ; `accent-2` (turquoise) désigne ce qui bouge dans le temps ou ce qui a le focus. Ne jamais les utiliser pour décorer, ni en grands aplats.
- **Dense mais lisible.** Texte de base à 13 px (`body`), contrôles de 28 px (`control-h`), espacement sur une base de 4 px. Un monteur doit voir beaucoup d'informations sans plisser les yeux.
- **Précis.** Chiffres en chasse fixe (`timecode`, `value`), angles de 2 à 6 px, alignements stricts sur la grille de 4 px.

## Rédaction de l'interface

- Tout est en français. L'interface parle surtout par verbes et par noms (« Exporter », « Ajouter une piste », « Format illisible ») ; quand elle s'adresse à l'utilisateur, elle le vouvoie.
- Boutons et commandes à l'infinitif, avec une majuscule initiale seulement : « Calculer l'aperçu », pas « Calculer L'Aperçu ».
- **Jamais de tiret cadratin.** Utiliser les deux-points, la virgule, les parenthèses ou une nouvelle phrase.
- Espace insécable avant `:` `;` `?` `!` `%` et entre un nombre et son unité : « 72 % », « 0,35 s », « 25 i/s ».
- Virgule décimale française (0,35), timecode au format `HH:MM:SS:II` (heures, minutes, secondes, images).
- Messages d'erreur : ce qui s'est passé, puis quoi faire. « Ce fichier BRAW n'est pas lisible. Demandez au monteur un export ProRes ou DNxHR. »
- Pas d'émoji, pas de point d'exclamation, pas de superlatifs.

## Couleur

- Fonds : `bg-app` entre les panneaux, `surface` pour les panneaux, `surface-raised` pour les menus, dialogues, champs et en-têtes de pistes, `surface-hover` au survol. La visionneuse est toujours sur `viewer-bg` (noir), quel que soit le thème.
- Texte : `ink` pour tout ce qu'on lit, `ink-muted` pour les libellés et métadonnées, `ink-faint` uniquement pour le désactivé et les graduations.
- Mauve `accent` : bouton principal (un seul par vue), sélection, tête de lecture (`playhead`), clips d'effet sélectionnés, préréglage actif. Texte posé sur un aplat mauve : `on-accent`, sombre en thème sombre.
- Turquoise `accent-2` : images clés (`keyframe`), paramètres animés, modulateurs, anneau de focus (`focus`).
- Fonds teintés : `accent-soft` derrière un texte mauve, `accent-2-soft` derrière un texte turquoise.
- États : `success` (bleu), `warning` (jaune), `danger` (rouge), toujours accompagnés d'un mot ou d'une icône. Le succès est bleu et non vert pour rester distinct de l'erreur chez les personnes daltoniennes ; l'avertissement est jaune.
- Timeline : `clip-video`, `clip-audio`, `clip-effect`, `clip-transition`, noms de clips en `ink`.
- Limite de contraste à respecter : en thème clair, ne pas poser de texte mauve, turquoise ou d'état sur `bg-app` ni `surface-hover` ; en thème sombre, pas de texte mauve sur `surface-hover`.

## Typographie

- Deux familles libres (OFL), embarquées dans l'application : **IBM Plex Sans** pour l'interface, **IBM Plex Mono** pour les timecodes et valeurs. Repli : Segoe UI et Consolas.
- `display` pour l'écran d'accueil seulement, `title` pour les dialogues, `heading` pour les sections, `body` partout ailleurs, `label` pour les libellés de paramètres, `caption` (capitales espacées) pour les en-têtes de pistes et les badges.
- Toute valeur numérique qui change en direct est en `value` ou `timecode`, pour qu'elle ne tremble pas.

## Espacement, formes et élévation

- Grille de 4 px : `space-2` dans les contrôles, `space-3` entre deux paramètres, `space-4` dans les panneaux, `space-6` entre les sections.
- Hauteurs fixes : `control-h` pour les contrôles, `toolbar-h` pour les barres d'outils, `track-video-h` et `track-audio-h` pour les pistes.
- Arrondis : `radius-xs` pour les clips, badges et vignettes ; `radius-sm` pour les boutons et champs ; `radius-md` pour les menus, dialogues et tuiles ; `radius-full` pour les interrupteurs uniquement.
- Les panneaux sont à plat, séparés par `line`. Seuls les éléments flottants (menus, info-bulles, dialogues) portent `shadow-float`.

## États et focus

- Focus clavier : `focus-ring` (2 px de la couleur du panneau puis 2 px de turquoise plein), visible sur tout élément focusable, à au moins 3:1 sur chaque surface.
- Survol : fond `surface-hover`. Appui : même fond, contenu décalé d'aucun pixel (pas d'effet d'enfoncement).
- Désactivé : texte `ink-faint`, bordure `line`, pas d'opacité globale (elle rendrait illisibles les vignettes).
- Sélection dans la timeline : liseré de 2 px `accent` autour du clip.

## Timeline

- Ligne de tête de lecture en `playhead` sur toute la hauteur, poignée triangulaire en haut.
- Losanges d'images clés en `keyframe`, de `keyframe-size`, pleins quand une valeur est posée, vides quand la piste est interpolée.
- Les images clés du flux vidéo (changements de plan) apparaissent en traits verticaux `ink-faint`, rouges `danger` quand le datamosh les supprime.
- En-têtes de pistes en `caption`, sur `surface-raised`.

## Iconographie

- Jeu d'icônes **Lucide** (licence ISC), au trait de 1,5 px, en 16 px dans les contrôles et 20 px dans les barres d'outils, couleur `ink-muted`, `ink` au survol.
- Le logo est le symbole **Tranches** (dossier `assets/Logos`) suivi du nom en IBM Plex Sans 600 : voir le composant Logo. `remanence-symbole.svg` sur fond sombre, `remanence-symbole-clair.svg` sur fond clair, `remanence-symbole-mono.svg` pour une impression à une couleur, `remanence-icone-petite.svg` (trois tranches) en dessous de 32 px.
- Pas d'émoji dans l'interface.

## Mouvement

- Transitions d'interface de 120 ms maximum, sans rebond. Rien ne bouge seul dans l'interface : le seul mouvement est celui de la vidéo.

## Mise en œuvre dans Qt

- L'application est en PySide6 : ces tokens se traduisent en feuille de style Qt (QSS) générée depuis `tokens.json`, une par thème. Les noms de variables CSS (`--accent`, `--space-4`) servent de clés.
- Les composants de cette charte (`rm-btn`, `rm-param`, `rm-clip`, `rm-logo`…) sont des références visuelles en HTML : l'application les reproduit en widgets Qt avec les mêmes valeurs.
