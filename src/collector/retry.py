"""Try again when a chain's server is slow or drops a request.

A single slow answer used to end a chain's whole day (a "read operation timed out" while listing
Shufersal's promotion files made the 2026-11-04 run publish without Shufersal). Network
failures are retried with growing pauses; a clear "no" from the server (404, 403 ...) is not.
"""

import http.client
import time
import urllib.error
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

ATTEMPTS = 5
FIRST_WAIT = 2.0  # seconds; doubles each time: 2, 4, 8, 16


def worth_retrying(error: Exception) -> bool:
    """Timeouts, dropped connections and the server's "try later" (429, 5xx), yes; the
    server saying no (other 4xx), and anything that is not a network failure, no."""
    if isinstance(error, urllib.error.HTTPError):
        return error.code == 429 or error.code >= 500
    return isinstance(error, OSError | http.client.HTTPException)  # incl. TimeoutError, URLError


def with_retries(
    call: Callable[[], T],
    attempts: int = ATTEMPTS,
    first_wait: float = FIRST_WAIT,
    sleep: Callable[[float], None] = time.sleep,
    note: Callable[[str], None] | None = print,
) -> T:
    wait = first_wait
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception as error:
            if attempt == attempts or not worth_retrying(error):
                raise
            if note:
                note(
                    f"  try {attempt} of {attempts} failed ({type(error).__name__}: {error}); "
                    f"again in {wait:.0f}s"
                )
            sleep(wait)
            wait *= 2
    raise AssertionError("unreachable")
