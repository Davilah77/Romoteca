from __future__ import annotations

from collections import defaultdict

from .models import DatCatalog, GameResult, GameState, ScanSummary, ScannedFile


def compare_catalog(
    catalog: DatCatalog, scanned: list[ScannedFile]
) -> tuple[list[GameResult], ScanSummary]:
    by_sha1: dict[str, list[ScannedFile]] = defaultdict(list)
    by_crc_size: dict[tuple[str, int], list[ScannedFile]] = defaultdict(list)
    matched_ids: set[int] = set()

    for item in scanned:
        if item.sha1:
            by_sha1[item.sha1.lower()].append(item)
        if item.crc:
            by_crc_size[(item.crc.lower(), item.size)].append(item)

    results: list[GameResult] = []
    for game in catalog.games:
        matches: list[ScannedFile] = []
        found = 0
        for asset in game.assets:
            candidates: list[ScannedFile] = []
            if asset.sha1:
                candidates = by_sha1.get(asset.sha1, [])
            if not candidates and asset.crc and asset.size is not None:
                candidates = by_crc_size.get((asset.crc, asset.size), [])
            if candidates:
                found += 1
                selected = candidates[0]
                matches.append(selected)
                matched_ids.add(id(selected))

        expected = len(game.assets)
        state = (
            GameState.COMPLETE
            if found == expected
            else GameState.PARTIAL
            if found
            else GameState.MISSING
        )
        results.append(
            GameResult(
                game=game,
                state=state,
                found_assets=found,
                expected_assets=expected,
                matches=matches,
            )
        )

    summary = ScanSummary(
        complete=sum(result.state == GameState.COMPLETE for result in results),
        partial=sum(result.state == GameState.PARTIAL for result in results),
        missing=sum(result.state == GameState.MISSING for result in results),
        unknown=sum(item.verifiable and id(item) not in matched_ids for item in scanned),
        unverified_containers=sum(not item.verifiable for item in scanned),
    )
    return results, summary


def find_unknown_files(
    results: list[GameResult], scanned: list[ScannedFile]
) -> list[ScannedFile]:
    matched = {id(item) for result in results for item in result.matches}
    return [item for item in scanned if item.verifiable and id(item) not in matched]
