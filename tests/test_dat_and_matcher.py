import tempfile
import unittest
from pathlib import Path

from romoteca.dat_parser import load_dat
from romoteca.matcher import compare_catalog
from romoteca.models import DatAsset, DatCatalog, DatGame, GameState, ScannedFile


class DatAndMatcherTests(unittest.TestCase):
    def test_load_and_compare_dat(self) -> None:
        temporary = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(temporary.cleanup)
        tmp_path = Path(temporary.name)
        dat = tmp_path / "sample.dat"
        dat.write_text(
        """<?xml version="1.0"?>
<datafile>
  <header><name>Prueba</name><version>2026-01-01</version></header>
  <game name="juego-uno">
    <description>Juego Uno</description>
    <rom name="juego.bin" size="4" crc="12345678" sha1="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" />
  </game>
  <machine name="juego-dos">
    <description>Juego Dos</description>
    <rom name="dos.bin" size="8" crc="87654321" />
  </machine>
  <machine name="juego-clon" cloneof="juego-dos">
    <description>Juego Clon</description>
    <rom name="clon.bin" size="2" crc="11223344" />
  </machine>
</datafile>""",
            encoding="utf-8",
        )
        catalog = load_dat(dat)
        self.assertEqual(catalog.name, "Prueba")
        self.assertEqual(len(catalog.games), 3)
        self.assertEqual(catalog.games[2].clone_of, "juego-dos")

        scanned = [
            ScannedFile(
                path=tmp_path / "renombrado.bin",
                display_name="renombrado.bin",
                size=4,
                crc="12345678",
                sha1="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            )
        ]
        results, summary = compare_catalog(catalog, scanned)
        self.assertEqual(results[0].state, GameState.COMPLETE)
        self.assertEqual(results[1].state, GameState.MISSING)
        self.assertEqual(summary.complete, 1)
        self.assertEqual(summary.missing, 2)

    def test_duplicate_content_is_reported_separately(self) -> None:
        catalog = DatCatalog(
            name="Test",
            description="",
            version="",
            source_path=Path("test.dat"),
            games=(DatGame("game", "game", (DatAsset("game.bin", size=3, crc="352441c2"),)),),
        )
        first = ScannedFile(Path("game.bin"), "game.bin", 3, "352441c2", None)
        duplicate = ScannedFile(Path("game.chd"), "game.bin", 3, "352441c2", None, source_format="chd")
        results, summary = compare_catalog(catalog, [first, duplicate])

        self.assertEqual(results[0].state, GameState.COMPLETE)
        self.assertEqual(summary.duplicates, 1)
        self.assertEqual(summary.unknown, 0)


if __name__ == "__main__":
    unittest.main()
