from heterscan.http import AdaptiveRateLimiter


def test_rate_limiter_reduces_rate_after_source_penalty() -> None:
    limiter = AdaptiveRateLimiter(
        requests_per_second=2.0,
        minimum_requests_per_second=0.5,
        maximum_requests_per_second=3.0,
    )

    limiter.penalize()

    assert limiter.snapshot() == {"requests_per_second": 1.2, "penalties": 1}
