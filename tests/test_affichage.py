"""LUT d'affichage et avant / après (étape 5, lot 6) : les moniteurs seulement."""

import numpy as np

from remanence.rendu import lut as module_lut


def _cube(tmp_path, n=5, transformer=lambda r, v, b: (r, v, b)):
    lignes = ['TITLE "Essai"', f"LUT_3D_SIZE {n}"]
    for b in range(n):
        for v in range(n):
            for r in range(n):
                lignes.append(" ".join(f"{x:.6f}" for x in transformer(r / (n - 1), v / (n - 1),
                                                                     b / (n - 1))))
    chemin = tmp_path / "essai.cube"
    chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    return chemin


def test_lecture_et_application_d_une_lut(tmp_path):
    neutre = module_lut.lire_cube(_cube(tmp_path))
    assert neutre.nom == "Essai" and neutre.taille == 5
    image = np.random.default_rng(1).random((8, 9, 3)).astype(np.float32)
    assert np.allclose(module_lut.appliquer(image, neutre), image, atol=1e-5), "neutre"
    inverse = module_lut.lire_cube(_cube(tmp_path, transformer=lambda r, v, b: (1 - r, 1 - v,
                                                                                 1 - b)))
    assert np.allclose(module_lut.appliquer(image, inverse), 1 - image, atol=1e-5)
    canaux = module_lut.lire_cube(_cube(tmp_path, transformer=lambda r, v, b: (b, r, v)))
    assert np.allclose(module_lut.appliquer(image, canaux), image[..., [2, 0, 1]], atol=1e-5), \
        "le rouge varie le plus vite dans le fichier"
