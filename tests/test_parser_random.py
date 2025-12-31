from pathlib import Path

from pms_analyzer.pms_parser import KEY_CHANNELS, PMSParser


def test_random_branch_is_deterministic(tmp_path: Path) -> None:
    content = """
#RANDOM 4
#IF 1
#00011:0100
#ENDIF
#IF 2
#00012:0200
#ENDIF
#IF 3
#00013:0300
#ENDIF
#IF 4
#00014:0400
#ENDIF
    """.strip()
    file_path = tmp_path / "random_branch.pms"
    file_path.write_text(content, encoding="utf-8")

    parser = PMSParser()
    result = parser.parse(file_path)

    assert len(result.notes) == 1
    assert result.notes[0].key_index == KEY_CHANNELS[11]
