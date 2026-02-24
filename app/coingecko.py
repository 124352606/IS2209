"""
CoinGecko public API wrapper for DeployHub.

This module provides two public functions:

- :func:`fetch_prices` — fetch live USD prices and 24 h changes for one or
  more coin identifiers in a single batched API call.
- :func:`ping` — lightweight reachability check used by the ``/health``
  endpoint.

Both functions are designed to be fully unit-testable: they accept an
optional ``session`` parameter so that callers (and tests) can inject a
pre-configured :class:`requests.Session` without monkey-patching global
state.  No side effects occur at import time.

Retry strategy
--------------
Up to three attempts are made for each request.  Back-off delays between
attempts are 1 s, 2 s, and 4 s (exponential).  After all attempts are
exhausted a :exc:`CoinGeckoUnavailableError` is raised.
"""

import logging
import time
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_BASE_URL = "https://api.coingecko.com/api/v3"
_MAX_RETRIES = 3
_BACKOFF_DELAYS = (1, 2, 4)  # seconds between attempts
_REQUEST_TIMEOUT = 10  # seconds


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class CoinGeckoUnavailableError(Exception):
    """
    Raised when the CoinGecko API cannot be reached after all retry attempts.

    Attributes
    ----------
    message:
        Human-readable description of the failure.
    attempts:
        Number of attempts made before giving up.
    """

    def __init__(self, message: str, attempts: int = _MAX_RETRIES) -> None:
        """Initialise the exception with a message and attempt count."""
        super().__init__(message)
        self.attempts = attempts


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_prices(
    tickers: List[str],
    base_url: str = _DEFAULT_BASE_URL,
    session: Optional[requests.Session] = None,
    request_id: str = "n/a",
) -> Dict[str, Dict[str, float]]:
    """
    Fetch live USD prices and 24 h changes for the given coin identifiers.

    Parameters
    ----------
    tickers:
        List of CoinGecko coin IDs (e.g. ``["bitcoin", "ethereum"]``).
    base_url:
        CoinGecko API base URL.  Override in tests or to point at a staging
        instance.
    session:
        Optional :class:`requests.Session` to use.  A new session is created
        if not provided.
    request_id:
        Correlation ID attached to log records for this call.

    Returns
    -------
    Dict[str, Dict[str, float]]
        Mapping of ``{ticker: {"usd": price, "usd_24h_change": change}}``.

    Raises
    ------
    CoinGeckoUnavailableError
        If all retry attempts fail.
    ValueError
        If ``tickers`` is empty.
    """
    if not tickers:
        raise ValueError("tickers list must not be empty")

    ids_param = ",".join(tickers)
    url = f"{base_url}/simple/price"
    params = {
        "ids": ids_param,
        "vs_currencies": "usd",
        "include_24hr_change": "true",
    }

    _session = session or requests.Session()
    last_exc: Optional[Exception] = None

    for attempt in range(1, _MAX_RETRIES + 1):
        logger.info(
            "CoinGecko fetch attempt",
            extra={
                "request_id": request_id,
                "attempt": attempt,
                "tickers": ids_param,
            },
        )
        try:
            response = _session.get(url, params=params, timeout=_REQUEST_TIMEOUT)
            response.raise_for_status()
            data: Dict[str, Dict[str, float]] = response.json()
            logger.info(
                "CoinGecko fetch succeeded",
                extra={
                    "request_id": request_id,
                    "attempt": attempt,
                    "tickers_returned": list(data.keys()),
                },
            )
            return data
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            logger.warning(
                "CoinGecko fetch failed",
                extra={
                    "request_id": request_id,
                    "attempt": attempt,
                    "error": str(exc),
                },
            )
            if attempt < _MAX_RETRIES:
                delay = _BACKOFF_DELAYS[attempt - 1]
                logger.info(
                    "Retrying after back-off",
                    extra={
                        "request_id": request_id,
                        "delay_seconds": delay,
                    },
                )
                time.sleep(delay)

    logger.error(
        "CoinGecko unavailable after all retries",
        extra={
            "request_id": request_id,
            "attempts": _MAX_RETRIES,
            "error": str(last_exc),
        },
    )
    raise CoinGeckoUnavailableError(
        f"CoinGecko API unavailable after {_MAX_RETRIES} attempts: {last_exc}",
        attempts=_MAX_RETRIES,
    )


def ping(
    base_url: str = _DEFAULT_BASE_URL,
    session: Optional[requests.Session] = None,
) -> bool:
    """
    Check whether the CoinGecko API is reachable.

    Calls the ``/ping`` endpoint which returns a lightweight JSON response
    when the API is up.  Does not retry on failure.

    Parameters
    ----------
    base_url:
        CoinGecko API base URL.
    session:
        Optional :class:`requests.Session` to use.

    Returns
    -------
    bool
        ``True`` if CoinGecko responds successfully, ``False`` otherwise.
    """
    _session = session or requests.Session()
    url = f"{base_url}/ping"
    try:
        response = _session.get(url, timeout=_REQUEST_TIMEOUT)
        response.raise_for_status()
        logger.debug("CoinGecko ping succeeded", extra={"url": url})
        return True
    except (requests.RequestException, ValueError) as exc:
        logger.warning(
            "CoinGecko ping failed",
            extra={"url": url, "error": str(exc)},
        )
        return False
