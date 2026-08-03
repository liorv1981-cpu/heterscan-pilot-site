from heterscan.runner import _claim_limit


def test_sequential_adapters_claim_one_unit_for_responsive_cancellation() -> None:
    assert _claim_limit("complot") == 1
    assert _claim_limit("tel_aviv") == 1


def test_jerusalem_keeps_its_parallel_batch() -> None:
    assert _claim_limit("jerusalem") == 20
