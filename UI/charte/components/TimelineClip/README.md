# TimelineClip

Un clip posé sur une piste de la timeline : vidéo, audio, effet ou transition.

- **Fourni par l'appelant** : le type de clip, son nom, sa position et sa durée, ses images clés, l'état sélectionné.
- Fond selon le type : `clip-video`, `clip-audio`, `clip-effect`, `clip-transition` ; nom en `ink`, style `label`. Arrondi `radius-xs`.
- Sélection : liseré intérieur de 2 px `accent`. Images clés : losanges `keyframe` en bas du clip. Audio : forme d'onde en `ink-muted`.
- La tête de lecture (`playhead`) traverse toutes les pistes, avec sa poignée triangulaire en haut.
- En-têtes de pistes en `caption` sur `surface-raised`, pistes séparées par `line`. Hauteurs `track-video-h` et `track-audio-h`.
- À éviter : colorer les clips librement (la couleur dit le type), du texte mauve sur un clip.
