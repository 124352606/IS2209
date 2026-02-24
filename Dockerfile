# ---------------------------------------------------------------------------
# DeployHub — Production Dockerfile
# ---------------------------------------------------------------------------
# Base image: python:3.11-slim keeps the image small while providing a
# complete CPython 3.11 environment.
# ---------------------------------------------------------------------------

FROM python:3.11-slim

# --- OS-level dependencies --------------------------------------------------
# libpq-dev is required by psycopg2-binary at import time on slim images.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# --- Non-root user ----------------------------------------------------------
# Running as a non-root user limits the blast radius of any vulnerabilities.
RUN addgroup --system appgroup \
    && adduser --system --ingroup appgroup appuser

# --- Working directory -------------------------------------------------------
WORKDIR /app

# --- Python dependencies -----------------------------------------------------
# Copy requirements first so Docker can cache this layer independently of
# the application source.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- Application source ------------------------------------------------------
COPY app/ ./app/
COPY templates/ ./templates/

# --- Ownership ---------------------------------------------------------------
RUN chown -R appuser:appgroup /app

# --- Runtime user ------------------------------------------------------------
USER appuser

# --- Port --------------------------------------------------------------------
EXPOSE 5000

# --- Health check ------------------------------------------------------------
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')" || exit 1

# --- Entrypoint --------------------------------------------------------------
# gunicorn with 4 workers; the port can be overridden via the PORT env var.
CMD ["sh", "-c", "gunicorn -w 4 -b 0.0.0.0:${PORT:-5000} \"app:create_app()\""]
