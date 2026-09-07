"""Shared HTTP plumbing for the source clients: a retrying GET/POST and a
token-bucket rate limiter (BscScan is capped at 5 req/s → we run at 4)."""

from __future__ import annotations

import threading
import time
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

DEFAULT_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500 or exc.response.status_code == 429
    return False


class TokenBucket:
    """Simple thread-safe token bucket. `rate` tokens/sec, burst `capacity`."""

    def __init__(self, rate: float, capacity: float | None = None) -> None:
        self.rate = rate
        self.capacity = capacity if capacity is not None else rate
        self._tokens = self.capacity
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def take(self, n: float = 1.0) -> None:
        with self._lock:
            now = time.monotonic()
            self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate)
            self._last = now
            if self._tokens < n:
                deficit = n - self._tokens
                time.sleep(deficit / self.rate)
                self._tokens = 0.0
                self._last = time.monotonic()
            else:
                self._tokens -= n


@retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=0.5, max=8),
    reraise=True,
)
def request_json(
    method: str,
    url: str,
    *,
    client: httpx.Client | None = None,
    **kwargs: Any,
) -> Any:
    """GET/POST returning parsed JSON, with exponential backoff on 5xx / network
    errors. 4xx is raised immediately (not retried)."""
    owns = client is None
    client = client or httpx.Client(timeout=DEFAULT_TIMEOUT)
    try:
        resp = client.request(method, url, **kwargs)
        resp.raise_for_status()  # 5xx -> HTTPStatusError -> retried; 4xx -> raised now
        return resp.json()
    finally:
        if owns:
            client.close()


def get_json(url: str, **kwargs: Any) -> Any:
    return request_json("GET", url, **kwargs)


def post_json(url: str, **kwargs: Any) -> Any:
    return request_json("POST", url, **kwargs)
