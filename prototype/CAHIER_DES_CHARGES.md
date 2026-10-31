# Bavure : cahier des charges de la version complète

À donner à Claude Code en ouvrant ce dossier : « Lis CAHIER_DES_CHARGES.md et fais évoluer le prototype
vers la version complète, étape par étape, en me montrant chaque étape avant de passer à la suivante. »

## 1. Contexte

Bavure est un logiciel Windows de datamosh et d'effets glitch sur des fichiers vidéo, pour un usage créatif
(clips, courts-métrages, contenus pour les réseaux). L'utilisateur n'est pas développeur : tout doit
s'installer et se lancer par double-clic, et l'interface doit être entièrement en français.

Un prototype fonctionnel existe déjà dans ce dossier. Il faut **le faire évoluer, pas le réécrire** :
le moteur de datamosh (`bavure/moteur_mosh.py`) est validé et doit être conservé tel quel dans son principe.

## 2. Ce que fait déjà le prototype

| Fichier | Rôle |
|---|---|
| `bavure/outils.py` | Localise FFmpeg (fourni par `imageio-ffmpeg`), lit les infos vidéo, lance les commandes sans fenêtre console |
| `bavure/moteur_mosh.py` | Réencode en MPEG-4 Part 2 sans images B, découpe le flux brut aux marqueurs `00 00 01 B6`, supprime les images I dans une zone, répète des images P (bloom), databending sur les images P |
| `bavure/effets.py` | Effets image par image (numpy/OpenCV) : décalage RVB, tri de pixels vectorisé, scanlines, blocs déplacés, VHS |
| `bavure/rendu.py` | Chaîne complète : flux moshé, décodage par tuyau, effets Python, encodage H.264 + AAC |
| `bavure/app.py` | Interface tkinter sombre : lecteur avec frise, repères des images clés, aperçu datamosh basse résolution, glitchs en direct, préréglages, export avec progression et annulation |

Principes techniques à respecter :
- Ne jamais écrire les octets `0x00` ou `0x01` lors du databending (risque de faux marqueur de début d'image).
- Une image I supprimée est remplacée par une copie de l'image P précédente pour garder la synchro audio.
- Les intensités des effets sont relatives à la taille de l'image (aperçu et export identiques).
- Tout traitement long tourne dans un thread, l'interface ne doit jamais se figer.

## 3. Évolutions demandées (par ordre de priorité)

### Étape 1 : chronologie et automatisation
- **Frise d'édition** sous l'aperçu : zones de datamosh et instants de bloom posés et déplacés à la souris,
  plusieurs zones et plusieurs blooms par vidéo (le moteur accepte déjà `blooms_supplementaires`).
- **Images clés cliquables** : chaque repère rose peut être conservé ou supprimé individuellement.
- **Courbes d'animation** pour chaque effet glitch : intensité qui varie dans le temps (points clés sur la frise),
  avec interpolation linéaire ou par paliers.
- **Option « images clés forcées »** : insérer une image clé toutes les N secondes pour pouvoir datamosher
  une vidéo en plan continu.

### Étape 2 : nouveaux effets
- Datamosh : **vecteurs de mouvement inversés ou amplifiés** (à étudier ; si trop complexe en MPEG-4 Part 2,
  proposer une alternative par flux optique OpenCV qui déplace les pixels de l'image précédente).
- Glitch : **décalage de lignes façon signal TV**, **compression JPEG extrême**, **pixellisation**, **inversion
  de couleurs par bandes**, **feedback / écho d'image**, **chromatic aberration radiale**.
- **Sonification** : appliquer un effet audio (écho, réverbération, bitcrush) aux données d'une image puis la
  relire comme image (databending façon Audacity).
- **Glitch audio** optionnel synchronisé (bégaiement du son pendant un bloom).

### Étape 3 : confort
- **Glisser-déposer** de fichiers dans la fenêtre (bibliothèque `tkinterdnd2`).
- **Liste des clips** réordonnable (monter, descendre, retirer), avec durée de chaque clip ; découpe début / fin
  par clip.
- **Audio** conservé et assemblé aussi en mode plusieurs clips.
- **Préréglages personnels** : enregistrer / charger ses réglages (fichiers JSON dans `%APPDATA%\Bavure`),
  avec les préréglages fournis non supprimables.
- **Projets** : enregistrer un projet `.bavure` (sources + réglages + frise) et le rouvrir.
- **Historique annuler / rétablir** (Ctrl+Z / Ctrl+Y) sur les réglages.
- **Aperçu en qualité finale** d'un court extrait (3 secondes autour de la position) avant l'export complet.
- **Export de l'image courante** en PNG, et export **GIF** (palette optimisée) ou **WebM**.
- Export **ProRes** (`prores_ks`) pour reprise dans un logiciel de montage.
- Raccourcis clavier : espace (lecture), flèches (image par image), Ctrl+O, Ctrl+E.

### Étape 4 : distribution
- Exécutable Windows autonome avec **PyInstaller** (`Bavure.exe`, sans installer Python), icône dédiée,
  FFmpeg inclus.
- Fichier de configuration et journaux d'erreurs dans `%APPDATA%\Bavure` ; en cas d'erreur, message clair en
  français et bouton « Copier le détail ».

## 4. Exigences générales
- Windows 10 et 11, Python 3.11 ou plus récent pour le développement.
- Interface entièrement en français ; dans les textes français, ne jamais utiliser le tiret cadratin (—).
- Garder le thème sombre actuel (fond `#141418`, accent rose `#ff3d7f`, cyan `#3df2ff`).
- Vidéos jusqu'à 4K acceptées ; l'aperçu reste en basse résolution pour rester fluide.
- Ne jamais modifier les fichiers sources de l'utilisateur ; les fichiers temporaires vont dans le dossier
  temporaire système et sont supprimés à la fermeture.
- Code commenté en français, découpé en modules ; tests automatiques (`pytest`) pour le moteur de datamosh
  et les effets, sur des vidéos de test générées avec FFmpeg (`testsrc2`, `mandelbrot`).

## 5. Critères de réussite
1. Une vidéo de téléphone 1080p de 30 secondes s'exporte avec datamosh et deux effets glitch en moins de 2 minutes
   sur un PC portable récent.
2. Deux clips enchaînés produisent une transition qui bave visiblement de l'un à l'autre.
3. Un utilisateur novice installe, lance et exporte sa première vidéo sans aide, en suivant le README.
4. Aucun plantage sur des fichiers MP4, MOV, AVI, MKV, en portrait, aux dimensions impaires, avec ou sans son.
