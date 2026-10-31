# Bavure · datamosh & glitch

Petit logiciel Windows pour faire baver, fondre et casser des vidéos.

## Installation (une seule fois)

1. Installe Python depuis https://www.python.org/downloads/ (coche **Add python.exe to PATH**).
2. Décompresse le dossier `Bavure` où tu veux.
3. Double-clique sur **Installer.bat** (il télécharge les bibliothèques et FFmpeg, quelques minutes).

## Utilisation

Double-clique sur **Lancer Bavure.bat**.

1. **Ouvrir une vidéo…** (MP4, MOV, AVI, MKV…).
2. Onglet **Datamosh** : règle les effets puis **Calculer l'aperçu datamosh** (aperçu en basse résolution).
3. Onglet **Glitchs** : les curseurs s'appliquent en direct sur l'aperçu.
4. Onglet **Export** : choisis résolution et qualité, puis **Exporter en MP4…**

Barre d'espace = lecture / pause. Les petits traits roses au-dessus de la frise marquent les images clés,
le rond cyan marque le bloom.

## Les effets en deux mots

| Effet | Ce qu'il fait |
|---|---|
| Supprimer les images clés | Au changement de plan, l'ancienne image reste et « bave » avec le mouvement de la nouvelle. Il faut donc une vidéo avec des coupes, ou deux clips enchaînés (**+ Ajouter un clip**). |
| Bloom | Le mouvement d'une image est répété N fois : les pixels coulent et fondent. Marche même sans coupe. |
| Taille des blocs | Plus c'est haut, plus les macroblocs sont gros et visibles. |
| Databending | Corrompt des octets au hasard. Change la **graine** (🎲) pour un autre résultat. |
| Décalage RVB, tri de pixels, scanlines, blocs déplacés, VHS | Effets visuels image par image. |

**Astuce** : Bavure recrée lui-même les images clés en détectant les changements de plan.
Une vidéo en un seul plan continu n'en a donc qu'une au début : dans ce cas, utilise le **bloom**
ou enchaîne un deuxième clip. Restreins la zone Début / Fin pour ne faire baver qu'une seule coupe.

## Bon à savoir

- Le son d'origine est conservé quand un seul clip est chargé (le bloom allonge la vidéo, le son s'arrête avant).
- L'aperçu datamosh est calculé en 854 px de large ; l'export se fait à la résolution choisie,
  donc le rendu peut légèrement différer (les blocs sont relatifs à la résolution).
- Dossier `bavure/` : `moteur_mosh.py` (datamosh), `effets.py` (glitchs), `rendu.py` (export), `app.py` (interface).
