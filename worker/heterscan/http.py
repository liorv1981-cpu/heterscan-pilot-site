from __future__ import annotations

import random
import time
from collections.abc import Callable

import httpx

from .domain import AdapterReviewRequired


class PublicHttpClient:
    def __init__(self, *, delay_seconds: float = 0.15, timeout_seconds: float = 45) -> None:
        self.delay_seconds = delay_seconds
        self._last_request_at = 0.0
        self.client = httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "HETERSCAN-Pilot/0.1 (+manual authorized run)"},
        )

    def close(self) -> None:
        self.client.close()

    def request(self, method: str, url: str, *, attempts: int = 4, **kwargs) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(attempts):
            wait = self.delay_seconds - (time.monotonic() - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
            try:
                response = self.client.request(method, url, **kwargs)
                self._last_request_at = time.monotonic()
                if response.status_code in (403, 429) or "captcha" in response.text[:5000].lower():
                    raise AdapterReviewRequired(f"המקור החזיר חסימה או CAPTCHA ({response.status_code}).")
                response.raise_for_status()
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
