from pytest import approx

from pms_analyzer.range_stats import calculate_range_selection_stats, compute_range_cms, compute_range_rms
from pms_analyzer.pms_parser import Note


def test_compute_range_cms_and_rms_partial_overlap() -> None:
    per_second = [1, 2, 3]
    bin_size = 1.0
    start = 0.0
    end = 2.0

    rms = compute_range_rms(per_second, bin_size, start, end)
    cms = compute_range_cms(per_second, bin_size, start, end)

    assert rms == approx((5.0 / 2.0) ** 0.5)
    assert cms == approx(4.5 ** (1.0 / 3.0))


def test_range_selection_stats_includes_cms_density() -> None:
    notes = [Note(time=0.0, key_index=0), Note(time=1.0, key_index=1), Note(time=2.0, key_index=2)]
    per_second = [1, 2, 1]
    stats = calculate_range_selection_stats(
        per_second_total=per_second,
        duration=3.0,
        notes=notes,
        total_value=100.0,
        start_bin=0.0,
        end_bin=3.0,
        bin_size=1.0,
    )

    assert stats is not None
    assert stats.cms_density > 0
    assert stats.rms_density > 0
