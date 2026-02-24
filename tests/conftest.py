"""
Shared pytest fixtures for the DeployHub test suite.

All fixtures mock external dependencies (PostgreSQL and CoinGecko) so that
tests can run without a live database or network access.
"""

import pytest

from app import create_app


# ---------------------------------------------------------------------------
# CoinGecko mock data
# ---------------------------------------------------------------------------

MOCK_COINGECKO_RESPONSE = {
    "bitcoin": {
        "usd": 65000.12345678,
        "usd_24h_change": 2.3456,
    },
    "ethereum": {
        "usd": 3200.87654321,
        "usd_24h_change": -1.2345,
    },
}

# ---------------------------------------------------------------------------
# Application fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def app():
    """
    Create a Flask test application with test configuration.

    DATABASE_URL is intentionally set to a dummy value; all DB calls are
    mocked in individual test fixtures, so no real connection is attempted.
    """
    flask_app = create_app(
        test_config={
            "TESTING": True,
            "DATABASE_URL": "postgresql://test:test@localhost:5432/test",
            "COINGECKO_BASE_URL": "https://api.coingecko.com/api/v3",
        }
    )
    return flask_app


@pytest.fixture()
def client(app):
    """Return a Flask test client for the test application."""
    return app.test_client()


# ---------------------------------------------------------------------------
# Database mock fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_db(mocker):
    """
    Patch all public functions in ``app.db`` so that no database connection
    is made during tests.

    Yields a namespace object whose attributes are the individual mocks,
    allowing tests to configure return values and assert calls.
    """
    patches = {
        "ping": mocker.patch("app.db.ping", return_value=True),
        "init_db": mocker.patch("app.db.init_db", return_value=None),
        "get_watchlist": mocker.patch("app.db.get_watchlist", return_value=[]),
        "add_ticker": mocker.patch("app.db.add_ticker"),
        "delete_ticker": mocker.patch("app.db.delete_ticker", return_value=True),
        "ticker_exists": mocker.patch("app.db.ticker_exists", return_value=False),
        "save_snapshot": mocker.patch("app.db.save_snapshot"),
        "get_ticker_history": mocker.patch("app.db.get_ticker_history", return_value=[]),
        "get_latest_snapshots": mocker.patch("app.db.get_latest_snapshots", return_value=[]),
        "get_latest_snapshot_for_ticker": mocker.patch(
            "app.db.get_latest_snapshot_for_ticker", return_value=None
        ),
        "get_last_successful_fetch": mocker.patch(
            "app.db.get_last_successful_fetch", return_value=None
        ),
    }

    class MockDB:
        """Namespace holding all DB mock objects."""

    ns = MockDB()
    for name, mock in patches.items():
        setattr(ns, name, mock)
    yield ns


# ---------------------------------------------------------------------------
# CoinGecko mock fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_coingecko(mocker):
    """
    Patch ``app.coingecko.fetch_prices`` and ``app.coingecko.ping`` so that
    tests never make real HTTP requests.

    Returns a namespace with ``fetch_prices`` and ``ping`` mocks pre-configured
    to return the standard mock response / True.
    """
    fetch_mock = mocker.patch(
        "app.coingecko.fetch_prices",
        return_value=MOCK_COINGECKO_RESPONSE,
    )
    ping_mock = mocker.patch("app.coingecko.ping", return_value=True)

    # Also patch the references in routes (imported via ``import app.coingecko as …``)
    routes_fetch_mock = mocker.patch(
        "app.routes.coingecko_client.fetch_prices",
        return_value=MOCK_COINGECKO_RESPONSE,
    )
    routes_ping_mock = mocker.patch(
        "app.routes.coingecko_client.ping",
        return_value=True,
    )

    class MockCoinGecko:
        """Namespace holding CoinGecko mock objects."""
        fetch_prices = routes_fetch_mock
        ping = routes_ping_mock
        module_fetch = fetch_mock
        module_ping = ping_mock

    yield MockCoinGecko()
