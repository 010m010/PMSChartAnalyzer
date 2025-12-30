from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .analysis import DensityResult
from .difficulty_table import DifficultyEntry, DifficultyTable

CONFIG_DIR = Path.home() / ".pms_chart_analyzer"
CONFIG_PATH = CONFIG_DIR / "config.json"
HISTORY_PATH = CONFIG_DIR / "history.json"
DIFFICULTY_CACHE_PATH = CONFIG_DIR / "difficulty_cache.json"


@dataclass
class AnalysisRecord:
    file_path: str
    title: str
    artist: str
    difficulty: Optional[str]
    metrics: Dict[str, float]


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> Dict[str, object]:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


def save_config(config: Dict[str, object]) -> None:
    ensure_config_dir()
    CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")

@dataclass
class SavedDifficultyTable:
    url: str
    name: Optional[str] = None


def _normalize_saved_tables(config: Dict[str, object]) -> list[SavedDifficultyTable]:
    raw_tables = config.get("difficulty_tables")
    tables: list[SavedDifficultyTable] = []

    if isinstance(raw_tables, list):
        for item in raw_tables:
            if isinstance(item, dict) and "url" in item:
                tables.append(SavedDifficultyTable(url=str(item.get("url")), name=item.get("name") or None))
            elif isinstance(item, str):
                tables.append(SavedDifficultyTable(url=item, name=None))

    # Backward compatibility: migrate from the old difficulty_urls list[str]
    raw_urls = config.get("difficulty_urls")
    if isinstance(raw_urls, list):
        for url in raw_urls:
            if isinstance(url, str) and all(existing.url != url for existing in tables):
                tables.append(SavedDifficultyTable(url=url, name=None))

    return tables


def _write_saved_tables(config: Dict[str, object], tables: list[SavedDifficultyTable]) -> None:
    config["difficulty_tables"] = [{"url": t.url, "name": t.name} for t in tables]
    # Keep legacy key in sync so older versions continue to work
    config["difficulty_urls"] = [t.url for t in tables]
    save_config(config)


def get_saved_tables() -> list[SavedDifficultyTable]:
    config = load_config()
    return _normalize_saved_tables(config)


def add_saved_table(url: str, *, name: Optional[str] = None) -> None:
    config = load_config()
    tables = _normalize_saved_tables(config)
    for table in tables:
        if table.url == url:
            if name:
                table.name = name
            _write_saved_tables(config, tables)
            return
    tables.append(SavedDifficultyTable(url=url, name=name))
    _write_saved_tables(config, tables)


def update_saved_table_name(url: str, name: str) -> None:
    config = load_config()
    tables = _normalize_saved_tables(config)
    updated = False
    for table in tables:
        if table.url == url:
            table.name = name
            updated = True
            break
    if updated:
        _write_saved_tables(config, tables)


def remove_saved_table(url: str) -> None:
    config = load_config()
    tables = [table for table in _normalize_saved_tables(config) if table.url != url]
    _write_saved_tables(config, tables)


def load_history() -> Dict[str, List[Dict[str, object]]]:
    if HISTORY_PATH.exists():
        return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    return {"records": []}


def append_history(record: AnalysisRecord) -> None:
    ensure_config_dir()
    history = load_history()
    history.setdefault("records", []).append(asdict(record))
    HISTORY_PATH.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")


