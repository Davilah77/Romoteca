from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


@dataclass(frozen=True)
class DatAsset:
    name: str
    size: int | None = None
    crc: str | None = None
    sha1: str | None = None
    kind: str = "rom"

    def __post_init__(self) -> None:
        object.__setattr__(self, "crc", self.crc.lower() if self.crc else None)
        object.__setattr__(self, "sha1", self.sha1.lower() if self.sha1 else None)


@dataclass(frozen=True)
class DatGame:
    name: str
    description: str
    assets: tuple[DatAsset, ...]
    clone_of: str | None = None


@dataclass(frozen=True)
class DatCatalog:
    name: str
    description: str
    version: str
    source_path: Path
    games: tuple[DatGame, ...]

    @property
    def asset_count(self) -> int:
        return sum(len(game.assets) for game in self.games)


@dataclass(frozen=True)
class ScannedFile:
    path: Path
    display_name: str
    size: int
    crc: str | None
    sha1: str | None
    archive_member: str | None = None
    verifiable: bool = True
    source_format: str | None = None
    duplicate_of: str | None = None


class GameState(str, Enum):
    COMPLETE = "Completo"
    PARTIAL = "Incompleto"
    MISSING = "Falta"


@dataclass
class GameResult:
    game: DatGame
    state: GameState
    found_assets: int
    expected_assets: int
    matches: list[ScannedFile] = field(default_factory=list)


@dataclass(frozen=True)
class ScanSummary:
    complete: int
    partial: int
    missing: int
    unknown: int
    unverified_containers: int
    duplicates: int = 0
