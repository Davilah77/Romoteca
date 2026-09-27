from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from typing import Callable, Iterable

from .models import ScannedFile


ProgressCallback = Callable[[int, int, str], None]
_UNVERIFIED_EXTENSIONS = {".chd", ".rar", ".7z"}


class ScanCancelled(Exception):
    pass


def _crc32_table() -> tuple[int, ...]:
    values = []
    for number in range(256):
        crc = number
        for _ in range(8):
            crc = (crc >> 1) ^ (0xEDB88320 if crc & 1 else 0)
        values.append(crc)
    return tuple(values)


_CRC_TABLE = _crc32_table()


def _hash_file(path: Path, cancelled: Callable[[], bool]) -> tuple[str, str]:
    crc = 0xFFFFFFFF
    sha1 = hashlib.sha1()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            if cancelled():
                raise ScanCancelled()
            sha1.update(chunk)
            for byte in chunk:
                crc = _CRC_TABLE[(crc ^ byte) & 0xFF] ^ (crc >> 8)
    return f"{crc ^ 0xFFFFFFFF:08x}", sha1.hexdigest()


def _scan_zip(path: Path) -> Iterable[ScannedFile]:
    try:
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                yield ScannedFile(
                    path=path,
                    display_name=Path(info.filename).name,
                    archive_member=info.filename,
                    size=info.file_size,
                    crc=f"{info.CRC:08x}",
                    sha1=None,
                )
    except (OSError, zipfile.BadZipFile):
        yield ScannedFile(
            path=path,
            display_name=path.name,
            size=path.stat().st_size if path.exists() else 0,
            crc=None,
            sha1=None,
            verifiable=False,
        )


def scan_folder(
    folder: str | Path,
    progress: ProgressCallback | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> list[ScannedFile]:
    root = Path(folder)
    is_cancelled = cancelled or (lambda: False)
    paths = [path for path in root.rglob("*") if path.is_file()]
    results: list[ScannedFile] = []

    for index, path in enumerate(paths, start=1):
        if is_cancelled():
            raise ScanCancelled()
        if progress:
            progress(index, len(paths), str(path.relative_to(root)))
        extension = path.suffix.lower()
        if extension == ".zip":
            results.extend(_scan_zip(path))
        elif extension in _UNVERIFIED_EXTENSIONS:
            results.append(
                ScannedFile(
                    path=path,
                    display_name=path.name,
                    size=path.stat().st_size,
                    crc=None,
                    sha1=None,
                    verifiable=False,
                )
            )
        else:
            try:
                crc, sha1 = _hash_file(path, is_cancelled)
                results.append(
                    ScannedFile(
                        path=path,
                        display_name=path.name,
                        size=path.stat().st_size,
                        crc=crc,
                        sha1=sha1,
                    )
                )
            except (OSError, PermissionError):
                results.append(
                    ScannedFile(
                        path=path,
                        display_name=path.name,
                        size=0,
                        crc=None,
                        sha1=None,
                        verifiable=False,
                    )
                )
    return results

