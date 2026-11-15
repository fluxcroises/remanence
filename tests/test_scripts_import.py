"""Étape 13, lot 1 : import des scripts de Live Mosher (dd_GlitchAssist, exemples de FFglitch).

Les scripts de Live Mosher n'ont pas de licence déclarée : les tests en fabriquent de faux, qui
reproduisent chaque cas rencontré à l'essai des 109 fichiers du dossier Examples."""

import numpy as np
import pytest

from remanence.effets import nouvel_effet
from remanence.effets import prereglages
from remanence.moteurs.codec import ffglitch, prerendu, scripts
from remanence.rendu.composition import actifs

GRAVITY = """// façon dd_gravity
var gravity = 4;
function glitch_frame(frame) {
  let fwd = frame["mv"] ? frame["mv"]["forward"] : null;
  if (!fwd) return;
  for (let i = 0; i < fwd.length; i++) {
    let row = fwd[i];
    for (let j = 0; j < row.length; j++) {
      let mv = row[j];
      mv[1] += gravity;
    }
  }
}
"""

HELPERS = """export function scaleValue(v, a, b, c, d) { return c + (v - a) * (d - c) / (b - a); }
export function get_forward_mvs(frame) { return frame.mv?.forward; }
"""

AVEC_AIDE = """import { get_forward_mvs, scaleValue } from "./helpers.mjs";
export function setup(args) {
  args.features = ["mv"];
  args.output = "glitched_ailleurs";
}
export function glitch_frame(frame) {
  const fwd = get_forward_mvs(frame);
  if (!fwd) return;
  frame.mv.overflow = "truncate";
  for (let i = 0; i < fwd.length; i++)
    for (let j = 0; j < fwd[i].length; j++)
      fwd[i][j][0] = scaleValue(fwd[i][j][0], 0, 1, 0, 3);
}
"""

MIDI = """import * as rtmidi from 'rtmidi';
export class MIDIInput { constructor() { this.in = new rtmidi.In(); } }
"""

AVEC_MIDI = """import { MIDIInput } from "../../midi.js";
const midi = new MIDIInput();
export function glitch_frame(frame) { }
"""

CLAVIER = """const sdl = new SDL();
export function glitch_frame(frame) { const e = sdl.poll(); }
"""

JPEG = """export function setup(args) { args.features = [ "dqt" ]; }
export function glitch_frame(frame) { }
"""

CROCHET = """export function pict_type_func(args) { return "I"; }
"""

PERDU = """import { x } from "./absent.mjs";
export function glitch_frame(f) { }
"""


@pytest.fixture
def live_mosher(tmp_path):
    racine = tmp_path / "LiveMosher-1.2-win" / "Examples"
    fichiers = {
        "dd-glitch-assist-scriptsv10/instant_damage/dd_gravity.js": GRAVITY,
        "free-for-all/helpers.mjs": HELPERS,
        "free-for-all/mv_average.js": AVEC_AIDE,
        "tutorial/scripts/mpeg4/mv_average.js": GRAVITY,  # même nom, autre dossier
        "midi.js": MIDI,
        "free-for-all/midi/offset.js": AVEC_MIDI,
        "basic-keyboard.js": CLAVIER,
        "free-for-all/perdu.js": PERDU,
        "tutorial/scripts/jpeg/dqt.js": JPEG,
        "free-for-all/pict_types.js": CROCHET,
    }
    for nom, texte in fichiers.items():
        chemin = racine / nom
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(texte, encoding="utf-8")
    return racine


def test_import_du_dossier_de_live_mosher(live_mosher):
    bilan = scripts.importer(live_mosher)
    assert bilan.importes == 5 and bilan.direct == 2
    raisons = dict((n.replace("\\", "/"), r) for n, r in bilan.ignores)
    assert raisons == {"midi.js": "module d'aide", "tutorial/scripts/jpeg/dqt.js":
                       "pour les images", "free-for-all/pict_types.js": "autre usage",
                       "free-for-all/perdu.js": "fichier voisin introuvable"}
    tous = {s.nom: s for s in scripts.scripts_de_la_bibliotheque() if not s.fourni}
    # Noms et dossiers d'origine ; deux scripts de même nom restent tous les deux.
    assert tous["dd gravity"].groupe == "instant damage"
    assert {"mv average", "mv average (mpeg4)"} <= set(tous)
    assert tous["offset"].direct and tous["basic keyboard"].direct
    assert not tous["dd gravity"].direct
    # Les modules voisins sont recopiés dans le script : il se suffit à lui-même.
    texte = tous["mv average"].texte
    assert "import" not in texte and "function scaleValue" in texte
    # Les tuiles de la bibliothèque disent d'où vient le script.
    p = next(p for p in prereglages.fournis() if p.nom == "dd gravity")
    assert p.description == "Script · instant damage"
    assert next(p for p in prereglages.fournis() if p.nom == "offset").description.endswith(
        "direct")


def test_live_mosher_trouve_tout_seul(live_mosher, tmp_path):
    assert scripts.trouver_live_mosher([tmp_path]) == live_mosher
    assert scripts.trouver_live_mosher([tmp_path / "LiveMosher-1.2-win" / "Examples"]) is None


def test_script_direct_sans_action_sur_la_timeline():
    e = nouvel_effet("script_ffglitch", script=CLAVIER)
    assert prerendu.en_direct(e) and not actifs([e])
    with pytest.raises(RuntimeError):
        from remanence.effets.script_ffglitch import script
        script([{}], 1, e)


def test_le_script_ne_choisit_pas_le_fichier_de_sortie():
    texte = scripts.adapter(AVEC_AIDE, {}, 1)
    assert "const __sortie = args.output;" in texte and "args.output = __sortie;" in texte


@pytest.mark.skipif(not ffglitch.disponible(), reason="FFglitch absent")
def test_scripts_importes_agissent(medias, live_mosher):
    """Un script avec module voisin et nom de sortie à lui (mv_average_0.10) et un script
    façon dd_GlitchAssist marchent une fois importés."""
    from tests.test_effets import _image, _projet
    scripts.importer(live_mosher)
    tous = {s.nom: s for s in scripts.scripts_de_la_bibliotheque() if not s.fourni}
    vide, clip = _projet(medias)
    clip.effets = [nouvel_effet("script_ffglitch", script="// rien\n")]
    prerendu.calculer(vide, vide.sequence, clip)
    reference = _image(vide, 20)
    for nom in ("dd gravity", "mv average"):
        projet, clip = _projet(medias)
        clip.effets = [nouvel_effet("script_ffglitch", script=tous[nom].texte)]
        prerendu.calculer(projet, projet.sequence, clip)
        assert np.abs(_image(projet, 20) - reference).max() > 0.002, nom
