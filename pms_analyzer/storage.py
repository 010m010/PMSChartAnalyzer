from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from math import ceil, floor
from pathlib import Path
from typing import Dict, List, Optional

from .analysis import DensityResult
from .difficulty_table import ChartAnalysis, DifficultyEntry, DifficultyTable

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
    level: Optional[str] = None


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


@dataclass
class CachedDifficultyData:
    table: DifficultyTable
    analyses: list[ChartAnalysis]


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
                density_change=float(metrics.get("density_change", 0.0)),
                high_density_occupancy_rate=float(metrics.get("high_density_occupancy_rate", 0.0)),
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
                terminal_density_difference=float(metrics.get("terminal_density_difference", 0.0)),
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


def _density_to_dict(density: DensityResult) -> dict[str, object]:
    return {
        "per_second_total": density.per_second_total,
        "per_second_by_key": density.per_second_by_key,
        "duration": density.duration,
    }


def _density_from_dict(data: object, *, total_value: float | None) -> Optional[DensityResult]:
    if not isinstance(data, dict):
        return None
    try:
        per_second_total = [int(v) for v in data.get("per_second_total", []) or []]
        per_second_by_key = [[int(v) for v in row] for row in data.get("per_second_by_key", []) or []]
        duration = float(data.get("duration", 0.0))
    except (TypeError, ValueError):
        return None

    if per_second_total and not per_second_by_key:
        per_second_by_key = [[count, 0, 0, 0, 0, 0, 0, 0, 0] for count in per_second_total]

    return _recompute_density_metrics(per_second_total, per_second_by_key, duration, total_value)


