"""Testy klasyfikacji błędów logowania (wymaga librus-apix i requests)."""

import importlib.util
import unittest
from pathlib import Path

try:
    import librus_apix  # noqa: F401
    import requests  # noqa: F401
except ImportError:  # pragma: no cover
    librus_apix = None

_SCIEZKA = Path(__file__).parents[1] / "custom_components" / "librus_ha" / "api.py"


@unittest.skipIf(librus_apix is None, "brak librus-apix")
class TestBledyLogowania(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("api", _SCIEZKA)
        cls.api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.api)

    def test_ogolny_blad_to_nie_zle_haslo(self):
        # 23.11.2026: tak Librus odpowiadał przez ~1,5 h – nie wolno wtedy żądać nowego hasła
        b = self.api._blad_logowania("Wystąpił błąd, spróbuj ponownie")
        self.assertIsInstance(b, self.api.LibrusLimit)
        self.assertNotIsInstance(b, self.api.LibrusBladLogowania)

    def test_zle_haslo(self):
        b = self.api._blad_logowania("Nieprawidłowy login i/lub hasło.")
        self.assertIsInstance(b, self.api.LibrusBladLogowania)

    def test_inny_blad(self):
        b = self.api._blad_logowania("Authorization cookies were not found")
        self.assertIs(type(b), self.api.LibrusBlad)


if __name__ == "__main__":
    unittest.main()
