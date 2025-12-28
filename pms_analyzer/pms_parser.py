from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

KEY_CHANNELS: Dict[int, int] = {
    11: 0,
    12: 1,
    13: 2,
    14: 3,
    15: 4,
    16: 5,
    17: 6,
    18: 7,
    19: 8,
}


@dataclass
class Note:
    time: float
    key_index: int


@dataclass
class ParseResult:
    notes: List[Note]
    total_time: float
    title: str
    artist: str
    file_path: Path


class PMSParser:
    header_pattern = re.compile(r"^#(\w+)(?:\s+(.+))?", re.IGNORECASE)
    line_pattern = re.compile(r"^#(\d{3})(\d{2}):(.+)$")

    def __init__(self, *, default_bpm: float = 130.0) -> None:
        self.default_bpm = default_bpm

    def parse(self, path: Path | str) -> ParseResult:
        path = Path(path)
        text = self._read_file(path)
        bpm = self.default_bpm
        bpm_defs: Dict[str, float] = {}
        measure_lengths: Dict[int, float] = {}
        measures: Dict[int, List[Tuple[int, str]]] = {}
        title = path.stem
        artist = ""

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("//"):
                continue

            header_match = self.header_pattern.match(line)
            if header_match and ":" not in line:
                tag = header_match.group(1).upper()
                value = (header_match.group(2) or "").strip()
                if tag == "BPM" and value:
                    try:
                        bpm = float(value)
                    except ValueError:
                        pass
                elif tag.startswith("BPM") and len(tag) == 5:
                    code = tag[3:]
                    try:
                        bpm_defs[code.upper()] = float(value)
                    except ValueError:
                        pass
                elif tag == "TITLE" and value:
                    title = value
                elif tag == "ARTIST" and value:
                    artist = value
                elif tag == "MEASURE" and value:
                    parts = value.split()
                    if len(parts) == 2 and parts[0].isdigit():
                        try:
                            measure_lengths[int(parts[0])] = float(parts[1])
                        except ValueError:
                            pass
                continue

            line_match = self.line_pattern.match(line)
            if not line_match:
                continue

            measure = int(line_match.group(1))
            channel = int(line_match.group(2))
            data = line_match.group(3)
            measures.setdefault(measure, []).append((channel, data))

        notes, total_time = self._convert_to_notes(measures, bpm, bpm_defs, measure_lengths)

        return ParseResult(
            notes=notes,
            total_time=total_time,
            title=title,
            artist=artist,
            file_path=path,
        )

    def _read_file(self, path: Path) -> str:
        encodings = ["utf-8", "shift_jis", "cp932", "euc-jp"]
        for enc in encodings:
            try:
                return path.read_text(encoding=enc)
            except UnicodeDecodeError:
                continue
        return path.read_text(errors="ignore")

    def _convert_to_notes(
        self,
        measures: Dict[int, List[Tuple[int, str]]],
        base_bpm: float,
        bpm_defs: Dict[str, float],
        measure_lengths: Dict[int, float],
    ) -> tuple[List[Note], float]:
        current_time = 0.0
        current_bpm = base_bpm
        notes: List[Note] = []

        for measure in sorted(measures.keys()):
            events = self._expand_measure_events(measures[measure], bpm_defs)
            measure_length = measure_lengths.get(measure, 1.0)
            events.sort(key=lambda item: (item[0], 0 if item[1] == "bpm" else 1))

            previous_position = 0.0
            for position, kind, value in events:
                delta_pos = position - previous_position
                current_time += self._position_to_seconds(delta_pos, current_bpm, measure_length)
                previous_position = position

                if kind == "bpm":
                    current_bpm = value  # type: ignore[assignment]
                elif kind == "note":
                    notes.append(Note(time=current_time, key_index=value))

            current_time += self._position_to_seconds(1.0 - previous_position, current_bpm, measure_length)

        notes.sort(key=lambda n: n.time)
        return notes, current_time

    def _expand_measure_events(
        self, measure_data: Iterable[Tuple[int, str]], bpm_defs: Dict[str, float]
    ) -> List[Tuple[float, str, float | int]]:
        events: List[Tuple[float, str, float | int]] = []
        for channel, data in measure_data:
            if len(data) % 2 != 0:
                continue
            slots = len(data) // 2
            for idx in range(slots):
                code = data[2 * idx : 2 * idx + 2]
                if code == "00":
                    continue
                position = idx / slots

                if channel in KEY_CHANNELS:
                    events.append((position, "note", KEY_CHANNELS[channel]))
                elif channel == 8:
                    bpm_value = bpm_defs.get(code.upper())
                    if bpm_value:
                        events.append((position, "bpm", bpm_value))
                elif channel == 3:
                    try:
                        bpm_value = int(code, 16)
                        events.append((position, "bpm", float(bpm_value)))
                    except ValueError:
                        continue
        return events

    def _position_to_seconds(self, portion: float, bpm: float, measure_length: float) -> float:
        if bpm <= 0:
            return 0.0
        beats_per_measure = 4.0 * measure_length
        seconds_per_beat = 60.0 / bpm
        return portion * beats_per_measure * seconds_per_beat


__all__ = ["PMSParser", "ParseResult", "Note"]
