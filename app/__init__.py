"""
DeployHub application factory and structured logging setup.

This module initialises the Flask application, configures JSON-formatted
structured logging, and attaches per-request tracing via Flask's ``g`` object.
"""

import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, g, request

# Load .env file in development (no-op if file does not exist or already set)
load_dotenv()


# ---------------------------------------------------------------------------
# JSON log formatter
# ---------------------------------------------------------------------------

class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON objects for structured output."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialise a log record to a JSON string."""
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Merge any extra fields attached to the record
        for key, value in record.__dict__.items():
            if key not in (
                "args", "asctime", "created", "exc_info", "exc_text",
                "filename", "funcName", "id", "levelname", "levelno",
                "lineno", "module", "msecs", "message", "msg", "name",
                "pathname", "process", "processName", "relativeCreated",
                "stack_info", "thread", "threadName",
            ):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def _configure_logging() -> None:
    """Configure root logger to emit JSON logs to stdout."""
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, log_level, logging.INFO))


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app(test_config: dict | None = None) -> Flask:
    """
    Create and configure the Flask application.

    Parameters
    ----------
    test_config:
        Optional mapping of configuration values to override defaults.
        Used by the test suite to inject mock settings.

    Returns
    -------
    Flask
        The configured Flask application instance.
    """
    _configure_logging()
    logger = logging.getLogger(__name__)

    app = Flask(__name__, template_folder="../templates")

    # ------------------------------------------------------------------
    # Load configuration
    # ------------------------------------------------------------------
    app.config["DATABASE_URL"] = os.environ.get("DATABASE_URL", "")
    app.config["COINGECKO_BASE_URL"] = os.environ.get(
        "COINGECKO_BASE_URL", "https://api.coingecko.com/api/v3"
    )
    app.config["LOG_LEVEL"] = os.environ.get("LOG_LEVEL", "INFO")
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")

    if test_config is not None:
        app.config.update(test_config)

    # ------------------------------------------------------------------
    # Per-request tracing hooks
    # ------------------------------------------------------------------

    @app.before_request
    def _attach_request_id() -> None:
        """Generate and store a UUID request_id on Flask's g object."""
        g.request_id = str(uuid.uuid4())
        g.start_time = time.monotonic()

    @app.after_request
    def _log_request(response):
        """Emit a structured access log line after every response."""
        duration_ms = round((time.monotonic() - g.start_time) * 1000, 2)
        request_id = getattr(g, "request_id", "unknown")
        logger.info(
            "request completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        response.headers["X-Request-ID"] = request_id
        return response

    # ------------------------------------------------------------------
    # Register blueprints
    # ------------------------------------------------------------------
    from app.routes import bp  # noqa: PLC0415
    app.register_blueprint(bp)

    # ------------------------------------------------------------------
    # Initialise database pool and schema (skipped in testing)
    # ------------------------------------------------------------------
    if not app.config.get("TESTING") and app.config.get("DATABASE_URL"):
        from app.db import init_db  # noqa: PLC0415
        init_db(app)

    logger.info(
        "DeployHub application created",
        extra={"config_env": os.environ.get("FLASK_ENV", "production")},
    )
    return app
