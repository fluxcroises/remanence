# Timecode

Affiche une position ou une durée au format `HH:MM:SS:II` (heures, minutes, secondes, images).

- **Fourni par l'appelant** : le nombre d'images, la cadence (dont 23,976 et 29,97), le rôle (position ou durée).
- Style `timecode`, chiffres à chasse fixe pour que rien ne tremble pendant la lecture. Sur la tête de lecture, les images sont en `accent` ; les autres timecodes sont en `ink-muted`.
- Cliquer sur le timecode permet de saisir une position ; `+` ou `-` suivi d'un nombre déplace d'autant d'images.
- Une légende en `value` (`ink-muted`) peut l'accompagner dessous.
