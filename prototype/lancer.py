"""Point d'entrée : double-clique sur « Lancer Bavure.bat » ou tape  python lancer.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bavure.app import main

main()
