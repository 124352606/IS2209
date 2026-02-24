"""
Route-level tests for DeployHub.

All database and CoinGecko calls are mocked; no real network or DB
connections are made.
"""

from datetime import datetime, timezone

from app.coingecko import CoinGeckoUnavailableError

# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

def test_health_returns_ok_when_all_dependencies_up(client, mock_db, mock_coingecko):
    """GET /health returns 200 with status='ok' when DB and CoinGecko are up."""
    mock_db.ping.return_value = True
    mock_coingecko.ping.return_value = True

    resp = client.get("/health")
    data = resp.get_json()

    assert resp.status_code == 200
    assert data["status"] == "ok"
    assert data["database"] == "ok"
    assert data["coingecko"] == "ok"
    assert "timestamp" in data
    assert "request_id" in data


def test_health_returns_degraded_when_db_down(client, mock_db, mock_coingecko):
    """GET /health returns 503 with status='degraded' when the database is unreachable."""
    mock_db.ping.return_value = False
    mock_coingecko.ping.return_value = True

    resp = client.get("/health")
    data = resp.get_json()

    assert resp.status_code == 503
    assert data["status"] == "degraded"
    assert data["database"] == "error"
    assert data["coingecko"] == "ok"


def test_health_returns_degraded_when_coingecko_down(client, mock_db, mock_coingecko):
    """GET /health returns 503 with status='degraded' when CoinGecko is unreachable."""
    mock_db.ping.return_value = True
    mock_coingecko.ping.return_value = False

    resp = client.get("/health")
    data = resp.get_json()

    assert resp.status_code == 503
    assert data["status"] == "degraded"
    assert data["database"] == "ok"
    assert data["coingecko"] == "error"


# ---------------------------------------------------------------------------
# GET /watchlist
# ---------------------------------------------------------------------------

def test_watchlist_returns_joined_result_when_both_sources_available(
    client, mock_db, mock_coingecko
):
    """
    GET /watchlist fetches live prices and merges them with watchlist entries
    when both DB and CoinGecko are available.
    """
    now = datetime.now(timezone.utc)
    mock_db.get_watchlist.return_value = [
        {"id": 1, "ticker": "bitcoin", "added_at": now},
        {"id": 2, "ticker": "ethereum", "added_at": now},
    ]
    mock_coingecko.fetch_prices.return_value = {
        "bitcoin": {"usd": 65000.0, "usd_24h_change": 2.34},
        "ethereum": {"usd": 3200.0, "usd_24h_change": -1.23},
    }

    resp = client.get("/watchlist")
    data = resp.get_json()

    assert resp.status_code == 200
    assert data["source"] == "live"
    assert len(data["watchlist"]) == 2

    btc = next(c for c in data["watchlist"] if c["ticker"] == "bitcoin")
    assert btc["price_usd"] == 65000.0
    assert btc["change_24h"] == 2.34


def test_watchlist_returns_cached_data_on_coingecko_failure(
    client, mock_db, mock_coingecko
):
    """
    GET /watchlist falls back to cached DB snapshots when CoinGecko is
    unavailable, returning source='cached' and HTTP 200.
    """
    now = datetime.now(timezone.utc)
    mock_db.get_watchlist.return_value = [
        {"id": 1, "ticker": "bitcoin", "added_at": now},
    ]
    mock_coingecko.fetch_prices.side_effect = CoinGeckoUnavailableError("down", attempts=3)
    mock_db.get_latest_snapshots.return_value = [
        {"id": 1, "ticker": "bitcoin", "price_usd": 60000.0, "change_24h": 1.5, "fetched_at": now},
    ]

    resp = client.get("/watchlist")
    data = resp.get_json()

    assert resp.status_code == 200
    assert data["source"] == "cached"
    assert data["watchlist"][0]["price_usd"] == 60000.0


def test_watchlist_returns_503_when_coingecko_down_and_no_cache(
    client, mock_db, mock_coingecko
):
    """
    GET /watchlist returns HTTP 503 when CoinGecko is down and no cached
    snapshots exist in the database.
    """
    now = datetime.now(timezone.utc)
    mock_db.get_watchlist.return_value = [
        {"id": 1, "ticker": "bitcoin", "added_at": now},
    ]
    mock_coingecko.fetch_prices.side_effect = CoinGeckoUnavailableError("down", attempts=3)
    mock_db.get_latest_snapshots.return_value = []

    resp = client.get("/watchlist")
    data = resp.get_json()

    assert resp.status_code == 503
    assert "error" in data


# ---------------------------------------------------------------------------
# POST /watchlist
# ---------------------------------------------------------------------------

def test_add_ticker_returns_201_on_success(client, mock_db, mock_coingecko):
    """POST /watchlist with a valid ticker returns HTTP 201 and the new entry."""
    now = datetime.now(timezone.utc)
    mock_db.add_ticker.return_value = {"id": 1, "ticker": "bitcoin", "added_at": now}

    resp = client.post(
        "/watchlist",
        json={"ticker": "bitcoin"},
        content_type="application/json",
    )
    data = resp.get_json()

    assert resp.status_code == 201
    assert data["ticker"] == "bitcoin"
    assert "added_at" in data
    assert "request_id" in data


def test_add_ticker_returns_409_on_duplicate(client, mock_db, mock_coingecko):
    """POST /watchlist with an already-existing ticker returns HTTP 409."""
    mock_db.add_ticker.side_effect = Exception("duplicate key value violates unique constraint")

    resp = client.post(
        "/watchlist",
        json={"ticker": "bitcoin"},
        content_type="application/json",
    )
    data = resp.get_json()

    assert resp.status_code == 409
    assert "error" in data


def test_add_ticker_returns_400_on_invalid_input(client, mock_db, mock_coingecko):
    """POST /watchlist with missing or invalid ticker field returns HTTP 400."""
    # Missing ticker field
    resp = client.post("/watchlist", json={}, content_type="application/json")
    assert resp.status_code == 400
    assert "error" in resp.get_json()

    # Empty ticker
    resp = client.post("/watchlist", json={"ticker": ""}, content_type="application/json")
    assert resp.status_code == 400

    # Uppercase ticker (must be lowercase)
    resp = client.post("/watchlist", json={"ticker": "Bitcoin"}, content_type="application/json")
    assert resp.status_code == 400

    # Non-JSON body
    resp = client.post("/watchlist", data="not-json", content_type="text/plain")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# DELETE /watchlist/<ticker>
# ---------------------------------------------------------------------------

def test_delete_ticker_returns_204_on_success(client, mock_db, mock_coingecko):
    """DELETE /watchlist/<ticker> returns HTTP 204 when the ticker is found."""
    mock_db.delete_ticker.return_value = True

    resp = client.delete("/watchlist/bitcoin")

    assert resp.status_code == 204
    assert resp.data == b""


def test_delete_ticker_returns_404_when_not_found(client, mock_db, mock_coingecko):
    """DELETE /watchlist/<ticker> returns HTTP 404 when the ticker is not in the DB."""
    mock_db.delete_ticker.return_value = False

    resp = client.delete("/watchlist/nonexistent")
    data = resp.get_json()

    assert resp.status_code == 404
    assert "error" in data
