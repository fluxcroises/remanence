# Dépannage

## Le journal

Remanence note dans un journal ce qu'il fait et chaque erreur, avec le détail technique. Aide > Ouvrir le journal ouvre son dossier : envoyez le fichier `remanence.log` avec une phrase sur ce que vous faisiez. Un plantage brutal laisse aussi un fichier `plantage.log`.

## Le diagnostic

Pour vérifier que le programme a tout ce qu'il lui faut, lancez `Remanence.exe --diagnostic` (depuis une invite de commandes, dans le dossier du programme). Il contrôle les effets, les ressources, les formats d'échange, FFmpeg, la carte graphique, l'interface, puis monte, enregistre et exporte un petit projet d'essai. Le résultat est écrit dans `diagnostic.txt`, dans le dossier du journal.

## Pas d'effets à l'image

Les effets demandent une carte graphique compatible OpenGL 4.3. Sans elle (pilote ancien, bureau à distance), Remanence monte et exporte, mais sans effets. Mettez à jour le pilote de la carte graphique.

## Un effet de datamosh ne fait rien

Les effets propres à FFglitch (vecteurs de mouvement, transfert de mouvement, scripts) en ont besoin : Aide > Installer FFglitch. Les autres effets de datamosh se calculent en arrière-plan : le badge « Calcul… » reste sur le clip le temps du calcul.

## L'export n'est pas conforme

Le rapport d'export compare le fichier à la séquence : durée en images, cadence, taille, timecode. Une ligne en défaut dit laquelle. Le format « Comme la source » donne le résultat le plus fidèle.
