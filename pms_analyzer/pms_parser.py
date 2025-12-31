
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


def _build_key_channels() -> Dict[int, int]:
    """Map PMS/BMS channels to 9key lanes.

    Pop'n Music 9key-style PMS files can place notes on multiple channel sets:
    - 11-19: primary 1P lanes
    - 21-29: secondary set (some creators/exporters use these)
    - 51-59: long-note channels (treated as standard notes for density)
    """

    mapping: Dict[int, int] = {}
    for base in (10, 20, 50):
        for offset, key_index in enumerate(range(1, 10)):
            mapping[base + key_index] = offset
    return mapping


KEY_CHANNELS: Dict[int, int] = _build_key_channels()
# Channels used for mines or invisible notes should be excluded from density counts.
# Common BMS/PMS mine channels mirror key channels with the "6" suffix.
MINE_CHANNELS: set[int] = {16, 26, 36, 46, 56, 66, 76, 86}


@dataclass
class Note:
    time: float
    key_index: int


@dataclass
class ParseResult:
    notes: List[Note]
    total_time: float
    title: str
    subtitle: str
    genre: str
    artist: str
    subartist: str
    rank: int | None
    level: str
    start_bpm: float
    min_bpm: float
    max_bpm: float
    total_value: float | None
    file_path: Path


@dataclass
class _ConditionBlock:
    type: str
    parent_active: bool
    current_active: bool
    matched_branch: bool
    switch_value: int | None = None


