import json
from pathlib import Path

from pms_analyzer import storage
from pms_analyzer.analysis import DensityResult
from pms_analyzer.difficulty_table import ChartAnalysis, DifficultyEntry, DifficultyTable


def test_cached_difficulty_includes_density(monkeypatch, tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(storage, "CONFIG_DIR", cache_dir)
    monkeypatch.setattr(storage, "CONFIG_PATH", cache_dir / "config.json")
    monkeypatch.setattr(storage, "HISTORY_PATH", cache_dir / "history.json")
    monkeypatch.setattr(storage, "DIFFICULTY_CACHE_PATH", cache_dir / "difficulty_cache.json")
    storage.ensure_config_dir()

    entry = DifficultyEntry(
        difficulty="12",
        title="Test Song",
        subtitle=None,
        chart_path=tmp_path / "test.pms",
        artist="Tester",
        md5="abc",
        sha256="def",
        total_value=120.0,
        note_count=3,
    )
    density = DensityResult(
        per_second_total=[1, 2],
        per_second_by_key=[[1, 0, 0, 0, 0, 0, 0, 0, 0], [2, 0, 0, 0, 0, 0, 0, 0, 0]],
        max_density=2.0,
        average_density=1.5,
        cms_density=1.5,
        chm_density=1.5,
        high_density_occupancy_rate=50.0,
        terminal_density=0.5,
        terminal_rms_density=0.5,
        terminal_cms_density=0.5,
        terminal_chm_density=0.5,
        rms_density=1.25,
        duration=2.0,
        terminal_window=1.0,
        overall_difficulty=1.0,
        terminal_difficulty=0.1,
        terminal_difficulty_cms=0.2,
        terminal_difficulty_chm=0.3,
        terminal_density_difference=0.4,
        gustiness=0.5,
        terminal_gustiness=0.6,
    )
    analysis = ChartAnalysis(
        difficulty="12",
        density=density,
        entry=entry,
        resolved_path=entry.chart_path,
        note_count=entry.note_count or 0,
        total_value=entry.total_value,
        title=entry.title,
        subtitle=entry.subtitle,
        md5=entry.md5,
        sha256=entry.sha256,
    )
    table = DifficultyTable(name="example", entries=[entry], symbol="☆")

    url = "http://example.com/table.csv"
    storage.save_cached_difficulty_table(url, table, [analysis])

    raw_cache = json.loads(storage.DIFFICULTY_CACHE_PATH.read_text(encoding="utf-8"))
    assert url in raw_cache
    assert "analyses" in raw_cache[url]
    assert raw_cache[url]["analyses"]
    assert set(raw_cache[url]["analyses"][0]["density"].keys()) == {
        "per_second_total",
        "per_second_by_key",
        "duration",
    }

    cached = storage.load_cached_difficulty_data(url)
    assert cached is not None
    assert cached.table.name == "example"
    assert cached.analyses
    loaded_analysis = cached.analyses[0]
    assert loaded_analysis.density.per_second_total == density.per_second_total
    assert loaded_analysis.density.high_density_occupancy_rate == 100.0
    assert loaded_analysis.density.average_density == 1.5
    assert loaded_analysis.density.terminal_density == 1.5
    assert loaded_analysis.resolved_path == entry.chart_path
