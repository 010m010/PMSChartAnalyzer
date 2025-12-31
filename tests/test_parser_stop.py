from pathlib import Path

from pms_analyzer.pms_parser import PMSParser


def test_stop_events_extend_time(tmp_path: Path) -> None:
    content = """
#BPM 120
#STOP01 96
#00011:0100
#00009:0001
#00111:0001
    """.strip()
    file_path = tmp_path / "stop_basic.pms"
    file_path.write_text(content, encoding="utf-8")

    parser = PMSParser()
    result = parser.parse(file_path)

    # STOP01 (96/192 of a measure) at BPM 120 should add ~1 second.
    # Without the STOP, two measures would be ~4 seconds; expect >4s here.
    assert len(result.notes) == 2
    assert result.total_time > 4.0
    assert abs(result.notes[1].time - result.notes[0].time) > 3.5


def test_stop_applies_before_simultaneous_note(tmp_path: Path) -> None:
    content = """
#BPM 150
#STOPAA 192
#00011:0100
#00009:AA00
    """.strip()
    file_path = tmp_path / "stop_same_position.pms"
    file_path.write_text(content, encoding="utf-8")

    parser = PMSParser()
    result = parser.parse(file_path)

    # STOPAA equals one full measure (192 units) at BPM 150 (~1.6s).
    # Note at the same position should be delayed by the STOP duration.
    assert len(result.notes) == 1
    assert 1.5 <= result.notes[0].time <= 1.7
