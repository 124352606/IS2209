import os
import uuid
import time
import logging
import requests
import psycopg
from flask import Flask, jsonify, render_template, request, g
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

app = Flask(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")
COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"

DEFAULT_COINS = "bitcoin,ethereum,solana,cardano,dogecoin"

# -----------------------------
# LOGGING SETUP
# -----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


@app.before_request
def before_request():
    g.request_id = str(uuid.uuid4())[:8]
    g.start_time = time.time()
    logger.info("[%s] %s %s", g.request_id, request.method, request.path)


@app.after_request
def after_request(response):
    duration_ms = round((time.time() - g.start_time) * 1000)
    logger.info(
        "[%s] %s %s %d (%dms)",
        g.request_id,
        request.method,
        request.path,
        response.status_code,
        duration_ms
    )
    return response


# -----------------------------
# DATABASE FUNCTIONS
# -----------------------------
def get_watchlist():
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, coin_id, coin_name, added_at FROM watchlist ORDER BY added_at DESC;")
            rows = cur.fetchall()
    return [
        {"id": str(r[0]), "coin_id": r[1], "coin_name": r[2], "added_at": str(r[3])}
        for r in rows
    ]


def add_to_watchlist(coin_id, coin_name):
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO watchlist (coin_id, coin_name) VALUES (%s, %s);",
                (coin_id, coin_name)
            )
        conn.commit()


# -----------------------------
# COINGECKO API FUNCTION
# -----------------------------
def get_prices(coins=DEFAULT_COINS):
    try:
        r = requests.get(
            COINGECKO_URL,
            params={"ids": coins, "vs_currencies": "usd"},
            headers={"x-cg-demo-api-key": COINGECKO_API_KEY},
            timeout=5
        )

        data = r.json()

        if r.status_code != 200:
            return {"error": data}

        return [
            {"coin_id": coin_id, "price_usd": values.get("usd")}
            for coin_id, values in data.items()
        ]

    except requests.RequestException as e:
        return {"error": str(e)}


# -----------------------------
# ROUTES
# -----------------------------

@app.route("/")
def index():
    try:
        prices = get_prices()
        watchlist = get_watchlist()
        return render_template("index.html", prices=prices, watchlist=watchlist)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/prices")
def prices():
    try:
        results = get_prices()
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/watchlist", methods=["GET", "POST"])
def watchlist():
    try:
        if request.method == "POST":
            body = request.get_json()
            coin_id = body.get("coin_id")
            coin_name = body.get("coin_name")

            if not coin_id or not coin_name:
                return jsonify({"error": "coin_id and coin_name are required"}), 400

            add_to_watchlist(coin_id, coin_name)
            return jsonify({"status": "added", "coin_id": coin_id}), 201

        items = get_watchlist()
        return jsonify(items)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/status")
def status():
    try:
        get_watchlist()
        return jsonify({"database": "connected"})
    except Exception as e:
        return jsonify({"database": "disconnected", "error": str(e)}), 500


@app.route("/health")
def health():
    try:
        # Check DB
        get_watchlist()

        # Check CoinGecko
        r = requests.get(
            COINGECKO_URL,
            params={"ids": "bitcoin", "vs_currencies": "usd"},
            headers={"x-cg-demo-api-key": COINGECKO_API_KEY},
            timeout=5
        )
        r.raise_for_status()

        return jsonify({"status": "ok"})

    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500


# -----------------------------
# RUN
# -----------------------------
if __name__ == "__main__":
    app.run(debug=True)