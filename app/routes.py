"""
Flask route definitions for DeployHub.

All endpoints are registered on a single :class:`flask.Blueprint` (``bp``)
which is attached to the application in :func:`app.create_app`.

Error responses always follow the shape::

    {"error": "<message>", "request_id": "<uuid>"}

Successful JSON responses always include ``request_id`` at the top level.
"""

import logging
import sys
from datetime import datetime, timezone

from flask import Blueprint, current_app, g, jsonify, render_template, request

import app.coingecko as coingecko_client
import app.db as db
from app.coingecko import CoinGeckoUnavailableError

try:
    import psycopg2  #noqa: F401
    _PSYCOPG2_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PSYCOPG2_AVAILABLE = False

logger = logging.getLogger(__name__)

bp = Blueprint("main", __name__)

# Track when this process started (used by /status)
_APP_START_TIME = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _request_id() -> str:
    """Return the request-scoped UUID attached in the before_request hook."""
    return getattr(g, "request_id", "unknown")


def _error(message: str, status_code: int):
    """Build a consistent JSON error response."""
    return jsonify({"error": message, "request_id": _request_id()}), status_code


def _iso(dt: datetime | None) -> str | None:
    """Convert a datetime to ISO 8601 string, or return None."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@bp.route("/health")
def health():
    """
    Return the operational status of all service dependencies.

    Returns HTTP 200 when everything is healthy, HTTP 503 when any
    dependency (database or CoinGecko) is unavailable.
    """
    db_ok = db.ping()
    cg_ok = coingecko_client.ping(
        base_url=current_app.config.get(
            "COINGECKO_BASE_URL", "https://api.coingecko.com/api/v3"
        )
    )

    overall = "ok" if (db_ok and cg_ok) else "degraded"
    status_code = 200 if overall == "ok" else 503

    payload = {
        "status": overall,
        "database": "ok" if db_ok else "error",
        "coingecko": "ok" if cg_ok else "error",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request_id": _request_id(),
    }
    return jsonify(payload), status_code


# ---------------------------------------------------------------------------
# Status page (HTML)
# ---------------------------------------------------------------------------

@bp.route("/status")
def status():
    """
    Render an HTML status page showing service health and metadata.

    Displays: DB connectivity, last successful CoinGecko fetch time,
    application uptime, and Python version.
    """
    db_ok = db.ping()
    last_fetch = None
    try:
        last_fetch = db.get_last_successful_fetch()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not retrieve last fetch time", extra={"error": str(exc)})

    uptime_seconds = (datetime.now(timezone.utc) - _APP_START_TIME).total_seconds()
    hours, remainder = divmod(int(uptime_seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m {seconds}s"

    return render_template(
        "status.html",
        db_status="ok" if db_ok else "error",
        last_fetch=_iso(last_fetch) or "Never",
        uptime=uptime_str,
        python_version=sys.version,
        request_id=_request_id(),
    )


# ---------------------------------------------------------------------------
# Watchlist — GET
# ---------------------------------------------------------------------------

@bp.route("/watchlist", methods=["GET"])
def get_watchlist():
    """
    Return live prices for all tickers in the watchlist.

    Fetches prices from CoinGecko in a single batched API call, persists
    a snapshot for each ticker, and returns the merged result.

    If CoinGecko is unavailable the most recent snapshots from the database
    are returned with ``"source": "cached"``.  If no cache exists and
    CoinGecko is down the response is HTTP 503.
    """
    req_id = _request_id()
    base_url = current_app.config.get(
        "COINGECKO_BASE_URL", "https://api.coingecko.com/api/v3"
    )

    try:
        entries = db.get_watchlist()
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to fetch watchlist from DB", extra={"error": str(exc), "request_id": req_id})
        return _error("Database error: could not retrieve watchlist", 503)

    if not entries:
        return jsonify({"watchlist": [], "source": "live", "request_id": req_id}), 200

    tickers = [e["ticker"] for e in entries]
    added_at_map = {e["ticker"]: e["added_at"] for e in entries}

    # --- Try live prices ------------------------------------------------
    source = "live"
    try:
        raw = coingecko_client.fetch_prices(tickers, base_url=base_url, request_id=req_id)
        result = []
        for ticker in tickers:
            coin_data = raw.get(ticker, {})
            price_usd = coin_data.get("usd")
            change_24h = coin_data.get("usd_24h_change")
            if price_usd is not None:
                try:
                    db.save_snapshot(ticker, price_usd, change_24h or 0.0)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Failed to save snapshot",
                        extra={"ticker": ticker, "error": str(exc), "request_id": req_id},
                    )
            result.append({
                "ticker": ticker,
                "price_usd": price_usd,
                "change_24h": change_24h,
                "added_at": _iso(added_at_map.get(ticker)),
            })
        return jsonify({"watchlist": result, "source": source, "request_id": req_id}), 200

    except CoinGeckoUnavailableError:
        logger.warning(
            "CoinGecko unavailable; falling back to cached prices",
            extra={"request_id": req_id},
        )

    # --- Fall back to cached prices ------------------------------------
    source = "cached"
    try:
        snapshots = db.get_latest_snapshots(tickers)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to fetch cached snapshots", extra={"error": str(exc), "request_id": req_id})
        return _error("CoinGecko unavailable and database error reading cache", 503)

    snapshot_map = {s["ticker"]: s for s in snapshots}

    if not snapshot_map:
        return _error(
            "CoinGecko is unavailable and no cached prices exist", 503
        )

    result = []
    for ticker in tickers:
        snap = snapshot_map.get(ticker)
        result.append({
            "ticker": ticker,
            "price_usd": snap["price_usd"] if snap else None,
            "change_24h": snap["change_24h"] if snap else None,
            "added_at": _iso(added_at_map.get(ticker)),
        })

    return jsonify({"watchlist": result, "source": source, "request_id": req_id}), 200


# ---------------------------------------------------------------------------
# Watchlist — POST
# ---------------------------------------------------------------------------

@bp.route("/watchlist", methods=["POST"])
def add_ticker():
    """
    Add a ticker to the watchlist.

    Request body (JSON)::

        {"ticker": "bitcoin"}

    Returns HTTP 201 on success, 409 if already exists, 400 if the ticker
    field is missing, empty, or not a lowercase string.
    """
    req_id = _request_id()
    data = request.get_json(silent=True)

    if not data or "ticker" not in data:
        return _error("Request body must be JSON with a 'ticker' field", 400)

    ticker = data.get("ticker", "")
    if not isinstance(ticker, str) or not ticker.strip():
        return _error("'ticker' must be a non-empty string", 400)

    ticker = ticker.strip()
    if ticker != ticker.lower():
        return _error("'ticker' must be lowercase", 400)

    try:
        entry = db.add_ticker(ticker)
    except Exception as exc:
        exc_str = str(exc)
        if "unique" in exc_str.lower() or "duplicate" in exc_str.lower():
            return _error(f"Ticker '{ticker}' already exists in the watchlist", 409)
        logger.error(
            "Failed to add ticker",
            extra={"ticker": ticker, "error": exc_str, "request_id": req_id},
        )
        return _error("Database error: could not add ticker", 503)

    logger.info("Ticker added", extra={"ticker": ticker, "request_id": req_id})
    return jsonify({
        "ticker": entry["ticker"],
        "added_at": _iso(entry["added_at"]),
        "request_id": req_id,
    }), 201


# ---------------------------------------------------------------------------
# Watchlist — DELETE
# ---------------------------------------------------------------------------

@bp.route("/watchlist/<string:ticker>", methods=["DELETE"])
def delete_ticker(ticker: str):
    """
    Remove a ticker from the watchlist.

    Returns HTTP 204 on success, 404 if the ticker is not in the watchlist.
    """
    req_id = _request_id()
    try:
        deleted = db.delete_ticker(ticker)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Failed to delete ticker",
            extra={"ticker": ticker, "error": str(exc), "request_id": req_id},
        )
        return _error("Database error: could not delete ticker", 503)

    if not deleted:
        return _error(f"Ticker '{ticker}' not found", 404)

    logger.info("Ticker deleted", extra={"ticker": ticker, "request_id": req_id})
    return "", 204


# ---------------------------------------------------------------------------
# Live price for a single ticker
# ---------------------------------------------------------------------------

@bp.route("/prices/<string:ticker>")
def get_price(ticker: str):
    """
    Fetch the live price for a single coin from CoinGecko.

    Returns HTTP 200 with price data or HTTP 503 if CoinGecko is unavailable.
    """
    req_id = _request_id()
    base_url = current_app.config.get(
        "COINGECKO_BASE_URL", "https://api.coingecko.com/api/v3"
    )
    try:
        raw = coingecko_client.fetch_prices([ticker], base_url=base_url, request_id=req_id)
        coin_data = raw.get(ticker, {})
        if not coin_data:
            return _error(f"No data returned for ticker '{ticker}'", 404)
        return jsonify({
            "ticker": ticker,
            "price_usd": coin_data.get("usd"),
            "change_24h": coin_data.get("usd_24h_change"),
            "request_id": req_id,
        }), 200
    except CoinGeckoUnavailableError:
        return _error("CoinGecko API is currently unavailable", 503)


# ---------------------------------------------------------------------------
# Price history for a single ticker
# ---------------------------------------------------------------------------

@bp.route("/history/<string:ticker>")
def get_history(ticker: str):
    """
    Return the last 100 price snapshots for a given ticker.

    Records are ordered newest-first.  Returns an empty list if no snapshots
    exist for the ticker.
    """
    req_id = _request_id()
    try:
        snapshots = db.get_ticker_history(ticker)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Failed to fetch history",
            extra={"ticker": ticker, "error": str(exc), "request_id": req_id},
        )
        return _error("Database error: could not retrieve history", 503)

    return jsonify({
        "ticker": ticker,
        "history": [
            {
                "id": s["id"],
                "price_usd": s["price_usd"],
                "change_24h": s["change_24h"],
                "fetched_at": _iso(s["fetched_at"]),
            }
            for s in snapshots
        ],
        "request_id": req_id,
    }), 200


# ---------------------------------------------------------------------------
# Index (HTML)
# ---------------------------------------------------------------------------

@bp.route("/")
def index():
    """
    Render the main HTML dashboard page.

    Displays the watchlist with live prices in a table, along with a form
    to add or remove tickers.  Falls back gracefully if CoinGecko or the
    database is unavailable.
    """
    req_id = _request_id()
    base_url = current_app.config.get(
        "COINGECKO_BASE_URL", "https://api.coingecko.com/api/v3"
    )

    watchlist_data = []
    error_message = None
    data_source = "live"

    try:
        entries = db.get_watchlist()
    except Exception as exc:  # noqa: BLE001
        logger.error("Index: DB error fetching watchlist", extra={"error": str(exc)})
        return render_template(
            "index.html",
            watchlist=[],
            error="Database unavailable",
            source="error",
            request_id=req_id,
        )

    if entries:
        tickers = [e["ticker"] for e in entries]
        added_at_map = {e["ticker"]: e["added_at"] for e in entries}
        try:
            raw = coingecko_client.fetch_prices(tickers, base_url=base_url, request_id=req_id)
            for ticker in tickers:
                coin_data = raw.get(ticker, {})
                price_usd = coin_data.get("usd")
                change_24h = coin_data.get("usd_24h_change")
                if price_usd is not None:
                    try:
                        db.save_snapshot(ticker, price_usd, change_24h or 0.0)
                    except Exception:  # noqa: BLE001
                        pass
                watchlist_data.append({
                    "ticker": ticker,
                    "price_usd": price_usd,
                    "change_24h": change_24h,
                    "added_at": _iso(added_at_map.get(ticker)),
                })
        except CoinGeckoUnavailableError:
            data_source = "cached"
            error_message = "CoinGecko unavailable — showing cached prices"
            snapshots = db.get_latest_snapshots(tickers)
            snapshot_map = {s["ticker"]: s for s in snapshots}
            for e in entries:
                snap = snapshot_map.get(e["ticker"])
                watchlist_data.append({
                    "ticker": e["ticker"],
                    "price_usd": snap["price_usd"] if snap else None,
                    "change_24h": snap["change_24h"] if snap else None,
                    "added_at": _iso(e["added_at"]),
                })

    return render_template(
        "index.html",
        watchlist=watchlist_data,
        error=error_message,
        source=data_source,
        request_id=req_id,
    )
