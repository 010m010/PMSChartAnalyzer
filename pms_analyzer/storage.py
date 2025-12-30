from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .analysis import DensityResult

CONFIG_DIR = Path.home() / ".pms_chart_analyzer"
CONFIG_PATH = CONFIG_DIR / "config.json"
HISTORY_PATH = CONFIG_DIR / "history.json"


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
]
