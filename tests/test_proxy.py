from fractions import Fraction

import numpy as np

from remanence.media.intermediaire import creer_intermediaire
from remanence.media.lecteur import AudioCache, generer_cache_audio
from remanence.media.proxy import chemin_audio, generer_proxy, proxy_utile
from remanence.media.sonde import analyser


def test_proxy_demi_resolution(medias, tmp_path):
    infos, _ = analyser(str(medias["dnxhr_hqx"]))
    assert proxy_utile(infos, largeur_mini=100)
    p = generer_proxy(infos, cible=tmp_path / "proxy.mov")
    v = analyser(str(p))[0].video
    assert (v.largeur, v.hauteur, v.nb_images) == (320, 180, 24)
    assert v.profil == "Proxy" and Fraction(v.cadence) == Fraction(30000, 1001)
    assert (v.couleur.primaires, v.couleur.matrice) == (1, 1)


def test_pas_de_proxy_pour_le_rvb(medias):
    infos, _ = analyser(str(medias["dpx"]), "24")
    assert not proxy_utile(infos, largeur_mini=100)


def test_cache_audio(medias):
    infos, _ = analyser(str(medias["prores_hq"]))
    f = generer_cache_audio(infos, chemin_audio(infos))
    cache = AudioCache(f)
    assert abs(cache.nb - round(30 * 1001 / 24000 * 48000)) <= 1024
    bloc = cache.lire(-10, 20)
    assert np.all(bloc[:10] == 0) and np.abs(bloc[10:]).max() < 0.31


def test_intermediaire_cadence_fixe(medias):
    infos, _ = analyser(str(medias["vfr"]))
    sortie = creer_intermediaire(infos)
    v = analyser(str(sortie))[0].video
    # Images espacées de 33, 33 puis 50 ms : 25,8 i/s en moyenne, la cadence standard la plus
    # proche est 25 i/s, et la durée doit être conservée à une image près.
    assert not v.cadence_variable and Fraction(v.cadence) == Fraction(25)
    _, index = analyser(str(medias["vfr"]))
    duree_source = float((index.pts[-1] - index.pts[0]) * index.base_temps) + 0.05
    assert abs(v.nb_images / 25 - duree_source) <= 1 / 25
    assert v.codec == "prores"


def test_intermediaire_ramene_la_plage_complete(medias):
    """La mire en plage complète doit garder les mêmes couleurs une fois en ProRes."""
    from remanence.media.lecteur import LecteurVideo
    from remanence.rendu.couleur import vers_rvba
    infos, index = analyser(str(medias["vfr"]))
    sortie = creer_intermediaire(infos)
    infos_i, index_i = analyser(str(sortie))
    assert infos_i.video.couleur.plage == 1
    a = LecteurVideo(infos.chemin, index).image(0)
    b = LecteurVideo(str(sortie), index_i).image(0)
    ecart = np.abs(vers_rvba(a, infos.video.couleur) - vers_rvba(b, infos_i.video.couleur))
    assert np.median(ecart[..., :3]) < 0.01
