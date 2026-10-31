# Button

Déclenche une commande : exporter, calculer un aperçu, couper, supprimer.

- **Variantes** : `rm-btn-primary` (une seule par vue, l'action qui fait avancer le travail : Exporter, Appliquer), `rm-btn` par défaut, `rm-btn-ghost` dans les barres d'outils, `rm-btn-danger` pour une action destructrice (elle demande toujours confirmation).
- **Fourni par l'appelant** : le libellé à l'infinitif, une icône Lucide facultative de 16 px placée avant le libellé, l'état désactivé.
- Hauteur `control-h`, arrondi `radius-sm`, focus `focus-ring`. Le texte du bouton principal est en `on-accent`.
- À éviter : deux boutons principaux côte à côte, un bouton sans libellé hors des barres d'outils (une icône seule exige une info-bulle).
