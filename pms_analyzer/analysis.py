from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import ceil
from typing import Dict, Iterable, List, Sequence

from .pms_parser import Note, ParseResult


@dataclass
class DensityResult:
    per_second_total: List[int]
    per_second_by_key: List[List[int]]
    max_density: float
    average_density: float
    terminal_density: float
    rms_density: float


def compute_density(
    notes: Sequence[Note],
    total_time: float,
    *,
    bin_size: float = 1.0,
    terminal_window: float = 5.0,
) -> DensityResult:
    if total_time <= 0 or not notes:
        empty_bins: List[int] = []
        empty_by_key: List[List[int]] = []
        return DensityResult(empty_bins, empty_by_key, 0.0, 0.0, 0.0, 0.0)

    num_bins = max(1, ceil(total_time / bin_size))
    per_second_by_key: List[List[int]] = [[0 for _ in range(9)] for _ in range(num_bins)]
    for note in notes:
        index = min(int(note.time // bin_size), num_bins - 1)
        per_second_by_key[index][note.key_index] += 1

    per_second_total = [sum(row) for row in per_second_by_key]
    max_density = max(per_second_total)
    average_density = len(notes) / max(total_time, 1e-6)
    terminal_start = max(total_time - terminal_window, 0)
    terminal_notes = [note for note in notes if note.time >= terminal_start]
    window = min(terminal_window, total_time)
    terminal_density = len(terminal_notes) / window if window > 0 else 0.0
    # Mean of squared per-second densities (二乗平均密度)
    rms_density = (
        sum(val * val for val in per_second_total) / len(per_second_total)
        if per_second_total
        else 0.0
    )

    return DensityResult(
        per_second_total=per_second_total,
        per_second_by_key=per_second_by_key,
        max_density=max_density,
        average_density=average_density,
        terminal_density=terminal_density,
        rms_density=rms_density,
    )


def summarize_history(results: Iterable[DensityResult]) -> Dict[str, float]:
    totals = list(results)
    if not totals:
        return {"max_density": 0.0, "average_density": 0.0, "terminal_density": 0.0, "rms_density": 0.0}

    return {
        "max_density": sum(r.max_density for r in totals) / len(totals),
        "average_density": sum(r.average_density for r in totals) / len(totals),
        "terminal_density": sum(r.terminal_density for r in totals) / len(totals),
        "rms_density": sum(r.rms_density for r in totals) / len(totals),
    }


def aggregate_by_difficulty(grouped: Dict[str, List[DensityResult]]) -> Dict[str, Dict[str, float]]:
    summary: Dict[str, Dict[str, float]] = {}
    for difficulty, results in grouped.items():
        summary[difficulty] = summarize_history(results)
    return summary


__all__ = [
    "DensityResult",
    "compute_density",
    "summarize_history",
    "aggregate_by_difficulty",
]
