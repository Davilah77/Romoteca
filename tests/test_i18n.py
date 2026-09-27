import unittest

from romoteca.i18n import Translator


class TranslationTests(unittest.TestCase):
    def test_english_and_spanish(self) -> None:
        translator = Translator("en")
        self.assertEqual(translator("scan"), "Scan")
        translator.set_language("es")
        self.assertEqual(translator("scan"), "Escanear")


if __name__ == "__main__":
    unittest.main()
