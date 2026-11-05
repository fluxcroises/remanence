# Notes de version

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
