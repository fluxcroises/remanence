"""Point d'entrée de Remanence.exe (PyInstaller) : le même que python -m remanence."""

import sys

from remanence.__main__ import principal

if __name__ == "__main__":
    sys.exit(principal())
