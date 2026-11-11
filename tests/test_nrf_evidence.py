"""Positive and adversarial checks on the privacy-filtered RF evidence."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'verify_nrf_evidence', ROOT / 'scripts/verify_nrf_evidence.py'
)
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)
EVIDENCE = ROOT / 'docs/evidence/nrf-validation'


class NrfEvidenceTests(unittest.TestCase):
    def packet(self):
        return json.loads((EVIDENCE / 'known-packets.json').read_text())[0]

    def test_all_published_evidence(self):
        result = verifier.verify(EVIDENCE)
        self.assertEqual(result['rf_crc_valid_recordings'], 25)
        self.assertIsNone(result['packet_recall'])

    def headline_inputs(self):
        return (
            json.loads((EVIDENCE / 'recordings.json').read_text()),
            json.loads((EVIDENCE / 'abab-comparison.json').read_text())['results'],
            json.loads((EVIDENCE / 'retention-comparison.json').read_text())['results'],
        )

    def test_headline_recomputation(self):
        h = verifier.recompute_headlines(*self.headline_inputs())
        self.assertAlmostEqual(
            h['abab_on_duty_percent']['historical']['local_rf_duty'], 32.11076093299004
        )
        self.assertAlmostEqual(
            h['abab_on_duty_percent']['optimized']['local_rf_duty'], 62.33194238798177
        )
        self.assertAlmostEqual(
            h['abab_cycle_effects'][0]['optimized_minus_historical_excess_per_second'],
            101.77296594732289,
        )
        self.assertAlmostEqual(
            h['abab_cycle_effects'][1]['optimized_minus_historical_excess_per_second'],
            102.88536633798697,
        )
        self.assertEqual(h['retention_on']['reservoir'], {'full_crc': 3, 'n': 12})
        self.assertEqual(h['retention_on']['strongest'], {'full_crc': 2, 'n': 12})
        self.assertAlmostEqual(h['retention_paired_difference'], 1 / 12)
        self.assertTrue(h['bootstrap_intervals_recomputed'])
        self.assertEqual(h['bootstrap_method']['resamples'], 20000)
        self.assertEqual(
            h['abab_exact_paired_sign_flip']['historical-1'],
            {
                'two_sided_p': 0.125,
                'assignments': 16,
            },
        )
        self.assertAlmostEqual(
            h['abab_cycle_effects'][0]['exact_pair_label_permutation']['two_sided_p'], 2 / 70
        )
        self.assertEqual(h['retention_exact_mcnemar_two_sided_p'], 1.0)
        self.assertEqual(h['retention_exact_paired_sign_flip']['two_sided_p'], 1.0)
        self.assertEqual(h['retention_paired_bootstrap_percentile_95'], [-1 / 6, 1 / 3])

    def test_changed_abab_interval_rejected(self):
        records, abab, retention = self.headline_inputs()
        abab['phases'][0]['states']['on']['candidate_rate']['bootstrap_percentile_95'][0] += 1
        with self.assertRaisesRegex(ValueError, 'interval mismatch'):
            verifier.recompute_headlines(records, abab, retention)

    def test_changed_cycle_interval_rejected(self):
        records, abab, retention = self.headline_inputs()
        abab['cycle_effects'][0]['bootstrap_percentile_95'][0] += 1
        with self.assertRaisesRegex(ValueError, 'cycle excess interval mismatch'):
            verifier.recompute_headlines(records, abab, retention)

    def test_changed_retention_interval_rejected(self):
        records, abab, retention = self.headline_inputs()
        retention['paired_bootstrap_percentile_95'][0] += 0.1
        with self.assertRaisesRegex(ValueError, 'Retention paired bootstrap interval mismatch'):
            verifier.recompute_headlines(records, abab, retention)

    def test_changed_wilson_interval_rejected(self):
        records, abab, retention = self.headline_inputs()
        retention['groups'][0]['full_crc_wilson_95'][0] += 0.1
        with self.assertRaisesRegex(ValueError, 'Retention Wilson interval mismatch'):
            verifier.recompute_headlines(records, abab, retention)

    def test_changed_exact_mcnemar_rejected(self):
        records, abab, retention = self.headline_inputs()
        retention['exact_mcnemar_two_sided_p'] = 0.5
        with self.assertRaisesRegex(ValueError, 'McNemar mismatch'):
            verifier.recompute_headlines(records, abab, retention)

    def test_exact_paired_permutation_known_answers(self):
        self.assertEqual(verifier.exact_sign_flip([1, 2, 3, 4])['two_sided_p'], 0.125)
        self.assertEqual(verifier.exact_sign_flip([1, -1, 2, -2])['two_sided_p'], 1.0)
        self.assertEqual(verifier.exact_sign_flip([0, 0, 0, 0])['two_sided_p'], 1.0)
        self.assertEqual(verifier.exact_sign_flip([1, 0, 0, 0])['two_sided_p'], 1.0)
        with self.assertRaises(ValueError):
            verifier.exact_sign_flip([])

    def test_exact_independent_permutation_known_answers(self):
        result = verifier.exact_independent_permutation([0, 0, 0, 0], [1, 1, 1, 1])
        self.assertEqual(result['assignments'], 70)
        self.assertAlmostEqual(result['two_sided_p'], 2 / 70)
        self.assertEqual(
            verifier.exact_independent_permutation([1] * 4, [1] * 4)['two_sided_p'], 1.0
        )

    def test_reordered_input_records_preserve_seeded_result(self):
        records, abab, retention = self.headline_inputs()
        self.assertEqual(
            verifier.recompute_headlines(records, abab, retention),
            verifier.recompute_headlines(list(reversed(records)), abab, retention),
        )

    def test_changed_detection_count_rejected(self):
        records, abab, retention = self.headline_inputs()
        row = next(r for r in records if r['recording'].startswith('nrf-abab/'))
        row['receiver_summary']['detections'] += 1
        with self.assertRaisesRegex(ValueError, 'candidate_rate'):
            verifier.recompute_headlines(records, abab, retention)

    def test_changed_sample_count_rejected(self):
        records, abab, retention = self.headline_inputs()
        row = next(r for r in records if r['recording'].startswith('nrf-abab/'))
        row['receiver_summary']['total_samples'] += 1000
        with self.assertRaisesRegex(ValueError, 'local_rf_duty'):
            verifier.recompute_headlines(records, abab, retention)

    def test_changed_retention_pair_rejected(self):
        records, abab, retention = self.headline_inputs()
        retention['pairs'][0]['reservoir_crc'] = not retention['pairs'][0]['reservoir_crc']
        with self.assertRaisesRegex(ValueError, 'Retention paired'):
            verifier.recompute_headlines(records, abab, retention)

    def test_corrupt_payload_rejected(self):
        p = self.packet()
        p['observed_payload_hex'] = '00' + p['observed_payload_hex'][2:]
        with self.assertRaisesRegex(ValueError, 'Observed payload'):
            verifier.verify_packet(p)

    def test_corrupt_crc_rejected(self):
        p = self.packet()
        p['crc_received_msb_first'] = '0000'
        with self.assertRaisesRegex(ValueError, 'RF CRC'):
            verifier.verify_packet(p)

    def test_wrong_address_rejected(self):
        p = self.packet()
        p['address_hex'] = '0000000000'
        with self.assertRaisesRegex(ValueError, 'address'):
            verifier.verify_packet(p)

    def test_modified_artifact_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            for p in EVIDENCE.iterdir():
                if p.is_file():
                    (target / p.name).write_bytes(p.read_bytes())
            (target / 'known-packets.json').write_text('[]')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                verifier.verify(target)


if __name__ == '__main__':
    unittest.main()