def history_by_difficulty() -> Dict[str, List[DensityResult]]:
    history = load_history()
    grouped: Dict[str, List[DensityResult]] = {}
    for item in history.get("records", []):
        diff = item.get("difficulty") or "Unknown"
        metrics = item.get("metrics", {})
        grouped.setdefault(diff, []).append(
            DensityResult(
                per_second_total=[],
                per_second_by_key=[],
                max_density=float(metrics.get("max_density", 0.0)),
                average_density=float(metrics.get("average_density", 0.0)),
                cms_density=float(metrics.get("cms_density", 0.0)),
                chm_density=float(metrics.get("chm_density", 0.0)),
                terminal_density=float(metrics.get("terminal_density", 0.0)),
                rms_density=float(metrics.get("rms_density", 0.0)),
                terminal_rms_density=float(metrics.get("terminal_rms_density", 0.0)),
                terminal_cms_density=float(metrics.get("terminal_cms_density", 0.0)),
                terminal_chm_density=float(metrics.get("terminal_chm_density", 0.0)),
                duration=0.0,
                terminal_window=None,
                overall_difficulty=float(metrics.get("overall_difficulty", 0.0)),
                terminal_difficulty=float(metrics.get("terminal_difficulty", 0.0)),
                terminal_difficulty_cms=float(metrics.get("terminal_difficulty_cms", 0.0)),
                terminal_difficulty_chm=float(metrics.get("terminal_difficulty_chm", 0.0)),
                terminal_difficulty_chm_ratio=float(metrics.get("terminal_difficulty_chm_ratio", 0.0)),
                gustiness=float(metrics.get("gustiness", 0.0)),
                terminal_gustiness=float(metrics.get("terminal_gustiness", 0.0)),
            )
        )
    return grouped


def _load_cached_tables() -> Dict[str, object]:
    if DIFFICULTY_CACHE_PATH.exists():
        try:
            return json.loads(DIFFICULTY_CACHE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_cached_difficulty_table(url: str, table: DifficultyTable) -> None:
    ensure_config_dir()
    cache = _load_cached_tables()
    entries: list[dict[str, object | None]] = []
    for entry in table.entries:
        entries.append(
            {
                "difficulty": entry.difficulty,
                "title": entry.title,
                "subtitle": entry.subtitle,
                "artist": entry.artist,
                "chart_path": str(entry.chart_path) if entry.chart_path else None,
                "md5": entry.md5,
                "sha256": entry.sha256,
                "total_value": entry.total_value,
                "note_count": entry.note_count,
            }
        )
    cache[url] = {"name": table.name, "symbol": table.symbol, "entries": entries}
    DIFFICULTY_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def load_cached_difficulty_table(url: str) -> Optional[DifficultyTable]:
    cache = _load_cached_tables()
    raw_table = cache.get(url)
    if not isinstance(raw_table, dict):
        return None
    raw_entries = raw_table.get("entries")
    if not isinstance(raw_entries, list):
        return None
    entries: list[DifficultyEntry] = []
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        chart_path = item.get("chart_path")
        path_obj = Path(str(chart_path)) if chart_path else None
        note_count = item.get("note_count")
        try:
            note_count_val: Optional[int] = int(note_count) if note_count is not None else None
        except (TypeError, ValueError):
            note_count_val = None
        total_value = item.get("total_value")
        try:
            total_value_val: Optional[float] = float(total_value) if total_value is not None else None
        except (TypeError, ValueError):
            total_value_val = None
        entries.append(
            DifficultyEntry(
                difficulty=str(item.get("difficulty") or "Unknown"),
                title=str(item.get("title") or "Unknown"),
                subtitle=item.get("subtitle") or None,
                chart_path=path_obj if chart_path else None,
                artist=item.get("artist") or None,
                md5=item.get("md5") or None,
                sha256=item.get("sha256") or None,
                total_value=total_value_val,
                note_count=note_count_val,
            )
        )
    name = raw_table.get("name") or Path(url).stem or "table"
    symbol = raw_table.get("symbol") if isinstance(raw_table.get("symbol"), str) else None
    return DifficultyTable(name=name, entries=entries, symbol=symbol)


def remove_cached_difficulty_table(url: str) -> None:
    if not DIFFICULTY_CACHE_PATH.exists():
        return
    cache = _load_cached_tables()
    if url in cache:
        cache.pop(url)
        DIFFICULTY_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


__all__ = [
    "AnalysisRecord",
    "append_history",
    "load_config",
    "save_config",
    "SavedDifficultyTable",
    "history_by_difficulty",
    "ensure_config_dir",
    "get_saved_tables",
    "add_saved_table",
    "update_saved_table_name",
    "remove_saved_table",
    "save_cached_difficulty_table",
    "load_cached_difficulty_table",
    "remove_cached_difficulty_table",
]
