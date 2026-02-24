"""
Unit tests for the CoinGecko API wrapper (app/coingecko.py).

All HTTP calls are intercepted via a mock ``requests.Session`` so no real
network requests are made.
"""

from unittest.mock import MagicMock, patch

import pytest
import requests

from app.coingecko import CoinGeckoUnavailableError, fetch_prices, ping


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session(status_code: int = 200, json_data: dict = None, raise_exc=None):
    """
    Build a mock ``requests.Session`` whose ``get`` method returns a
    pre-configured response or raises an exception.
    """
    session = MagicMock(spec=requests.Session)
    if raise_exc is not None:
        session.get.side_effect = raise_exc
        return session

    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data or {}
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(
            response=response
        )
    else:
        response.raise_for_status.return_value = None
    session.get.return_value = response
    return session


_MOCK_PRICE_DATA = {
    "bitcoin": {"usd": 65000.0, "usd_24h_change": 2.34},
    "ethereum": {"usd": 3200.0, "usd_24h_change": -1.23},
}


# ---------------------------------------------------------------------------
# fetch_prices
# ---------------------------------------------------------------------------

def test_fetch_prices_returns_data_on_success():
    """
    fetch_prices returns the parsed JSON body when the API responds with 200.
    """
    session = _make_session(json_data=_MOCK_PRICE_DATA)

    result = fetch_prices(["bitcoin", "ethereum"], session=session)

    assert result == _MOCK_PRICE_DATA
    session.get.assert_called_once()
    call_kwargs = session.get.call_args
    # Verify the correct endpoint is hit
    assert "/simple/price" in call_kwargs[0][0]


def test_fetch_prices_retries_on_failure_then_succeeds():
    """
    fetch_prices retries the request after transient failures and returns
    data as soon as one attempt succeeds.
    """
    good_response = MagicMock()
    good_response.status_code = 200
    good_response.json.return_value = _MOCK_PRICE_DATA
    good_response.raise_for_status.return_value = None

    # First call fails, second succeeds
    session = MagicMock(spec=requests.Session)
    session.get.side_effect = [
        requests.ConnectionError("connection refused"),
        good_response,
    ]

    with patch("app.coingecko.time.sleep"):  # prevent real sleep in tests
        result = fetch_prices(["bitcoin"], session=session)

    assert result == _MOCK_PRICE_DATA
    assert session.get.call_count == 2


def test_fetch_prices_raises_after_max_retries():
    """
    fetch_prices raises CoinGeckoUnavailableError when all retry attempts
    are exhausted.
    """
    session = MagicMock(spec=requests.Session)
    session.get.side_effect = requests.ConnectionError("always fails")

    with patch("app.coingecko.time.sleep"):
        with pytest.raises(CoinGeckoUnavailableError) as exc_info:
            fetch_prices(["bitcoin"], session=session)

    assert exc_info.value.attempts == 3
    assert session.get.call_count == 3


# ---------------------------------------------------------------------------
# ping
# ---------------------------------------------------------------------------

def test_ping_returns_true_when_reachable():
    """ping() returns True when the CoinGecko /ping endpoint responds 200."""
    session = _make_session(json_data={"gecko_says": "(V3) To the Moon!"})

    result = ping(session=session)

    assert result is True
    session.get.assert_called_once()
    assert "/ping" in session.get.call_args[0][0]


def test_ping_returns_false_when_unreachable():
    """ping() returns False when the CoinGecko /ping endpoint is unreachable."""
    session = _make_session(raise_exc=requests.ConnectionError("unreachable"))

    result = ping(session=session)

    assert result is False
