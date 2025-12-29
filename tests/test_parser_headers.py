from pathlib import Path

from pms_analyzer.pms_parser import PMSParser


def test_header_with_colon_value(tmp_path: Path) -> None:
    content = """
#TITLE: Colon Title
#SUBTITLE: Sub
#ARTIST: Main Artist
#SUBARTIST: Guest Artist
#GENRE: Test
#BPM:120
#00011:0100
    """.strip()
    file_path = tmp_path / "colon_header.pms"
    file_path.write_text(content, encoding="utf-8")

    parser = PMSParser()
    result = parser.parse(file_path)

    assert result.title == "Colon Title"
    assert result.subtitle == "Sub"
    assert result.artist == "Main Artist"
    assert result.subartist == "Guest Artist"
    assert result.genre == "Test"
    assert result.start_bpm == 120
