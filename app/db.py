"""
Database access layer for DeployHub.

Uses a ``ThreadedConnectionPool`` initialised once at startup via
``init_db(app)``.  All query functions return plain ``dict`` objects so
callers never depend on ORM or dataclass internals.  All SQL uses
parameterised queries exclusively — no string interpolation is ever used
to build SQL statements.
"""

import logging
import os
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Generator, List, Optional

import psycopg2
import psycopg2.errors
import psycopg2.extras
import psycopg2.pool

logger = logging.getLogger(__name__)

# Module-level pool, set by init_db().
_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None


# ---------------------------------------------------------------------------
# Schema SQL
# ---------------------------------------------------------------------------

_CREATE_WATCHLIST_SQL = """
CREATE TABLE IF NOT EXISTS watchlist (
    id        SERIAL PRIMARY KEY,
    ticker    VARCHAR(50) UNIQUE NOT NULL,
    added_at  TIMESTAMP DEFAULT NOW()
);
"""

_CREATE_SNAPSHOTS_SQL = """
CREATE TABLE IF NOT EXISTS price_snapshots (
    id          SERIAL PRIMARY KEY,
    ticker      VARCHAR(50) NOT NULL,
    price_usd   NUMERIC(20, 8),
    change_24h  NUMERIC(10, 4),
    fetched_at  TIMESTAMP DEFAULT NOW()
);
"""


# ---------------------------------------------------------------------------
# Pool initialisation
# ---------------------------------------------------------------------------

def init_db(app) -> None:
    """
    Initialise the connection pool and create database tables.

    Called from ``create_app()`` after configuration is loaded.  Retries
    the connection up to 10 times with a 2-second delay between attempts,
    logging each attempt as structured JSON.  If all retries fail a
    ``RuntimeError`` is raised so the process exits and Docker can restart
    the container rather than running in a broken state.

    Parameters
    ----------
    app:
        The Flask application instance.  ``DATABASE_URL`` is read from
        ``app.config`` (falling back to the environment).
    """
    global _pool

    url = app.config.get("DATABASE_URL") or os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")

    max_attempts = 10
    delay_seconds = 2

    for attempt in range(1, max_attempts + 1):
        logger.info(
            "db_connect_attempt",
            extra={"attempt": attempt, "max_attempts": max_attempts},
        )
        try:
            candidate = psycopg2.pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=10,
                dsn=url,
            )
            # Verify the pool can yield a live connection before accepting it.
            conn = candidate.getconn()
            candidate.putconn(conn)
            _pool = candidate
            logger.info(
                "db_pool_ready",
                extra={"attempt": attempt},
            )
            break
        except psycopg2.OperationalError as exc:
            logger.warning(
                "db_connect_failed",
                extra={
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "error": str(exc),
                },
            )
            if attempt == max_attempts:
                raise RuntimeError(
                    f"Could not connect to the database after {max_attempts} attempts"
                ) from exc
            time.sleep(delay_seconds)

    # Create schema tables idempotently.
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_CREATE_WATCHLIST_SQL)
            cur.execute(_CREATE_SNAPSHOTS_SQL)
    logger.info("db_schema_ready")


# ---------------------------------------------------------------------------
# Connection context manager
# ---------------------------------------------------------------------------

@contextmanager
def get_conn() -> Generator:
    """
    Context manager that yields a connection from the pool and returns it
    on exit.

    Commits on a clean exit; rolls back and re-raises on any exception.
    The connection is always returned to the pool in the ``finally`` block.

    Raises
    ------
    RuntimeError
        If ``init_db()`` has not been called yet.
    """
    if _pool is None:
        raise RuntimeError("Database pool is not initialised; call init_db() first")
    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

def ping() -> bool:
    """
    Return ``True`` if the database is reachable, ``False`` otherwise.

    Safe to call before ``init_db()``; returns ``False`` if the pool has
    not been set up yet.
    """
    if _pool is None:
        return False
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Database ping failed", extra={"error": str(exc)})
        return False


# ---------------------------------------------------------------------------
# Watchlist queries
# ---------------------------------------------------------------------------

_SELECT_ALL_WATCHLIST_SQL = """
SELECT id, ticker, added_at
FROM watchlist
ORDER BY added_at ASC;
"""

_INSERT_WATCHLIST_SQL = """
INSERT INTO watchlist (ticker)
VALUES (%s)
RETURNING id, ticker, added_at;
"""

_DELETE_WATCHLIST_SQL = """
DELETE FROM watchlist
WHERE ticker = %s
RETURNING id;
"""

_SELECT_TICKER_SQL = """
SELECT id, ticker, added_at
FROM watchlist
WHERE ticker = %s;
"""


def get_watchlist() -> List[dict]:
    """
    Return all tickers currently in the watchlist.

    Returns
    -------
    List[dict]
        Ordered list (oldest first) of dicts with keys:
        ``id``, ``ticker``, ``added_at``.
    """
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(_SELECT_ALL_WATCHLIST_SQL)
            rows = cur.fetchall()
    return [dict(row) for row in rows]


def add_ticker(ticker: str) -> dict:
    """
    Insert a new ticker into the watchlist.

    Parameters
    ----------
    ticker:
        The CoinGecko coin identifier to add (e.g. ``"bitcoin"``).

    Returns
    -------
    dict
        The newly created row with keys: ``id``, ``ticker``, ``added_at``.

    Raises
    ------
    psycopg2.errors.UniqueViolation
        If the ticker already exists in the watchlist.
    """
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(_INSERT_WATCHLIST_SQL, (ticker,))
            row = cur.fetchone()
    return dict(row)


