# Notes de version

## Remanence 1.1.2

Novembre 2026.

- Transition datamosh : la bavure part de l'image du premier plan avec ses effets. Avant, elle partait de l'image sans effet, et les effets semblaient disparaître sur la dernière image du premier plan.

## Remanence 1.1.1

Novembre 2026.

- Transition datamosh : réglage **Fondu**. Sur la fin de la transition, la bavure s'efface peu à peu au lieu de revenir au net d'un coup (8 images pour une nouvelle transition). Sur la timeline, les hachures s'éclaircissent sur cette partie.

## Remanence 1.1.0

Novembre 2026. Retours des premiers testeurs.

### Scripts de Live Mosher

- Fichier > Importer les scripts de Live Mosher… : les exemples de Live Mosher (dont les scripts dd_GlitchAssist de Daz Disley) s'importent en un clic, avec leurs noms et leurs dossiers d'origine. 82 agissent sur la timeline ; ceux qui demandent un clavier ou un contrôleur se lisent en direct.
- Aperçu en direct : le bouton Direct d'un effet à script montre le résultat en boucle, par-dessus le programme, et se relance à chaque réglage.
- Quatre effets de mouvement en plus : Gravité, Échange des axes, Sens unique, Tourbillon. Nouveaux préréglages : Miroir horizontal et vertical, Double vitesse, Coup de zoom.
- La recherche de la bibliothèque trouve un effet par le nom du script équivalent (dd_gravity, dd_swap, dd_slamZoom…).

### Interface

- Inspecteur en deux onglets, Clip et Effets : les réglages des effets ne sont plus mêlés à ceux du clip.
- Piste FX : les clips d'effet ont leur piste, en haut de la timeline.
- Double écran : Moniteur sur le second écran (l'image du programme en plein écran sur l'autre moniteur).

### Corrections

- La molette ne change plus un réglage survolé : le panneau défile.
- Au retour de l'espace Export, la fenêtre ne dépasse plus l'écran (le bas de la timeline était caché).
- Le moniteur garde son image quand il change de fenêtre (panneau détaché, second écran).
- Après l'espace Cut, plus de barre « Programme | Source » par-dessus le moniteur.

## Remanence 1.0.0

Novembre 2026. Première version publique, éditée par Flux Croisés, sous licence GPL 3.

### Montage

- Médias rangés en chutiers, grille ou liste, recherche, aperçu au survol.
- Moniteurs source et programme, points d'entrée et de sortie, insertion (F9) et écrasement (F10).
- Timeline à pistes vidéo et audio, gestes de Vegas Pro : slip, slide, roll, ripple, aimantation, fondus enchaînés au chevauchement.
- Vitesse par clip et lecture à rebours, séquences imbriquées, titres, rendu sur place.
- Position, taille, rotation, recadrage et miroir des clips, réglés dans l'inspecteur ou à la souris sur l'image.
- Espace Cut pour monter vite : bande source, insertion au raccord le plus proche, ajout à la fin, remplacement, pose au-dessus, double timeline, revue rapide, découpe aux changements de plan.
- Marqueurs nommés, timecode au choix, double écran.

### Effets

- 29 effets : glitch en temps réel sur la carte graphique, datamosh par le codec (Bavure ou FFglitch), flux optique, slit-scan, feedback.
- Scripts FFglitch, avec une bibliothèque et l'import de vos propres scripts.
- Transition datamosh entre deux plans, images clés supprimées aux coupes.
- Images clés, courbes de Bézier, masques animés et suivis automatiquement.
- Modulateurs : oscillateur, aléatoire, tempo, son ; enregistrement d'un contrôleur MIDI en courbe.
- Transitions glitch : volet, blocs, décalage RVB, coupure de signal.
- Scripts de montage : Scramble, Layer, Automator.
- Six effets audio glitch : bégaiement, bitcrusher, arrêt de bande, inversion par fragments, gel, databending audio ; le son peut baver avec l'image pendant un datamosh.

### Export

- ProRes, DNxHR, H.264, HEVC 10 bits, AV1, WebM avec transparence, GIF, séquences DPX, EXR et TIFF.
- Les images sans effet sont recopiées telles quelles : mêmes pixels que la source.
- Rapport de conformité : durée, cadence, résolution, timecode et couleurs vérifiés.
- Image fixe en PNG 16 bits ou EXR, modèles de nommage, un fichier par plan.
- Import d'un montage EDL ou FCP XML, liste de remplacement après export.

### Affichage

- Avant / après en volet ou côte à côte, LUT d'affichage .cube.
- Guide illustré (Aide > Guide) et fiches de prise en main (F1).

### Limites connues

- Les effets en temps réel demandent une carte graphique compatible OpenGL 4.3. Sans elle, le montage et l'export marchent, sans les effets.
- FFglitch est téléchargé au premier lancement. Sans lui, Bavure prend le relais, et les effets propres à FFglitch restent sans action.
- Le programme n'est pas signé : Windows peut afficher « Windows a protégé votre ordinateur ». Cliquer sur « Informations complémentaires », puis « Exécuter quand même ».
