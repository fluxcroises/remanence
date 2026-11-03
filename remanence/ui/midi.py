"""Contrôleur MIDI : ses boutons et curseurs (messages « control change ») enregistrés en
images clés sur un réglage, pendant la lecture. Le résultat est une courbe ordinaire,
modifiable, et le rendu reste le même d'un export à l'autre.

mido et python-rtmidi lisent les ports MIDI de Windows ; les messages arrivent sur un fil de
rtmidi et passent au fil de l'interface par un signal Qt.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


def ports() -> list[str]:
    """Les entrées MIDI branchées ; aucune si mido ou rtmidi manque."""
    try:
        import mido
        return list(mido.get_input_names())
    except Exception:
        return []


class EnregistreurMidi(QObject):
    # Numéro du contrôle, valeur de 0 à 1.
    recu = Signal(int, float)

    def __init__(self):
        super().__init__()
        self._port = None

    def ouvrir(self, nom: str) -> bool:
        self.fermer()
        try:
            import mido
            self._port = mido.open_input(nom, callback=self.recevoir)
        except Exception:
            self._port = None
            return False
        return True

    def fermer(self):
        if self._port is not None:
            try:
                self._port.close()
            except Exception:
                pass
            self._port = None

    def recevoir(self, message):
        """Appelé par rtmidi pour chaque message (et par les tests)."""
        if getattr(message, "type", "") == "control_change":
            self.recu.emit(int(message.control), message.value / 127)
