from __future__ import annotations

import hashlib
import os
import zipfile
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Iterable

from .models import ScannedFile


ProgressCallback = Callable[[int, int, str], None]
_UNVERIFIED_EXTENSIONS = {".chd", ".rar", ".7z"}


class ScanCancelled(Exception):
    pass

def _hash_file(path: Path, cancelled: Callable[[], bool]) -> tuple[str, str]:
    crc = 0
    sha1 = hashlib.sha1()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            if cancelled():
                raise ScanCancelled()
            sha1.update(chunk)
            crc = zlib.crc32(chunk, crc)
    return f"{crc & 0xFFFFFFFF:08x}", sha1.hexdigest()


def _scan_hashed_file(path: Path, cancelled: Callable[[], bool]) -> ScannedFile:
    crc, sha1 = _hash_file(path, cancelled)
    return ScannedFile(
        path=path,
        display_name=path.name,
        size=path.stat().st_size,
        crc=crc,
        sha1=sha1,
    )


def _scan_zip(path: Path, allowed_extensions: set[str] | None = None) -> Iterable[ScannedFile]:
    try:
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                member_extension = Path(info.filename).suffix.lower()
                if allowed_extensions is not None and member_extension not in allowed_extensions:
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
    allowed_extensions: set[str] | None = None,
    workers: int | None = None,
) -> list[ScannedFile]:
    root = Path(folder)
    is_cancelled = cancelled or (lambda: False)
    paths = [
        path for path in root.rglob("*")
        if path.is_file() and (
            allowed_extensions is None
            or path.suffix.lower() in allowed_extensions
            or path.suffix.lower() == ".zip"
        )
    ]
    results: list[ScannedFile] = []
    hash_paths = [path for path in paths if path.suffix.lower() not in {".zip", *_UNVERIFIED_EXTENSIONS}]
    worker_count = workers if workers is not None else min(4, max(1, os.cpu_count() or 1))
    worker_count = max(1, min(32, int(worker_count)))
    executor = ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="romoteca-hash") if hash_paths else None
    futures = {path: executor.submit(_scan_hashed_file, path, is_cancelled) for path in hash_paths} if executor else {}
    try:
        for index, path in enumerate(paths, start=1):
            if is_cancelled():
                raise ScanCancelled()
            if progress:
                progress(index, len(paths), str(path.relative_to(root)))
            extension = path.suffix.lower()
            if extension == ".zip":
                results.extend(_scan_zip(path, allowed_extensions))
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
                    results.append(futures[path].result())
                except ScanCancelled:
                    raise
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
    finally:
        if executor:
            executor.shutdown(wait=not is_cancelled(), cancel_futures=is_cancelled())
    return results
