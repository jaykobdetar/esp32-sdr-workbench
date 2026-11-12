"""Reference-model parity with actual firmware headers, without radio hardware."""

import random
import shutil
import subprocess
from pathlib import Path

import pytest

from sdr_research.detector_model import SCALE, Background, energy

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def reference_binary(tmp_path_factory):
    if not shutil.which('cc'):
        pytest.skip('Host C compiler unavailable')
    folder = tmp_path_factory.mktemp('detector-model')
    source = folder / 'check.c'
    source.write_text(r"""
#include <stdio.h>
#include <inttypes.h>
#include "firmware/main/targets/esp32/detector_energy.h"
#include "firmware/main/targets/esp32/pipeline_energy3.h"
#include "firmware/main/targets/esp32/detector_background.h"
int main(void) {
    uint32_t words[16380], mean, peak, other_mean, other_peak;
    unsigned n, ratio, score;
    char mode;
    detector_background_t background = {0};
    /* Historical optimized-v2 state, stepped by the lines quoted from its source. */
    unsigned captures = 0, background_v2 = 1;
    uint64_t warm_total = 0;
    while(scanf(" %c", &mode) == 1) {
        if(mode == 'e') {
            if(scanf("%u", &n) != 1 || n > 16380) return 1;
            for(unsigned j=0;j<n;j++) if(scanf("%" SCNu32, &words[j]) != 1) return 2;
            detector_energy(words,n,&mean,&peak);
            pipeline_energy_flash_3(words,n,&other_mean,&other_peak);
            if(mean != other_mean || peak != other_peak) return 3;
            printf("%u %u\n",mean,peak);
        } else if(mode == 'b') {
            if(scanf("%" SCNu32 " %" SCNu32 " %u",&mean,&peak,&ratio)!=3) return 4;
            bool event = detector_background_step(&background,mean,peak,ratio,&score);
            printf("%u %u %" PRIu64 "\n",event,score,background.q16);
        } else if(mode == 'p') {
            if(scanf("%u",&n)!=1) return 6;
            background = detector_background_start(n);
            captures = 0; background_v2 = 1; warm_total = 0;
        } else if(mode == 'h') {
            if(scanf("%" SCNu32 " %" SCNu32 " %u",&mean,&peak,&ratio)!=3) return 7;
            unsigned event = 0, v2_score = 0;
            unsigned background = background_v2;
            captures++;
            if (captures <= 16) {
                warm_total += mean;
                background = warm_total / captures;
                if (!background) background = 1;
            } else if ((uint64_t)peak * 1000 > (uint64_t)background * ratio) {
                event = 1;
                unsigned score = (uint64_t)peak * 1000 / background;
                v2_score = score;
            } else {
                v2_score = (uint64_t)peak * 1000 / background;
                background = ((uint64_t)background * 63 + mean + 32) / 64;
                if (!background) background = 1;
            }
            background_v2 = background;
            printf("%u %u %" PRIu64 "\n",event,v2_score,(uint64_t)background_v2 * 65536);
        } else return 5;
    }
    return 0;
}
""")
    binary = folder / 'check'
    subprocess.run(
        [
            'cc',
            '-std=c11',
            '-O2',
            '-Wall',
            '-Wextra',
            '-Werror',
            '-fsanitize=undefined',
            '-fno-sanitize-recover=all',
            '-I',
            str(ROOT),
            str(source),
            '-o',
            str(binary),
        ],
        check=True,
    )
    return binary


def test_energy_matches_both_c_kernels(reference_binary):
    rng = random.Random(2741)
    cases = [[], [0] * 64, [0xFFFFFFFF] * 16380]
    for n in (1, 63, 64, 65, 127, 128, 256, 4096, 16380):
        cases.extend(
            [
                [rng.getrandbits(32) for _ in range(n)],
                [((511 if j % 2 else 512) | ((511 if j % 3 else 512) << 10)) for j in range(n)],
            ]
        )
    result = subprocess.run(
        [str(reference_binary)],
        input=''.join(
            'e ' + str(len(words)) + ' ' + ' '.join(map(str, words)) + '\n' for words in cases
        ),
        text=True,
        capture_output=True,
        check=True,
    )
    assert [tuple(map(int, line.split())) for line in result.stdout.splitlines()] == [
        energy(words) for words in cases
    ]