def _recompute_density_metrics(
    per_second_total: list[int],
    per_second_by_key: list[list[int]],
    duration: float,
    total_value: float | None,
) -> DensityResult:
    epsilon = 1e-6
    if not per_second_total:
        return DensityResult(
            per_second_total=[],
            per_second_by_key=per_second_by_key,
            max_density=0.0,
            average_density=0.0,
            cms_density=0.0,
            chm_density=0.0,
            density_change=0.0,
            high_density_occupancy_rate=0.0,
            terminal_density=0.0,
            terminal_rms_density=0.0,
            terminal_cms_density=0.0,
            terminal_chm_density=0.0,
            rms_density=0.0,
            duration=duration,
            terminal_window=None,
            overall_difficulty=0.0,
            terminal_difficulty=0.0,
            terminal_difficulty_cms=0.0,
            terminal_difficulty_chm=0.0,
            terminal_density_difference=0.0,
            gustiness=0.0,
            terminal_gustiness=0.0,
        )

    non_zero_bins = [val for val in per_second_total if val > 0]
    max_density = max(per_second_total)
    average_density = sum(non_zero_bins) / len(non_zero_bins) if non_zero_bins else 0.0

    terminal_density = 0.0
    terminal_rms_density = 0.0
    terminal_cms_density = 0.0
    terminal_chm_density = 0.0
    terminal_density_difference = 0.0
    terminal_max_density = 0.0
    terminal_gustiness = 0.0
    terminal_window_used: float | None = None
    terminal_start_bin = len(per_second_total)
    bin_size = duration / len(per_second_total) if per_second_total and duration > 0 else 1.0
    total_notes = sum(per_second_total)

    if total_value is not None and total_notes > 0:
        gauge_rate = total_value / total_notes
        if gauge_rate > 0:
            required_notes = ceil((85.0 - 2.0) / gauge_rate)
            start_note_index = max(total_notes - required_notes, 0)
            cumulative = 0
            for idx, val in enumerate(per_second_total):
                cumulative += val
                if cumulative > start_note_index:
                    terminal_start_bin = idx
                    break
            terminal_bins = per_second_total[terminal_start_bin:] if terminal_start_bin < len(per_second_total) else []
            terminal_window_used = len(terminal_bins) * bin_size if terminal_bins else 0.0
            note_count_terminal = sum(terminal_bins)
            if terminal_window_used and terminal_window_used > 0 and note_count_terminal > 0:
                terminal_density = note_count_terminal / terminal_window_used
            terminal_max_density = max(terminal_bins) if terminal_bins else 0.0
            terminal_bins_non_zero = [val for val in terminal_bins if val > 0]
            if terminal_bins_non_zero:
                terminal_rms_density = (
                    sum(val * val for val in terminal_bins_non_zero) / len(terminal_bins_non_zero)
                ) ** 0.5
                terminal_cms_density = (
                    sum(val**3 for val in terminal_bins_non_zero) / len(terminal_bins_non_zero)
                ) ** (1.0 / 3.0)
                terminal_chm_density = sum(val * val for val in terminal_bins_non_zero) / sum(terminal_bins_non_zero)
                terminal_mean_per_second = sum(terminal_bins_non_zero) / len(terminal_bins_non_zero)
                terminal_variance = (
                    sum((val - terminal_mean_per_second) ** 2 for val in terminal_bins_non_zero)
                    / len(terminal_bins_non_zero)
                )
                terminal_std_per_second = terminal_variance**0.5
                if terminal_std_per_second > 0:
                    terminal_gustiness = (terminal_max_density - terminal_mean_per_second) / (
                        terminal_std_per_second + epsilon
                    )

    rms_density = (
        (sum(val * val for val in non_zero_bins) / len(non_zero_bins)) ** 0.5 if non_zero_bins else 0.0
    )
    cms_density = (
        (sum(val**3 for val in non_zero_bins) / len(non_zero_bins)) ** (1.0 / 3.0) if non_zero_bins else 0.0
    )
    chm_density = sum(val * val for val in non_zero_bins) / sum(non_zero_bins) if non_zero_bins else 0.0
    density_change = 0.0
    if per_second_total:
        diffs = [abs(per_second_total[i] - per_second_total[i - 1]) for i in range(1, len(per_second_total))]
        if diffs:
            total_diff = sum(diffs)
            density_change = total_diff / (total_notes + epsilon)
    if per_second_total:
        threshold = floor(chm_density)
        occupied_bins = sum(1 for val in per_second_total if val >= threshold)
        high_density_occupancy_rate = (occupied_bins / len(per_second_total)) * 100
    else:
        high_density_occupancy_rate = 0.0

    mean_per_second = sum(non_zero_bins) / len(non_zero_bins) if non_zero_bins else 0.0
    variance = (
        sum((val - mean_per_second) ** 2 for val in non_zero_bins) / len(non_zero_bins) if non_zero_bins else 0.0
    )
    std_per_second = variance**0.5

    non_terminal_bins = per_second_total[:terminal_start_bin]
    non_terminal_bins_non_zero = [val for val in non_terminal_bins if val > 0]
    non_terminal_rms = (
        (sum(val * val for val in non_terminal_bins_non_zero) / len(non_terminal_bins_non_zero)) ** 0.5
        if non_terminal_bins_non_zero
        else rms_density
    )
    non_terminal_cms = (
        (sum(val**3 for val in non_terminal_bins_non_zero) / len(non_terminal_bins_non_zero)) ** (1.0 / 3.0)
        if non_terminal_bins_non_zero
        else cms_density
    )
    non_terminal_chm = (
        sum(val * val for val in non_terminal_bins_non_zero) / sum(non_terminal_bins_non_zero)
        if non_terminal_bins_non_zero and sum(non_terminal_bins_non_zero) > 0
        else chm_density
    )

    overall_difficulty = mean_per_second / (std_per_second + epsilon) if mean_per_second > 0 else 0.0
    terminal_difficulty = (
        (terminal_rms_density - non_terminal_rms) / (std_per_second + epsilon) if std_per_second > 0 else 0.0
    )
    terminal_difficulty_cms = (
        (terminal_cms_density - non_terminal_cms) / (std_per_second + epsilon) if std_per_second > 0 else 0.0
    )
    terminal_difficulty_chm = (
        (terminal_chm_density - non_terminal_chm) / (std_per_second + epsilon) if std_per_second > 0 else 0.0
    )
    if terminal_window_used is not None:
        terminal_density_difference = terminal_chm_density - non_terminal_chm
    gustiness = (max_density - mean_per_second) / (std_per_second + epsilon) if std_per_second > 0 else 0.0
    if terminal_window_used is None:
        terminal_gustiness = 0.0

    return DensityResult(
        per_second_total=per_second_total,
        per_second_by_key=per_second_by_key,
        max_density=max_density,
        average_density=average_density,
        cms_density=cms_density,
        chm_density=chm_density,
        density_change=density_change,
        high_density_occupancy_rate=high_density_occupancy_rate,
        terminal_density=terminal_density,
        terminal_rms_density=terminal_rms_density,
        terminal_cms_density=terminal_cms_density,
        terminal_chm_density=terminal_chm_density,
        rms_density=rms_density,
        duration=duration,
        terminal_window=terminal_window_used,
        overall_difficulty=overall_difficulty,
        terminal_difficulty=terminal_difficulty,
        terminal_difficulty_cms=terminal_difficulty_cms,
        terminal_difficulty_chm=terminal_difficulty_chm,
        terminal_density_difference=terminal_density_difference,
        gustiness=gustiness,
        terminal_gustiness=terminal_gustiness,
    )


