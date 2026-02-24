"""
Unit tests for the database layer (app/db.py).

All tests mock ``app.db._pool`` directly so that no real database connection
is needed.  Each test verifies that the correct parameterised SQL is executed
and that the correct dict values are returned.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

import app.db as db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pool_mock(fetchall_return=None, fetchone_return=None):
    """
    Build a mock ``ThreadedConnectionPool`` whose ``getconn()`` returns a
    connection mock whose cursor returns the supplied row data.

    The returned pool, connection, and cursor mocks all support the
    context-manager protocol used by ``get_conn()`` and
    ``with conn.cursor() as cur:``.
    """
    cur = MagicMock()
    cur.__enter__ = lambda s: s
    cur.__exit__ = MagicMock(return_value=False)
    if fetchall_return is not None:
        cur.fetchall.return_value = fetchall_return
    if fetchone_return is not None:
        cur.fetchone.return_value = fetchone_return

    conn = MagicMock()
    conn.cursor.return_value = cur
    conn.commit = MagicMock()
    conn.rollback = MagicMock()

    pool = MagicMock()
    pool.getconn.return_value = conn
    pool.putconn = MagicMock()

    return pool, conn, cur


# ---------------------------------------------------------------------------
# get_watchlist
# ---------------------------------------------------------------------------

def test_get_watchlist_returns_all_tickers():
    """
    get_watchlist() executes a SELECT and returns a list of dicts matching
    the rows returned by the cursor.
    """
    now = datetime.now(timezone.utc)
    rows = [
        {"id": 1, "ticker": "bitcoin", "added_at": now},
        {"id": 2, "ticker": "ethereum", "added_at": now},
    ]
    pool, _conn, cur = _make_pool_mock(fetchall_return=rows)

    with patch("app.db._pool", pool):
        result = db.get_watchlist()

    assert len(result) == 2
    assert result[0]["ticker"] == "bitcoin"
    assert result[1]["ticker"] == "ethereum"
    assert isinstance(result[0], dict)


# ---------------------------------------------------------------------------
# add_ticker
# ---------------------------------------------------------------------------

def test_add_ticker_inserts_row():
    """
    add_ticker() executes an INSERT and returns the newly created row dict
    with the database-assigned id and added_at.
    """
    now = datetime.now(timezone.utc)
    row = {"id": 42, "ticker": "solana", "added_at": now}
    pool, _conn, cur = _make_pool_mock(fetchone_return=row)

    with patch("app.db._pool", pool):
        result = db.add_ticker("solana")

    assert result["id"] == 42
    assert result["ticker"] == "solana"
    assert result["added_at"] == now
    # Verify a parameterised INSERT was executed (not string interpolation).
    execute_args = cur.execute.call_args[0]
    assert "INSERT" in execute_args[0]
    assert execute_args[1] == ("solana",)


# ---------------------------------------------------------------------------
# save_snapshot
# ---------------------------------------------------------------------------

def test_save_snapshot_inserts_row():
    """
    save_snapshot() executes an INSERT and returns the newly created
    snapshot dict with the server-assigned fetched_at timestamp.
    """
    now = datetime.now(timezone.utc)
    row = {
        "id": 7,
        "ticker": "bitcoin",
        "price_usd": 65000.12345678,
        "change_24h": 2.3456,
        "fetched_at": now,
    }
    pool, _conn, cur = _make_pool_mock(fetchone_return=row)

    with patch("app.db._pool", pool):
        result = db.save_snapshot("bitcoin", 65000.12345678, 2.3456)

    assert result["id"] == 7
    assert result["ticker"] == "bitcoin"
    assert result["price_usd"] == pytest.approx(65000.12345678)
    assert result["change_24h"] == pytest.approx(2.3456)
    assert result["fetched_at"] == now
    # Ensure parameterised query.
    execute_args = cur.execute.call_args[0]
    assert "INSERT" in execute_args[0]
    assert execute_args[1] == ("bitcoin", 65000.12345678, 2.3456)


# ---------------------------------------------------------------------------
# get_latest_snapshots
# ---------------------------------------------------------------------------

def test_get_latest_snapshots_returns_most_recent():
    """
    get_latest_snapshots() returns the most recent snapshot dict for each
    requested ticker.
    """
    now = datetime.now(timezone.utc)
    rows = [
        {"id": 1, "ticker": "bitcoin", "price_usd": 65000.0, "change_24h": 2.5, "fetched_at": now},
        {"id": 2, "ticker": "ethereum", "price_usd": 3200.0, "change_24h": -1.2, "fetched_at": now},
    ]
    pool, _conn, cur = _make_pool_mock(fetchall_return=rows)

    with patch("app.db._pool", pool):
        result = db.get_latest_snapshots(["bitcoin", "ethereum"])

    assert len(result) == 2
    tickers = {s["ticker"] for s in result}
    assert tickers == {"bitcoin", "ethereum"}
    assert isinstance(result[0], dict)
    # Verify parameterised query (list passed as parameter, not interpolated).
    execute_args = cur.execute.call_args[0]
    assert "SELECT" in execute_args[0]
    assert ["bitcoin", "ethereum"] in execute_args[1] or ("bitcoin", "ethereum") in str(execute_args[1])


def test_get_latest_snapshots_returns_empty_list_for_no_tickers():
    """
    get_latest_snapshots() short-circuits and returns [] when given an
    empty tickers list without hitting the database.
    """
    pool, _conn, cur = _make_pool_mock(fetchall_return=[])

    with patch("app.db._pool", pool):
        result = db.get_latest_snapshots([])

    assert result == []
    cur.execute.assert_not_called()


# ---------------------------------------------------------------------------
# get_ticker_history
# ---------------------------------------------------------------------------

def test_get_ticker_history_returns_paginated_rows():
    """
    get_ticker_history() executes a SELECT with LIMIT and OFFSET parameters
    and returns a list of snapshot dicts ordered newest-first.
    """
    now = datetime.now(timezone.utc)
    rows = [
        {"id": 3, "ticker": "bitcoin", "price_usd": 66000.0, "change_24h": 1.1, "fetched_at": now},
        {"id": 2, "ticker": "bitcoin", "price_usd": 65000.0, "change_24h": 0.5, "fetched_at": now},
    ]
    pool, _conn, cur = _make_pool_mock(fetchall_return=rows)

    with patch("app.db._pool", pool):
        result = db.get_ticker_history("bitcoin", limit=50, offset=10)

    assert len(result) == 2
    assert result[0]["ticker"] == "bitcoin"
    assert isinstance(result[0], dict)
    # Verify limit and offset were passed as parameters.
    execute_args = cur.execute.call_args[0]
    assert "SELECT" in execute_args[0]
    assert execute_args[1] == ("bitcoin", 50, 10)


# ---------------------------------------------------------------------------
# delete_ticker
# ---------------------------------------------------------------------------

def test_delete_ticker_returns_true_when_row_deleted():
    """delete_ticker() returns True when the DELETE removes a row."""
    pool, _conn, cur = _make_pool_mock(fetchone_return=(1,))

    with patch("app.db._pool", pool):
        result = db.delete_ticker("bitcoin")

    assert result is True
    execute_args = cur.execute.call_args[0]
    assert "DELETE" in execute_args[0]
    assert execute_args[1] == ("bitcoin",)


def test_delete_ticker_returns_false_when_not_found():
    """delete_ticker() returns False when no row matched the ticker."""
    pool, _conn, cur = _make_pool_mock(fetchone_return=None)

    with patch("app.db._pool", pool):
        result = db.delete_ticker("nonexistent")

    assert result is False
