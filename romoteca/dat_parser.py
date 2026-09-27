from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from .models import DatAsset, DatCatalog, DatGame


class DatError(ValueError):
    pass


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(element: ET.Element, name: str) -> str:
    for child in element:
        if _local_name(child.tag) == name:
            return (child.text or "").strip()
    return ""


def load_dat(path: str | Path) -> DatCatalog:
    source = Path(path)
    try:
        root = ET.parse(source).getroot()
    except (ET.ParseError, OSError) as exc:
        raise DatError(f"No se pudo leer el DAT: {exc}") from exc

    header = next((e for e in root if _local_name(e.tag) == "header"), None)
    catalog_name = _child_text(header, "name") if header is not None else source.stem
    description = _child_text(header, "description") if header is not None else ""
    version = _child_text(header, "version") if header is not None else ""

    games: list[DatGame] = []
    for node in root.iter():
        if _local_name(node.tag) not in {"game", "machine"}:
            continue
        name = (node.get("name") or "").strip()
        game_description = _child_text(node, "description") or name
        assets: list[DatAsset] = []
        for child in node:
            kind = _local_name(child.tag)
            if kind not in {"rom", "disk"}:
                continue
            raw_size = child.get("size")
            try:
                size = int(raw_size) if raw_size else None
            except ValueError:
                size = None
            assets.append(
                DatAsset(
                    name=(child.get("name") or "").strip(),
                    size=size,
                    crc=child.get("crc"),
                    sha1=child.get("sha1"),
                    kind=kind,
                )
            )
        if name and assets:
            games.append(
                DatGame(
                    name=name,
                    description=game_description,
                    assets=tuple(assets),
                    clone_of=(node.get("cloneof") or node.get("romof") or "").strip() or None,
                )
            )

    if not games:
        raise DatError("El archivo no contiene entradas game/machine con ROMs o discos.")

    return DatCatalog(
        name=catalog_name or source.stem,
        description=description,
        version=version,
        source_path=source,
        games=tuple(games),
    )