def test_q16_background_matches_c_long_sequences(reference_binary):
    rng = random.Random(739)
    cases = [(0, 0, 4000)] * 16 + [(0, 1, 4000)]
    cases += [(2, 2, 4000)] * 1000 + [(34, 34, 4000)] * 1600
    cases += [(524288, 524288, 1000000)] * 5
    cases += [
        (mean := rng.randrange(524289), rng.randrange(mean, 524289), rng.randrange(1000, 1000001))
        for _ in range(500)
    ]
    result = subprocess.run(
        [str(reference_binary)],
        input=''.join(f'b {a} {b} {r}\n' for a, b, r in cases),
        text=True,
        capture_output=True,
        check=True,
    )
    model = Background()
    expected = []
    for mean, peak, ratio in cases:
        event, score = model.step(mean, peak, ratio)
        expected.append((int(event), score, model.background_q16))
    assert [tuple(map(int, line.split())) for line in result.stdout.splitlines()] == expected


def test_sustained_step_recovers_and_preserves_fractional_background():
    old, new = Background(1), Background(2)
    for _ in range(16):
        old.step(2, 2)
        new.step(2, 2)
    assert old.step(34, 34)[0] and new.step(34, 34)[0]
    assert new.background_q16 % SCALE
    for _ in range(1500):
        assert old.step(34, 34)[0]
        last, _ = new.step(34, 34)
    assert not last
    assert new.background_q16 > 33 * SCALE


def test_warmup_zero_floor_and_tail():
    model = Background()
    assert all(not model.step(0, 0)[0] for _ in range(16))
    assert model.background_q16 == 1
    assert model.step(0, 524288)[1] == 0xFFFFFFFF
    assert energy([0] * 64 + [0xFFFFFFFF] * 63) == (0, 0)
    with pytest.raises(ValueError):
        model.step(1, 0)


def test_saved_cf32_cap20_roundtrip_and_reject_loss():
    from sdr_research.detector_model import words_from_iq
    from sdr_research.protocol import decode_iq

    rng = random.Random(928)
    words = [rng.randrange(1 << 20) for _ in range(256)] + [512 | (512 << 10), 511 | (511 << 10)]
    packed = sum(word << (20 * j) for j, word in enumerate(words)).to_bytes(
        (len(words) * 20 + 7) // 8, 'little'
    )
    iq = decode_iq(packed, len(words), 10)
    assert words_from_iq(iq, bits=10) == words
    for values, bits in [
        ([0j], 8),
        ([0.00001j], 10),
        ([complex(float('nan'), 0)], 10),
        ([1 + 0j], 10),
        ([], 10),
    ]:
        with pytest.raises(ValueError):
            words_from_iq(values, bits=bits)


def test_offline_replay_explicit_sequence_and_selected_guard(tmp_path):
    import numpy as np

    from sdr_research.detector_model import replay_sigmf
    from sdr_research.protocol import Capture
    from sdr_research.recording import save_capture

    paths = []
    for j in range(18):
        iq = np.array([1 / 512, -1 / 512] * 32, dtype=np.complex64)
        capture = Capture(
            iq,
            16000000,
            2440000000,
            '2026-11-11T00:00:00Z',
            0,
            1,
            1,
            10,
            True,
            {'settings': {'gain': 40}},
        )
        paths.append(str(save_capture(capture, tmp_path / f'capture-{j}')))
    result = replay_sigmf(paths)
    assert [row['file'] for row in result['records']] == paths
    assert all(row['mean_adc2'] == 1 for row in result['records'])
    capture.metadata['detector_summary'] = {}
    selected = str(save_capture(capture, tmp_path / 'selected'))
    with pytest.raises(ValueError, match='biased'):
        replay_sigmf([selected])
    assert replay_sigmf([selected], allow_selected=True)['selected_capture_count'] == 1


