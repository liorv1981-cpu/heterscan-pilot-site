from __future__ import annotations

import random
import re
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from collections.abc import Callable
from urllib.parse import urlparse, parse_qs

import httpx

from .domain import AdapterRateLimited, AdapterReviewRequired


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> tuple[float | None, str]:
    if value is None:
        return None, "missing"
    value = value.strip()
    if re.fullmatch(r"[0-9]+", value):
        return float(value), "seconds"
    try:
        deadline = parsedate_to_datetime(value)
        if deadline.tzinfo is None:
            return None, "invalid"
        return max(0.0, (deadline - (now or datetime.now(timezone.utc))).total_seconds()), "http_date"
    except (TypeError, ValueError, OverflowError):
        return None, "invalid"


def endpoint_category(url: str) -> str:
    parsed = urlparse(url)
    if "GetBakashot" in parsed.path:
        return "autocomplete"
    name = parse_qs(parsed.query).get("prgname", [""])[0]
    return {"GetBakashotByNumber": "number_search", "GetBakashotByAddress": "address_search",
            "GetBakashaFile": "detail"}.get(name, "other")


def _challenge_diagnostics(markup: str) -> dict:
    """Log structural flags only, not response bodies, cookies or form values."""
    sample = markup[:50000]
    title = re.search(r"<title[^>]*>(.*?)</title>", sample, re.I | re.S)
    rendered = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", sample, flags=re.I | re.S)
    rendered = unescape(re.sub(r"<[^>]+>", " ", rendered))
    return {
        "title": re.sub(r"\s+", " ", unescape(title.group(1))).strip()[:120] if title else None,
        "request_detail_markup": "info-main" in sample and "result-title-div-id" in sample,
        "captcha_in_rendered_text": "captcha" in rendered.lower(),
        "script_markers": [marker for marker in ("recaptcha", "hcaptcha", "cf-chl-") if marker in sample.lower()],
    }


