import httpx
import pytest

from heterscan.domain import AdapterRateLimited
from heterscan.http import AdaptiveRateLimiter, PublicHttpClient


def test_rate_limiter_reduces_rate_after_source_penalty() -> None:
    limiter = AdaptiveRateLimiter(
        requests_per_second=2.0,
        minimum_requests_per_second=0.5,
        maximum_requests_per_second=3.0,
    )

    limiter.penalize()

    assert limiter.snapshot() == {"requests_per_second": 1.2, "penalties": 1}


def test_rate_limiter_fails_fast_during_shared_cooldown() -> None:
    limiter = AdaptiveRateLimiter(requests_per_second=2.0)
    limiter.penalize(retry_after_seconds=10)

    with pytest.raises(AdapterRateLimited) as raised:
        limiter.wait()

    assert 0 < raised.value.retry_after_seconds <= 10


def test_shared_client_does_not_retry_429_during_cooldown() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, request=request)

    limiter = AdaptiveRateLimiter(requests_per_second=2.0)
    client = PublicHttpClient(rate_limiter=limiter)
    client.client.close()
    client.client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(AdapterRateLimited) as raised:
        client.request("GET", "https://example.test/source")

    client.close()
    assert calls == 1
    assert raised.value.retry_after_seconds == 60
