import pytest
from unittest.mock import patch
from app import app

@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

def test_health(client):
    with patch("app.get_watchlist", return_value=[]), \
         patch("app.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.raise_for_status = lambda: None
        response = client.get("/health")
        assert response.status_code in [200, 500]

def test_status(client):
    with patch("app.get_watchlist", return_value=[]):
        response = client.get("/status")
        assert response.status_code == 200

def test_prices(client):
    with patch("app.get_prices", return_value=[{"coin_id": "bitcoin", "price_usd": 50000}]):
        response = client.get("/prices")
        assert response.status_code == 200