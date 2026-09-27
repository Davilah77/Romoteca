from __future__ import annotations

import csv
import io
import zipfile
import io
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen


REDUMP_DOWNLOADS = "https://redump.info/downloads"
GITHUB_RAW = "https://raw.githubusercontent.com/open-retrogaming-archive/dat-catalog/main/root/normalized"


@dataclass(frozen=True)
class OnlineDat:
    source: str
    platform: str
    url: str
    filename: str


def _get(url: str) -> bytes:
    if not url.lower().startswith("https://"):
        raise ValueError("Romoteca solo acepta descargas HTTPS.")
    parts = urlsplit(url)
    safe_url = urlunsplit((parts.scheme, parts.netloc, quote(parts.path, safe="/%()._-"), parts.query, parts.fragment))
    request = Request(safe_url, headers={"User-Agent": "Romoteca/0.3 (+https://github.com/Davilah77/Romoteca)"})
    with urlopen(request, timeout=45) as response:
        return response.read()


class _RedumpParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_row = False
        self.in_cell = False
        self.cell_text: list[str] = []
        self.cells: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.active_href: str | None = None
        self.active_link_text: list[str] = []
        self.rows: list[tuple[list[str], list[tuple[str, str]]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "tr":
            self.in_row, self.cells, self.links = True, [], []
        elif tag == "td" and self.in_row:
            self.in_cell, self.cell_text = True, []
        elif tag == "a" and self.in_row:
            self.active_href, self.active_link_text = values.get("href"), []

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.cell_text.append(data)
        if self.active_href is not None:
            self.active_link_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.active_href is not None:
            self.links.append((self.active_href, " ".join("".join(self.active_link_text).split())))
            self.active_href = None
        elif tag == "td" and self.in_cell:
            self.cells.append(" ".join("".join(self.cell_text).split()))
            self.in_cell = False
        elif tag == "tr" and self.in_row:
            self.rows.append((self.cells, self.links))
            self.in_row = False


def list_redump_dats() -> list[OnlineDat]:
    parser = _RedumpParser()
    parser.feed(_get(REDUMP_DOWNLOADS).decode("utf-8", "replace"))
    result: list[OnlineDat] = []
    for cells, links in parser.rows:
        if not cells:
            continue
        platform = cells[0]
        for href, label in links:
            if label.lower() != "dat" or "/datfile/" not in href:
                continue
            url = urljoin(REDUMP_DOWNLOADS, href)
            result.append(OnlineDat("Redump (official HTTPS)", platform, url, f"Redump - {platform}.dat"))
    return result


def list_github_dats(category: str = "Redump") -> list[OnlineDat]:
    index_url = f"{GITHUB_RAW}/{quote(category, safe='')}/index.csv"
    rows = csv.DictReader(io.StringIO(_get(index_url).decode("utf-8", "replace")))
    result: list[OnlineDat] = []
    current_platform = ""
    for row in rows:
        if row.get("Type") == "DIRECTORY":
            current_platform = row.get("Name", "")
            continue
        name = row.get("Name", "")
        url = row.get("URL", "")
        if row.get("Type") == "FILE" and name.lower().endswith((".dat", ".xml")) and url.startswith("https://"):
            result.append(OnlineDat(f"GitHub DAT Catalog · {category}", current_platform, url, name))
    return result


def download_dat(entry: OnlineDat, destination: Path) -> Path:
    content = _get(entry.url)
    stripped = content.lstrip()
    if stripped.startswith(b"PK"):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                candidates = [name for name in archive.namelist() if name.lower().endswith((".dat", ".xml")) and not name.endswith("/")]
                if len(candidates) != 1:
                    raise ValueError("El ZIP no contiene un único DAT/XML identificable.")
                content = archive.read(candidates[0])
                stripped = content.lstrip()
        except zipfile.BadZipFile as exc:
            raise ValueError("La descarga ZIP no es válida.") from exc
    if stripped.startswith(b"\xef\xbb\xbf"):
        stripped = stripped[3:].lstrip()
    if not stripped.startswith(b"<"):
        raise ValueError("La descarga no parece un DAT/XML válido.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".download")
    temporary.write_bytes(content)
    temporary.replace(destination)
    return destination