def _serialize_analysis(analysis: ChartAnalysis, index: int) -> dict[str, object]:
    return {
        "entry_index": index,
        "difficulty": analysis.difficulty,
        "title": analysis.title,
        "subtitle": analysis.subtitle,
        "md5": analysis.md5,
        "sha256": analysis.sha256,
        "note_count": analysis.note_count,
        "total_value": analysis.total_value,
        "resolved_path": str(analysis.resolved_path) if analysis.resolved_path else None,
        "density": _density_to_dict(analysis.density),
    }


def _deserialize_cached_analyses(raw_analyses: object, entries: list[DifficultyEntry]) -> list[ChartAnalysis]:
    if not isinstance(raw_analyses, list):
        return []
    analyses: list[ChartAnalysis] = []
    for item in raw_analyses:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("entry_index"))
        except (TypeError, ValueError):
            continue
        if not 0 <= index < len(entries):
            continue
        entry = entries[index]
        resolved_raw = item.get("resolved_path")
        resolved_path = Path(str(resolved_raw)) if resolved_raw else None
        note_count = item.get("note_count")
        total_value = item.get("total_value")
        try:
            note_count_val: int = int(note_count) if note_count is not None else 0
        except (TypeError, ValueError):
            note_count_val = 0
        try:
            total_value_val: Optional[float] = float(total_value) if total_value is not None else None
        except (TypeError, ValueError):
            total_value_val = None
        density = _density_from_dict(item.get("density"), total_value=total_value_val)
        if density is None:
            continue
        entry.note_count = entry.note_count or note_count_val
        entry.total_value = entry.total_value or total_value_val
        analyses.append(
            ChartAnalysis(
                difficulty=str(item.get("difficulty") or entry.difficulty),
                density=density,
                entry=entry,
                resolved_path=resolved_path,
                note_count=note_count_val,
                total_value=total_value_val,
                title=str(item.get("title") or entry.title),
                subtitle=item.get("subtitle") or entry.subtitle,
                md5=item.get("md5") or entry.md5,
                sha256=item.get("sha256") or entry.sha256,
            )
        )
    return analyses


def save_cached_difficulty_table(url: str, table: DifficultyTable, analyses: list[ChartAnalysis] | None = None) -> None:
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
    analyses_payload = []
    for idx, analysis in enumerate(analyses or []):
        analyses_payload.append(_serialize_analysis(analysis, idx))
    cache[url] = {"name": table.name, "symbol": table.symbol, "entries": entries, "analyses": analyses_payload}
    DIFFICULTY_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def load_cached_difficulty_data(url: str) -> Optional[CachedDifficultyData]:
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
    analyses = _deserialize_cached_analyses(raw_table.get("analyses"), entries)
    return CachedDifficultyData(table=DifficultyTable(name=name, entries=entries, symbol=symbol), analyses=analyses)


def load_cached_difficulty_table(url: str) -> Optional[DifficultyTable]:
    cached = load_cached_difficulty_data(url)
    return cached.table if cached else None


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
    "CachedDifficultyData",
    "history_by_difficulty",
    "ensure_config_dir",
    "get_saved_tables",
    "add_saved_table",
    "update_saved_table_name",
    "remove_saved_table",
    "save_cached_difficulty_table",
    "load_cached_difficulty_table",
    "remove_cached_difficulty_table",
    "load_cached_difficulty_data",
]
