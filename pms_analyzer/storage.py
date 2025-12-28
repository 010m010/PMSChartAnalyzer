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


def load_config() -> Dict[str, str]:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


def save_config(config: Dict[str, str]) -> None:
    ensure_config_dir()
    CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


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
                terminal_density=float(metrics.get("terminal_density", 0.0)),
                rms_density=float(metrics.get("rms_density", 0.0)),
            )
        )
    return grouped


__all__ = [
    "AnalysisRecord",
    "append_history",
    "load_config",
    "save_config",
    "history_by_difficulty",
    "ensure_config_dir",
]
