from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence

from .pms_parser import Note


@dataclass
class RangeSelectionStats:
    start_seconds: float
    end_seconds: float
    note_count: int
    gauge_increase: float | None
    average_density: float
    rms_density: float
    cms_density: float


def compute_range_rms(per_second: List[int], bin_size: float, start: float, end: float) -> float:
    if end <= start or not per_second or bin_size <= 0:
        return 0.0
    total_duration = end - start
    weighted_sum = 0.0
    for idx, val in enumerate(per_second):
        bin_start = idx * bin_size
        bin_end = bin_start + bin_size
        overlap = max(0.0, min(bin_end, end) - max(bin_start, start))
        if overlap <= 0:
            continue
        weighted_sum += (val * val) * overlap
    return (weighted_sum / total_duration) ** 0.5 if total_duration > 0 else 0.0


def compute_range_cms(per_second: List[int], bin_size: float, start: float, end: float) -> float:
    if end <= start or not per_second or bin_size <= 0:
        return 0.0
    total_duration = end - start
    weighted_sum = 0.0
    for idx, val in enumerate(per_second):
        bin_start = idx * bin_size
        bin_end = bin_start + bin_size
        overlap = max(0.0, min(bin_end, end) - max(bin_start, start))
        if overlap <= 0:
            continue
        weighted_sum += (val**3) * overlap
    return (weighted_sum / total_duration) ** (1.0 / 3.0) if total_duration > 0 else 0.0


def calculate_range_selection_stats(
    per_second_total: List[int],
    duration: float,
    notes: Sequence[Note],
    total_value: float | None,
    start_bin: float,
    end_bin: float,
    *,
    bin_size: float | None = None,
) -> RangeSelectionStats | None:
    if not per_second_total or duration <= 0:
        return None

    bin_count = len(per_second_total)
    resolved_bin_size = bin_size if bin_size and bin_size > 0 else duration / bin_count
    total_span = resolved_bin_size * bin_count

    start_bin_clamped = max(min(start_bin, end_bin), 0.0)
    end_bin_clamped = min(max(start_bin, end_bin), float(bin_count))

    start_bin_index = int(start_bin_clamped)
    end_bin_index = int(end_bin_clamped)
    if end_bin_index <= start_bin_index and end_bin_clamped > start_bin_clamped:
        end_bin_index = min(start_bin_index + 1, bin_count)

    start_seconds = start_bin_index * resolved_bin_size
    end_seconds = min(end_bin_index * resolved_bin_size, total_span)

    first_note_time = notes[0].time if notes else 0.0
    note_count = 0
    if notes:
        end_with_tolerance = end_seconds + 1e-6
        note_count = sum(
            1 for note in notes if start_seconds <= note.time - first_note_time <= end_with_tolerance
        )

    span = end_seconds - start_seconds
    average_density = note_count / span if span > 0 else 0.0

    gauge_increase = None
    if total_value is not None and notes:
        gauge_rate = total_value / len(notes)
        gauge_increase = gauge_rate * note_count

    rms_density = compute_range_rms(per_second_total, resolved_bin_size, start_seconds, end_seconds)
    cms_density = compute_range_cms(per_second_total, resolved_bin_size, start_seconds, end_seconds)

    return RangeSelectionStats(
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        note_count=note_count,
        gauge_increase=gauge_increase,
        average_density=average_density,
        rms_density=rms_density,
        cms_density=cms_density,
    )


__all__ = [
    "RangeSelectionStats",
    "calculate_range_selection_stats",
    "compute_range_rms",
    "compute_range_cms",
]
