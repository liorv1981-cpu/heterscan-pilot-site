import httpx
import pytest
import threading
import time
from datetime import datetime, timezone
from email.utils import format_datetime

from heterscan.domain import AdapterRateLimited, AdapterReviewRequired
from heterscan.http import AdaptiveRateLimiter, PublicHttpClient, parse_retry_after


def test_rate_limiter_reduces_rate_after_source_penalty() -> None:
    limiter = AdaptiveRateLimiter(
        requests_per_second=2.0,
        minimum_requests_per_second=0.5,
        maximum_requests_per_second=3.0,
    )

    limiter.penalize()

    assert limiter.snapshot() == {"requests_per_second": 1.2, "penalties": 1, "in_flight_limit": 1}


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
    assert 60 <= raised.value.retry_after_seconds <= 65
    assert raised.value.retry_after_kind == "missing"


@pytest.mark.parametrize("value,expected,kind", [
    ("120", 120, "seconds"), ("0", 0, "seconds"),
    ("Fri, 02 Oct 2026 12:02:00 GMT", 120, "http_date"),
    ("nonsense", None, "invalid"),
])
def test_retry_after_standard_formats(value, expected, kind) -> None:
    assert parse_retry_after(value, now=datetime(2026, 10, 2, 12, tzinfo=timezone.utc)) == (expected, kind)


def test_server_retry_after_is_used_without_jitter() -> None:
    for header in ("3", format_datetime(datetime(2026, 10, 2, 12, 0, 3, tzinfo=timezone.utc), usegmt=True)):
        limiter = AdaptiveRateLimiter(requests_per_second=100)
        client = PublicHttpClient(rate_limiter=limiter)
        client.client.close()
        client.client = httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(429, headers={"Retry-After": header,
                "Date": "Fri, 02 Oct 2026 12:00:00 GMT"}, request=request)
        ))
        try:
            with pytest.raises(AdapterRateLimited) as raised:
                client.request("GET", "https://example.test/source")
            if header == "3":
                assert raised.value.retry_after_seconds == 3
            else:
                assert raised.value.retry_after_kind == "http_date"
                assert raised.value.retry_after_seconds == 3
        finally:
            client.close()


class _SharedCoordinator:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.busy = False
        self.blocked_until = 0.0
        self.token = 0

    def acquire_source_slot(self, _origin, _interval):
        with self.lock:
            remaining = self.blocked_until - time.monotonic()
            if remaining > 0:
                return {"acquired": False, "blocked": True, "retry_after_seconds": remaining}
            if self.busy:
                return {"acquired": False, "blocked": False, "retry_after_seconds": 0.01}
            self.busy = True
            self.token += 1
            return {"acquired": True, "token": str(self.token)}

    def release_source_slot(self, _origin, _token):
        with self.lock:
            self.busy = False

    def penalize_source(self, _origin, seconds):
        with self.lock:
            self.blocked_until = time.monotonic() + seconds


def test_cooldown_is_shared_between_independent_limiters() -> None:
    coordinator = _SharedCoordinator()
    first = AdaptiveRateLimiter(requests_per_second=100, origin="example.test", coordinator=coordinator)
    second = AdaptiveRateLimiter(requests_per_second=100, origin="example.test", coordinator=coordinator)
    first.penalize(retry_after_seconds=2)
    with pytest.raises(AdapterRateLimited) as raised:
        second.wait()
    assert 0 < raised.value.retry_after_seconds <= 2


def test_two_clients_never_request_same_origin_concurrently() -> None:
    coordinator = _SharedCoordinator()
    active = 0
    maximum = 0
    lock = threading.Lock()
    clients = []

    def handler(request):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        return httpx.Response(200, request=request)

    for _ in range(2):
        limiter = AdaptiveRateLimiter(requests_per_second=100, origin="example.test", coordinator=coordinator)
        client = PublicHttpClient(rate_limiter=limiter)
        client.client.close()
        client.client = httpx.Client(transport=httpx.MockTransport(handler))
        clients.append(client)
    threads = [threading.Thread(target=client.request, args=("GET", "https://example.test/other"))
               for client in clients]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)
        assert not thread.is_alive()
    for client in clients:
        client.close()
    assert maximum == 1


def test_only_positive_search_results_are_cached_within_client() -> None:
    calls = 0
    responses = [
        (429, "blocked"),
        (403, "captcha"),
        (200, '<a href="javascript:getRequest(20260005)">20260005</a>'),
    ]

    def handler(request):
        nonlocal calls
        status, body = responses[min(calls, len(responses) - 1)]
        calls += 1
        return httpx.Response(status, text=body, request=request)

    client = PublicHttpClient(delay_seconds=0)
    client.client.close()
    client.client = httpx.Client(transport=httpx.MockTransport(handler))
    url = "https://handasi.complot.co.il/magicscripts/mgrqispi.dll?prgname=GetBakashotByNumber&b=20260005"
    try:
        with pytest.raises(AdapterRateLimited):
            client.request("GET", url, attempts=1)
        with pytest.raises(AdapterReviewRequired):
            client.request("GET", url, attempts=1)
        assert client.request("GET", url).status_code == 200
        assert client.request("GET", url).status_code == 200
        assert calls == 3
    finally:
        client.close()
