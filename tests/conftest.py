import os
import tempfile
from pathlib import Path

import pytest

# Le cache des tests reste isolé de celui de l'utilisateur.
os.environ["REMANENCE_CACHE"] = tempfile.mkdtemp(prefix="remanence_tests_")

from PySide6.QtCore import QSettings  # noqa: E402

# Les dispositions mémorisées pendant les tests ne touchent pas celles de l'utilisateur.
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope,
                  tempfile.mkdtemp(prefix="remanence_reglages_"))

from remanence.config import reglages_interface  # noqa: E402

reglages_interface().setValue("sequence/timecode_debut", "clip")

from tests.generer_medias import generer  # noqa: E402


@pytest.fixture(scope="session")
def medias() -> dict[str, Path]:
    return generer()


@pytest.fixture
def dossier(tmp_path) -> Path:
    return tmp_path