class AdaptiveRateLimiter:
    """Thread-safe shared request scheduler with conservative adaptive backoff."""

    def __init__(
        self,
        *,
        requests_per_second: float,
        target_requests_per_second: float | None = None,
        minimum_requests_per_second: float = 0.5,
        maximum_requests_per_second: float | None = None,
        success_window: int = 200,
        max_in_flight: int = 1,
        origin: str | None = None,
        coordinator=None,
    ) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        if minimum_requests_per_second <= 0 or (maximum_requests_per_second is not None
                                              and maximum_requests_per_second < minimum_requests_per_second):
            raise ValueError("rate limits must be positive and ordered")
        if target_requests_per_second is not None and target_requests_per_second <= 0:
            raise ValueError("target_requests_per_second must be positive")
        if success_window < 1 or max_in_flight < 1:
            raise ValueError("success_window and max_in_flight must be positive")
        self._minimum_rate = minimum_requests_per_second
        self._maximum_rate = maximum_requests_per_second or requests_per_second
        self._target_rate = min(target_requests_per_second or requests_per_second, self._maximum_rate)
        self._current_rate = min(requests_per_second, self._maximum_rate)
        self._next_request_at = 0.0
        self._blocked_until = 0.0
        self._success_streak = 0
        self._penalties = 0
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(max_in_flight)
        self._max_in_flight = max_in_flight
        self._success_window = success_window
        self.origin = origin
        self.coordinator = coordinator
        self._thread_slot = threading.local()

    def wait(self) -> None:
        self._slots.acquire()
        try:
            self._wait_for_turn()
            if self.coordinator and self.origin:
                while True:
                    slot = self.coordinator.acquire_source_slot(self.origin, 1 / self._current_rate)
                    if slot["acquired"]:
                        self._thread_slot.token = slot["token"]
                        return
                    if slot["blocked"]:
                        raise AdapterRateLimited("המקור נמצא בחלון צינון לאחר הגבלת קצב (429).",
                                                 retry_after_seconds=slot["retry_after_seconds"], origin=self.origin)
                    time.sleep(min(1.0, max(0.01, slot["retry_after_seconds"])))
        except BaseException:
            self._slots.release()
            raise

    def _wait_for_turn(self) -> None:
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

    def release(self) -> None:
        try:
            if self.coordinator and self.origin:
                self.coordinator.release_source_slot(self.origin, self._thread_slot.token)
        finally:
            self._slots.release()

    def penalize(self, *, retry_after_seconds: float | None = None) -> None:
        with self._lock:
            self._current_rate = max(self._minimum_rate, self._current_rate * 0.6)
            self._success_streak = 0
            self._penalties += 1
            if retry_after_seconds:
                self._blocked_until = max(self._blocked_until, time.monotonic() + retry_after_seconds)
        if self.coordinator and self.origin and retry_after_seconds is not None:
            self.coordinator.penalize_source(self.origin, retry_after_seconds)

    def reward(self) -> None:
        with self._lock:
            self._success_streak += 1
            if self._success_streak >= self._success_window and self._current_rate < self._target_rate:
                self._current_rate = min(self._target_rate, self._current_rate * 1.15)
                self._success_streak = 0

    def snapshot(self) -> dict[str, float | int]:
        with self._lock:
            return {
                "requests_per_second": round(self._current_rate, 3),
                "penalties": self._penalties,
                "in_flight_limit": self._max_in_flight,
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
        self._statistics: dict[str, dict[str, int]] = {}
        self._stats_lock = threading.Lock()
        self._positive_search_cache: dict[str, httpx.Response] = {}
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

    def statistics(self) -> dict[str, dict[str, int]]:
        with self._stats_lock:
            return {key: dict(value) for key, value in self._statistics.items()}

    def request(self, method: str, url: str, *, attempts: int = 4, **kwargs) -> httpx.Response:
        cacheable = method.upper() == "GET" and endpoint_category(url) == "number_search"
        if cacheable:
            with self._stats_lock:
                cached = self._positive_search_cache.get(url)
            if cached is not None:
                return cached
        last_error: Exception | None = None
        for attempt in range(attempts):
            slot_acquired = False
            if self.rate_limiter:
                self.rate_limiter.wait()
                slot_acquired = True
            elif self.delay_seconds:
                with self._delay_lock:
                    wait = self.delay_seconds - (time.monotonic() - self._last_request_at)
                    if wait > 0:
                        time.sleep(wait)
                    self._last_request_at = time.monotonic()
            try:
                response = self.client.request(method, url, **kwargs)
                self._last_request_at = time.monotonic()
                category = endpoint_category(url)
                with self._stats_lock:
                    counts = self._statistics.setdefault(category, {"requests": 0, "rate_limited": 0})
                    counts["requests"] += 1
                    if response.status_code == 429:
                        counts["rate_limited"] += 1
                if response.status_code == 429:
                    try:
                        response_date = parsedate_to_datetime(response.headers["Date"])
                        if response_date.tzinfo is None:
                            response_date = None
                    except (KeyError, TypeError, ValueError, OverflowError):
                        response_date = None
                    retry_after_seconds, retry_kind = parse_retry_after(
                        response.headers.get("Retry-After"), now=response_date
                    )
                    if self.rate_limiter:
                        previous_penalties = int(self.rate_limiter.snapshot()["penalties"])
                        fallback = min(900.0, 60.0 * (2 ** min(4, previous_penalties)))
                    else:
                        fallback = min(120.0, 30.0 * (attempt + 1))
                    cooldown_seconds = (retry_after_seconds if retry_after_seconds is not None
                                        else fallback + random.uniform(0, min(5.0, fallback * 0.1)))
                    if self.rate_limiter:
                        self.rate_limiter.penalize(retry_after_seconds=cooldown_seconds)
                        raise AdapterRateLimited(
                            "המקור הגביל את קצב הפניות (429).",
                            retry_after_seconds=cooldown_seconds,
                            origin=urlparse(url).netloc,
                            endpoint=category,
                            retry_after_kind=retry_kind,
                        )
                    last_error = AdapterRateLimited(
                        "המקור הגביל את קצב הפניות (429).",
                        retry_after_seconds=cooldown_seconds,
                        origin=urlparse(url).netloc,
                        endpoint=category,
                        retry_after_kind=retry_kind,
                    )
                    if attempt + 1 < attempts:
                        time.sleep(cooldown_seconds)
                        continue
                    raise last_error
                captcha = "captcha" in response.text[:5000].lower()
                if response.status_code == 403 or captcha:
                    raise AdapterReviewRequired(
                        f"המקור החזיר חסימה או CAPTCHA ({response.status_code}).",
                        diagnostics=_challenge_diagnostics(response.text),
                    )
                response.raise_for_status()
                if self.rate_limiter:
                    self.rate_limiter.reward()
                requested_number = parse_qs(urlparse(url).query).get("b", [""])[0] if cacheable else ""
                if cacheable and requested_number and "captcha" not in response.text.lower() and re.search(
                    rf"getRequest\(\s*{re.escape(requested_number)}\s*\)", response.text
                ):
                    with self._stats_lock:
                        if len(self._positive_search_cache) >= 1000:
                            self._positive_search_cache.pop(next(iter(self._positive_search_cache)))
                        self._positive_search_cache[url] = response
                return response
            except AdapterReviewRequired:
                raise
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as error:
                last_error = error
                if isinstance(error, httpx.HTTPStatusError) and error.response.status_code < 500:
                    break
                if slot_acquired:
                    slot_acquired = False
                    self.rate_limiter.release()
                time.sleep(min(8.0, (2**attempt) + random.random()))
            finally:
                if slot_acquired:
                    self.rate_limiter.release()
        raise RuntimeError(f"Public request failed: {last_error}")


def with_client(fn: Callable[[PublicHttpClient], object]) -> object:
    client = PublicHttpClient()
    try:
        return fn(client)
    finally:
        client.close()