class PMSParser:
    header_pattern = re.compile(r"^#(\w+)(?::|\s+)?(.*)$", re.IGNORECASE)
    line_pattern = re.compile(r"^#(\d{3})(\d{2}):(.+)$")
    extension_command_pattern = re.compile(
        r"^#\s*(RANDOM|SETRANDOM|IF|ELSEIF|ELSE|ENDIF|SWITCH|CASE|DEFAULT|ENDSWITCH|ENDRANDOM)\b",
        re.IGNORECASE,
    )

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
        subtitle = ""
        genre = ""
        total_value: float | None = None
        artist = ""
        subartist = ""
        rank: int | None = None
        level = ""
        random_stack: List[int | None] = []
        condition_stack: List[_ConditionBlock] = []

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("//"):
                continue

            handled = self._handle_extension_command(line, condition_stack, random_stack)
            if handled:
                continue
            if not self._is_currently_active(condition_stack):
                continue

            line_match = self.line_pattern.match(line)
            if line_match:
                measure = int(line_match.group(1))
                channel = int(line_match.group(2))
                data = line_match.group(3)
                if channel == 2:  # measure length (e.g., #00102:1.50)
                    try:
                        measure_lengths[measure] = float(data)
                    except ValueError:
                        pass
                    continue
                measures.setdefault(measure, []).append((channel, data))
                continue

            header_match = self.header_pattern.match(line)
            if header_match:
                tag = header_match.group(1).upper()
                value = (header_match.group(2) or "").lstrip()
                if value.startswith(":"):
                    value = value[1:].lstrip()
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
                elif tag == "SUBTITLE" and value:
                    subtitle = value
                elif tag == "TOTAL" and value:
                    try:
                        total_value = float(value)
                    except ValueError:
                        pass
                elif tag == "GENRE" and value:
                    genre = value
                elif tag == "SUBARTIST" and value:
                    subartist = value
                elif tag == "RANK" and value:
                    try:
                        rank = int(value)
                    except ValueError:
                        rank = None
                elif tag in {"LEVEL", "PLAYLEVEL"} and value:
                    level = value
                elif tag == "MEASURE" and value:
                    parts = value.split()
                    if len(parts) == 2 and parts[0].isdigit():
                        try:
                            measure_lengths[int(parts[0])] = float(parts[1])
                        except ValueError:
                            pass
                continue

        notes, total_time, bpm_stats = self._convert_to_notes(measures, bpm, bpm_defs, measure_lengths)
        start_bpm, min_bpm, max_bpm = bpm_stats

        return ParseResult(
            notes=notes,
            total_time=total_time,
            title=title,
            subtitle=subtitle,
            genre=genre,
            artist=artist,
            subartist=subartist,
            rank=rank,
            level=level,
            start_bpm=start_bpm,
            min_bpm=min_bpm,
            max_bpm=max_bpm,
            total_value=total_value,
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

    def _handle_extension_command(
        self, line: str, condition_stack: List["_ConditionBlock"], random_stack: List[int | None]
    ) -> bool:
        match = self.extension_command_pattern.match(line)
        if not match:
            return False

        command = match.group(1).upper()
        argument = line[match.end() :].strip()
        if command == "RANDOM":
            self._push_random(argument, random_stack)
        elif command == "SETRANDOM":
            self._set_random(argument, random_stack)
        elif command == "ENDRANDOM":
            if random_stack:
                random_stack.pop()
        elif command == "IF":
            parent_active = self._is_currently_active(condition_stack)
            condition_result = parent_active and self._evaluate_condition(argument, random_stack)
            condition_stack.append(
                _ConditionBlock(
                    type="if",
                    parent_active=parent_active,
                    current_active=condition_result,
                    matched_branch=condition_result,
                )
            )
        elif command == "ELSEIF":
            if condition_stack and condition_stack[-1].type == "if":
                block = condition_stack[-1]
                if not block.parent_active:
                    block.current_active = False
                elif block.matched_branch:
                    block.current_active = False
                else:
                    condition_result = self._evaluate_condition(argument, random_stack)
                    block.current_active = condition_result
                    block.matched_branch = condition_result
        elif command == "ELSE":
            if condition_stack and condition_stack[-1].type == "if":
                block = condition_stack[-1]
                if not block.parent_active or block.matched_branch:
                    block.current_active = False
                else:
                    block.current_active = True
                    block.matched_branch = True
        elif command == "ENDIF":
            if condition_stack and condition_stack[-1].type == "if":
                condition_stack.pop()
        elif command == "SWITCH":
            parent_active = self._is_currently_active(condition_stack)
            switch_value = self._parse_int_argument(argument)
            if switch_value is None:
                switch_value = random_stack[-1] if random_stack else None
            condition_stack.append(
                _ConditionBlock(
                    type="switch",
                    parent_active=parent_active,
                    current_active=False,
                    matched_branch=False,
                    switch_value=switch_value,
                )
            )
        elif command == "CASE":
            if condition_stack and condition_stack[-1].type == "switch":
                block = condition_stack[-1]
                case_value = self._parse_int_argument(argument)
                if (
                    block.parent_active
                    and not block.matched_branch
                    and case_value is not None
                    and case_value == block.switch_value
                ):
                    block.current_active = True
                    block.matched_branch = True
                else:
                    block.current_active = False
        elif command == "DEFAULT":
            if condition_stack and condition_stack[-1].type == "switch":
                block = condition_stack[-1]
                if block.parent_active and not block.matched_branch:
                    block.current_active = True
                    block.matched_branch = True
                else:
                    block.current_active = False
        elif command == "ENDSWITCH":
            if condition_stack and condition_stack[-1].type == "switch":
                condition_stack.pop()

        return True

    def _push_random(self, argument: str, random_stack: List[int | None]) -> None:
        value = self._parse_int_argument(argument)
        if value is None:
            selected_value = 1
        elif value > 0:
            selected_value = 1
        else:
            selected_value = None

        random_stack.append(selected_value)

    def _set_random(self, argument: str, random_stack: List[int | None]) -> None:
        value = self._parse_int_argument(argument)
        selected_value = 1 if value is None else value
        if random_stack:
            random_stack[-1] = selected_value
        else:
            random_stack.append(selected_value)

    def _evaluate_condition(self, argument: str, random_stack: List[int | None]) -> bool:
        condition_value = self._parse_int_argument(argument)
        current_random = random_stack[-1] if random_stack else None
        if current_random is not None:
            return condition_value is not None and current_random == condition_value
        if condition_value is None:
            return False
        return condition_value != 0

    def _parse_int_argument(self, argument: str) -> int | None:
        if not argument:
            return None
        token = argument.split()[0]
        try:
            return int(token)
        except ValueError:
            return None

    def _is_currently_active(self, condition_stack: List["_ConditionBlock"]) -> bool:
        return all(block.current_active for block in condition_stack)

    def _convert_to_notes(
        self,
        measures: Dict[int, List[Tuple[int, str]]],
        base_bpm: float,
        bpm_defs: Dict[str, float],
        measure_lengths: Dict[int, float],
    ) -> tuple[List[Note], float, tuple[float, float, float]]:
        current_time = 0.0
        current_bpm = base_bpm
        notes: List[Note] = []
        previous_measure = -1
        min_bpm = base_bpm
        max_bpm = base_bpm

        for measure in sorted(measures.keys()):
            # Skip missing measures while keeping BPM
            for missing in range(previous_measure + 1, measure):
                gap_length = measure_lengths.get(missing, 1.0)
                current_time += self._position_to_seconds(1.0, current_bpm, gap_length)

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
                    min_bpm = min(min_bpm, current_bpm)
                    max_bpm = max(max_bpm, current_bpm)
                elif kind == "note":
                    notes.append(Note(time=current_time, key_index=value))

            current_time += self._position_to_seconds(1.0 - previous_position, current_bpm, measure_length)
            previous_measure = measure

        notes.sort(key=lambda n: n.time)
        unique_notes: List[Note] = []
        for note in notes:
            if unique_notes and note.key_index == unique_notes[-1].key_index and abs(note.time - unique_notes[-1].time) < 1e-6:
                continue
            unique_notes.append(note)
        return unique_notes, current_time, (base_bpm, min_bpm, max_bpm)

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

                if channel in MINE_CHANNELS:
                    continue
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
