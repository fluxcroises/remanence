# Refonte de l'interface utilisateur

## 1. Objectif

Je souhaite revoir l'interface graphique de mon logiciel de datamoshing professionnel en m'appuyant sur la maquette jointe.

L'application doit adopter une ergonomie comparable à **DaVinci Resolve et VEGAS Pro**, tout en disposant d'une identité graphique propre.

Le logiciel est avant tout un **éditeur vidéo multipiste**, intégrant des fonctionnalités avancées de datamoshing.

Il ne doit pas ressembler à une application web ou à un simple outil de génération d'effets. L'objectif est une interface de bureau professionnelle, dense, précise, réactive et adaptée à un usage intensif.

La maquette jointe est notre référence visuelle principale.

**Important :** conserver les fonctionnalités déjà implémentées dans l'application. La refonte concerne principalement l'organisation, l'ergonomie et l'apparence des composants existants. Ne pas réécrire inutilement le moteur vidéo ou la logique métier.

## 2. Direction artistique

### Principes visuels

- Interface compacte, sans espacements excessifs.
- Pas de grandes cartes arrondies ni de boutons surdimensionnés.
- Séparateurs fins entre les zones.
- Police sans-serif moderne et lisible.
- Icônes vectorielles monochromes.
- Utilisation du violet uniquement pour les sélections, actions importantes et fonctionnalités spécifiques au datamoshing.
- Aucune décoration superflue.

L'ensemble doit évoquer un logiciel de postproduction audiovisuelle plutôt qu'un tableau de bord web.

## 3. Structure générale de la fenêtre

L'interface est organisée en cinq zones principales :

1. Barre supérieure : titre de l'application, menus et informations du projet.
2. Partie supérieure gauche : explorateur de médias, effets et transitions.
3. Partie supérieure centrale : moniteurs vidéo.
4. Partie supérieure droite : inspecteur et réglages contextuels.
5. Partie inférieure : barre d'outils de montage, timeline multipiste et navigation entre espaces de travail.

Tous les panneaux principaux doivent pouvoir être redimensionnés grâce à des séparateurs déplaçables.

La disposition doit s'adapter à différentes résolutions d'écran, notamment 1920 × 1080 et 2560 × 1440.

## 4. Barre de menus supérieure

Conserver une barre de menus classique, comparable à celle des logiciels professionnels sous Windows.

Exemples de menus :

Fichier | Édition | Montage | Lecture | Effets | Datamosh | Fusion | Étalonnage | Affichage | Fenêtre | Aide

À droite, afficher discrètement :

- Le nom du projet courant.
- La résolution du projet.
- La fréquence d'images.
- Les contrôles natifs de fenêtre.

Le logo et le nom de l'application doivent apparaître uniquement dans cette zone supérieure.

## 5. Navigation entre les espaces de travail

**C'est un point essentiel de la refonte.**

Les espaces de travail doivent être accessibles depuis une barre horizontale située tout en bas de la fenêtre, directement inspirée du fonctionnement de DaVinci Resolve.

Espaces proposés :

- Média
- Cut
- Montage
- Couleur
- Datamosh
- Fusion
- Export

### Contraintes impératives

- Barre inférieure de 36 pixels de hauteur cible.
- Aucun logo ou nom de l'application dans cette barre.
- Aucun numéro de version.
- Navigation centrée horizontalement.
- Petites icônes vectorielles accompagnées de libellés discrets.
- Aucun grand bouton ni gros fond coloré.
- L'espace actif est identifiable par un fin soulignement violet et une icône légèrement accentuée.
- Aucun espacement vertical inutile.
- Possibilité de masquer cette barre depuis le menu Affichage.

Chaque espace représente une disposition fonctionnelle de l'application, et non une fenêtre indépendante.

Le passage d'un espace à l'autre doit être rapide et préserver le projet, la sélection et la position de lecture.

L'espace **Montage** est l'espace de travail principal.

## 6. Panneau gauche — Bibliothèque de médias

Créer une zone d'exploration organisée avec plusieurs onglets :

Média | Effets | Transitions | Titres

Dans l'onglet Média :

- Arborescence des dossiers et collections.
- Importation de fichiers.
- Affichage des fichiers sous forme de vignettes ou de liste.
- Prévisualisation des médias.
- Recherche et filtres.
- Affichage des noms et durées des médias.
- Glisser-déposer vers la timeline.

Le panneau doit être redimensionnable et masquable.

Prévoir une largeur initiale indicative de 300 à 340 pixels sur un écran Full HD.

## 7. Moniteurs vidéo centraux

L'espace Montage doit proposer deux moniteurs côte à côte.

### Moniteur source

Affiche le média sélectionné dans la bibliothèque.

Fonctions :

- Lecture / pause.
- Navigation image par image.
- Points d'entrée et de sortie.
- Timecode.
- Zoom et adaptation de l'image.

### Moniteur programme

Affiche le résultat de la séquence en cours, avec les effets appliqués.

Fonctions :

- Lecture de la timeline.
- Prévisualisation du datamoshing.
- Navigation temporelle précise.
- Contrôle de la qualité de prévisualisation.
- Mode plein écran.

Les moniteurs doivent conserver le ratio de la vidéo, avec des bandes neutres lorsque nécessaire.

Ils doivent occuper le maximum d'espace disponible sans déformer l'image.

## 8. Panneau droit — Inspecteur

Créer un inspecteur contextuel, inspiré des logiciels de montage professionnels.

Onglets proposés :

Inspecteur | Métadonnées | Historique | Scopes

Son contenu dépend de l'élément sélectionné.

