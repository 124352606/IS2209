"""
Data model dataclasses for DeployHub.

These lightweight dataclasses are used for type-safe data transfer between
the database layer, the CoinGecko wrapper, and the route handlers.
They carry no ORM logic; persistence is handled exclusively in ``app.db``.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class WatchlistEntry:
    """
    Represents a single row in the ``watchlist`` database table.

    Attributes
    ----------
    ticker:
        The CoinGecko coin identifier (e.g. ``"bitcoin"``).
    added_at:
        Timestamp when the ticker was added to the watchlist.
    id:
        Primary key assigned by the database (``None`` before insertion).
    """

    ticker: str
    added_at: Optional[datetime] = None
    id: Optional[int] = None


@dataclass
class PriceSnapshot:
    """
    Represents a single row in the ``price_snapshots`` database table.

    Attributes
    ----------
    ticker:
        The CoinGecko coin identifier.
    price_usd:
        Current price in USD at the time of the snapshot.
    change_24h:
        Percentage price change over the previous 24 hours.
    fetched_at:
        Timestamp when the price was fetched from CoinGecko.
    id:
        Primary key assigned by the database (``None`` before insertion).
    """

    ticker: str
    price_usd: Optional[float] = None
    change_24h: Optional[float] = None
    fetched_at: Optional[datetime] = None
    id: Optional[int] = None


@dataclass
class CoinPrice:
    """
    Transient price data returned from the CoinGecko API.

    This dataclass is used internally by ``app.coingecko`` and is not
    persisted directly; it is converted to a ``PriceSnapshot`` before storage.

    Attributes
    ----------
    ticker:
        The CoinGecko coin identifier.
    price_usd:
        Current price in USD.
    change_24h:
        Percentage price change over the previous 24 hours.
    """

    ticker: str
    price_usd: float
    change_24h: float
