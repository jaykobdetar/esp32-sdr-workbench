"""A later legacy anchor epoch must not hide an invalidated earlier intended trial."""

import sys

import pytest

import scripts.multi_stream_campaign as module


@pytest.mark.parametrize('fault', ['missing', 'unverified', 'duplicate', 'mislabeled'])
def test_intended_trial_inventory_fails_closed(fault):
    report = dict(
        measurement_run_indices=[0],
        runs=[dict(index=0, trial_role='measurement', analysis=dict(status='verified-telemetry'))],
    )
    if fault == 'missing':
        report['runs'] = []
    if fault == 'unverified':
        report['runs'][0]['analysis']['status'] = 'unverified'
    if fault == 'duplicate':
        report['measurement_run_indices'].append(0)
    if fault == 'mislabeled':
        report['runs'][0]['trial_role'] = 'phase-sweep'
    with pytest.raises(RuntimeError):
        module.validate_measurement_runs(report, 1)


@pytest.mark.parametrize('phase_sweep', [False, True])
def test_main_gates_all_measurements_but_not_failed_exploratory_phases(
    monkeypatch, tmp_path, phase_sweep
):
    campaigns = []

    class Radio:
        info = {'caps': ['DSTREAM']}

        def __init__(self, port):
            pass

        def connect(self):
            return self.info

        def command(self, *args):
            pass

        def configure(self, *args):
            pass

    class TX:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def stop(self):
            pass

        def status(self):
            return {'running': False}

        def configure(self, **kwargs):
            pass

    class Campaign:
        def __init__(self, *args, **kwargs):
            self.report = dict(status='running', runs=[], anchors=[])
            campaigns.append(self)

        def check_calibration(self, *args):
            return []

        def anchors(self, **kwargs):
            self.report['anchors'] = [len(self.report['runs'])]

        def run(self, milliseconds, period_ns, phases, compensate):
            self.report['runs'].append(dict(index=len(self.report['runs']), yield_phases=phases))

        def cleanup(self):
            if self.report['status'] == 'validated':
                self.report['status'] = 'passed'
            return []

        def save(self):
            pass

    def analyze(row, anchors):
        # Without sweep: run0 initially passes; after run1, run0 fails while run1 passes.
        # With sweep: failed phase0 must not invalidate successful intended trials8/9.
        invalid = row['index'] == 0 and (phase_sweep or anchors[0] >= 2)
        if invalid:
            return dict(status='unverified', reason='late anchor invalidation')
        return dict(
            status='verified-telemetry', nominal_union=dict(coverage_percent=99, max_gap_us=1)
        )

    monkeypatch.setattr(module, 'Radio', Radio)
    monkeypatch.setattr(module, 'Transmitter', TX)
    monkeypatch.setattr(module, 'Campaign', Campaign)
    monkeypatch.setattr(module, 'analyze_run', analyze)
    argv = [
        'campaign',
        '--port',
        'mockA',
        '--port',
        'mockB',
        '--tx-serial',
        'fake',
        '--output',
        str(tmp_path / 'out'),
        '--trials',
        '2',
        '--run',
    ]
    if phase_sweep:
        argv.append('--phase-sweep')
    monkeypatch.setattr(sys, 'argv', argv)
    if phase_sweep:
        module.main()
        assert campaigns[0].report['status'] == 'passed'
        assert campaigns[0].report['measurement_run_indices'] == [8, 9]
        assert campaigns[0].report['runs'][0]['analysis']['status'] == 'unverified'
    else:
        with pytest.raises(RuntimeError, match='measurement run 0'):
            module.main()
        assert campaigns[0].report['status'] == 'failed'
        assert campaigns[0].report['runs'][1]['analysis']['status'] == 'verified-telemetry'
