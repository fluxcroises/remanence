"""Timecode SMPTE : conversion entre numéro d'image et texte HH:MM:SS:FF."""

from __future__ import annotations

from fractions import Fraction


def cadence_nominale(cadence: Fraction) -> int:
    """Nombre d'images par seconde du compteur (24 pour 23,976, 30 pour 29,97)."""
    return max(1, round(float(cadence)))


def est_drop_frame_possible(cadence: Fraction) -> bool:
    return cadence.denominator == 1001 and cadence_nominale(cadence) in (30, 60)


def _images_sautees(cadence: Fraction) -> int:
    # 2 images sautées par minute en 29,97, 4 en 59,94, sauf les minutes multiples de 10.
    return 2 * cadence_nominale(cadence) // 30


def images_vers_tc(images: int, cadence: Fraction, drop: bool = False) -> str:
    nominal = cadence_nominale(cadence)
    signe = "-" if images < 0 else ""
    n = abs(int(images))
    if drop and est_drop_frame_possible(cadence):
        saut = _images_sautees(cadence)
        par_10_min = nominal * 600 - saut * 9
        par_min = nominal * 60 - saut
        dizaines, reste = divmod(n, par_10_min)
        if reste > saut:
            n += saut * 9 * dizaines + saut * ((reste - saut) // par_min)
        else:
            n += saut * 9 * dizaines
    ff = n % nominal
    total_s = n // nominal
    ss = total_s % 60
    mm = (total_s // 60) % 60
    hh = total_s // 3600
    sep = ";" if drop and est_drop_frame_possible(cadence) else ":"
    return f"{signe}{hh:02d}:{mm:02d}:{ss:02d}{sep}{ff:02d}"


def tc_vers_images(texte: str, cadence: Fraction) -> tuple[int, bool]:
    """Renvoie (numéro d'image, drop frame). Accepte ':' ou ';' avant les images."""
    t = texte.strip()
    drop = ";" in t or "." in t[-3:]
    morceaux = t.replace(";", ":").replace(".", ":").split(":")
    if len(morceaux) != 4:
        raise ValueError(f"Timecode illisible : « {texte} »")
    hh, mm, ss, ff = (int(m) for m in morceaux)
    nominal = cadence_nominale(cadence)
    n = ((hh * 60 + mm) * 60 + ss) * nominal + ff
    if drop and est_drop_frame_possible(cadence):
        saut = _images_sautees(cadence)
        minutes = hh * 60 + mm
        n -= saut * (minutes - minutes // 10)
    else:
        drop = False
    return n, drop
