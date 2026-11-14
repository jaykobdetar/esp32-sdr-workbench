import math

import pytest

from scripts.dual_stream_campaign import full_burst_opportunity
from sdr_research.dual_timing import coverage


def test_gap_free_combined_timeline_can_miss_whole_bursts():
    # A captures [0,1000], B captures [1000,2000]. No RF time is uncovered,
    # but a 500us packet starting at750 cannot fit in either capture alone.
    windows = [(0, 1000), (1000, 2000)]
    assert coverage(windows, 0, 2000)['coverage_percent'] == 100
    result = full_burst_opportunity(windows, 0, 2000, 500)
    assert result['start_window_us'] == [0, 1500]
    assert result['eligible_start_time_us'] == 1000
    assert result['opportunity_percent'] == pytest.approx(100 * 2 / 3)
    assert result['max_ineligible_start_gap_us'] == 500


def test_overlap_can_make_whole_bursts_fit_without_combining_samples():
    windows = [(0, 1500), (1000, 2500)]
    assert full_burst_opportunity(windows, 0, 2500, 500)['opportunity_percent'] == 100
    assert full_burst_opportunity(windows, 0, 2500, 750)['opportunity_percent'] < 100


def test_each_capture_eroded_before_union_including_same_receiver():
    assert full_burst_opportunity([(0, 100), (100, 200)], 0, 300, 150)['opportunity_percent'] == 0
    assert full_burst_opportunity([(0, 200)], 0, 300, 150)['eligible_start_time_us'] == 50


def test_explicit_denominator_clipping_empty_and_zero_measure():
    result = full_burst_opportunity([(-1000, 2000)], 0, 1000, 100)
    assert result['denominator_us'] == 900 and result['opportunity_percent'] == 100
    assert full_burst_opportunity([], 0, 1000, 100)['opportunity_percent'] == 0
    assert full_burst_opportunity([(0, 100)], 0, 1000, 100)['opportunity_percent'] == 0


@pytest.mark.parametrize('duration', [0, -1, 1000, 1001, math.nan, math.inf, True, '50', 50 + 1j])
def test_reject_bad_duration(duration):
    with pytest.raises(ValueError):
        full_burst_opportunity([(0, 1000)], 0, 1000, duration)


@pytest.mark.parametrize('windows', [[(0, 0)], [(2, 1)], [(0, math.inf)], [(0,)], [(False, 100)]])
def test_reject_bad_capture_windows(windows):
    with pytest.raises(ValueError):
        full_burst_opportunity(windows, 0, 1000, 50)
