from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable

import httpx

from .domain import AdapterRateLimited, AdapterReviewRequired


class AdaptiveRateLimiter:
    """Thread-safe shared request scheduler with conservative adaptive backoff."""

    def __init__(
        self,
        *,
        requests_per_second: float,
        target_requests_per_second: float | None = None,
        minimum_requests_per_second: float = 0.5,
        maximum_requests_per_second: float | None = None,
    ) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        self._minimum_rate = minimum_requests_per_second
        self._maximum_rate = maximum_requests_per_second or requests_per_second
        self._target_rate = min(target_requests_per_second or requests_per_second, self._maximum_rate)
        self._current_rate = min(requests_per_second, self._maximum_rate)
        self._next_request_at = 0.0
        self._blocked_until = 0.0
        self._success_streak = 0
        self._penalties = 0
        self._lock = threading.Lock()

    def wait(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                if now < self._blocked_until:
                    raise AdapterRateLimited(
                        "המקור נמצא בחלון צינון לאחר הגבלת קצב (429).",
                        retry_after_seconds=self._blocked_until - now,
                    )
                else:
                    scheduled_at = max(now, self._next_request_at)
                    self._next_request_at = scheduled_at + (1.0 / self._current_rate)
                    wait_seconds = scheduled_at - now
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            with self._lock:
                remaining = self._blocked_until - time.monotonic()
                if remaining > 0:
                    raise AdapterRateLimited(
                        "המקור נמצא בחלון צינון לאחר הגבלת קצב (429).",
                        retry_after_seconds=remaining,
                    )
            return

    def penalize(self, *, retry_after_seconds: float | None = None) -> None:
        with self._lock:
            self._current_rate = max(self._minimum_rate, self._current_rate * 0.6)
            self._success_streak = 0
            self._penalties += 1
            if retry_after_seconds:
                self._blocked_until = max(self._blocked_until, time.monotonic() + retry_after_seconds)

    def reward(self) -> None:
        with self._lock:
            self._success_streak += 1
            if self._success_streak >= 40 and self._current_rate < self._target_rate:
                self._current_rate = min(self._target_rate, self._current_rate * 1.15)
                self._success_streak = 0

    def snapshot(self) -> dict[str, float | int]:
        with self._lock:
            return {
                "requests_per_second": round(self._current_rate, 3),
                "penalties": self._penalties,
            }


class PublicHttpClient:
    def __init__(
        self,
        *,
        delay_seconds: float = 0.15,
        timeout_seconds: float = 45,
        rate_limiter: AdaptiveRateLimiter | None = None,
        max_connections: int = 10,
    ) -> None:
        self.delay_seconds = delay_seconds
        self._last_request_at = 0.0
        self._delay_lock = threading.Lock()
        self.rate_limiter = rate_limiter
        self.client = httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=max_connections,
                max_keepalive_connections=max_connections,
                keepalive_expiry=60,
            ),
            headers={"User-Agent": "HETERSCAN-Pilot/0.1 (+manual authorized run)"},
        )

    def close(self) -> None:
        self.client.close()

    def request(self, method: str, url: str, *, attempts: int = 4, **kwargs) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(attempts):
            if self.rate_limiter:
                self.rate_limiter.wait()
            elif self.delay_seconds:
                with self._delay_lock:
                    wait = self.delay_seconds - (time.monotonic() - self._last_request_at)
                    if wait > 0:
                        time.sleep(wait)
                    self._last_request_at = time.monotonic()
            try:
                response = self.client.request(method, url, **kwargs)
                self._last_request_at = time.monotonic()
                captcha = "captcha" in response.text[:5000].lower()
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    retry_after_seconds = (
                        float(retry_after) if retry_after and retry_after.isdigit() else None
                    )
                    if self.rate_limiter:
                        previous_penalties = int(self.rate_limiter.snapshot()["penalties"])
                        cooldown_seconds = retry_after_seconds or min(
                            900.0, 60.0 * (2 ** min(4, previous_penalties))
                        )
                    else:
                        cooldown_seconds = retry_after_seconds or min(120.0, 30.0 * (attempt + 1))
                    if self.rate_limiter:
                        self.rate_limiter.penalize(retry_after_seconds=cooldown_seconds)
                        raise AdapterRateLimited(
                            "המקור הגביל את קצב הפניות (429).",
                            retry_after_seconds=cooldown_seconds,
                        )
                    last_error = AdapterRateLimited(
                        "המקור הגביל את קצב הפניות (429).",
                        retry_after_seconds=cooldown_seconds,
                    )
                    if attempt + 1 < attempts:
                        time.sleep(cooldown_seconds + random.random())
                        continue
                    raise last_error
                if response.status_code == 403 or captcha:
                    if self.rate_limiter:
                        self.rate_limiter.penalize(retry_after_seconds=10)
                    raise AdapterReviewRequired(f"המקור החזיר חסימה או CAPTCHA ({response.status_code}).")
                response.raise_for_status()
                if self.rate_limiter:
                    self.rate_limiter.reward()
                return response
            except AdapterReviewRequired:
                raise
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as error:
                last_error = error
                if isinstance(error, httpx.HTTPStatusError) and error.response.status_code < 500:
                    break
                time.sleep(min(8.0, (2**attempt) + random.random()))
        raise RuntimeError(f"Public request failed: {last_error}")


def with_client(fn: Callable[[PublicHttpClient], object]) -> object:
    client = PublicHttpClient()
    try:
        return fn(client)
    finally:
        client.close()