def test_retention_crop_helpers_under_ubsan(tmp_path):
    if not shutil.which('cc'):
        pytest.skip('Host C compiler unavailable')
    source = tmp_path / 'retention.c'
    source.write_text(
        r"""
#include <assert.h>
#include <stdio.h>
#include "firmware/main/targets/esp32/detector_energy.h"
#include "firmware/main/targets/esp32/detector_retention.h"
static uint32_t words[16380];
int main(void) {
    detector_candidate_t candidates[3] = {{0}};
    for(unsigned n=256;n<=16380;n++) {
        unsigned crop=detector_crop_length(n), offset=detector_crop_offset(words,n,crop);
        assert(crop<=n && crop<=5120 && !(crop&7));
        assert(offset+crop<=n && !(offset&7));
    }
    assert(3u*5120*20/8 <= 16380u*20/8);
    for(unsigned j=0;j<3;j++) {
        assert(detector_candidate_slot(candidates,3,100)==j);
        candidates[j]=(detector_candidate_t){.samples=5120,.score_milli=100+j};
    }
    assert(detector_candidate_slot(candidates,3,99)==3);
    assert(detector_candidate_slot(candidates,3,100)==3);
    assert(detector_candidate_slot(candidates,3,103)==0);
    /* A 4672-sample/292 us source centered on the highest-energy block fits
     * at 16 MS/s, but duration alone cannot guarantee arbitrary alignment. */
    for(unsigned j=6000;j<10672;j++) words[j]=(j&1)?511u:512u;
    for(unsigned j=8320;j<8384;j++) words[j]=(j&1)?(511u|(511u<<10)):(512u|(512u<<10));
    unsigned offset=detector_crop_offset(words,16380,5120);
    assert(offset<=6000 && offset+5120>=10672);
    assert(5120u*1000000u/16000000u >= 292u); /* promote below to avoid overflow */
    puts("retention bounds and known-frame fixture passed");
}
""".replace('5120u*1000000u', 'UINT64_C(5120)*1000000')
    )
    binary = tmp_path / 'retention'
    subprocess.run(
        [
            'cc',
            '-O2',
            '-std=c11',
            '-Wall',
            '-Wextra',
            '-Werror',
            '-fsanitize=undefined',
            '-fno-sanitize-recover=all',
            '-I',
            str(ROOT),
            str(source),
            '-o',
            str(binary),
        ],
        check=True,
    )
    subprocess.run([str(binary)], check=True)


HISTORICAL_RULE_LINES = (
    'if (captures <= 16) {',
    'warm_total += mean;',
    'background = warm_total / captures;',
    'if (!background) background = 1;',
    '} else if ((uint64_t)peak * 1000 > (uint64_t)background * ratio) {',
    'unsigned score = (uint64_t)peak * 1000 / background;',
    'background = ((uint64_t)background * 63 + mean + 32) / 64;',
)


def legacy_cases():
    rng = random.Random(4471)
    cases = [(0, 0, 4000)] * 16 + [(0, 1, 4000)]
    cases += [(2, 2, 4000)] * 400 + [(34, 34, 4000)] * 400 + [(3, 20, 4000)] * 50
    cases += [(524288, 524288, 1000000)] * 5 + [(1, 524288, 1000)] * 5
    cases += [
        (mean := rng.randrange(524289), rng.randrange(mean, 524289), rng.randrange(1000, 1000001))
        for _ in range(500)
    ]
    return cases


