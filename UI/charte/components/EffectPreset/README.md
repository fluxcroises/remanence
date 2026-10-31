# EffectPreset

Une tuile de la bibliothèque d'effets : un préréglage prêt à glisser sur un clip, une piste ou la séquence.

- **Fourni par l'appelant** : le nom du préréglage, l'effet et le moteur dont il dépend, une vignette (image figée du rendu sur une vidéo de démonstration ; animée au survol).
- Tuile `surface-raised`, arrondi `radius-md`, vignette sur `viewer-bg`. Nom en `heading` réduit à 13 px, métadonnées en `label` `ink-muted`.
- Préréglage appliqué au clip sélectionné : bordure `accent` (classe `is-active`).
- Un préréglage glissé reste entièrement modifiable dans l'inspecteur ; « Enregistrer comme préréglage » crée une tuile personnelle.
- À éviter : des noms techniques (« bloom_30_q4 ») ; nommer par l'effet visuel produit (« Fonte lente »).
