# ParameterSlider

Une ligne de réglage de l'inspecteur : bouton d'image clé, libellé, curseur et valeur saisissable.

- **Fourni par l'appelant** : le libellé (`label`, dans `ink-muted`), la plage, le pas, l'unité, la valeur, et si le paramètre est animé.
- Le losange de gauche ajoute une image clé à la position de la tête de lecture. Paramètre animé (classe `is-animated`) : losange plein `keyframe`, libellé et remplissage en `accent-2`.
- La valeur est en `value` (chasse fixe), modifiable au clavier, à la molette et par glisser horizontal ; double-clic sur le libellé pour revenir à la valeur par défaut.
- Lignes espacées de `space-3`, hauteur `control-h`.
- À éviter : des curseurs sans valeur affichée, une unité absente (« 72 » au lieu de « 72 % »).
