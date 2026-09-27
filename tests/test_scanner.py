import zipfile
import tempfile
import unittest
from pathlib import Path

from romoteca.scanner import scan_folder


class ScannerTests(unittest.TestCase):
    def test_scan_raw_zip_and_chd(self) -> None:
        temporary = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(temporary.cleanup)
        tmp_path = Path(temporary.name)
        (tmp_path / "raw.bin").write_bytes(b"romoteca")
        (tmp_path / "disc.chd").write_bytes(b"not-a-real-chd")
        with zipfile.ZipFile(tmp_path / "set.zip", "w") as archive:
            archive.writestr("inside.rom", b"abc")

        results = scan_folder(tmp_path)
        by_name = {item.display_name: item for item in results}
        self.assertTrue(by_name["raw.bin"].crc)
        self.assertTrue(by_name["raw.bin"].sha1)
        self.assertEqual(by_name["inside.rom"].archive_member, "inside.rom")
        self.assertFalse(by_name["disc.chd"].verifiable)


if __name__ == "__main__":
    unittest.main()
