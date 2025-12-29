from pathlib import Path

from pms_analyzer.analysis import compute_density
from pms_analyzer.pms_parser import PMSParser


def test_parse_and_density(tmp_path: Path) -> None:
    content = """
#TITLE Test Song
#ARTIST Tester
#BPM 120
#00011:0100
#00012:0001
#00111:0001
#00103:7800
    """.strip()
    file_path = tmp_path / "test.pms"
    file_path.write_text(content, encoding="utf-8")

    parser = PMSParser()
    result = parser.parse(file_path)

    assert result.title == "Test Song"
    assert len(result.notes) == 3
    # With BPM 120 and two measures, expect around 4 seconds total
    assert 3.5 <= result.total_time <= 4.5

    density = compute_density(result.notes, result.total_time, terminal_window=2.0, total_value=result.total_value)
    assert density.max_density >= 1
    assert density.average_density > 0
    assert density.terminal_density >= 0
    assert density.terminal_rms_density >= 0
    assert density.rms_density > 0


def test_hex_bpm_parsing(tmp_path: Path) -> None:
    content = """
#BPM 120
#00011:0100
#00003:7800
#00011:0001
    """.strip()
    file_path = tmp_path / "hex.pms"
    file_path.write_text(content, encoding="utf-8")

    parser = PMSParser()
    result = parser.parse(file_path)

    # BPM hex 0x78 -> 120, so spacing should keep measure roughly 2 seconds
    assert result.total_time >= 1.9
    assert len(result.notes) == 2


def test_skipped_measures_accumulate_time(tmp_path: Path) -> None:
    content = """
#BPM 120
#00011:0100
#00211:0001
    """.strip()
    file_path = tmp_path / "skip.pms"
    file_path.write_text(content, encoding="utf-8")

    parser = PMSParser()
    result = parser.parse(file_path)

    # Two measures with BPM 120 => ~2 seconds per measure, so skipping #001 should advance time
    # Last note is in measure 2 (0-indexed 002), so expect roughly 4 seconds total
    assert result.total_time >= 3.5


def test_mine_channels_are_ignored(tmp_path: Path) -> None:
    content = """
#BPM 120
#00011:0100
#00016:0001
    """.strip()
    file_path = tmp_path / "mine.pms"
    file_path.write_text(content, encoding="utf-8")

    parser = PMSParser()
    result = parser.parse(file_path)

    # Channel 16 is a mine; only the playable note on channel 11 should be counted
    assert len(result.notes) == 1


def test_duplicate_notes_collapsed(tmp_path: Path) -> None:
    content = """
#BPM 120
#00011:0100
#00051:0100
    """.strip()
    file_path = tmp_path / "dupe.pms"
    file_path.write_text(content, encoding="utf-8")

    parser = PMSParser()
    result = parser.parse(file_path)

    # Same timing, same lane (11 and 51 map to lane 1); should count as one note
    assert len(result.notes) == 1
