from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor
from typing import Dict, Iterable, List, Sequence

from .pms_parser import Note


@dataclass
class DensityResult:
    per_second_total: List[int]
    per_second_by_key: List[List[int]]
    max_density: float
    average_density: float
    cms_density: float
    chm_density: float
    density_change: float
    high_density_occupancy_rate: float
    terminal_density: float
    terminal_rms_density: float
    terminal_cms_density: float
    terminal_chm_density: float
    rms_density: float
    duration: float
    terminal_window: float | None
    overall_difficulty: float
    terminal_difficulty: float
    terminal_difficulty_cms: float
    terminal_difficulty_chm: float
    terminal_density_difference: float
    gustiness: float
    terminal_gustiness: float


def compute_density(
    notes: Sequence[Note],
    total_time: float,
    *,
    bin_size: float = 1.0,
    terminal_window: float = 5.0,
    total_value: float | None = None,
) -> DensityResult:
    epsilon = 1e-6
    if not notes:
        empty_bins: List[int] = []
        empty_by_key: List[List[int]] = []
        return DensityResult(
            per_second_total=empty_bins,
            per_second_by_key=empty_by_key,
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
            duration=0.0,
            terminal_window=None,
            overall_difficulty=0.0,
            terminal_difficulty=0.0,
            terminal_difficulty_cms=0.0,
            terminal_difficulty_chm=0.0,
            terminal_density_difference=0.0,
            gustiness=0.0,
            terminal_gustiness=0.0,
        )

    note_count = len(notes)
    # Trim leading/trailing silence to avoid skewing density
    start_time = notes[0].time
    end_time = notes[-1].time
    duration = max(end_time - start_time, 1e-6)

    num_bins = max(1, ceil(duration / bin_size))
    per_second_by_key: List[List[int]] = [[0 for _ in range(9)] for _ in range(num_bins)]
    for note in notes:
        adjusted = max(note.time - start_time, 0.0)
        index = min(int(adjusted // bin_size), num_bins - 1)
        per_second_by_key[index][note.key_index] += 1

    per_second_total = [sum(row) for row in per_second_by_key]
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
    start_bin = len(per_second_total)
    terminal_window_used: float | None = None
    if total_value and note_count > 0:
        gauge_rate = total_value / note_count
        if gauge_rate > 0:
            required_notes = ceil((85.0 - 2.0) / gauge_rate)
            start_idx = max(note_count - required_notes, 0)
            terminal_notes = notes[start_idx:]
            terminal_start = terminal_notes[0].time if terminal_notes else end_time
            window = max(end_time - terminal_start, 0.0)
            terminal_window_used = window
            if window > 0:
                terminal_density = len(terminal_notes) / window
            start_bin = min(max(int(max(terminal_start - start_time, 0.0) // bin_size), 0), len(per_second_total))
            terminal_bins = per_second_total[start_bin:] if start_bin < len(per_second_total) else []
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
    # Root-mean-square of per-second densities
    rms_density = (
        (sum(val * val for val in non_zero_bins) / len(non_zero_bins)) ** 0.5
        if non_zero_bins
        else 0.0
    )
    cms_density = (
        (sum(val**3 for val in non_zero_bins) / len(non_zero_bins)) ** (1.0 / 3.0) if non_zero_bins else 0.0
    )
    chm_density = sum(val * val for val in non_zero_bins) / sum(non_zero_bins) if non_zero_bins else 0.0
    density_change = 0.0
    if per_second_total:
        diffs = [abs(per_second_total[i] - per_second_total[i - 1]) for i in range(1, len(per_second_total))]
        if diffs:
            mean_diff = sum(diffs) / len(diffs)
            density_change = mean_diff / (note_count + epsilon)
    if per_second_total:
        threshold = floor(chm_density)
        occupied_bins = sum(1 for val in per_second_total if val >= threshold)
        high_density_occupancy_rate = (occupied_bins / len(per_second_total)) * 100
    else:
        high_density_occupancy_rate = 0.0

    mean_per_second = sum(non_zero_bins) / len(non_zero_bins) if non_zero_bins else 0.0
    variance = (
        sum((val - mean_per_second) ** 2 for val in non_zero_bins) / len(non_zero_bins)
        if non_zero_bins
        else 0.0
    )
    std_per_second = variance**0.5

    non_terminal_bins = per_second_total[:start_bin]
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


def summarize_history(results: Iterable[DensityResult]) -> Dict[str, float]:
    totals = list(results)
    if not totals:
        return {
            "max_density": 0.0,
            "average_density": 0.0,
            "cms_density": 0.0,
            "chm_density": 0.0,
            "density_change": 0.0,
            "high_density_occupancy_rate": 0.0,
            "terminal_density": 0.0,
            "terminal_rms_density": 0.0,
            "terminal_cms_density": 0.0,
            "terminal_chm_density": 0.0,
            "rms_density": 0.0,
            "overall_difficulty": 0.0,
            "terminal_difficulty": 0.0,
            "terminal_difficulty_cms": 0.0,
            "terminal_difficulty_chm": 0.0,
            "terminal_density_difference": 0.0,
            "gustiness": 0.0,
            "terminal_gustiness": 0.0,
        }

    return {
        "max_density": sum(r.max_density for r in totals) / len(totals),
        "average_density": sum(r.average_density for r in totals) / len(totals),
        "cms_density": sum(r.cms_density for r in totals) / len(totals),
        "chm_density": sum(r.chm_density for r in totals) / len(totals),
        "density_change": sum(r.density_change for r in totals) / len(totals),
        "high_density_occupancy_rate": sum(r.high_density_occupancy_rate for r in totals) / len(totals),
        "terminal_density": sum(r.terminal_density for r in totals) / len(totals),
        "terminal_rms_density": sum(r.terminal_rms_density for r in totals) / len(totals),
        "terminal_cms_density": sum(r.terminal_cms_density for r in totals) / len(totals),
        "terminal_chm_density": sum(r.terminal_chm_density for r in totals) / len(totals),
        "rms_density": sum(r.rms_density for r in totals) / len(totals),
        "overall_difficulty": sum(r.overall_difficulty for r in totals) / len(totals),
        "terminal_difficulty": sum(r.terminal_difficulty for r in totals) / len(totals),
        "terminal_difficulty_cms": sum(r.terminal_difficulty_cms for r in totals) / len(totals),
        "terminal_difficulty_chm": sum(r.terminal_difficulty_chm for r in totals) / len(totals),
        "terminal_density_difference": sum(r.terminal_density_difference for r in totals) / len(totals),
        "gustiness": sum(r.gustiness for r in totals) / len(totals),
        "terminal_gustiness": sum(r.terminal_gustiness for r in totals) / len(totals),
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
