"""Jeu de test généré par FFmpeg (via PyAV) : mire testsrc2, son sinusoïdal, timecodes."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import av
import numpy as np

DOSSIER = Path(__file__).parent / "medias"


def _mire(largeur, hauteur, cadence: Fraction, pix_fmt: str, n: int, source="testsrc2",
          interlace=False):
    g = av.filter.Graph()
    src = g.add(source, f"size={largeur}x{hauteur}:rate={cadence.numerator}/{cadence.denominator}")
    fmt = g.add("format", pix_fmt)
    sink = g.add("buffersink")
    if interlace:
        champ = g.add("setfield", "tff")
        src.link_to(champ)
        champ.link_to(fmt)
    else:
        src.link_to(fmt)
    fmt.link_to(sink)
    g.configure()
    for _ in range(n):
        yield sink.pull()


def _ecrire(nom, codec, pix_fmt, cadence, n, largeur=320, hauteur=180, options=None, tc=None,
            audio=None, alpha=False, couleur=1, interlace=False, source="testsrc2"):
    chemin = DOSSIER / nom
    if chemin.exists():
        return chemin
    DOSSIER.mkdir(parents=True, exist_ok=True)
    partiel = chemin.with_name("partiel_" + nom)
    with av.open(str(partiel), "w") as c:
        if tc:
            c.metadata["timecode"] = tc
        v = c.add_stream(codec, rate=cadence)
        v.width, v.height, v.pix_fmt = largeur, hauteur, pix_fmt
        base_temps = 1 / cadence
        v.time_base = base_temps
        v.codec_context.options = options or {}
        cc = v.codec_context
        cc.color_primaries = cc.color_trc = cc.colorspace = couleur
        cc.color_range = 1
        a = None
        trames_audio = []
        if audio:
            a = c.add_stream(audio, rate=48000)
            a.layout = "stereo"
            trames_audio = _son(n / float(cadence), audio)
        for i, img in enumerate(_mire(largeur, hauteur, cadence, pix_fmt, n, source, interlace)):
            if alpha:
                p = img.planes[3]
                plan = np.frombuffer(p, np.uint16).reshape(p.height, p.line_size // 2).copy()
                rampe = np.linspace(0, 1023, p.width, dtype=np.float32)
                plan[:, : p.width] = ((rampe + i * 37) % 1024).astype(np.uint16)
                p.update(plan.tobytes())
            img.pts = i
            img.time_base = base_temps
            img.color_primaries = img.color_trc = img.colorspace = couleur
            img.color_range = 1
            for paquet in v.encode(img):
                c.mux(paquet)
            while trames_audio and trames_audio[0].pts / 48000 < (i + 1) / float(cadence):
                for paquet in a.encode(trames_audio.pop(0)):
                    c.mux(paquet)
        for paquet in v.encode():
            c.mux(paquet)
        if a is not None:
            for trame in trames_audio:
                for paquet in a.encode(trame):
                    c.mux(paquet)
            for paquet in a.encode():
                c.mux(paquet)
    partiel.replace(chemin)
    return chemin


def _son(duree_s: float, codec: str) -> list:
    total = round(duree_s * 48000)
    t = np.arange(total) / 48000.0
    son = np.stack([np.sin(2 * np.pi * 440 * t), np.sin(2 * np.pi * 660 * t)]) * 0.3
    fmt_a = "fltp" if codec == "aac" else "s32"
    trames = []
    for pos in range(0, total, 1024):
        bloc = son[:, pos:pos + 1024].astype(np.float32)
        if fmt_a == "s32":
            donnees = (np.rint(bloc.T * 8388607).astype(np.int32) << 8).reshape(1, -1)
        else:
            donnees = np.ascontiguousarray(bloc)
        trame = av.AudioFrame.from_ndarray(donnees, format=fmt_a, layout="stereo")
        trame.sample_rate = 48000
        trame.pts = pos
        trame.time_base = Fraction(1, 48000)
        trames.append(trame)
    return trames


def _vfr(nom="cadence_variable.mkv"):
    """Images encodées à 30 i/s puis réhorodatées à intervalles irréguliers, comme un téléphone."""
    chemin = DOSSIER / nom
    if chemin.exists():
        return chemin
    with av.open(str(chemin), "w") as c:
        v = c.add_stream("mjpeg", rate=30)
        v.width, v.height, v.pix_fmt = 320, 180, "yuvj422p"
        base_temps = Fraction(1, 30)
        ms = Fraction(1, 1000)
        t = 0
        for i, img in enumerate(_mire(320, 180, Fraction(30), "yuvj422p", 30)):
            img.pts = i
            img.time_base = base_temps
            for p in v.encode(img):
                p.pts = p.dts = t
                p.time_base = ms
                c.mux(p)
                t += 33 if i % 3 else 50
        for p in v.encode():
            c.mux(p)
    return chemin


def _dpx(nom="sequence_dpx"):
    dossier = DOSSIER / nom
    if dossier.exists() and len(list(dossier.glob("*.dpx"))) == 10:
        return dossier / "plan_000100.dpx"
    dossier.mkdir(parents=True, exist_ok=True)
    for i, img in enumerate(_mire(320, 180, Fraction(24), "rgb48le", 10)):
        with av.open(str(dossier / f"plan_{100 + i:06d}.dpx"), "w", format="image2") as c:
            v = c.add_stream("dpx", rate=24)
            v.width, v.height, v.pix_fmt = 320, 180, "rgb48le"
            img.pts = 0
            for p in v.encode(img):
                c.mux(p)
            for p in v.encode():
                c.mux(p)
    return dossier / "plan_000100.dpx"


def generer() -> dict[str, Path]:
    c2398 = Fraction(24000, 1001)
    c2997 = Fraction(30000, 1001)
    return {
        "prores_hq": _ecrire("prores_422hq_23976_tc.mov", "prores_ks", "yuv422p10le", c2398, 30,
                             options={"profile": "3"}, tc="01:00:00:00", audio="pcm_s24le"),
        "prores_4444": _ecrire("prores_4444_alpha_25_tc.mov", "prores_ks", "yuva444p10le",
                               Fraction(25), 20, options={"profile": "4"}, tc="10:00:00:00",
                               alpha=True),
        "dnxhr_hqx": _ecrire("dnxhr_hqx_2997df_tc.mov", "dnxhd", "yuv422p10le", c2997, 24,
                             largeur=640, hauteur=360, options={"profile": "dnxhr_hqx"},
                             tc="00:59:59;00", audio="pcm_s24le"),
        "h264": _ecrire("h264_8bits_30.mp4", "libx264", "yuv420p", Fraction(30), 40,
                        options={"g": "12", "bf": "2", "crf": "18"}, audio="aac"),
        "hevc10": _ecrire("hevc_10bits_24_tc.mov", "libx265", "yuv420p10le", Fraction(24), 30,
                          options={"g": "10", "x265-params": "log-level=error"}, tc="00:00:10:00"),
        "portrait_impair": _ecrire("prores_4444_portrait_impair.mov", "prores_ks", "yuv444p10le",
                                   Fraction(24), 12, largeur=181, hauteur=321,
                                   options={"profile": "4"}),
        "entrelace": _ecrire("prores_entrelace_25.mov", "prores_ks", "yuv422p10le", Fraction(25),
                             10, largeur=320, hauteur=180, options={"profile": "3", "flags": "+ildct"},
                             interlace=True),
        "sans_audio_2997": _ecrire("prores_lt_2997ndf_tc.mov", "prores_ks", "yuv422p10le", c2997,
                                   15, options={"profile": "1"}, tc="00:10:00:00",
                                   source="mandelbrot"),
        "vfr": _vfr(),
        "dpx": _dpx(),
    }


if __name__ == "__main__":
    for cle, chemin in generer().items():
        print(cle, chemin)