def test_legacy_policy_matches_model_and_the_measured_v2_rule(reference_binary):
    """Selectable policy 1 must be the optimized-v2 rule, not an approximation of it."""
    cases = legacy_cases()

    def run(mode):
        result = subprocess.run(
            [str(reference_binary)],
            input='p 1\n' + ''.join(f'{mode} {a} {b} {r}\n' for a, b, r in cases),
            text=True,
            capture_output=True,
            check=True,
        )
        return [tuple(map(int, line.split())) for line in result.stdout.splitlines()]

    selectable, historical = run('b'), run('h')
    model = Background(policy=1)
    expected = []
    for mean, peak, ratio in cases:
        event, score = model.step(mean, peak, ratio)
        expected.append((int(event), score, model.background_q16))
    assert selectable == expected
    assert selectable == historical
    assert all(q16 % SCALE == 0 and q16 >= SCALE for _, _, q16 in selectable)
    # The harness steps the historical state with lines quoted from the archived v2 source.
    fixture = ROOT / 'tests/fixtures/retention-base/firmware/main/targets/esp32'
    v2_source = (fixture / 'detector_experiment.h').read_text()
    harness = Path(__file__).read_text()
    for line in HISTORICAL_RULE_LINES:
        assert line in v2_source and line in harness.split('HISTORICAL_RULE_LINES')[0], line


def test_policy_start_selects_rule_and_zero_state_stays_policy_two(reference_binary):
    """Latch contrast on one sustained level step: legacy never recovers, Q16 does."""
    cases = [(20, 27, 4000)] * 100 + [(200, 270, 4000)] * 400

    def events(prefix):
        result = subprocess.run(
            [str(reference_binary)],
            input=prefix + ''.join(f'b {a} {b} {r}\n' for a, b, r in cases),
            text=True,
            capture_output=True,
            check=True,
        )
        return [int(line.split()[0]) for line in result.stdout.splitlines()]

    legacy, q16, zero_state = events('p 1\n'), events('p 2\n'), events('')
    assert zero_state == q16
    assert sum(legacy[100:]) == 400  # latched for the rest of the run
    assert 0 < sum(q16[100:]) < 150 and not any(q16[300:])


def persistent_source_flag_rate(policy, strength, runs=20, captures=600):
    """Share of source-bearing captures flagged when a periodic source is on all run.

    Model of the controlled-source geometry: a frame lands in about two thirds of
    captures and fills about 28.5% of one, so a burst `strength` times the floor
    raises that capture's mean by 0.285 * strength and its peak block by strength.
    """
    floor, hits, total = 400, 0, 0
    for run in range(runs):
        rng = random.Random(1000 * run + 7)
        model = Background(policy=policy)
        for index in range(captures):
            burst = rng.random() < 0.66
            jitter = rng.uniform(0.93, 1.07)
            mean = floor * jitter * (1 + 0.285 * strength if burst else 1)
            peak = floor * jitter * (1 + strength if burst else 1.35)
            positive, _ = model.step(int(mean), int(peak), 4000)
            if index >= 16 and burst:
                total += 1
                hits += positive
    return 100 * hits / total


def test_model_prediction_rules_differ_only_for_a_moderate_persistent_source():
    """Pins the reference model's behavior, not hardware.

    The v7 same-image board comparison did not show this legacy advantage; see
    docs/adaptive-detector.md. The burst geometry and noise here are simplifications.
    """
    # Weak bursts are missed and strong bursts caught by both rules alike.
    for strength in (3, 5):
        assert persistent_source_flag_rate(1, strength) == 0
        assert persistent_source_flag_rate(2, strength) == 0
    for strength in (20, 50):
        legacy = persistent_source_flag_rate(1, strength)
        assert legacy > 95 and abs(legacy - persistent_source_flag_rate(2, strength)) < 1
    # In between, the Q16 rule absorbs part of the source into its background.
    legacy, q16 = persistent_source_flag_rate(1, 8), persistent_source_flag_rate(2, 8)
    assert 35 < legacy < 50 and 20 < q16 < 35 and legacy - q16 > 8
