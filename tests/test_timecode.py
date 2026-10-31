from fractions import Fraction

import pytest

from remanence.media.timecode import images_vers_tc, tc_vers_images

C2398 = Fraction(24000, 1001)
C2997 = Fraction(30000, 1001)


@pytest.mark.parametrize("texte,cadence,images", [
    ("01:00:00:00", C2398, 86400),
    ("00:00:01:00", Fraction(25), 25),
    ("10:00:00:00", Fraction(25), 900000),
    ("00:01:00;02", C2997, 1800),
    ("00:10:00;00", C2997, 17982),
    ("01:00:00;00", C2997, 107892),
])
def test_aller_retour(texte, cadence, images):
    n, drop = tc_vers_images(texte, cadence)
    assert n == images
    assert images_vers_tc(n, cadence, drop) == texte


def test_drop_frame_saute_les_bonnes_images():
    assert images_vers_tc(1799, C2997, True) == "00:00:59;29"
    assert images_vers_tc(1800, C2997, True) == "00:01:00;02"
    for n in range(0, 40000, 7):
        tc = images_vers_tc(n, C2997, True)
        assert tc_vers_images(tc, C2997)[0] == n


def test_drop_ignore_hors_29_97():
    n, drop = tc_vers_images("00:00:01;00", Fraction(25))
    assert (n, drop) == (25, False)
