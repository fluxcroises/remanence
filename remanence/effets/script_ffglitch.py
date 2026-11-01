"""Script FFglitch : un script JavaScript de la bibliothèque (fournis, importés) ou écrit dans
l'éditeur (mode expert). Ses déclarations numériques du haut deviennent des réglages
(moteur codec, FFglitch)."""

from remanence.effets import DescriptionEffet, Parametre
from remanence.moteurs.codec import scripts

BLOCS = Parametre("blocs", "Blocs", 1, 31, 2)


def parametres_de(effet) -> list[Parametre]:
    """Les réglages trouvés dans le script de l'effet, puis Blocs. La plage s'étend autour de
    la valeur du script."""
    resultat = []
    for nom, v in scripts.reglages(effet.script if effet is not None else "").items():
        decimales = 0 if float(v).is_integer() else 2
        haut = max(1.0, abs(v) * 4)
        resultat.append(Parametre(nom, nom, -haut if v < 0 else 0, haut, v, "", decimales))
    return resultat + [BLOCS]


def script(valeurs: list[dict], graine: int, effet=None) -> str:
    noms = scripts.reglages(effet.script)
    reglages = {nom: effet.params.get(nom, v) for nom, v in noms.items()}
    return scripts.adapter(effet.script, reglages, graine)


def _textes() -> dict[str, str]:
    return {nom: texte for nom, (texte, fourni) in scripts.bibliotheque().items() if fourni}


_FOURNIS = _textes()

DESCRIPTION = DescriptionEffet(
    cle="script_ffglitch",
    nom="Script FFglitch",
    famille="Scripts",
    moteur="codec",
    script=script,
    parametres=[BLOCS],
    parametres_de=parametres_de,
    prereglages={nom: {} for nom in _FOURNIS},
    textes=_FOURNIS,
)
