from pms_analyzer.utils import difficulty_sort_key


def test_difficulty_sort_key_numeric_ordering() -> None:
    labels = ["10", "2", "9", "A", "☆12", "☆2"]
    ordered = sorted(labels, key=difficulty_sort_key)
    assert ordered[:4] == ["2", "☆2", "9", "10"]
    assert ordered[-2:] == ["☆12", "A"]


def test_difficulty_sort_key_handles_non_numeric() -> None:
    labels = ["Hard", "Normal", "Easy"]
    ordered = sorted(labels, key=difficulty_sort_key)
    assert ordered == sorted(labels)
