from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import uuid
import json
import zipfile
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Iterable

from .models import ScannedFile


ProgressCallback = Callable[[int, int, str], None]
_UNVERIFIED_EXTENSIONS = {".chd", ".rar", ".7z"}


def _chd_cache_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Romoteca"
    return base / "chd-cache.json"


def _load_chd_cache() -> dict:
    try:
        data = json.loads(_chd_cache_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_chd_cache(cache: dict) -> None:
    try:
        # Keep only live entries and cap growth if a large collection is reorganized.
        live = {key: value for key, value in cache.items() if Path(key.split("|", 1)[0]).is_file()}
        if len(live) > 10000:
            live = dict(list(live.items())[-10000:])
        target = _chd_cache_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(live, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _chd_cache_key(path: Path, chdman_path: str) -> str:
    stat = path.stat()
    return "|".join((str(path.resolve()).lower(), str(stat.st_size), str(stat.st_mtime_ns), str(Path(chdman_path).resolve()).lower()))


def _cached_scanned_files(path: Path, values: list[dict]) -> list[ScannedFile]:
    return [
        ScannedFile(
            path=path,
            display_name=str(item.get("display_name", path.name)),
            size=int(item.get("size", 0)),
            crc=item.get("crc"),
            sha1=item.get("sha1"),
            archive_member=item.get("archive_member"),
            verifiable=bool(item.get("verifiable", True)),
            source_format=item.get("source_format", "chd"),
        )
        for item in values
    ]


def _cache_scanned_files(items: Iterable[ScannedFile]) -> list[dict]:
    return [
        {
            "display_name": item.display_name,
            "size": item.size,
            "crc": item.crc,
            "sha1": item.sha1,
            "archive_member": item.archive_member,
            "verifiable": item.verifiable,
            "source_format": item.source_format,
        }
        for item in items
    ]


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


def _find_chdman(chdman_path: str | Path | None) -> str | None:
    if chdman_path:
        candidate = Path(chdman_path)
        if candidate.is_file():
            return str(candidate)
    return shutil.which("chdman") or shutil.which("chdman.exe")


def _scan_chd(
    path: Path,
    chdman_path: str,
    allowed_extensions: set[str] | None,
    cancelled: Callable[[], bool],
) -> Iterable[ScannedFile]:
    """Extract a CHD into a disposable directory and hash its virtual tracks."""
    temp_parent = Path(os.environ.get("ROMOTECA_CHD_TEMP", Path.cwd() / ".romoteca-chd-temp"))
    try:
        temp_parent.mkdir(parents=True, exist_ok=True)
        temporary_path = temp_parent / f"romoteca-chd-{uuid.uuid4().hex}"
        temporary_path.mkdir()
        temporary = str(temporary_path)
    except OSError:
        temporary = tempfile.mkdtemp(prefix="romoteca-chd-")
    try:
        output = Path(temporary) / path.stem
        if cancelled():
            raise ScanCancelled()
        completed = subprocess.run(
            [chdman_path, "extractcd", "-i", str(path), "-o", f"{output}.cue"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if cancelled():
            raise ScanCancelled()
        if completed.returncode != 0:
            yield ScannedFile(path=path, display_name=path.name, size=path.stat().st_size, crc=None, sha1=None, verifiable=False, source_format="chd")
            return
        extracted = sorted(Path(temporary).glob("*") )
        for item in extracted:
            if not item.is_file() or (allowed_extensions is not None and item.suffix.lower() not in allowed_extensions):
                continue
            scanned = _scan_hashed_file(item, cancelled)
            yield ScannedFile(
                path=path,
                display_name=scanned.display_name,
                size=scanned.size,
                crc=scanned.crc,
                sha1=scanned.sha1,
                archive_member=item.name,
                source_format="chd",
            )
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
        try:
            Path(temporary).rmdir()
        except OSError:
            pass


def scan_folder(
    folder: str | Path,
    progress: ProgressCallback | None = None,
    cancelled: Callable[[], bool] | None = None,
    allowed_extensions: set[str] | None = None,
    workers: int | None = None,
    chdman_path: str | Path | None = None,
) -> list[ScannedFile]:
    root = Path(folder)
    is_cancelled = cancelled or (lambda: False)
    paths = [
        path for path in root.rglob("*")
        if path.is_file() and (
            allowed_extensions is None
            or path.suffix.lower() in allowed_extensions
            or path.suffix.lower() == ".chd"
            or path.suffix.lower() == ".zip"
        )
    ]
    results: list[ScannedFile] = []
    chd_cache = _load_chd_cache() if chdman_path or shutil.which("chdman") else {}
    cache_changed = False
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
                resolved_chdman = _find_chdman(chdman_path)
                if extension == ".chd" and resolved_chdman:
                    key = _chd_cache_key(path, resolved_chdman)
                    cached = chd_cache.get(key)
                    if isinstance(cached, list):
                        results.extend(_cached_scanned_files(path, cached))
                    else:
                        extracted = list(_scan_chd(path, resolved_chdman, allowed_extensions, is_cancelled))
                        results.extend(extracted)
                        chd_cache[key] = _cache_scanned_files(extracted)
                        cache_changed = True
                else:
                    results.append(
                        ScannedFile(
                            path=path,
                            display_name=path.name,
                            size=path.stat().st_size,
                            crc=None,
                            sha1=None,
                            verifiable=False,
                            source_format=extension.removeprefix("."),
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
        if cache_changed:
            _save_chd_cache(chd_cache)
    return results
