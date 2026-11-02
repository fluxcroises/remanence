# Licences des dépendances

Remanence est distribué en code source, sans but commercial. Ce fichier liste chaque bibliothèque utilisée, sa version et sa licence. Il est mis à jour à chaque ajout de dépendance.

| Bibliothèque | Version | Rôle | Licence |
| --- | --- | --- | --- |
| Python | 3.12.16 | Langage | PSF |
| PySide6 et shiboken6 (Qt 6) | 6.12.0 | Interface | LGPL 3 (ou GPL 2 / GPL 3) |
| PyAV | 19.0.2 | Lecture et écriture des médias | BSD 3 clauses |
| FFmpeg (embarqué dans PyAV) | libavcodec 63.1 | Décodeurs, encodeurs, conteneurs | LGPL 3 ou ultérieure |
| x264 et x265 (embarqués dans PyAV) | fournis par PyAV | Encodage H.264 et HEVC | GPL 2 ou ultérieure |
| SVT-AV1 (embarqué dans PyAV) | fourni par PyAV | Encodage AV1 | BSD 3 clauses (avec licence de brevets AOM) |
| libvpx (embarqué dans PyAV) | fourni par PyAV | Encodage VP9 (WebM) | BSD 3 clauses |
| Opus (embarqué dans PyAV) | fourni par PyAV | Son des fichiers WebM | BSD 3 clauses |
| NumPy | 2.5.4 | Tampons d'images et de son | BSD 3 clauses (et 0BSD, MIT, Zlib, CC0 pour des parties) |
| moderngl et glcontext | 5.13.0 et 3.1.0 | Affichage OpenGL de la visionneuse | MIT |
| sounddevice (et PortAudio) | 0.5.6 | Lecture du son | MIT |
| cffi | 2.1.1 | Dépendance de sounddevice | MIT-0 |
| IBM Plex Sans et IBM Plex Mono | 1.1.0 et 2.5.0 | Polices de l'interface, embarquées dans `remanence/ressources/polices` | SIL Open Font License 1.1 (texte joint : `OFL-IBM-Plex.txt`) |
| Lucide (lucide-static) | 1.66.0 | Icônes de l'interface, dans `remanence/ressources/icones` | ISC (texte joint : `LICENCE-Lucide.txt`) |
| FFglitch (ffgac, ffedit), avec Xvid, QuickJS, zlib-ng, SDL2, RtMidi, ZeroMQ | 0.10.2 | Moteur codec : encodage MPEG-4 sans macroblocs intra, réécriture des vecteurs de mouvement. Programme externe, téléchargé par `Installer.bat` dans `outils/` (empreinte SHA-256 vérifiée), non modifié | GPL 2 ou ultérieure |
| OpenCV (opencv-contrib-python-headless) | 5.0.0.93 | Flux optique DIS du moteur flux optique, suivi des masques (étape 4). Version sans interface : la version complète embarque son propre Qt | Apache 2.0 |
| mido | 1.3.3 | Messages MIDI des contrôleurs (modulateurs, étape 4) | MIT |
| python-rtmidi (et RtMidi) | 1.5.8 | Accès aux ports MIDI de Windows pour mido | MIT |
| pytest | 9.2.0 | Tests automatiques (développement seulement) | MIT |
| uv | 0.13.6 | Installation de l'environnement (outil, non embarqué) | MIT ou Apache 2.0 |

## Code repris

- Prototype Bavure (`prototype/`) : code du même auteur, utilisé comme référence pour les algorithmes à partir de l'étape 2.
- Charte graphique, maquettes et logo (symbole Tranches) : fournis par l'auteur du projet, dans `UI/`.
- Remanence est édité par l'association Flux Croisés ; son logo lui appartient.
- Remanence fait partie de Creative Orbit, la famille de logiciels de Flux Croisés ; le logo
  Creative Orbit (`UI/charte/assets/Logos/creative-orbit-sombre.*`) lui appartient. Il s'utilise
  selon les règles de son kit : 24 px de haut au moins, espace libre autour, jamais recoloré.
- Le script des vecteurs de mouvement (`remanence/effets/vecteurs.py`) reprend les idées des
  scripts du tutoriel de ffglitch-scripts (Ramiro Polla, domaine public, Unlicense) :
  `mv_pan`, `mv_average`, `mv_sink_and_rise`. Aucun shader tiers n'est inclus.
- Scripts fournis de la bibliothèque (`remanence/ressources/scripts_ffglitch/`) : adaptés des
  scripts du tutoriel de ffglitch-scripts (domaine public, Unlicense), avec mention d'origine
  en tête de chaque fichier.
- Écho de mouvement, Zoom de mouvement, Inversion et Zoom par saccades : idées des scripts
  Delay, Buffer, Zoom, Invert-reverse et Slice de dd_GlitchAssist (Daz Disley, licence non
  précisée), tels que repris par Datamosher Pro (MIT). Le code est écrit pour Remanence, sans
  reprise. Les scripts de dd_GlitchAssist ne sont pas inclus : l'utilisateur importe sa propre
  copie (Fichier > Importer des scripts FFglitch), qui reste sur sa machine.