def delete_ticker(ticker: str) -> bool:
    """
    Remove a ticker from the watchlist.

    Parameters
    ----------
    ticker:
        The CoinGecko coin identifier to remove.

    Returns
    -------
    bool
        ``True`` if a row was deleted, ``False`` if the ticker was not found.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_DELETE_WATCHLIST_SQL, (ticker,))
            deleted = cur.fetchone()
    return deleted is not None


def ticker_exists(ticker: str) -> bool:
    """
    Return ``True`` if the ticker is in the watchlist, ``False`` otherwise.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_SELECT_TICKER_SQL, (ticker,))
            row = cur.fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Price snapshot queries
# ---------------------------------------------------------------------------

_INSERT_SNAPSHOT_SQL = """
INSERT INTO price_snapshots (ticker, price_usd, change_24h)
VALUES (%s, %s, %s)
RETURNING id, ticker, price_usd, change_24h, fetched_at;
"""

_SELECT_HISTORY_SQL = """
SELECT id, ticker, price_usd, change_24h, fetched_at
FROM price_snapshots
WHERE ticker = %s
ORDER BY fetched_at DESC
LIMIT %s OFFSET %s;
"""

_SELECT_LATEST_SNAPSHOTS_SQL = """
SELECT DISTINCT ON (ticker)
    id, ticker, price_usd, change_24h, fetched_at
FROM price_snapshots
WHERE ticker = ANY(%s)
ORDER BY ticker, fetched_at DESC;
"""

_SELECT_LATEST_FOR_TICKER_SQL = """
SELECT id, ticker, price_usd, change_24h, fetched_at
FROM price_snapshots
WHERE ticker = %s
ORDER BY fetched_at DESC
LIMIT 1;
"""


def save_snapshot(ticker: str, price_usd: float, change_24h: float) -> dict:
    """
    Persist a price snapshot row to the database.

    Parameters
    ----------
    ticker:
        The CoinGecko coin identifier.
    price_usd:
        Price in USD at the time of fetching.
    change_24h:
        24-hour percentage price change.

    Returns
    -------
    dict
        The newly persisted snapshot with keys:
        ``id``, ``ticker``, ``price_usd``, ``change_24h``, ``fetched_at``.
    """
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(_INSERT_SNAPSHOT_SQL, (ticker, price_usd, change_24h))
            row = cur.fetchone()
    return {
        "id": row["id"],
        "ticker": row["ticker"],
        "price_usd": float(row["price_usd"]) if row["price_usd"] is not None else None,
        "change_24h": float(row["change_24h"]) if row["change_24h"] is not None else None,
        "fetched_at": row["fetched_at"],
    }


def get_ticker_history(ticker: str, limit: int = 100, offset: int = 0) -> List[dict]:
    """
    Return paginated price snapshots for a given ticker, newest first.

    Parameters
    ----------
    ticker:
        The CoinGecko coin identifier to look up.
    limit:
        Maximum number of rows to return (default 100).
    offset:
        Number of rows to skip before returning results (for pagination).

    Returns
    -------
    List[dict]
        Snapshot dicts ordered by ``fetched_at`` descending.  Each dict
        has keys: ``id``, ``ticker``, ``price_usd``, ``change_24h``,
        ``fetched_at``.
    """
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(_SELECT_HISTORY_SQL, (ticker, limit, offset))
            rows = cur.fetchall()
    return [
        {
            "id": row["id"],
            "ticker": row["ticker"],
            "price_usd": float(row["price_usd"]) if row["price_usd"] is not None else None,
            "change_24h": float(row["change_24h"]) if row["change_24h"] is not None else None,
            "fetched_at": row["fetched_at"],
        }
        for row in rows
    ]


def get_latest_snapshots(tickers: List[str]) -> List[dict]:
    """
    Return the most recent price snapshot for each of the given tickers.

    Parameters
    ----------
    tickers:
        List of CoinGecko coin identifiers.

    Returns
    -------
    List[dict]
        One snapshot dict per ticker (the most recent), or an empty list
        if ``tickers`` is empty or no snapshots exist.
    """
    if not tickers:
        return []
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(_SELECT_LATEST_SNAPSHOTS_SQL, (tickers,))
            rows = cur.fetchall()
    return [
        {
            "id": row["id"],
            "ticker": row["ticker"],
            "price_usd": float(row["price_usd"]) if row["price_usd"] is not None else None,
            "change_24h": float(row["change_24h"]) if row["change_24h"] is not None else None,
            "fetched_at": row["fetched_at"],
        }
        for row in rows
    ]


def get_latest_snapshot_for_ticker(ticker: str) -> Optional[dict]:
    """
    Return the single most recent price snapshot for a given ticker.

    Returns ``None`` if no snapshots exist for the ticker.
    """
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(_SELECT_LATEST_FOR_TICKER_SQL, (ticker,))
            row = cur.fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "ticker": row["ticker"],
        "price_usd": float(row["price_usd"]) if row["price_usd"] is not None else None,
        "change_24h": float(row["change_24h"]) if row["change_24h"] is not None else None,
        "fetched_at": row["fetched_at"],
    }


def get_last_successful_fetch() -> Optional[datetime]:
    """
    Return the timestamp of the most recent price snapshot across all tickers.

    Used by the ``/status`` page to display when CoinGecko was last polled
    successfully.

    Returns
    -------
    Optional[datetime]
        The most recent ``fetched_at`` timestamp, or ``None`` if no
        snapshots exist.
    """
    sql = "SELECT MAX(fetched_at) AS last_fetch FROM price_snapshots;"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
    return row[0] if row else None
