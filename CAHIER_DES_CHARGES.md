# Remanence : cahier des charges

31 octobre 2026 · Lewis

## 1. Présentation

**Remanence** est un logiciel de montage vidéo pour Windows pensé pour le datamosh et le glitch art, dans l'esprit de Vegas Pro : on y monte des clips de n'importe quel format sur une timeline multipiste, on leur applique des effets prédéfinis entièrement modifiables, on cible ces effets dans le temps et dans l'image, et on exporte en qualité master.

Le nom s'écrit et se comprend de la même façon en français et en anglais (remanence). Il désigne la persistance d'une image ou d'un signal après sa disparition, exactement ce que produit le datamosh : l'image précédente reste et bave dans la suivante.

**Utilisateur.** Un monteur, truquiste ou créateur vidéo qui travaille sur des courts-métrages, clips et contenus pour les réseaux. Il maîtrise la vidéo mais ne programme pas : tout doit s'installer et se lancer simplement, et l'interface est entièrement en français.

**Cas d'usage de référence.** Un court-métrage dont certaines séquences doivent être datamoshées :

1. Le monteur exporte les plans concernés en ProRes 422 HQ, avec leur timecode et quelques secondes de marge, ainsi que le plan voisin quand l'effet doit traverser un raccord.
2. Dans Remanence, chaque plan a sa timeline avec des pistes d'effets : zones ciblées, masques, images clés, modulateurs.
3. L'export ProRes conserve exactement la durée, la cadence, la résolution et le timecode d'origine.
4. Le monteur remplace ses plans par ceux de Remanence, sans aucun recalage.