Pour un clip vidéo classique, afficher les paramètres habituels : position, taille, rotation, opacité, vitesse et autres propriétés disponibles.

Pour un clip ou un effet Datamosh, afficher des paramètres spécifiques organisés en sections repliables :

### Structure de compression

- Gestion des I-frames.
- Gestion des P-frames.
- Paramètres de GOP.
- Suppression ou manipulation des images de référence, selon les capacités du moteur.

### Propagation

- Nombre d'images.
- Intensité ou atténuation.
- Direction.
- Bouclage lorsque pris en charge.

### Vecteurs de mouvement

- Réutilisation des vecteurs.
- Intensité.
- Distorsion.
- Échelle.

### Opérations de datamoshing

- Suppression.
- Réutilisation.
- Fusion.

### Réglages complémentaires

- Zones et masques.
- Mélange et opacité.
- Préréglages.
- Réinitialisation des paramètres.

Les paramètres affichés doivent correspondre aux fonctionnalités réellement implémentées. Ne pas créer de contrôles purement décoratifs.

Privilégier des sliders précis, accompagnés de champs numériques modifiables, plutôt que de grands contrôles graphiques.

## 9. Timeline multipiste

La timeline constitue l'élément central du logiciel.

Elle doit occuper la partie inférieure de la zone de travail, juste au-dessus de la barre de navigation.

### Fonctionnalités et présentation

- Pistes vidéo V1, V2, V3, etc.
- Pistes audio A1, A2, etc.
- Vignettes de prévisualisation des clips.
- Formes d'onde audio.
- Règle temporelle.
- Tête de lecture visible.
- Marqueurs.
- Zoom horizontal.
- Défilement horizontal et vertical.
- Outils de sélection, découpe et déplacement.
- Contrôles de visibilité, verrouillage et sourdine des pistes.

### Représentation des effets Datamosh

Les effets de datamoshing doivent être particulièrement identifiables.

Utiliser des blocs violets sur les clips ou les pistes d'effets, selon le modèle de montage retenu.

Un effet doit pouvoir être sélectionné afin d'afficher ses paramètres dans l'inspecteur.

Les effets doivent pouvoir être positionnés temporellement lorsque le moteur le permet.

**L'utilisateur doit pouvoir monter une vidéo normalement, puis appliquer du datamoshing à des segments précis sans détruire les médias d'origine.**

## 10. Barre d'outils de montage

Placer une petite barre d'outils directement au-dessus de la timeline.

Elle contient notamment les fonctions disponibles de :

- Sélection.
- Découpe.
- Déplacement.
- Accrochage magnétique.
- Liaison / dissociation des clips.
- Marqueurs.
- Zoom.
- Outils de datamoshing rapides.

Les icônes doivent être compactes et accompagnées d'infobulles.

## 11. Comportement des espaces de travail

Chaque espace doit privilégier les panneaux nécessaires à son activité.

**Média :** importation, classement, métadonnées et prévisualisation.

**Cut :** montage rapide, opérations de découpe et assemblage.

**Montage :** timeline multipiste complète, moniteurs et inspecteur.

**Couleur :** correction colorimétrique, scopes et prévisualisation.

**Datamosh :** analyse des images de compression, opérations de datamoshing, visualisation des vecteurs de mouvement et réglages avancés, selon les capacités du moteur.

**Fusion :** composition et combinaison d'effets, selon les fonctionnalités implémentées.

**Export :** choix des formats, codecs, paramètres de rendu et progression d'exportation.

Ne pas construire des espaces vides uniquement pour reproduire la maquette. Adapter leur présence à la feuille de route réelle de l'application.

## 12. Redimensionnement et personnalisation

Prévoir une interface modulaire :

- Séparateurs entre les panneaux.
- Redimensionnement vertical de la timeline.
- Redimensionnement horizontal de la bibliothèque et de l'inspecteur.
- Affichage ou masquage des panneaux secondaires.
- Restauration de la disposition par défaut.
- Sauvegarde des préférences de disposition.
- Utilisation cohérente des résolutions et facteurs de mise à l'échelle Windows.

La timeline doit notamment pouvoir être agrandie pour bénéficier d'un espace de montage confortable.

## 13. Contraintes de développement

Avant d'effectuer des modifications, analyser l'architecture actuelle de l'application, ses composants UI, son framework et les fonctionnalités déjà opérationnelles.

Réutiliser autant que possible l'existant.

Séparer clairement :

- La présentation des composants.
- L'état des panneaux et des espaces de travail.
- La logique de montage.
- Le moteur de traitement vidéo et de datamoshing.
- La gestion des médias et du projet.

Ne pas modifier les formats de projet ou les comportements existants sans nécessité.

Les contrôles visuels doivent être reliés à des fonctionnalités réelles et ne pas simuler des traitements inexistants.

## 14. Résultat attendu

Obtenir une interface :

- Visuellement proche de la maquette jointe.
- Sérieuse et adaptée à un usage professionnel.
- Inspirée de DaVinci Resolve et VEGAS Pro sans les copier à l'identique.
- Compacte et optimisée pour l'espace de travail.
- Modulaire et redimensionnable.
- Cohérente avec un logiciel natif.
- Centrée sur un workflow de montage vidéo non destructif, enrichi par les outils de datamoshing.

**Priorité absolue : respecter la navigation inférieure compacte de 36 px, sans logo et avec un simple indicateur violet pour l'espace actif.**

Commencer par examiner l'interface actuelle et identifier les composants à conserver, déplacer, adapter ou créer. Ensuite, proposer une stratégie de refonte progressive permettant de conserver une application fonctionnelle à chaque étape.

Ne pas entreprendre une réécriture complète de l'application sans justification technique.
