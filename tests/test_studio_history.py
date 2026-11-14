"""History rendering contracts with inert widget doubles, no QApplication/hardware."""

from types import SimpleNamespace

import pytest

from sdr_research.studio_gui import StudioWindow


class Text:
    def setText(self, value):
        self.value = value


class Items:
    def __init__(self):
        self.items = []

    def clear(self):
        self.items.clear()

    def addItem(self, value):
        self.items.append(value)

    def setCurrentRow(self, row):
        self.row = row


def fake_window(tmp_path):
    return SimpleNamespace(
        history_root=tmp_path,
        history_list=Items(),
        history_path=Text(),
        history_summary=Text(),
        capture_list=Items(),
        history=[],
    )


@pytest.mark.parametrize('receivers', [None, 1, 'bad', {}, [None], [42], [[]]])
def test_bad_receiver_descriptors_do_not_crash_refresh(tmp_path, monkeypatch, receivers):
    w = fake_window(tmp_path)
    monkeypatch.setattr(
        'sdr_research.studio_gui.session_history',
        lambda root: [(tmp_path, {'receivers': receivers})],
    )
    StudioWindow.refresh_history(w)
    assert 'Unknown device data' in w.history_list.items[0]


@pytest.mark.parametrize(
    'receivers,expected',
    [
        ([], 'Hardware'),
        ([{'demo': True}], 'Simulation'),
        ([{'demo': False}], 'Hardware'),
        ([{'demo': 'false'}], 'Hardware'),
    ],
)
def test_history_mode_uses_literal_demo_boolean(tmp_path, monkeypatch, receivers, expected):
    w = fake_window(tmp_path)
    monkeypatch.setattr(
        'sdr_research.studio_gui.session_history',
        lambda root: [(tmp_path, {'receivers': receivers})],
    )
    StudioWindow.refresh_history(w)
    assert expected in w.history_list.items[0]


@pytest.mark.parametrize(
    'results',
    [
        None,
        [],
        'bad',
        2,
        {'RX': None},
        {'RX': {'captures': '12', 'retained': []}},
        {'RX': {'captures': True, 'retained': -2}},
    ],
)
def test_bad_receiver_results_do_not_crash_selection(tmp_path, results):
    w = fake_window(tmp_path)
    w.history = [(tmp_path, {'receiver_results': results})]
    StudioWindow.select_history(w, 0)
    assert 'unavailable' in w.history_summary.value or 'unknown' in w.history_summary.value
    assert len(w.capture_list.items) == 1


def test_valid_counts_and_missing_counts_remain_distinct(tmp_path):
    w = fake_window(tmp_path)
    w.history = [
        (tmp_path, {'receiver_results': {'RX': {'captures': 1000, 'retained': 0}, 'Other': {}}})
    ]
    StudioWindow.select_history(w, 0)
    assert '1,000 captures, 0 detector events retained' in w.history_summary.value
    assert 'unknown captures, unknown detector events retained' in w.history_summary.value


def test_invalid_selection_clears_previous_capture_list(tmp_path):
    w = fake_window(tmp_path)
    w.capture_list.addItem('old')
    StudioWindow.select_history(w, -1)
    assert not w.capture_list.items