Le ProRes n'est que l'exemple de ce projet : Remanence accepte tout ce que FFmpeg sait lire (rushs de caméra, fichiers de téléphone, intermédiaires de montage, séquences d'images) et exporte par défaut dans le format de la source.

**Second cas d'usage.** Un clip musical ou un contenu pour les réseaux monté entièrement dans Remanence : rushs importés, montés sur plusieurs pistes, effets glissés depuis la bibliothèque puis ajustés, export direct.

**Ce que Remanence n'est pas.** Ce n'est pas une suite de postproduction complète : pas de compositing 3D, d'étalonnage avancé ni de mixage audio professionnel. Remanence fait le montage et le glitch, et échange avec Resolve, Premiere ou Avid pour le reste.

**Point de départ.** Le prototype « Bavure » (Python, tkinter, FFmpeg) a validé la suppression d'images clés, le bloom, le databending et cinq effets visuels. Remanence reprend ses algorithmes, mais pas son interface.

## 2. Principes et contraintes

Ces règles priment sur toute fonctionnalité : une appli qui abîme les pixels hors des zones voulues ou décale le timecode est inutilisable en production.

- **Non destructif.** Les fichiers sources ne sont jamais modifiés. Un projet ne stocke que des références aux médias et des réglages.
- **Qualité préservée.** Toute la chaîne interne travaille en 16 bits flottants par canal, pas en 8 bits. Hors des zones et des masques ciblés, l'image exportée est identique à la source au niveau du pixel.
- **Recomposition.** Les moteurs qui dégradent l'image (datamosh codec en MPEG-4 8 bits 4:2:0) calculent leur résultat à part. Ce résultat est ensuite recomposé sur l'original 10 bits, uniquement où et quand l'effet est actif.
- **Conformité temporelle.** Quand un plan est traité pour retourner dans un autre logiciel, l'export conserve la durée en images, la cadence (y compris 23,976 et 29,97), la résolution, le rapport de pixels et le timecode de départ. Le bloom ne rallonge jamais un plan : il remplace des images au lieu d'en ajouter.
- **Couleur.** Aucune conversion de couleur implicite. Les métadonnées de couleur (primaires, transfert, matrice, plage) sont lues et réécrites à l'identique. Les rushs en log sont traités tels quels.
- **Reproductible.** Un même projet produit toujours le même rendu, image pour image : tout aléatoire passe par une graine enregistrée.
- **Fluide.** L'interface ne se fige jamais. Tout calcul long tourne en arrière-plan, avec progression et annulation.
- **Français.** Interface, messages d'erreur, documentation et commentaires du code en français. Dans les textes français, ne jamais utiliser le tiret cadratin.
- **Code source ouvert.** L'appli est distribuée en code source, sans but commercial. Les bibliothèques sous GPL, LGPL, MIT, BSD ou Apache sont donc acceptables. Chaque dépendance et sa licence sont listées dans un fichier `LICENCES.md`. Aucun code n'est repris de logiciels propriétaires comme Mosh-Pro ou Datamosh 2 : on s'inspire de leurs fonctionnalités, jamais de leur code ni de leur interface.

## 3. Architecture et bibliothèques

Remanence est une application Python 3.12 avec une interface Qt, un rendu sur carte graphique en OpenGL, et trois moteurs d'effets qui convergent vers une même étape de recomposition.

```
                    Projet et timeline (Qt)
              zones, masques, images clés, modulateurs
                 |  réglages animés        |  masques
                 v                         v
Clips des   +--> Effets temps réel --+
pistes      |    (shaders GLSL)       |
(tous    ---+--> Flux optique -------+--> Recomposition --+--> Visionneuse (proxy)
formats,    |    (OpenCV, 16 bits)    |    masques, zones,  |
PyAV,       +--> Moteur codec -------+    fusion, opacité  +--> Export (comme la source)
16 bits)         (FFglitch, en cache)
```

Quel que soit le moteur, son résultat passe par la recomposition : c'est elle qui garantit que l'image reste intacte hors des zones et des masques ciblés.

### Bibliothèques

| Brique | Rôle dans Remanence | Licence |
| --- | --- | --- |
| Qt 6 via PySide6 | Interface : timeline, panneaux ancrables, visionneuse, raccourcis | LGPL |
| PyAV (FFmpeg) | Lecture et écriture de tous les formats, 10 et 12 bits, timecode, métadonnées couleur, audio | BSD + LGPL |
| FFmpeg et ffprobe | Conversions, proxies, analyse des fichiers | LGPL / GPL |
| OpenGL 4.3 (QOpenGLWidget, moderngl) | Pile d'effets en temps réel par shaders GLSL, textures 16 bits flottants | Libre |
| NumPy | Tampons d'images côté processeur | BSD |
| OpenCV contrib | Flux optique (DIS, Farnebäck), suivi de masques | Apache 2.0 |
| FFglitch (ffgac, ffedit) | Moteur codec : vecteurs de mouvement, types de macroblocs, coefficients | À vérifier, téléchargé à l'installation |
| OpenTimelineIO | Échanges avec le logiciel du monteur : EDL CMX 3600, FCP XML | Apache 2.0 |
| sounddevice | Lecture audio synchronisée, analyse pour les modulateurs audio | MIT |
| mido + python-rtmidi | Contrôleurs MIDI | MIT |
| PyInstaller | Exécutable Windows autonome | GPL avec exception |
| pytest | Tests automatiques | MIT |

### Organisation du code

- `remanence/media/` : lecture, écriture, proxies, timecode, métadonnées couleur.
- `remanence/projet/` : modèle de données (séquences, pistes, clips, effets), outils de montage et sérialisation JSON (fichiers `.remanence`), historique annuler / rétablir.
- `remanence/rendu/` : graphe de rendu, contexte OpenGL hors écran, cache, file de rendu en arrière-plan.
- `remanence/effets/` : un module par effet, avec sa description (paramètres, plages, valeurs par défaut) et son shader ou sa fonction.
- `remanence/moteurs/` : `codec/` (FFglitch et moteur Bavure), `flux/` (flux optique).
- `remanence/ui/` : fenêtres et widgets Qt.
- `tests/` : vidéos de test générées par FFmpeg (`testsrc2`, `mandelbrot`), tests de conformité image pour image.

### Modèle de données

Un **projet** contient des **médias** et une ou plusieurs **séquences**. Une séquence est une timeline multipiste avec ses réglages (résolution, cadence, timecode de départ) ; elle peut être imbriquée dans une autre. Elle porte des **pistes** vidéo et audio. Chaque piste contient des **clips** : un média, ses points d'entrée et de sortie, sa position, sa vitesse, ses enveloppes d'opacité ou de volume.

Les **effets** s'appliquent à trois niveaux, comme dans Vegas Pro : sur un clip, sur une piste entière, ou sur toute la séquence. Les **clips d'effet** (calques d'ajustement) appliquent un effet à tout ce qui se trouve sous eux pendant leur durée. Chaque effet a des paramètres, un masque facultatif, un mode de fusion et une opacité ; chaque paramètre est une valeur fixe, une courbe d'images clés ou un modulateur, les deux derniers pouvant se combiner. Les **transitions** relient deux clips adjacents.

### Rendu d'une image

1. Pour chaque piste vidéo visible, de bas en haut : décodage de l'image du clip présent à cet instant, en 16 bits flottants, sans conversion de couleur.
2. Application de la chaîne d'effets du clip : évaluation des paramètres à cet instant, puis shader en temps réel, flux optique ou lecture du pré-rendu codec en cache.
3. Fusion du clip sur les pistes inférieures selon son masque, son mode de fusion et son opacité, puis effets de piste, clips d'effet, transitions et effets de séquence.
4. Envoi vers la visionneuse (proxy) ou vers l'encodeur d'export (pleine résolution).

Les pré-rendus codec et flux optique sont mis en cache sur disque, en FFV1 sans perte, dans un dossier du projet. Chaque entrée de cache est identifiée par l'empreinte de ses réglages : changer un réglage n'invalide que les clips concernés.

## 4. Fonctionnalités

Remanence couvre toute la chaîne d'un plan : import dans n'importe quel format, ciblage précis des effets, animation, aperçu fluide et export conforme.

### 4.1 Formats acceptés

**Import.** Tout ce que FFmpeg sait décoder, sans réglage de la part de l'utilisateur :

| Famille | Exemples |
| --- | --- |
| Intermédiaires de montage | ProRes (422 Proxy à 4444 XQ), DNxHD, DNxHR, CineForm |
| Formats de diffusion et caméras | H.264, H.265 / HEVC 8 et 10 bits, XAVC, XDCAM, MPEG-2, AV1, VP9 |
| Conteneurs | MOV, MP4, MXF, MKV, AVI, WebM, MTS / M2TS |
| Séquences d'images | DPX, EXR, TIFF, PNG, JPEG (cadence demandée à l'import) |
| Audio accompagnant | PCM, AAC, AC-3, et tout format lu par FFmpeg |

- Les formats RAW de caméra (BRAW, R3D, ARRIRAW) ne sont pas lisibles par FFmpeg. Remanence l'explique clairement et conseille de demander un ProRes ou un DNxHR au monteur.
- Cadence variable (fréquente sur téléphone) : détectée à l'import, signalée, et convertie en cadence fixe dans un intermédiaire du projet. La source n'est jamais touchée.
- Vidéo entrelacée : détectée et signalée, avec un choix entre la traiter telle quelle ou la désentrelacer.
- Canal alpha (ProRes 4444, PNG, EXR) : conservé de bout en bout.
- Une fiche technique s'affiche pour chaque média : codec, profil, profondeur, échantillonnage, cadence, timecode, couleur, audio.

**Export.** Par défaut, « comme la source » : même codec, même profil et même profondeur quand l'encodage est possible. Sinon, ProRes 422 HQ est proposé. Formats disponibles :

| Usage | Formats |
| --- | --- |
| Retour au montage | ProRes 422 Proxy, LT, 422, HQ, 4444, 4444 XQ ; DNxHR LB, SQ, HQ, HQX, 444 |
| Étalonnage et effets | Séquences DPX 10 bits, EXR demi-flottant, TIFF 16 bits |
| Diffusion | H.264, H.265 10 bits, AV1 |
| Web et réseaux | MP4 H.264, WebM avec alpha, GIF |

L'audio de la source est recopié sans réencodage quand le conteneur le permet. Timecode, métadonnées couleur et nom de bobine sont réécrits à l'identique.

### 4.2 Montage multipiste

Le montage fonctionne comme dans Vegas Pro : on glisse des médias sur la timeline, on les coupe et on les arrange, et chaque clip reçoit directement ses effets.

- Pistes vidéo et audio en nombre illimité, réordonnables, que l'on peut masquer, couper ou verrouiller.
- Outils de montage : couper (S), rogner, ripple, roll, slip, slide, aimantation, groupes de clips, liaison son et image.
- Enveloppes d'opacité et de volume tracées directement sur les clips, fondus d'entrée et de sortie par poignées aux coins du clip, comme dans Vegas.
- Transitions entre clips adjacents, dont la durée se règle en les tirant : fondu, volets, et transitions glitch. La **transition datamosh** fait baver un clip dans le suivant en supprimant automatiquement l'image clé du raccord.
- Vitesse de clip : ralenti, accéléré, inversé, arrêt sur image.
- Effets sur un clip, sur une piste ou sur toute la séquence ; clips d'effet qui s'appliquent à tout ce qui se trouve dessous.
- Séquences imbriquées : une séquence peut devenir un clip dans une autre.
- Rendu sur place : figer une portion de la timeline en un nouveau média, pour enchaîner les traitements sans tout recalculer.
- Titres simples (texte, police, couleur, position) auxquels on applique les mêmes effets.
- Audio de base : volume, panoramique, fondus, vumètres. Pas de plugins audio.

### 4.3 Projet et médias

- Un projet regroupe des médias, listés dans un panneau Médias avec vignette, durée et format, et rangés dans des chutiers.
- Glisser-déposer de fichiers ou de dossiers entiers.
- Relink automatique si les médias ont été déplacés (recherche par nom, durée et timecode).
- Enregistrement automatique toutes les 2 minutes, et versions numérotées du projet.
- Historique annuler / rétablir illimité dans la session.

### 4.4 Outils de glitch sur la timeline

- Les pistes d'effets s'empilent au-dessus des pistes vidéo, sur la même timeline graduée en timecode.
- Pistes d'effets empilées, que l'on peut masquer, verrouiller, isoler ou réordonner.
- Clips d'effet que l'on crée, déplace, rogne, coupe et duplique à la souris, avec aimantation sur les images clés de la vidéo, les marqueurs et la tête de lecture.
- Marqueurs nommés et colorés, points d'entrée et de sortie pour limiter l'aperçu ou l'export.
- Les images clés du flux vidéo (changements de plan détectés) apparaissent sur une piste dédiée : chacune peut être conservée ou supprimée d'un clic pour le datamosh.
- Raccourcis inspirés des logiciels de montage : J, K, L, I, O, flèches image par image, B pour couper.

### 4.5 Ciblage dans l'image

- Masques rectangle, ellipse et forme libre (courbes de Bézier), avec contour adouci, expansion et inversion.
- Plusieurs masques par clip, combinés en addition, soustraction ou intersection.
- Masques animés par images clés, et suivi automatique d'une zone par OpenCV pour qu'un masque accompagne un sujet.
- Import d'une image ou d'une vidéo de cache (noir et blanc) fournie par un truquiste.
- Modes de fusion : normal, addition, écran, produit, différence, luminosité seule, couleur seule.

### 4.6 Animation des paramètres

- Chaque paramètre numérique peut être animé par images clés, avec un éditeur de courbes : linéaire, paliers, lissage, Bézier.
- **Modulateurs**, combinables avec les images clés : oscillateur (sinus, triangle, carré, dents de scie), aléatoire lissé, réaction à l'audio (volume ou bande de fréquences), calage sur un tempo en BPM, contrôleur MIDI.
- Un modulateur peut piloter plusieurs paramètres, avec une profondeur réglable pour chacun.
- Toute modulation est déterministe : même projet, même rendu.

### 4.7 Moteurs de datamosh

**Moteur codec (FFglitch).** Le rendu authentique, calculé en arrière-plan puis recomposé.

- Suppression d'images clés : l'image précédente bave avec le mouvement de la suivante, au raccord choisi.
- Bloom : répétition du mouvement d'une image sur une durée donnée, sans rallonger le plan.
- Transfert de mouvement : les vecteurs de mouvement d'un clip appliqués à un autre. Datamix : les premières images d'un clip remplacées par la dernière image du clip précédent.
- Opérations sur les vecteurs : amplifier, inverser, figer un axe, moyenner dans le temps, décaler, bruiter. Chaque opération est animable.
- Remanence génère lui-même les scripts FFglitch à partir des réglages de la timeline : l'utilisateur n'écrit jamais de code.
- Mode expert : éditeur de script JavaScript FFglitch pour les utilisateurs avancés.
- Moteur de secours : l'algorithme du prototype Bavure (découpage du flux MPEG-4) si FFglitch n'est pas installé.

**Moteur flux optique.** Le datamosh simulé, entièrement maîtrisé.

- Le mouvement est calculé entre deux images, puis les pixels d'une image de référence sont déplacés avec lui, image après image.
- Fonctionne sur un plan isolé, sans raccord.
- Réglages : image de référence, force, lissage, rafraîchissement partiel, persistance, influence du masque.
- Travaille directement en 16 bits flottants, donc sans perte de qualité.

### 4.8 Visionneuse

- Lecture en temps réel sur proxies : résolution réglable (pleine, 1/2, 1/4), proxies générés en arrière-plan à l'import.
- Bascule avant / après, et affichage côte à côte ou en volet.
- Zoom, affichage du masque, des vecteurs de mouvement et des zones de sécurité.
- LUT d'affichage facultative pour regarder des rushs en log sans modifier le rendu.
- Plein écran sur un second moniteur.

### 4.9 Export

- File d'attente d'export : plusieurs plans et plusieurs formats, traités en arrière-plan avec estimation du temps restant.
- Modèle de nommage, par exemple `{plan}_remanence_v{version}`.
- Export d'une seule image en PNG 16 bits ou EXR.
- Vérification automatique après export : durée en images, cadence, résolution et timecode identiques à la source.

### 4.10 Échanges avec d'autres logiciels

- Import d'une EDL ou d'un FCP XML (via OpenTimelineIO) pour retrouver les plans à traiter avec leurs timecodes.
- Export d'une liste de remplacement pour que le monteur relie les nouveaux plans en un geste.

### 4.11 Bibliothèque d'effets prédéfinis

Chaque effet est livré avec plusieurs préréglages prêts à l'emploi, et chaque préréglage reste entièrement modifiable : on le glisse sur un clip, une piste ou la séquence, puis on ajuste tous ses paramètres dans l'inspecteur.

- Préréglages fournis (non supprimables) et personnels, enregistrés en JSON dans `%APPDATA%\Remanence`.
- Un préréglage peut porter un effet seul ou toute une pile de pistes.
- Aperçu animé du préréglage au survol.

### 4.12 Scripts de glitch

Certains traitements s'appliquent à une sélection de clips plutôt qu'image par image. Remanence les propose comme des commandes, sur le modèle des scripts Vegas de datamosh et de dd\_GlitchAssist :

- **Scramble** : découper les clips sélectionnés en morceaux d'une durée donnée et les mélanger.
- **Layer** : dupliquer un clip sur plusieurs pistes avec un décalage d'images, pour un effet d'écho.
- **Automator** : poser des images clés aléatoires sur les paramètres d'un effet, avec une graine.
- **Scripts FFglitch** façon dd\_GlitchAssist : Buffer, Delay, Invert-reverse, Zoom, Slice.
- Import de scripts FFglitch JavaScript existants, notamment la bibliothèque de dd\_GlitchAssist (plus de 150 scripts) depuis la copie de l'utilisateur, présentés avec leurs paramètres réglables. Les scripts du dépôt officiel ffglitch-scripts, dans le domaine public (Unlicense), sont inclus d'office et servent de base aux effets codec.

Chaque script crée de nouveaux clips ou de nouvelles images clés sur la timeline : le résultat reste éditable et s'annule d'un Ctrl+Z.

## 5. Catalogue des effets

La version 1.0 livre 29 effets répartis en cinq familles, plus les transitions et les scripts de la section 4.12. Chaque effet est fourni avec au moins trois préréglages, soit une centaine au total. Tous acceptent masques, images clés et modulateurs, et tous ont une intensité relative à la taille de l'image pour que l'aperçu et l'export soient identiques.

| Famille | Effet | Moteur | Étape |
| --- | --- | --- | --- |
| Datamosh | Suppression d'images clés | Codec | 3 |
| Datamosh | Bloom | Codec | 3 |
| Datamosh | Transfert de mouvement | Codec | 3 |
| Datamosh | Opérations sur les vecteurs | Codec | 3 |
| Datamosh | Bavure par flux optique | Flux optique | 4 |
| Datamosh | Persistance (traînées) | Flux optique | 4 |
| Corruption | Databending | Codec | 3 |
| Corruption | Macroblocs (quantification extrême) | Codec | 3 |
| Corruption | Compression JPEG extrême | Temps réel | 5 |
| Corruption | Blocs déplacés | Temps réel | 2 |
| Couleur | Décalage RVB | Temps réel | 2 |
| Couleur | Aberration chromatique radiale | Temps réel | 5 |
| Couleur | Inversion par bandes | Temps réel | 5 |
| Couleur | Postérisation et tramage | Temps réel | 5 |
| Pixels | Tri de pixels (horizontal, vertical, angle libre) | Temps réel | 2 |
| Pixels | Pixellisation | Temps réel | 5 |
| Pixels | Slit-scan | Temps réel | 5 |
| Pixels | Tranches décalées | Temps réel | 5 |
| Signal | Cassette VHS | Temps réel | 2 |
| Signal | Scanlines et lignes qui sautent | Temps réel | 2 |
| Signal | Écran CRT | Temps réel | 5 |
| Signal | Perte de synchro TV | Temps réel | 5 |
| Signal | Feedback / écho d'image | Temps réel | 5 |
| Signal | Grain et bruit | Temps réel | 5 |

S'y ajoutent les cinq effets inspirés de dd\_GlitchAssist, tous sur le moteur codec à l'étape 3 : **Buffer**, **Delay**, **Invert-reverse**, **Zoom** et **Slice**. Les transitions glitch (datamosh, décalage RVB, blocs, coupure de signal) arrivent à l'étape 3 pour la transition datamosh et à l'étape 5 pour les autres.

Ajouter un effet doit être simple : un fichier dans `remanence/effets/` qui décrit ses paramètres et fournit son shader GLSL ou sa fonction. L'interface (réglages, animation, préréglages) se construit alors automatiquement à partir de cette description.

Les shaders repris d'autres projets doivent être sous licence compatible et crédités dans `LICENCES.md`. Les shaders de Shadertoy sont exclus sauf licence explicite, car la licence par défaut du site interdit l'usage commercial, ce qui pose problème sur un film où l'on est rémunéré.

## 6. Interface

L'interface reprend les codes de Vegas Pro et des logiciels de montage courants pour qu'un monteur s'y retrouve sans formation : visionneuse au centre, timeline en bas, réglages à droite.

- **Médias** et Effets (à gauche, en onglets) : médias du projet avec leurs fiches techniques ; bibliothèque d'effets, de transitions et de scripts prédéfinis, classés par famille, avec aperçu animé au survol, à glisser sur un clip, une piste ou la séquence.
- **Visionneuse** (au centre) : image, outils de masque, bascule avant / après, timecode.
- **Inspecteur** (à droite) : réglages du clip d'effet sélectionné, groupés par section, avec une icône d'animation à côté de chaque paramètre.
- **Timeline** (en bas) : pistes vidéo et audio, pistes d'effets, transitions, enveloppes, images clés de la vidéo, marqueurs.
- **Courbes** (onglet de la timeline) : éditeur d'images clés et de modulateurs.
- **File d'export** (onglet de la timeline) : rendus en cours et terminés.

Tous les panneaux sont ancrables, redimensionnables et détachables. La disposition est mémorisée, avec un bouton pour revenir à la disposition par défaut.

**Apparence.** Thème sombre neutre, adapté au travail de l'image (gris proches du neutre, aucun fond coloré qui fausserait la perception des couleurs). Deux accents désaturés, comme dans les logiciels de montage professionnels : mauve `#b07cc6` pour l'action, la sélection et la tête de lecture, turquoise `#5fb4c0` pour l'animation et le focus. Polices IBM Plex Sans et IBM Plex Mono, embarquées dans l'application ; adaptation aux écrans haute densité. Logo : le symbole Tranches. Tout le détail (couleurs des deux thèmes, typographie, composants, fichiers du logo) est dans la charte graphique Remanence.

**Aide intégrée.** Chaque effet a une info-bulle qui explique en une phrase ce qu'il fait. Un panneau « Premiers pas » guide un premier projet de bout en bout. Les messages d'erreur disent quoi faire, en français, avec un bouton « Copier le détail » pour le diagnostic.

## 7. Étapes de développement

Le développement avance en six étapes livrables. Dès la fin de l'étape 3, Remanence est utilisable sur le court-métrage.

**Méthode de travail pour Claude Code.**

- Une étape à la fois. À la fin de chacune : démonstration, tests au vert, et validation de l'utilisateur avant de passer à la suivante.
- Dépôt git, un commit par avancée cohérente, messages en français.
- Un fichier `CLAUDE.md` à la racine tient à jour les décisions, l'état d'avancement et les commandes utiles.
- Le prototype Bavure est placé dans `prototype/` comme référence ; ses algorithmes sont réutilisés, pas son interface.
- Toute bibliothèque ajoutée est inscrite avec sa licence dans `LICENCES.md`.

1. **Socle et visionneuse.**
   - Lecture et écriture de tous les formats via PyAV ; fiche technique ; proxies en arrière-plan.
   - Fenêtre Qt avec panneaux ancrables, visionneuse OpenGL, lecture fluide avec son. Timeline multipiste : glisser des médias, couper, rogner et déplacer des clips vidéo et audio, liaison son et image, aimantation, enveloppes et fondus.
   - Projet `.remanence` (enregistrer, ouvrir, enregistrement automatique), annuler / rétablir.
   - Validation : un export « sans effet » donne la même durée en images, la même cadence, le même timecode et les mêmes pixels que la source, pour ProRes 422 HQ, ProRes 4444 avec alpha, DNxHR HQX, H.264 et HEVC 10 bits.
2. **Effets en temps réel et ciblage.**
   - Graphe de rendu en 16 bits flottants ; les cinq effets du prototype portés en shaders.
   - Effets sur clip, sur piste et sur séquence, clips d'effet ; bibliothèque d'effets prédéfinis à glisser-déposer, tous modifiables, avec enregistrement de variantes ; inspecteur généré à partir de la description des effets.
   - Masques rectangle, ellipse et Bézier avec contour adouci ; images clés sur tous les paramètres ; modes de fusion.
   - Export conforme dans tous les formats de la section 4.1.
   - Validation : hors masque et hors clip, l'export est identique à la source au pixel près.
3. **Moteur codec.**
   - Téléchargement et vérification de FFglitch à l'installation ; moteur de secours Bavure.
   - Piste des images clés de la vidéo ; transition datamosh entre deux clips ; scripts FFglitch façon dd\_GlitchAssist ; suppression d'images clés, bloom, transfert de mouvement, opérations sur les vecteurs, databending, macroblocs.
   - Génération automatique des scripts FFglitch, pré-rendu en cache, recomposition sur l'original.
   - Validation : deux plans ProRes enchaînés produisent une transition qui bave, et le plan exporté se réintègre au montage sans décalage.
4. **Flux optique et modulateurs.**
   - Bavure par flux optique et persistance.
   - Modulateurs : oscillateur, aléatoire lissé, audio, tempo, MIDI.
   - Suivi automatique des masques ; éditeur de courbes complet.
5. **Catalogue complet et confort.**
   - Les 29 effets de la section 5 avec leurs préréglages, toutes les transitions glitch ; scripts Scramble, Layer et Automator. Montage avancé : ripple, roll, slip, slide, vitesse variable, séquences imbriquées, rendu sur place, titres simples.
   - File d'export, modèles de nommage, export d'image fixe, vérification après export.
   - Import EDL et FCP XML, liste de remplacement pour le monteur.
   - LUT d'affichage, avant / après en volet, second moniteur.
6. **Distribution.**
   - `Remanence.exe` autonome avec PyInstaller, FFmpeg et FFglitch inclus ou téléchargés au premier lancement, icône dédiée.
   - Guide utilisateur illustré en français, `LICENCES.md` complet, journal des erreurs dans `%APPDATA%\Remanence`.

## 8. Critères de réussite et tests

Remanence est prêt pour la production quand ces critères sont tenus sur un PC portable récent équipé d'une carte graphique dédiée.

| Critère | Seuil |
| --- | --- |
| Conformité de l'export | Durée en images, cadence, résolution, timecode et métadonnées couleur identiques à la source, à 100 % |
| Intégrité hors effet | Pixels identiques à la source hors masques et hors clips d'effet |
| Lecture de l'aperçu | 24 images/s en proxy 1/2 avec 3 effets temps réel sur une source UHD |
| Export | Plan ProRes 422 HQ UHD de 10 s, avec datamosh codec et 2 effets : moins de 3 minutes |
| Réactivité | Un curseur déplacé met à jour l'image en moins de 100 ms |
| Robustesse | Aucun plantage sur les fichiers du jeu de test |
| Prise en main | Un monteur exporte son premier plan datamoshé en moins de 15 minutes, guide en main |

**Montage.** Une séquence de 10 pistes et 200 clips doit rester fluide : défilement, zoom et lecture sans saccade.

**Jeu de test.** Généré automatiquement par FFmpeg dans `tests/medias/` : ProRes 422 HQ et 4444 avec alpha, DNxHR HQX, H.264 8 bits, HEVC 10 bits, cadence variable, 23,976 et 29,97 avec timecode, portrait, dimensions impaires, vidéo entrelacée, séquence DPX, avec et sans audio.

**Tests automatiques.** Lecture et écriture de chaque format, conformité de l'export, intégrité hors masque, déterminisme (deux rendus identiques), chaque effet aux intensités 0, 50 et 100, sérialisation des projets. Ils tournent avec `pytest` avant chaque commit.

## 9. Annexes

### Message d'amorce pour Claude Code

Ce dossier contient tout le nécessaire : ce cahier des charges, la charte graphique dans `charte/` (couleurs, typographie, composants, logos) et le prototype Bavure dans `prototype/`. Ouvrir le dossier dans Claude Code et envoyer le message indiqué dans `LISEZ-MOI.txt`.

### Inspirations

- FFglitch, l'éditeur de flux binaires sur lequel repose le moteur codec ; ses scripts d'exemple sur les vecteurs de mouvement servent de point de départ.
- Datamosher Pro (Python, utilise FFglitch) pour la liste d'effets : Fluid, Shuffle, Motion Transfer, WaterBloom.
- Mosh-Pro pour l'expérience temps réel et les modulateurs (audio, tempo, MIDI). Logiciel propriétaire : inspiration seulement.
- Datamosh 2 pour After Effects, référence du contrôle précis des vecteurs de mouvement, qui repose lui aussi sur FFglitch en interne. Logiciel propriétaire : inspiration seulement.

* Vegas Pro pour l'ergonomie de montage : effets appliqués sur un clip, une piste ou la sortie, enveloppes et fondus tracés sur les clips. Logiciel propriétaire : inspiration seulement.
* vegas-datamosh, scripts Vegas Pro sous licence MIT (Datamosh, Datamix, Layer, Render, Scramble, Automator) : leurs idées sont reprises en commandes natives.
* dd\_GlitchAssist (Daz Disley), interface Windows pour FFglitch livrée avec plus de 150 scripts JavaScript modifiables : c'est le modèle le plus proche du moteur codec de Remanence. Certains de ses scripts (Buffer, Delay, Invert-reverse, Zoom, Slice) sont déjà repris par Datamosher Pro. Sa licence n'est pas précisée : demander l'accord de l'auteur avant d'inclure ses scripts.

- ffglitch-scripts (Ramiro Polla), le dépôt officiel de scripts FFglitch, dans le domaine public : ses scripts peuvent être repris et modifiés librement dans Remanence.

### Interfaces FFglitch existantes

Le site de FFglitch recense sept interfaces construites sur son moteur. Remanence est la première à l'intégrer dans un vrai logiciel de montage ; les autres servent de référence pour les scripts et l'ergonomie. Aucune licence n'est indiquée pour les projets gratuits : vérifier avant de reprendre du code.

| Interface | Auteur | Type | Ce qu'on en retient |
| --- | --- | --- | --- |
| [Live Mosher](https://github.com/pawelzwronek/LiveMosher) | Pawel Zwronek | Multiplateforme | Éditeur de scripts avec lecture en direct : modèle pour le mode expert |
| [dd\_GlitchAssist](https://dazdisley.co.uk/dd_GlitchAssist/) | Daz Disley | Windows | Plus de 150 scripts, référence des effets codec |
| [Datamosh 2](https://aescripts.com/datamosh) | Danny Perry | Plugin After Effects (payant) | Contrôle fin intégré à un logiciel hôte |
| [glitchbox-cli](https://github.com/pcktm/glitchbox-cli) | Jakub Kopańko | Ligne de commande | Écriture simplifiée des scripts |
| [Datamoshing in python](https://github.com/tiberiuiancu/datamoshing) | Tiberiu Iancu | Python, ligne de commande | Pilotage de FFglitch depuis Python, scripts dd\_GlitchAssist |
| [Datamoshing-GUI](https://github.com/CubeZeero/datamoshing_GUI) | CubeZeero | Python, interface graphique | Variante graphique du précédent |
| Datamosher Pro | Akascape | Python, interface graphique | Liste d'effets et modes de fusion de clips |

### Noms écartés

| Nom | Raison |
| --- | --- |
| Rémanence (avec accent) | Peu pratique en anglais ; Remanence garde le sens dans les deux langues |
| Bavure | Très parlant en français, intraduisible ; reste le nom du prototype |
| Interframe | Déjà utilisé par un outil vidéo d'interpolation d'images |

### Sources

- [FFglitch, the multimedia bitstream editor (FOSDEM 2025)](https://fosdem.org/schedule/event/fosdem-2025-6416-ffglitch-the-multimedia-bitstream-editor)
- [Tutoriel ffglitch-scripts](https://cdn.jsdelivr.net/gh/ramiropolla/ffglitch-scripts@main/tutorial/readme.md)
- [Datamosher Pro : modes FFglitch](https://github.com/Akascape/Datamosher-Pro/wiki/7.FFGLITCH-Modes)
- [Mosh, conditions d'utilisation](https://moshpro.app/terms/)
- [Mosh-Pro, historique des versions](https://moshpro.app/history)
- [Datamosh 2 (aescripts)](https://aescripts.com/datamosh)
- [InterFrame (discussion Doom9)](https://forum.doom9.org/archive/index.php/t-160226-p-17.html)

* [vegas-datamosh (GitHub)](https://github.com/delthas/vegas-datamosh)

- [dd\_GlitchAssist (Daz Disley)](https://dazdisley.co.uk/dd_GlitchAssist/)

* [ffglitch-scripts (GitHub)](https://github.com/ramiropolla/ffglitch-scripts)

- [FFglitch : Frontends](https://ffglitch.org/frontends/)
