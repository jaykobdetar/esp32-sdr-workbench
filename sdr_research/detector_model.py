"""Integer reference for original ESP32 ADC energy and background policies.

Input words are raw dump words, not CAP20 wire bytes. Q inversion does not
change energy. This is an uncalibrated candidate model, not packet decoding.
"""

from collections.abc import Iterable
from dataclasses import dataclass

SCALE = 65536
MAX_ENERGY = 524288


def energy(words: Iterable[int]) -> tuple[int, int]:
    """Match detector_energy.h exactly, including each block's truncation/tail."""
    values = list(words)
    if len(values) > 16380:
        raise ValueError('At most 16380 raw ADC words per capture')
    energies = []
    for start in range(0, len(values) - 63, 64):
        si = sq = squares = 0
        for word in values[start : start + 64]:
            word = int(word)
            i = ((word & 1023) ^ 512) - 512
            q = (((word >> 10) & 1023) ^ 512) - 512
            si += i
            sq += q
            squares += i * i + q * q
        energies.append(((squares << 6) - si * si - sq * sq) >> 12)
    return (sum(energies) // len(energies), max(energies)) if energies else (0, 0)


@dataclass
class Background:
    """Policy 1 reproduces historical latch; policy 2 matches Q16 firmware.

    score uses the pre-update background; background_q16 is the post-update
    estimate. Positive captures adapt 4x slower than negative captures.
    """

    policy: int = 2
    background_q16: int = 1
    count: int = 0
    warm_sum: int = 0

    def __post_init__(self) -> None:
        if self.policy not in (1, 2):
            raise ValueError('Unknown background policy')
        if self.policy == 1:
            self.background_q16 = SCALE

    def step(self, mean: int, peak: int, ratio_milli: int = 4000) -> tuple[bool, int]:
        if not (0 <= mean <= peak <= MAX_ENERGY and 1000 <= ratio_milli <= 1000000):
            raise ValueError('Invalid bounded energy or ratio')
        self.count += 1
        if self.count <= 16:
            self.warm_sum += mean
            self.background_q16 = (
                max(SCALE, (self.warm_sum // self.count) * SCALE)
                if self.policy == 1
                else max(1, self.warm_sum * SCALE // self.count)
            )
            return False, 0
        scaled_peak = peak * 1000 * SCALE
        positive = scaled_peak > self.background_q16 * ratio_milli
        score = min(0xFFFFFFFF, scaled_peak // self.background_q16)
        if self.policy == 1:
            if not positive:
                old = self.background_q16 // SCALE
                self.background_q16 = max(1, (old * 63 + mean + 32) // 64) * SCALE
        else:
            divisor = 256 if positive else 64
            self.background_q16 = max(
                1,
                (self.background_q16 * (divisor - 1) + mean * SCALE + divisor // 2) // divisor,
            )
        return positive, score


def words_from_iq(iq: Iterable[complex], *, bits: int) -> list[int]:
    """Invert protocol.decode_iq for lossless CAP20 cf32, including Q inversion.

    Do not rescale CAP16/8-bit or rounded, clipped, filtered, nonfinite inputs.
    This cannot recover hardware metadata in the upper 12 bits (unused by DSP).
    """
    if bits != 10:
        raise ValueError('Only original 10-bit CAP20 samples can reproduce firmware energy')
    words = []
    for value in iq:
        i, q = float(value.real) * 512, -float(value.imag) * 512
        if not (-512 <= i <= 511 and -512 <= q <= 511 and i.is_integer() and q.is_integer()):
            raise ValueError(
                'IQ is nonfinite, lossy, processed, or outside signed 10-bit ADC range'
            )
        words.append((int(i) & 1023) | ((int(q) & 1023) << 10))
    if not 1 <= len(words) <= 16380:
        raise ValueError('Expected one nonempty bounded capture, not concatenated bursts')
    return words


def replay_sigmf(
    paths: Iterable[str], *, policy: int = 2, ratio_milli: int = 4000, allow_selected: bool = False
) -> dict:
    """Replay supplied file order as a hypothetical contiguous decision sequence.

    Files are not silently sorted, missing intervening captures are unknown, and
    this does not reconstruct a run from its selectively retained strongest IQ.
    Reject mixed frequency/rate/gain configurations rather than mixing baselines.
    """
    from .recording import load_capture

    model = Background(policy)
    rows = []
    configuration = None
    selected_count = 0
    for path in paths:
        capture = load_capture(path)
        if not capture.crc_ok:
            raise ValueError(f'Capture transport CRC not validated: {path}')
        selected = 'detector_summary' in capture.metadata
        if selected and not allow_selected:
            raise ValueError('Selected detector captures are biased; opt in with allow_selected')
        selected_count += int(selected)
        settings = capture.metadata.get('settings', capture.metadata.get('receiver_settings', {}))
        key = (capture.sample_rate_hz, capture.frequency_hz, settings.get('gain'))
        if configuration is not None and key != configuration:
            raise ValueError('Mixed rate, frequency or gain; replay each configuration separately')
        configuration = key
        mean, peak = energy(words_from_iq(capture.iq, bits=capture.bits))
        event, score = model.step(mean, peak, ratio_milli)
        rows.append(
            {
                'file': str(path),
                'mean_adc2': mean,
                'peak_adc2': peak,
                'positive': event,
                'score_milli': score,
                'background_q16': model.background_q16,
                'selected_capture': selected,
                'host_timestamp': capture.timestamp,
            }
        )
    if not rows:
        raise ValueError('At least one capture is required')
    return {
        'background_policy': policy,
        'ratio_milli': ratio_milli,
        'records': rows,
        'selected_capture_count': selected_count,
        'caveats': [
            'Supplied file order is a hypothetical sequence; no missing captures are reconstructed.',
            'First 16 supplied captures are model warmup, not necessarily original run warmup.',
            'Selected retained buffers are biased and cannot establish detector recall or false-positive rate.',
            'Gain settings may be absent; hardware AGC energies are not comparable across gain steps.',
            'Energy arithmetic is exact for original CAP20 samples, not a reconstruction of RF coverage.',
        ],
    }


def main() -> None:
    """Read-only offline CLI: python -m sdr_research.detector_model FILE..."""
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('captures', nargs='+', help='SigMF metadata files in explicit replay order')
    parser.add_argument('--policy', type=int, choices=(1, 2), default=2)
    parser.add_argument('--ratio-milli', type=int, default=4000)
    parser.add_argument('--allow-selected', action='store_true')
    args = parser.parse_args()
    print(
        json.dumps(
            replay_sigmf(
                args.captures,
                policy=args.policy,
                ratio_milli=args.ratio_milli,
                allow_selected=args.allow_selected,
            ),
            indent=2,
        )
    )


if __name__ == '__main__':
    main()
