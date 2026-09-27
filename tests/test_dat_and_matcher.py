import tempfile
import unittest
from pathlib import Path

from romoteca.dat_parser import load_dat
from romoteca.matcher import compare_catalog
from romoteca.models import GameState, ScannedFile


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
</datafile>""",
            encoding="utf-8",
        )
        catalog = load_dat(dat)
        self.assertEqual(catalog.name, "Prueba")
        self.assertEqual(len(catalog.games), 2)

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
        self.assertEqual(summary.missing, 1)


if __name__ == "__main__":
    unittest.main()
