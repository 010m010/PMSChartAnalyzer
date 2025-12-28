from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .analysis import DensityResult, compute_density
from .pms_parser import PMSParser


@dataclass
class DifficultyEntry:
    difficulty: str
    title: str
    chart_path: Path
    artist: str | None = None


@dataclass
class DifficultyTable:
    name: str
    entries: List[DifficultyEntry]


@dataclass
class TableAnalysis:
    difficulty: str
    results: List[DensityResult]


SUPPORTED_SUFFIXES = {".csv", ".json"}


def load_difficulty_table(path: Path | str, *, base_dir: Optional[Path] = None) -> DifficultyTable:
    table_path = Path(path)
    if table_path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Unsupported difficulty table format: {table_path.suffix}")

    entries = (
        _read_csv(table_path, base_dir=base_dir)
        if table_path.suffix.lower() == ".csv"
        else _read_json(table_path, base_dir=base_dir)
    )
    return DifficultyTable(name=table_path.stem, entries=entries)


def analyze_table(
    table: DifficultyTable,
    parser: PMSParser,
    *,
    terminal_window: float = 5.0,
) -> List[TableAnalysis]:
    grouped: Dict[str, List[DensityResult]] = {}
    for entry in table.entries:
        parse_result = parser.parse(entry.chart_path)
        density = compute_density(parse_result.notes, parse_result.total_time, terminal_window=terminal_window)
        grouped.setdefault(entry.difficulty, []).append(density)

    return [TableAnalysis(difficulty=diff, results=results) for diff, results in grouped.items()]


def _read_csv(path: Path, *, base_dir: Optional[Path]) -> List[DifficultyEntry]:
    entries: List[DifficultyEntry] = []
    with path.open(encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            difficulty = (row.get("difficulty") or row.get("level") or "Unknown").strip()
            title = (row.get("title") or row.get("name") or Path(row.get("pms_path", "")).stem).strip()
            pms_raw = (row.get("pms_path") or row.get("chart") or "").strip()
            artist = (row.get("artist") or "").strip() or None
            resolved = _resolve_path(pms_raw, base_dir or path.parent)
            if resolved:
                entries.append(DifficultyEntry(difficulty=difficulty, title=title, chart_path=resolved, artist=artist))
    return entries


def _read_json(path: Path, *, base_dir: Optional[Path]) -> List[DifficultyEntry]:
    data = json.loads(path.read_text(encoding="utf-8"))
    entries: List[DifficultyEntry] = []
    if isinstance(data, dict):
        items = data.get("charts") or data.get("entries") or []
    else:
        items = data

    for item in items:
        difficulty = str(item.get("difficulty") or item.get("level") or "Unknown")
        title = item.get("title") or item.get("name") or Path(item.get("pms_path", "")).stem
        artist = item.get("artist")
        pms_raw = item.get("pms_path") or item.get("chart") or ""
        resolved = _resolve_path(str(pms_raw), base_dir or path.parent)
        if resolved:
            entries.append(DifficultyEntry(difficulty=difficulty, title=str(title), chart_path=resolved, artist=artist))
    return entries


def _resolve_path(value: str, base_dir: Path) -> Optional[Path]:
    if not value:
        return None
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return candidate if candidate.exists() else None


__all__ = [
    "DifficultyEntry",
    "DifficultyTable",
    "TableAnalysis",
    "load_difficulty_table",
    "analyze_table",
]
