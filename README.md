# DeployHub — Cryptocurrency Price Tracker

DeployHub is a Flask-based web service that tracks cryptocurrency prices using
the [CoinGecko](https://www.coingecko.com/) public API. It provides a REST API
and minimal HTML dashboard for managing a personal watchlist of coins, fetching
live prices, and browsing historical snapshots stored in PostgreSQL.

This project was built as an IS2209 university CI/CD assignment. Engineering
practices (structured logging, Docker, GitHub Actions CI/CD) are a core part
of the deliverable alongside the working application.

---

## Prerequisites

| Tool | Minimum version |
|------|----------------|
| Python | 3.11 |
| Docker | 24.x |
| Docker Compose | v2.x (`docker compose` not `docker-compose`) |
| PostgreSQL | 15 (provided via Docker) |

---

## Local Setup

```bash
# 1. Clone the repository
git clone https://github.com/<your-username>/deployhub.git
cd deployhub

# 2. Copy the environment template and configure values
cp .env.example .env
# Edit .env — at minimum set a strong SECRET_KEY

# 3. Start both services (app + PostgreSQL)
docker compose up --build

# 4. Open the dashboard
open http://localhost:5000
```

The application will automatically create the `watchlist` and `price_snapshots`
tables on first start.

### Running without Docker (development)

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env               # configure DATABASE_URL to a local Postgres
python -c "from app import create_app; create_app().run(debug=True)"
```

---

## Running the Tests

```bash
# Install dev dependencies (if not already done)
pip install -r requirements-dev.txt

# Run the full test suite with coverage
pytest --cov=app --cov-report=term-missing -v

# Run a specific test file
pytest tests/test_routes.py -v
```

Tests mock all external calls (CoinGecko and PostgreSQL) so **no network
connection or database** is required to run them.

---

## API Endpoints

| Method | Path | Description | Example Response |
|--------|------|-------------|-----------------|
| `GET` | `/` | HTML dashboard — watchlist table + add/remove form | HTML page |
| `GET` | `/health` | JSON health check for all dependencies | `{"status":"ok","database":"ok","coingecko":"ok","timestamp":"…"}` |
| `GET` | `/status` | HTML status page — uptime, Python version, last fetch | HTML page |
| `GET` | `/watchlist` | Live prices for all watchlist coins (falls back to cache) | `{"watchlist":[…],"source":"live","request_id":"…"}` |
| `POST` | `/watchlist` | Add a ticker — body: `{"ticker":"bitcoin"}` | `201 {"ticker":"bitcoin","added_at":"…"}` |
| `DELETE` | `/watchlist/<ticker>` | Remove a ticker from the watchlist | `204 (no body)` |
| `GET` | `/prices/<ticker>` | Live price for a single coin | `{"ticker":"bitcoin","price_usd":65000,"change_24h":2.34}` |
| `GET` | `/history/<ticker>` | Last 100 price snapshots for a coin | `{"ticker":"bitcoin","history":[…]}` |

All JSON error responses follow the shape:
```json
{"error": "human-readable message", "request_id": "<uuid>"}
```

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | — | PostgreSQL connection string |
| `COINGECKO_BASE_URL` | No | `https://api.coingecko.com/api/v3` | CoinGecko API base URL |
| `FLASK_ENV` | No | `production` | Flask environment name |
| `FLASK_DEBUG` | No | `0` | Enable Flask debug mode (`1`/`0`) |
| `LOG_LEVEL` | No | `INFO` | Python logging level |
| `PORT` | No | `5000` | TCP port to bind |
| `SECRET_KEY` | Yes (prod) | `dev-secret-key` | Flask session signing key |
| `POSTGRES_USER` | No | `deployhub` | DB user (docker-compose only) |
| `POSTGRES_PASSWORD` | No | `deployhub_secret` | DB password (docker-compose only) |
| `POSTGRES_DB` | No | `deployhub` | Database name (docker-compose only) |

---

## CI/CD Pipeline

```
  ┌──────────────────────────────────────────────────────────────────┐
  │                       Push / Pull Request                        │
  └───────────────────────────┬──────────────────────────────────────┘
                              │
                     ┌────────▼────────┐
                     │   CI Pipeline   │  (.github/workflows/ci.yml)
                     └────────┬────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
      ┌───────▼──────┐ ┌──────▼──────┐ ┌─────▼──────┐
      │  1. lint     │ │  2. test    │ │  3. build  │
      │  ruff check  │ │  pytest     │ │  docker    │
      │              │ │  coverage   │ │  build     │
      └──────────────┘ └─────────────┘ └────────────┘
              (sequential — each depends on previous)

  ┌──────────────────────────────────────────────────────────────────┐
  │                     Push to main only                            │
  └───────────────────────────┬──────────────────────────────────────┘
                              │
                     ┌────────▼────────┐
                     │   CD Pipeline   │  (.github/workflows/cd.yml)
                     └────────┬────────┘
                              │
              ┌───────────────┴───────────────┐
              │                               │
      ┌───────▼──────┐               ┌────────▼────────┐
      │  1. publish  │               │   2. deploy     │
      │  ghcr.io     │──(needs)─────►│   Render hook   │
      │  push image  │               │   curl POST     │
      └──────────────┘               └─────────────────┘
```

### Secrets Required

| Secret | Used by | Description |
|--------|---------|-------------|
| `GITHUB_TOKEN` | CD / publish | Auto-provided by GitHub Actions |
| `RENDER_DEPLOY_HOOK_URL` | CD / deploy | Render deploy webhook URL |

---

## Deployment

The production deployment target is **Render**: https://deployhub.onrender.com

Deployments are triggered automatically when a commit is merged to `main` via
the CD pipeline webhook.

### Tagging a Release

```bash
git tag v1.0.0
git push origin v1.0.0
```

---

## Project Structure

```
deployhub/
├── app/
│   ├── __init__.py       # Application factory, structured JSON logging
│   ├── routes.py         # All Flask route handlers
│   ├── db.py             # PostgreSQL access layer (parameterised queries)
│   ├── coingecko.py      # CoinGecko API wrapper with retry logic
│   └── models.py         # Dataclasses for WatchlistEntry, PriceSnapshot
├── tests/
│   ├── conftest.py       # Shared fixtures (mock DB, mock CoinGecko)
│   ├── test_routes.py    # Route-level integration tests
│   ├── test_coingecko.py # CoinGecko wrapper unit tests
│   └── test_db.py        # Database layer unit tests
├── templates/
│   ├── base.html         # Shared HTML layout
│   ├── index.html        # Dashboard page
│   └── status.html       # System status page
├── .github/workflows/
│   ├── ci.yml            # Lint → Test → Build (all branches)
│   └── cd.yml            # Publish → Deploy (main only)
├── Dockerfile
├── docker-compose.yaml
├── .env.example
├── requirements.txt
├── requirements-dev.txt
└── .gitignore
```

---

## External Code Citations

- Flask documentation — application factory pattern:
  https://flask.palletsprojects.com/en/3.0.x/patterns/appfactories/
- psycopg2 documentation — connection and cursor usage:
  https://www.psycopg.org/docs/usage.html
- CoinGecko public API — simple price endpoint:
  https://www.coingecko.com/api/documentation
- Docker best practices — non-root user, layer caching:
  https://docs.docker.com/develop/develop-images/dockerfile_best-practices/
- GitHub Actions — docker/build-push-action:
  https://github.com/docker/build-push-action
- pytest-mock documentation:
  https://pytest-mock.readthedocs.io/en/latest/
- Render deploy hooks documentation:
  https://render.com/docs/deploy-hooks
