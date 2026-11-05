# Licences

Remanence est édité par l'association Flux Croisés, sans but commercial. C'est un logiciel libre sous licence **GNU GPL version 3** (texte dans `LICENSE`, et `licences/gpl-3.0.txt` à côté du programme) : chacun peut l'utiliser, l'étudier, le modifier et le redistribuer, à condition de redistribuer aussi le code source sous la même licence. Il est distribué en code source et en programme Windows (`Remanence.exe`, construit par `Construire.bat`). Ce fichier liste tout ce que le programme embarque, sa version et sa licence ; il est mis à jour à chaque ajout de dépendance. Les textes des licences sont dans le dossier `licences` livré à côté de `Remanence.exe`.

## Embarqué dans Remanence.exe

| Composant | Version | Rôle | Licence |
| --- | --- | --- | --- |
| Python | 3.12.16 | Langage | PSF |
| Bibliothèques livrées avec Python : OpenSSL, libffi, bzip2, xz, expat, mpdecimal, zlib | OpenSSL 3.5.9 | Réseau (téléchargement de FFglitch), types C, archives | Apache 2.0 (OpenSSL), MIT (libffi, expat), BSD (bzip2, mpdecimal), 0BSD (xz), zlib |
| Runtime Visual C++ (VCRUNTIME140, MSVCP140) | fourni par Python et Qt | Bibliothèques système de Microsoft | Licence de redistribution de Microsoft Visual C++ |
| PySide6 et shiboken6 (Qt 6 : Core, Gui, Widgets, OpenGL, Svg, Network) | 6.12.0 | Interface | LGPL 3 |
| Composants tiers de Qt (FreeType, HarfBuzz, libpng, libjpeg, PCRE2, double-conversion, md4c…) | fournis par Qt 6.12.0 | Polices, images, texte | Licences libres listées par Qt : https://doc.qt.io/qt-6/licenses-used-in-qt.html |
| Mesa llvmpipe (`opengl32sw.dll`) | fourni par Qt | OpenGL sans carte graphique | MIT |
| PyAV | 19.0.2 | Lecture et écriture des médias | BSD 3 clauses |
| FFmpeg (embarqué dans PyAV : avcodec, avformat, avfilter, avutil, avdevice, swscale, swresample) | 9.0.2 | Décodeurs, encodeurs, conteneurs | LGPL 3 ou ultérieure (compilé sans `--enable-gpl`) |
| x264 (embarqué dans PyAV, `libx264-165.dll`) | build 165 | Encodage H.264 | GPL 2 ou ultérieure |
| x265 (embarqué dans PyAV) | 4.3 | Encodage HEVC | GPL 2 ou ultérieure |
| LAME (dans avcodec) | fourni par PyAV | MP3 | LGPL 2 ou ultérieure |
| libiconv (embarqué dans PyAV) | fourni par PyAV | Conversion de texte | LGPL 2.1 ou ultérieure |
| dav1d | 1.5.4 | Décodage AV1 | BSD 2 clauses |
| SVT-AV1 | fourni par PyAV | Encodage AV1 | BSD 3 clauses Clear, avec licence de brevets AOM |
| libvpx | 1.17.0 | Encodage VP9 (WebM) | BSD 3 clauses, avec licence de brevets |
| Opus | 1.6.1 | Son des fichiers WebM | BSD 3 clauses |
| libwebp, sharpyuv | fournis par PyAV | Images WebP | BSD 3 clauses |
| libvmaf | fourni par PyAV | Mesure de qualité (dépendance d'FFmpeg) | BSD 2 clauses avec brevets |
| libvpl | fourni par PyAV | Encodage matériel Intel | MIT |
| zlib | 1.3.2 | Compression | zlib |
| Runtime GCC (libgcc_s, libstdc++), winpthreads | fournis par PyAV | Bibliothèques de compilation des DLL d'FFmpeg | GPL 3 avec exception de la bibliothèque d'exécution GCC ; MIT et ZPL 2.1 (winpthreads) |
| NumPy | 2.5.4 | Tampons d'images et de son | BSD 3 clauses (et 0BSD, MIT, Zlib, CC0 pour des parties) |
| OpenBLAS (embarqué dans NumPy) | fourni par NumPy | Calcul matriciel | BSD 3 clauses |
| moderngl et glcontext | 5.13.0 et 3.1.0 | Affichage OpenGL et composition | MIT |
| sounddevice et PortAudio | 0.5.6 et 19.7.0 | Lecture du son | MIT |
| cffi, pycparser | 2.1.1 et 3.12 | Dépendances de sounddevice | MIT-0, BSD 3 clauses |
| OpenCV (opencv-contrib-python-headless) | 5.0.0.93 | Flux optique, suivi des masques | Apache 2.0 |
| FFmpeg d'OpenCV (`opencv_videoio_ffmpeg500_64.dll`) | fourni par OpenCV | Lecture vidéo d'OpenCV (non utilisée par Remanence, livrée avec le paquet) | LGPL 2.1 ou ultérieure |
| mido | 1.3.3 | Messages MIDI | MIT |
| python-rtmidi et RtMidi | 1.5.8 | Ports MIDI de Windows | MIT |
| OpenTimelineIO | 0.18.1 | Montages EDL et FCP XML, liste de remplacement | Apache 2.0 |
| otio-cmx3600-adapter, otio-fcp-adapter | 1.0.0 | Formats EDL CMX 3600 et FCP XML | Apache 2.0 |
| setuptools, packaging | 84.2.1 et 26.3 | Découverte des formats d'OpenTimelineIO | MIT ; Apache 2.0 ou BSD 2 clauses |
| Chargeur de PyInstaller | 6.22.3 | Lance `Remanence.exe` | GPL 2 avec exception (distribuable sous toute licence) |
| IBM Plex Sans et IBM Plex Mono | 1.1.0 et 2.5.0 | Polices de l'interface | SIL Open Font License 1.1 (`OFL-IBM-Plex.txt`) |
| Lucide (lucide-static) | 1.66.0 | Icônes de l'interface | ISC (`LICENCE-Lucide.txt`) |

## Téléchargé à la demande

| Composant | Version | Rôle | Licence |
| --- | --- | --- | --- |
| FFglitch (ffgac, ffedit), avec Xvid, QuickJS, zlib-ng, SDL2, RtMidi, ZeroMQ | 0.10.2 | Moteur codec : encodage MPEG-4 sans macroblocs intra, réécriture des vecteurs de mouvement. Programme externe, non modifié, téléchargé depuis ffglitch.org au premier lancement ou par `Installer.bat` (empreinte SHA-256 vérifiée) ; il n'est pas dans `Remanence.exe` | GPL 2 ou ultérieure |

## Outils de développement (non livrés)

| Outil | Version | Rôle | Licence |
| --- | --- | --- | --- |
| PyInstaller et pyinstaller-hooks-contrib | 6.22.3 et 2026.9 | Construction de `Remanence.exe` | GPL 2 avec exception ; GPL 2 et Apache 2.0 |
| pytest | 9.2.0 | Tests automatiques | MIT |
| uv | 0.13.6 | Installation de l'environnement | MIT ou Apache 2.0 |
| Inno Setup | 6.7.3 | Construction de l'installateur `Remanence-<version>-installation.exe` ; son programme d'installation et de désinstallation est livré dans ce fichier | Licence d'Inno Setup (permissive : usage libre, y compris commercial, mentions de copyright conservées) |

## Obligations de la distribution

- **LGPL (Qt, FFmpeg, LAME, libiconv)** : ces bibliothèques restent des fichiers séparés (DLL) dans le dossier `_internal` ; on peut les remplacer par une autre version compatible. Leurs sources : Qt sur https://download.qt.io (version 6.12.0), FFmpeg sur https://ffmpeg.org/releases (version 9.0.2), et la façon dont PyAV les compile sur https://github.com/PyAV-Org/pyav-ffmpeg.
- **GPL 2 (x264, x265)** : leurs sources sont sur https://code.videolan.org/videolan/x264 et https://bitbucket.org/multicoreware/x265_git (versions indiquées plus haut). Flux Croisés fournit sur demande, pendant trois ans après la diffusion de cette version de Remanence, une copie du code source de Remanence et des sources des composants sous GPL et LGPL qu'elle livre.
- Les textes complets des licences (GPL 2 et 3, LGPL 2.1 et 3, et les licences de chaque paquet) sont copiés dans le dossier `licences` du programme livré.

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
