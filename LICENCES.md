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
| pytest | 9.2.0 | Tests automatiques (développement seulement) | MIT |
| uv | 0.13.6 | Installation de l'environnement (outil, non embarqué) | MIT ou Apache 2.0 |

## Code repris

- Prototype Bavure (`prototype/`) : code du même auteur, utilisé comme référence pour les algorithmes à partir de l'étape 2.
- Charte graphique, maquettes et logo (symbole Tranches) : fournis par l'auteur du projet, dans `UI/`.
- Remanence est édité par l'association Flux Croisés ; son logo lui appartient.
- Remanence fait partie de Creative Orbit, la famille de logiciels de Flux Croisés ; le logo
  Creative Orbit (`UI/charte/assets/Logos/creative-orbit-sombre.*`) lui appartient. Il s'utilise
  selon les règles de son kit : 24 px de haut au moins, espace libre autour, jamais recoloré.
- Aucun shader et aucun script tiers n'est inclus à ce stade.
