"""Keep the published v7 measurement arithmetic reproducible without hardware."""

from scripts.verify_v7_evidence import verify


def test_v7_evidence():
    result = verify()
    assert result['captures'] == 1288396
    assert result['exact_p_values_recomputed'] is True
